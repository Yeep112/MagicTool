"""Raman：石墨烯 G / 2D 峰（取代原 notebook 的 monolayer / multilayer / hybrid 幾個 cell）。"""
import numpy as np

from ..core.registry import P, Result, analysis
from ..core.units import decimate
from . import _common as C
from .labels import register_peak

COLORS = {"G": "#e4572e", "2D": "#2563eb", "hBN": "#17a398", "D": "#7c3aed"}


def _compute(items, p, progress):
    return C.compute(items, p, progress)


def _mark(ax, f, name, offset=0.0, show_fit=True, series=0):
    """畫擬合曲線，並告訴標註系統峰的位置（文字由「🏷 峰標註」決定：文字、顏色、大小、字型都可以改）。"""
    if not f["ok"]:
        return
    if show_fit and f["x_fit"].size:
        ax.plot(f["x_fit"], f["y_fit"] + offset, "--", color=COLORS.get(name, "k"), lw=1.2, gid="nohover")
    top = f["height"] + (f["offset"] if np.isfinite(f["offset"]) else 0) + offset
    register_peak(ax, name, f["pos"], top, series)


@analysis("Raman", "石墨烯 G / 2D 峰", group="參數萃取", icon="G", order=10,
          params=C.peak_params() + [P("x_range", "顯示範圍 (cm⁻¹)", "1100, 3000", kind="range")],
          compute=_compute,
          help="扣背景後在指定範圍內找 G、2D（可加 hBN、D）峰，Lorentzian 擬合求峰位、FWHM、高度與面積，"
               "算 I(2D)/I(G)。選一個檔案顯示背景與擬合細節；選多個檔案則疊圖比較。")
def raman_graphene(fig, items, p, data=None):
    rows = data or []
    if not rows:
        return Result(text="沒有資料")
    warns = []
    if len(rows) == 1:
        r = rows[0]
        ax1 = fig.add_subplot(2, 1, 1)
        ax2 = fig.add_subplot(2, 1, 2, sharex=ax1)
        m = C.mask(r["x"], p["x_range"])
        xs, ys = decimate(r["x"][m], r["y"][m])
        ax1.plot(xs, ys, color="#374151", lw=1, label="原始")
        ax1.plot(r["x"][m], r["bg"][m], "--", color="#e4572e", lw=1.4, label=f"背景（{p['baseline']}）")
        ax1.set_ylabel("Intensity")
        ax1.legend(fontsize=8, loc="upper left")
        ax1.set_title(r["item"].label)
        xs, cs = decimate(r["x"][m], r["corr"][m])
        ax2.plot(xs, cs, color=r["item"].color, lw=1.1,
                 label=f"I(2D)/I(G) = {C.fmt(r['ratio'], 3)}")
        for name, f in r["fits"].items():
            _mark(ax2, f, name)
            if f["ok"] and np.isfinite(f["fwhm"]):
                lo, hi = f["pos"] - f["fwhm"] / 2, f["pos"] + f["fwhm"] / 2
                half = f["height"] / 2 + (f["offset"] if np.isfinite(f["offset"]) else 0)
                ax2.annotate("", (hi, half), (lo, half), arrowprops=dict(arrowstyle="<->", color=COLORS.get(name), lw=1))
        ax2.axhline(0, color="#9ca3af", lw=0.8)
        ax2.set_xlabel("Raman shift (cm$^{-1}$)")
        ax2.set_ylabel("扣背景後")
        ax2.legend(fontsize=9, loc="upper left")
        lo, hi = p["x_range"]
        if lo is not None or hi is not None:
            ax2.set_xlim(lo, hi)
        top = max([f["height"] + (f["offset"] if np.isfinite(f["offset"]) else 0)
                   for f in r["fits"].values() if f["ok"]] or [np.nanmax(cs)])
        ax2.set_ylim(min(np.nanmin(cs), 0) - 0.05 * top, top * 1.3)
    else:
        ax = fig.add_subplot()
        off = 0.0
        for k, r in enumerate(rows):
            m = C.mask(r["x"], p["x_range"])
            xs, cs = decimate(r["x"][m], r["corr"][m])
            ax.plot(xs, cs + off, color=r["item"].color, lw=1.1,
                    label=f"{r['item'].label}（2D/G = {C.fmt(r['ratio'], 2)}）")
            for name, f in r["fits"].items():
                _mark(ax, f, name, off, show_fit=False, series=k)
            off += (np.nanmax(cs) if cs.size else 0) * 1.15
        ax.set_xlabel("Raman shift (cm$^{-1}$)")
        ax.set_ylabel("扣背景後（平移疊圖）")
        ax.legend(fontsize=8, loc="upper left")
    for r in rows:
        for name, f in r["fits"].items():
            if not f["ok"]:
                warns.append(f"{r['item'].label}：{name} {f['reason']}")
            elif f["reason"]:
                warns.append(f"{r['item'].label}：{name} {f['reason']}")
    table = C.summary_rows(rows)
    summary = {r["item"].label: {"ratio_2D_G": r["ratio"],
                                 **{f"{n}_pos": f["pos"] for n, f in r["fits"].items()},
                                 **{f"{n}_fwhm": f["fwhm"] for n, f in r["fits"].items()}} for r in rows}
    return Result(text=C.text_rows(rows), tables={"peaks": table}, summary=summary, warnings=warns)
