"""Raman：背景扣除比較（多項式只用無峰區 / ALS / 指數），可匯出扣背景後的光譜。"""
import numpy as np
import pandas as pd

from ..core.peaks import BASELINES, MANUAL, baseline
from ..core.registry import P, Result, analysis
from ..core.units import decimate, in_range
from ..readers.raman_txt import xy
from ._common import anchor_kw, parse_windows


def _compute(items, p, progress):
    out = []
    excl = parse_windows(p["exclude"])
    methods = BASELINES[1:]
    for k, it in enumerate(items):
        x, y = xy(it.data)
        bgs = {}
        for mth in methods:
            if mth == MANUAL and not it.data.header.get("anchors") and p["method"] != MANUAL:
                continue                                 # 沒有錨點就不畫手動背景（除非選的就是它）
            try:
                bgs[mth] = baseline(x, y, mth, degree=int(p["degree"]), exclude=excl, lam=p["lam"], p=p["p"],
                                    **anchor_kw(it.data))
            except Exception as e:                      # 某個方法失敗不影響其他方法
                bgs[mth] = np.full_like(y, np.nan)
                bgs[mth + "（失敗）"] = str(e)
        out.append(dict(item=it, x=x, y=y, bgs=bgs))
        progress(k + 1, len(items), it.label)
    return out


@analysis("Raman", "背景扣除", group="參數萃取", icon="⌁", order=20,
          params=[
              P("method", "使用的背景", BASELINES[1], choices=BASELINES[1:]),
              P("degree", "多項式階數", 3),
              P("exclude", "有峰的範圍（不用來擬合背景）", "1320-1400, 1540-1630, 2620-2780"),
              P("lam", "ALS 平滑度 λ", 1e5, tip="越大越平滑（10⁴–10⁷）"),
              P("p", "ALS 不對稱 p", 0.01, tip="越小越貼近底部（0.001–0.05）"),
              P("compare", "同時畫出其他方法", True),
              P("x_range", "顯示範圍 (cm⁻¹)", "", kind="range"),
          ],
          compute=_compute,
          help="比較幾種背景的擬合結果，選一種扣除。匯出的 CSV 有原始、背景、扣背景後三欄。"
               "多項式與指數只用「有峰的範圍」以外的點擬合，背景不會被峰拉高。")
def raman_background(fig, items, p, data=None):
    rows = data or []
    if not rows:
        return Result(text="沒有資料")
    ax1 = fig.add_subplot(2, 1, 1)
    ax2 = fig.add_subplot(2, 1, 2, sharex=ax1)
    tables, lines, warns = {}, [], []
    style = {BASELINES[1]: "#e4572e", BASELINES[2]: "#17a398", BASELINES[3]: "#7c3aed", MANUAL: "#f2a541"}
    for k, r in enumerate(rows):
        x, y = r["x"], r["y"]
        m = in_range(x, p["x_range"])
        xs, ys = decimate(x[m], y[m])
        ax1.plot(xs, ys, color=r["item"].color, lw=1, label=r["item"].label if len(rows) > 1 else "原始")
        for mth, bg in r["bgs"].items():
            if mth.endswith("（失敗）"):
                warns.append(f"{r['item'].label}：{mth} {bg}")
                continue
            if mth == p["method"] or (p["compare"] and k == 0):
                ax1.plot(x[m], bg[m], "--" if mth == p["method"] else ":", color=style.get(mth, "k"),
                         lw=1.6 if mth == p["method"] else 1.1, label=mth if k == 0 else None, gid="nohover")
        bg = r["bgs"][p["method"]]
        corr = y - bg
        xs, cs = decimate(x[m], corr[m])
        ax2.plot(xs, cs, color=r["item"].color, lw=1.1, label=r["item"].label)
        tables[f"corrected_{r['item'].label}"] = pd.DataFrame(
            {"Raman shift (cm-1)": x, "Intensity raw": y, "Baseline": bg, "Intensity corrected": corr})
        neg = float(np.mean(corr < -3 * np.std(np.diff(y)) / np.sqrt(2)))
        lines.append(f"{r['item'].label}：{p['method']}，扣除後低於 0 的點約 {neg * 100:.1f}%")
    ax1.set_ylabel("Intensity")
    ax1.legend(fontsize=8)
    ax2.axhline(0, color="#9ca3af", lw=0.8)
    ax2.set_xlabel("Raman shift (cm$^{-1}$)")
    ax2.set_ylabel(f"扣背景後（{p['method']}）")
    if len(rows) <= 12:
        ax2.legend(fontsize=8)
    lines.append("\n低於 0 的點很多：背景太高（多項式階數太高、或排除範圍沒有蓋到峰）")
    return Result(text="\n".join(lines), tables=tables, warnings=warns)
