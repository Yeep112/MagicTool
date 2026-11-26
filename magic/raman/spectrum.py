"""Raman 快速檢視：光譜疊圖（可平移、正規化、扣背景）。"""
import numpy as np

from ..core.peaks import BASELINES, baseline
from ..core.registry import P, Result, analysis
from ..core.units import decimate, in_range
from ..readers.raman_txt import xy
from ._common import parse_windows


@analysis("Raman", "光譜檢視", group="快速檢視", icon="∿", order=10,
          params=[
              P("x_range", "顯示範圍 (cm⁻¹)", "", kind="range", tip="例如「1100, 3000」；空白 = 全部"),
              P("baseline", "背景", BASELINES[0], choices=BASELINES),
              P("degree", "多項式階數", 3),
              P("exclude", "背景排除範圍", "1320-1400, 1540-1630, 2620-2780", tip="有峰的範圍，多項式 / 指數背景不會用這些點"),
              P("normalize", "正規化", "不正規化", choices=["不正規化", "最大值 = 1"]),
              P("offset", "每條往上平移", 0.0, tip="疊圖時每條曲線往上移多少（正規化後的單位）"),
          ],
          help="一次看好幾條光譜。可以扣背景、正規化、平移疊圖。")
def raman_spectrum(fig, items, p, data=None):
    ax = fig.add_subplot()
    lines, warns = [], []
    for k, it in enumerate(items):
        x, y = xy(it.data)
        if p["baseline"] != BASELINES[0]:
            y = y - baseline(x, y, p["baseline"], degree=int(p["degree"]), exclude=parse_windows(p["exclude"]))
        m = in_range(x, p["x_range"])
        if not m.any():
            warns.append(f"{it.label}：顯示範圍內沒有資料")
            continue
        xs, ys = x[m], y[m]
        if p["normalize"] == "最大值 = 1":
            top = np.nanmax(ys)
            if top > 0:
                ys = ys / top
        xs, ys = decimate(xs, ys)
        ax.plot(xs, ys + k * p["offset"], color=it.color, lw=1.1, label=it.label)
        lines.append(f"{it.label}：{x.size} 點，{x.min():.1f}–{x.max():.1f} cm⁻¹")
        warns += [f"{it.label}：{n}" for n in it.data.notes]
    ax.set_xlabel("Raman shift (cm$^{-1}$)")
    ax.set_ylabel("Intensity" + ("（正規化）" if p["normalize"] != "不正規化" else "") +
                  ("（已扣背景）" if p["baseline"] != BASELINES[0] else ""))
    if len(items) <= 15:
        ax.legend(fontsize=8)
    return Result(text="\n".join(lines), warnings=warns)
