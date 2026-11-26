"""Etching 批次比較：不同線寬的蝕刻率（其他參數固定）。

線寬越窄，電漿中的離子與自由基越不容易進到溝槽底部（loading / aspect-ratio dependent etching），
蝕刻率通常會變低。比較時其他參數必須一樣：程式會把選到的紀錄依配方
（材料、機台、氣體與流量、ICP / RF 功率、DC bias、壓力、光阻）分組，每一組各畫一條線。

線寬模型（選用）：r(w) = r∞ · (1 − exp(−w / w₀))
  r∞ = 很寬的開口（不受線寬影響）時的蝕刻率；w₀ = 特徵線寬（線寬 = w₀ 時蝕刻率約剩 63%）
蝕刻率來源可以選「多時間擬合的斜率」：同一線寬有好幾個時間時，用 d 對 t 的斜率（扣掉電漿起始延遲），
比每筆 d / t 的平均更準。
"""
import numpy as np
import pandas as pd

from ..core.registry import P, Result, analysis
from ._common import (PALETTE, R_MAT, R_SIO2, SIG, different_columns, material_name, recipe_groups, recipe_tag,
                      recipe_title)

YCOL = {"材料蝕刻率": R_MAT, "SiO2 蝕刻率": R_SIO2}
DEPTH = {R_MAT: ("d_material (nm)", "σ d_material (nm)"), R_SIO2: ("d_SiO2 (nm)", "σ d_SiO2 (nm)")}
SOURCES = ["每筆 d / t 的平均", "多時間擬合的斜率（扣掉起始延遲）"]


def wmodel(w, r_inf, w0):
    return r_inf * (1 - np.exp(-np.asarray(w, float) / w0))


def fit_width_model(w, r, s=None):
    """r(w) = r∞(1 − e^(−w/w₀)) 擬合。回傳 dict(r_inf, s_r_inf, w0, s_w0, r2, n, ok, reason)。"""
    from scipy.optimize import curve_fit
    w, r = np.asarray(w, float), np.asarray(r, float)
    out = dict(r_inf=np.nan, s_r_inf=np.nan, w0=np.nan, s_w0=np.nan, r2=np.nan, n=int(w.size), ok=False, reason="")
    good = np.isfinite(w) & np.isfinite(r) & (w > 0)
    w, r = w[good], r[good]
    if s is not None:
        s = np.asarray(s, float)[good]
        if not np.all(s > 0):
            s = None
    if w.size < 3:
        out["reason"] = "至少要 3 種線寬才能擬合（2 個參數）"
        return out
    p0 = [float(np.max(r)) * 1.05, float(np.median(w))]
    try:
        popt, pcov = curve_fit(wmodel, w, r, p0=p0, sigma=s, absolute_sigma=False,
                               bounds=([0, 1e-3], [np.inf, 1e7]), maxfev=20000)
    except Exception as e:
        out["reason"] = f"擬合沒有收斂（{e}）"
        return out
    err = np.sqrt(np.diag(pcov)) if np.all(np.isfinite(pcov)) else [np.nan, np.nan]
    fit = wmodel(w, *popt)
    ss = np.sum((r - r.mean()) ** 2)
    out.update(r_inf=popt[0], w0=popt[1], s_r_inf=err[0], s_w0=err[1], ok=True,
               r2=1 - np.sum((r - fit) ** 2) / ss if ss > 0 else np.nan)
    if popt[1] > 5 * w.max():
        out["reason"] = "w₀ 比最寬的線寬還大很多：還沒看到飽和，r∞ 不可靠（需要更寬的線寬）"
    elif popt[1] < 0.2 * w.min():
        out["reason"] = "w₀ 比最窄的線寬還小很多：線寬效應不明顯，w₀ 不可靠"
    return out


@analysis("Etching", "線寬比較", group="批次比較", icon="⫴", order=20,
          params=[
              P("y", "Y 軸", "材料蝕刻率", choices=list(YCOL)),
              P("log_x", "線寬用對數座標", True),
              P("normalize", "除以最寬線寬的蝕刻率", False, tip="不同配方之間比較「變慢多少」時用"),
              P("skip_through", "蝕穿的紀錄不算進平均", True, tip="蝕穿只是下限；排除後另外畫成空心三角形"),
              P("source", "蝕刻率來源", SOURCES[0], choices=SOURCES,
                tip="同一線寬做過好幾個時間時，選「多時間擬合的斜率」比較準（不受電漿起始延遲影響）"),
              P("fit_model", "擬合 r(w) = r∞(1 − e^(−w/w₀))", True,
                tip="r∞ = 不受線寬影響的蝕刻率；w₀ = 特徵線寬（線寬 = w₀ 時蝕刻率剩約 63%）。至少要 3 種線寬"),
          ],
          help="選好幾筆不同線寬的紀錄：每個配方（其他參數都一樣）畫一條「蝕刻率 vs 線寬」。"
               "同一線寬有好幾筆時取平均 ± 標準差。參數不同的紀錄會自動分到不同組，不會混在一起比。")
def etch_linewidth(fig, items, p, data=None):
    if not items or items[0].data.df.empty:
        return Result(text="沒有紀錄")
    df = items[0].data.df.copy()
    ycol = YCOL[p["y"]]
    no_w = df["Line width (nm)"].isna()
    notes = []
    if no_w.any():
        notes.append(f"沒有填線寬的 {int(no_w.sum())} 筆不列入（編號 {', '.join(map(str, df['#'][no_w]))}）")
    df = df[~no_w & np.isfinite(df[ycol])]
    if df.empty:
        return Result(text="選到的紀錄都沒有線寬。新增紀錄時在「樣品」填 pattern 線寬。", warnings=notes)
    diff = different_columns(df)
    if diff:
        notes.append("選到的紀錄裡這些參數不同，已依配方分組（每組各一條線）：" + "；".join(diff))
    ax = fig.add_subplot()
    rows, lines, fits = [], [], []
    k = 0
    plottable = []
    for label, mask in recipe_groups(df):
        widths = sorted(set(df[mask]["Line width (nm)"]))
        if len(widths) < 2:
            notes.append(f"「{label}」只有一種線寬（{widths[0]:g} nm），無法比較")
        else:
            plottable.append((label, mask, widths))
    for label, mask, widths in plottable:
        g = df[mask]
        tag = recipe_tag(k, len(plottable)) or "平均 ± σ"
        color = PALETTE[k % len(PALETTE)]
        k += 1
        xs, ys, es, lb = [], [], [], []
        through_pts = []
        for wv in widths:
            gw_all = g[g["Line width (nm)"] == wv]
            thr = gw_all["Etched through"].to_numpy(bool)
            gw = gw_all[~thr] if (p["skip_through"] and (~thr).any()) else gw_all
            if p["skip_through"] and thr.any():
                for _, rr in gw_all[thr].iterrows():
                    through_pts.append((wv, rr[ycol]))
            v = gw[ycol].to_numpy(float)
            how = "平均"
            m = e = None
            if p.get("source", SOURCES[0]) == SOURCES[1]:
                dcol, scol = DEPTH[ycol]
                ok = gw[np.isfinite(gw[dcol]) & np.isfinite(gw["T (sec)"])]
                if len(set(np.round(ok["T (sec)"], 6))) >= 2:
                    from .time_fit import linfit
                    fit = linfit(ok["T (sec)"], ok[dcol], ok[scol] if scol in ok else None)
                    if np.isfinite(fit["slope"]):
                        m, e, how = fit["slope"], (fit["s_slope"] if np.isfinite(fit["s_slope"]) else 0.0), "擬合"
                if m is None:
                    notes.append(f"「{label}」線寬 {wv:g} nm：只有一種蝕刻時間，用 d / t 的平均")
            if m is None:
                if len(v) > 1:
                    m, e = v.mean(), v.std(ddof=1)
                else:
                    m = v[0]
                    e = float(gw[SIG[ycol]].iloc[0]) if SIG[ycol] in gw and np.isfinite(gw[SIG[ycol]].iloc[0]) else 0.0
            xs.append(wv)
            ys.append(m)
            es.append(e)
            lb.append(bool(gw["Etched through"].any()))
            if gw is not gw_all and len(gw) < len(gw_all):
                notes.append(f"「{label}」線寬 {wv:g} nm：{int(thr.sum())} 筆蝕穿的紀錄沒有算進平均（畫成 ▲）")
            rows.append({"配方": label, "線寬 (nm)": wv, "筆數": len(v), "蝕刻率 (nm/s)": m, "σ": e, "來源": how,
                         "含蝕穿（下限）": lb[-1], "紀錄編號": ", ".join(map(str, gw["#"]))})
        xs, ys, es = np.array(xs), np.array(ys), np.array(es)
        ref = ys[np.argmax(xs)]
        if p["normalize"] and ref:
            ys, es = ys / ref, es / ref
        ax.errorbar(xs, ys, yerr=es, fmt="o-", color=color, ms=6, capsize=3, lw=1.3, label=tag)
        for x0, y0 in through_pts:
            yy = y0 / ref if (p["normalize"] and ref) else y0
            ax.plot([x0], [yy], "^", mfc="white", mec=color, ms=9, mew=1.5, label=None)
        for x0, y0, b in zip(xs, ys, lb):
            if b:
                ax.plot([x0], [y0], "^", mfc="white", mec=color, ms=10, mew=1.5, gid="nohover")
        if p.get("fit_model", True):
            mf = fit_width_model(xs, ys, es if np.all(es > 0) else None)
            if mf["ok"]:
                ww = np.geomspace(max(xs.min() * 0.5, 1e-3), xs.max() * 2, 200)
                ax.plot(ww, wmodel(ww, mf["r_inf"], mf["w0"]), "--", color=color, lw=1.2, gid="nohover")
                ax.axhline(mf["r_inf"], color=color, lw=0.7, ls=":", gid="nohover")
                fits.append({"配方": label, "r∞": mf["r_inf"], "σ r∞": mf["s_r_inf"], "w₀ (nm)": mf["w0"],
                             "σ w₀ (nm)": mf["s_w0"], "R²": mf["r2"], "線寬數": mf["n"], "備註": mf["reason"]})
                unit = "" if p["normalize"] else " nm/s"
                lines.append(f"{label}：r(w) 擬合 r∞ = {mf['r_inf']:.4g} ± {mf['s_r_inf']:.2g}{unit}，"
                             f"w₀ = {mf['w0']:.4g} ± {mf['s_w0']:.2g} nm（R² = {mf['r2']:.3f}）")
                if mf["reason"]:
                    notes.append(f"「{label}」{mf['reason']}")
            else:
                notes.append(f"「{label}」r(w) 擬合：{mf['reason']}")
        drop = (1 - ys[np.argmin(xs)] / ys[np.argmax(xs)]) * 100 if ys[np.argmax(xs)] else np.nan
        lines.append(f"{label}：線寬 {xs.min():g} → {xs.max():g} nm，蝕刻率 {ys[np.argmin(xs)]:.4g} → "
                     f"{ys[np.argmax(xs)]:.4g}{'（相對值）' if p['normalize'] else ' nm/s'}"
                     + (f"；最窄的比最寬的慢 {drop:.0f}%" if np.isfinite(drop) else ""))
    if p["log_x"]:
        ax.set_xscale("log")
    ax.set_xlabel("pattern 線寬 (nm)")
    mat = material_name(df)
    ax.set_ylabel(("相對蝕刻率（÷ 最寬線寬）" if p["normalize"] else
                   f"{'R_' + mat if ycol == R_MAT else 'R_SiO2'} (nm/s)"))
    if k:
        ax.legend(fontsize=8, loc="upper left", bbox_to_anchor=(1.01, 1.0), borderaxespad=0)
        recipe_title(ax, [lb for lb, _, _ in plottable])
    else:
        lines.append("沒有可以比較的組合：同一個配方需要至少兩種線寬")
    tables = {"linewidth": pd.DataFrame(rows)}
    if fits:
        tables["linewidth_fit"] = pd.DataFrame(fits)
    return Result(text="\n".join(lines), tables=tables, warnings=notes,
                  summary={"groups": k}, hint="▲ = 含蝕穿的紀錄（只是下限）；虛線 = r(w) 擬合、點線 = r∞")
