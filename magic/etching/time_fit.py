"""Etching 參數萃取：多個蝕刻時間做線性擬合（斜率 = 蝕刻率，截距 → 起始延遲）。

同一個配方（材料、機台、氣體與流量、ICP / RF 功率、壓力、光阻都一樣）、同一個線寬的紀錄放在一起：
    d(t) = r · t + c        r：蝕刻率；c < 0 → 電漿點起來到開始蝕刻有延遲 t0 = −c / r
加權擬合：權重 1/σ²（σ = 多點量測的標準差）；蝕穿的紀錄只是下限，不放進擬合（畫成空心三角形）。

分段蝕刻時，如果每一段都要重新點火，每段都會有延遲 t0，延遲會累加：
    d = r · (t − N · t0)       N = 分段數（紀錄的 N steps），t = 各段時間加總
選「每段都有延遲」就用這個模型（需要不同的 t 或不同的 N，例如 40 s 一次 和 2×20 s）。
"""
import math

import numpy as np
import pandas as pd

from ..core.registry import P, Result, analysis
from ._common import PALETTE, material_name, recipe_groups, recipe_tag, recipe_title

Y = {"材料蝕刻深度": ("d_material (nm)", "σ d_material (nm)"), "SiO2 蝕刻深度": ("d_SiO2 (nm)", "σ d_SiO2 (nm)")}
MODELS = ["整段一次延遲（d = r·t + c）", "每段都有延遲（d = r·(t − N·t₀)）"]
MARKERS = ["o", "s", "D", "P", "X", "v"]
DASHES = ["-", "--", ":", "-."]


def segfit(t, N, y, s=None):
    """d = r·t − r·t0·N（每段延遲 t0）的加權最小平方。回傳 dict(slope, s_slope, t0, s_t0, r2, n, ok)。"""
    t, N, y = (np.asarray(a, float) for a in (t, N, y))
    n = t.size
    use_w = s is not None and np.all(np.asarray(s) > 0)
    w = 1.0 / np.asarray(s, float) ** 2 if use_w else np.ones(n)
    out = dict(n=n, slope=np.nan, s_slope=np.nan, t0=np.nan, s_t0=np.nan, r2=np.nan, weighted=use_w, ok=False)
    X = np.column_stack([t, N])
    if n < 2 or np.linalg.matrix_rank(X) < 2:
        return out
    A = X.T @ (w[:, None] * X)
    try:
        Ainv = np.linalg.inv(A)
    except np.linalg.LinAlgError:
        return out
    a, b = Ainv @ (X.T @ (w * y))
    res = y - X @ np.array([a, b])
    dof = n - 2
    if use_w:
        k = max(np.sum(w * res ** 2) / dof, 1.0) if dof > 0 else 1.0
        cov = Ainv * k
    elif dof > 0:
        cov = Ainv * (np.sum(res ** 2) / dof)
    else:
        cov = np.full((2, 2), np.nan)
    t0 = -b / a if a else np.nan
    var_t0 = (cov[1, 1] / a ** 2 + b ** 2 * cov[0, 0] / a ** 4 - 2 * b * cov[0, 1] / a ** 3) if a else np.nan
    ss_tot = np.sum((y - y.mean()) ** 2)
    out.update(slope=a, s_slope=math.sqrt(cov[0, 0]) if np.isfinite(cov[0, 0]) else np.nan, t0=t0,
               s_t0=math.sqrt(var_t0) if np.isfinite(var_t0) and var_t0 >= 0 else np.nan,
               r2=1 - np.sum(res ** 2) / ss_tot if ss_tot > 0 else np.nan, ok=True)
    return out


def linfit(x, y, s=None, origin=False):
    """加權線性擬合。回傳 dict(slope, s_slope, intercept, s_intercept, r2, n)。"""
    x, y = np.asarray(x, float), np.asarray(y, float)
    n = x.size
    use_w = s is not None and np.all(np.asarray(s) > 0)
    w = 1.0 / np.asarray(s, float) ** 2 if use_w else np.ones(n)
    out = dict(n=n, slope=np.nan, s_slope=np.nan, intercept=0.0 if origin else np.nan, s_intercept=np.nan,
               r2=np.nan, weighted=use_w)
    if origin:
        sxx = np.sum(w * x * x)
        if n < 1 or sxx == 0:
            return out
        b = np.sum(w * x * y) / sxx
        res = y - b * x
        dof = n - 1
        out["slope"] = b
        if use_w:
            chi = np.sum(w * res ** 2) / dof if dof > 0 else 1.0
            out["s_slope"] = math.sqrt(1 / sxx * max(chi, 1.0))
        elif dof > 0:
            out["s_slope"] = math.sqrt(np.sum(res ** 2) / dof / np.sum(x * x))
    else:
        S, Sx, Sy = w.sum(), np.sum(w * x), np.sum(w * y)
        Sxx, Sxy = np.sum(w * x * x), np.sum(w * x * y)
        D = S * Sxx - Sx * Sx
        if n < 2 or D == 0:
            return out
        b = (S * Sxy - Sx * Sy) / D
        a = (Sxx * Sy - Sx * Sxy) / D
        res = y - (a + b * x)
        dof = n - 2
        out.update(slope=b, intercept=a)
        if use_w:
            chi = np.sum(w * res ** 2) / dof if dof > 0 else 1.0
            k = max(chi, 1.0)                         # 點的散布比誤差棒大時，放大誤差（保守）
            out.update(s_slope=math.sqrt(S / D * k), s_intercept=math.sqrt(Sxx / D * k))
        elif dof > 0:
            s2 = np.sum(res ** 2) / dof
            out.update(s_slope=math.sqrt(s2 * S / D), s_intercept=math.sqrt(s2 * Sxx / D))
    fit = out["intercept"] + out["slope"] * x
    ss_tot = np.sum((y - y.mean()) ** 2)
    out["r2"] = 1 - np.sum((y - fit) ** 2) / ss_tot if ss_tot > 0 else np.nan
    return out


@analysis("Etching", "多時間線性擬合", group="參數萃取", icon="⟋", order=10,
          params=[
              P("y", "擬合哪個深度", "材料蝕刻深度", choices=list(Y)),
              P("model", "延遲模型", MODELS[0], choices=MODELS,
                tip="每段都要重新點火時，延遲會累加：選「每段都有延遲」，擬合 d = r·(t − N·t₀)。"
                    "需要不同的時間或不同的分段數（例如 40 s 一次、2×20 s）"),
              P("by_width", "不同線寬分開擬合", True),
              P("weighted", "依誤差加權（1/σ²）", True),
              P("origin", "強制通過原點", False, tip="勾選 = 假設沒有起始延遲；不勾 = 擬合截距，可以看出延遲"),
          ],
          help="同一個配方、做了好幾個不同蝕刻時間的紀錄：蝕刻深度對時間做線性擬合，斜率就是蝕刻率，"
               "比單一時間的 d / t 更準（不受電漿起始延遲影響）。蝕穿的紀錄只是下限，不放進擬合。")
def etch_time_fit(fig, items, p, data=None):
    if not items or items[0].data.df.empty:
        return Result(text="沒有紀錄")
    df = items[0].data.df.copy()
    ycol, scol = Y[p["y"]]
    df = df[np.isfinite(df[ycol]) & np.isfinite(df["T (sec)"])]
    if df.empty:
        return Result(text=f"選到的紀錄沒有「{ycol}」或時間")
    ax = fig.add_subplot()
    rows, lines, warns = [], [], []
    k = 0
    groups = list(recipe_groups(df))
    for gi, (label, mask) in enumerate(groups):
        tag = recipe_tag(gi, len(groups))
        sub = df[mask]
        widths = [None]
        if p["by_width"]:
            widths = list(dict.fromkeys(sub["Line width (nm)"].tolist()))
        for wv in widths:
            g = sub if wv is None else sub[(sub["Line width (nm)"] == wv) | (pd.isna(wv) & sub["Line width (nm)"].isna())]
            if g.empty:
                continue
            color = PALETTE[k % len(PALETTE)]
            k += 1
            wtxt = "" if wv is None or (isinstance(wv, float) and wv != wv) else f"｜線寬 {wv:g} nm"
            name = f"{label}{wtxt}"
            short = "｜".join(x for x in (tag, wtxt.strip("｜")) if x) or "全部"
            thr = g["Etched through"].to_numpy(bool)
            ok = g[~thr]
            t, d = ok["T (sec)"].to_numpy(float), ok[ycol].to_numpy(float)
            Nst = ok["N steps"].fillna(1).clip(lower=1).to_numpy(float) if "N steps" in ok else np.ones(len(ok))
            s = ok[scol].to_numpy(float) if scol in ok else np.full(len(ok), np.nan)
            seg = p.get("model", MODELS[0]) == MODELS[1]
            nvals = sorted(set(Nst.astype(int).tolist()))
            for j, nv in enumerate(nvals):
                m = Nst.astype(int) == nv
                lab = short if j == 0 else "_nolegend_"
                ax.errorbar(t[m], d[m], yerr=np.nan_to_num(s[m]), fmt=MARKERS[(nv - 1) % len(MARKERS)] if seg else "o",
                            color=color, ms=6, capsize=3, label=lab)
            if thr.any():
                ax.plot(g["T (sec)"][thr], g[ycol][thr], "^", mfc="white", mec=color, ms=8, mew=1.5,
                        label=f"{short}（蝕穿）")
            n_t = len(set(zip(np.round(t, 6), Nst))) if seg else len(set(np.round(t, 6)))
            if n_t < 2:
                warns.append(f"{name}：只有 {n_t} 個不同的蝕刻時間，無法擬合（至少要 2 個，建議 3 個以上）")
                continue
            tt = np.linspace(0, t.max() * 1.05, 50)
            if seg:
                fit = segfit(t, Nst, d, s if p["weighted"] else None)
                if not fit["ok"]:
                    warns.append(f"{name}：時間和分段數成固定比例（例如只有 1×20、2×20、3×20），"
                                 f"分不出蝕刻率和每段延遲；請加一筆一次蝕刻、時間不同的紀錄")
                    continue
                for j, nv in enumerate(nvals):
                    ax.plot(tt, fit["slope"] * (tt - nv * fit["t0"]), DASHES[(nv - 1) % len(DASHES)], color=color, lw=1.3,
                            gid="nohover")
                rows.append({"配方": label, "線寬 (nm)": wv, "模型": "每段延遲", "點數": fit["n"],
                             "蝕刻率 (nm/s)": fit["slope"], "σ 蝕刻率": fit["s_slope"], "截距 (nm)": np.nan,
                             "σ 截距": np.nan, "起始延遲 (s)": np.nan, "每段延遲 t₀ (s)": fit["t0"],
                             "σ t₀ (s)": fit["s_t0"], "R²": fit["r2"], "加權": fit["weighted"],
                             "排除（蝕穿）": int(thr.sum())})
                st = "" if not np.isfinite(fit["s_slope"]) else f" ± {fit['s_slope']:.3g}"
                dl = "" if not np.isfinite(fit["s_t0"]) else f" ± {fit['s_t0']:.2g}"
                lines.append(f"{name}：r = {fit['slope']:.4g}{st} nm/s，每段延遲 t₀ = {fit['t0']:.2f}{dl} s"
                             f"（{fit['n']} 點，分段數 {', '.join(map(str, nvals))}，R² = {fit['r2']:.3f}）")
                if len(nvals) == 1:
                    warns.append(f"{name}：所有紀錄都是 {nvals[0]} 段，t₀ 等於「整段延遲 ÷ {nvals[0]}」；"
                                 f"要分辨兩種模型，需要不同分段數的紀錄")
                continue
            fit = linfit(t, d, s if p["weighted"] else None, p["origin"])
            ax.plot(tt, fit["intercept"] + fit["slope"] * tt, "-", color=color, lw=1.4, gid="nohover")
            delay = -fit["intercept"] / fit["slope"] if (not p["origin"] and fit["slope"] > 0) else np.nan
            rows.append({"配方": label, "線寬 (nm)": wv, "模型": "整段一次", "點數": fit["n"],
                         "蝕刻率 (nm/s)": fit["slope"], "σ 蝕刻率": fit["s_slope"], "截距 (nm)": fit["intercept"],
                         "σ 截距": fit["s_intercept"], "起始延遲 (s)": delay, "每段延遲 t₀ (s)": np.nan,
                         "σ t₀ (s)": np.nan, "R²": fit["r2"], "加權": fit["weighted"],
                         "排除（蝕穿）": int(thr.sum())})
            st = "" if not np.isfinite(fit["s_slope"]) else f" ± {fit['s_slope']:.3g}"
            dl = "" if not np.isfinite(delay) else f"，起始延遲 {delay:.2f} s"
            lines.append(f"{name}：r = {fit['slope']:.4g}{st} nm/s（{fit['n']} 點，R² = {fit['r2']:.3f}{dl}）")
            if fit["n"] == 2:
                warns.append(f"{name}：只有 2 點，直線一定通過，無法判斷線性好不好")
    ax.axhline(0, color="#9ca3af", lw=0.8)
    ax.axvline(0, color="#9ca3af", lw=0.8)
    ax.set_xlabel("蝕刻時間 t (s)（分段時為加總）")
    ax.set_ylabel(f"{p['y'].replace('材料', material_name(df))} (nm)")
    ax.legend(fontsize=8, loc="upper left", bbox_to_anchor=(1.01, 1.0), borderaxespad=0)
    recipe_title(ax, [lb for lb, _ in groups])
    if not rows:
        lines.append("沒有可以擬合的組合：需要同一個配方（材料、機台、氣體、功率、壓力、光阻相同）"
                     "做過 2 個以上不同的蝕刻時間")
    hint = ("每段延遲模型：○ 1 段、□ 2 段、◇ 3 段…；實線 = 1 段、虛線 = 2 段、點線 = 3 段的擬合線"
            if p.get("model", MODELS[0]) == MODELS[1] else "")
    return Result(text="\n".join(lines), tables={"time_fit": pd.DataFrame(rows)}, warnings=warns, hint=hint,
                  summary={r["配方"] + (f"｜{r['線寬 (nm)']:g}" if isinstance(r["線寬 (nm)"], float)
                                       and r["線寬 (nm)"] == r["線寬 (nm)"] else ""): r["蝕刻率 (nm/s)"] for r in rows})
