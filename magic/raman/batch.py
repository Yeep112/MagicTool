"""Raman 批次比較：多個檔案的峰值總表與趨勢圖。"""
import numpy as np

from ..core.registry import Result, analysis
from . import _common as C


def _compute(items, p, progress):
    return C.compute(items, p, progress)


@analysis("Raman", "多檔峰值總表", group="批次比較", icon="▦", order=10,
          params=C.peak_params(), compute=_compute,
          help="選一個資料夾裡的很多光譜：每個檔案的 G / 2D 位置、FWHM、I(2D)/I(G) 一次列成表（取代原本的快速版 cell），"
               "並畫成四張小圖方便比較。")
def raman_batch(fig, items, p, data=None):
    rows = data or []
    if not rows:
        return Result(text="沒有資料")
    names = [r["item"].label for r in rows]
    colors = [r["item"].color for r in rows]
    xs = np.arange(len(rows))

    def val(r, name, key):
        f = r["fits"].get(name)
        return f[key] if f and f["ok"] else np.nan
    panels = [
        ("I(2D)/I(G)", [r["ratio"] for r in rows], "bar"),
        ("2D FWHM (cm⁻¹)", [val(r, "2D", "fwhm") for r in rows], "bar"),
        ("G 位置 (cm⁻¹)", [val(r, "G", "pos") for r in rows], "dot"),
        ("2D 位置 (cm⁻¹)", [val(r, "2D", "pos") for r in rows], "dot"),
    ]
    for k, (title, vals, kind) in enumerate(panels, 1):
        ax = fig.add_subplot(2, 2, k)
        v = np.asarray(vals, float)
        if kind == "bar":
            ax.bar(xs, np.nan_to_num(v), color=colors, alpha=0.85)
        else:
            ax.plot(xs, v, "o-", color="#6b7280", lw=0.8, ms=0)
            ax.scatter(xs, v, c=colors, s=36, zorder=3)
        ax.set_title(title)
        ax.set_xticks(xs)
        ax.set_xticklabels(names if len(rows) <= 12 else [str(i + 1) for i in xs],
                           rotation=35, ha="right", fontsize=7)
        if k == 1:
            ax.axhline(2, color="#9ca3af", ls=":", lw=1)
    warns = [f"{r['item'].label}：{n} {f['reason']}" for r in rows for n, f in r["fits"].items() if not f["ok"]]
    return Result(text=C.text_rows(rows), tables={"peak_summary": C.summary_rows(rows)},
                  summary={"files": len(rows)}, warnings=warns,
                  hint="第一張圖的虛線：I(2D)/I(G) = 2")
