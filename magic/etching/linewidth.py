"""Etching 批次比較：不同線寬的蝕刻率（其他參數固定）。

線寬越窄，電漿中的離子與自由基越不容易進到溝槽底部（loading / aspect-ratio dependent etching），
蝕刻率通常會變低。比較時其他參數必須一樣：程式會把選到的紀錄依配方
（材料、機台、氣體與流量、ICP / RF 功率、DC bias、壓力、光阻）分組，每一組各畫一條線。
"""
import numpy as np
import pandas as pd

from ..core.registry import P, Result, analysis
from ._common import (PALETTE, R_MAT, R_SIO2, SIG, different_columns, material_name, recipe_groups, recipe_tag,
                      recipe_title)

YCOL = {"材料蝕刻率": R_MAT, "SiO2 蝕刻率": R_SIO2}


@analysis("Etching", "線寬比較", group="批次比較", icon="⫴", order=20,
          params=[
              P("y", "Y 軸", "材料蝕刻率", choices=list(YCOL)),
              P("log_x", "線寬用對數座標", True),
              P("normalize", "除以最寬線寬的蝕刻率", False, tip="不同配方之間比較「變慢多少」時用"),
              P("skip_through", "蝕穿的紀錄不算進平均", True, tip="蝕穿只是下限；排除後另外畫成空心三角形"),
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
    rows, lines = [], []
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
            rows.append({"配方": label, "線寬 (nm)": wv, "筆數": len(v), "蝕刻率 (nm/s)": m, "σ": e,
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
    return Result(text="\n".join(lines), tables={"linewidth": pd.DataFrame(rows)}, warnings=notes,
                  summary={"groups": k}, hint="▲ = 含蝕穿的紀錄（只是下限）")
