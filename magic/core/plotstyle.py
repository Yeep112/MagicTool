"""matplotlib 的字型與樣式（介面、Jupyter、自我測試共用；取自 LowTempAnalysis 的 theme.apply_mpl_style）。

重點：中文要「逐一列出字型名稱」matplotlib 才會逐字備援；英文、符號（μ Ω ⁻¹）用 DejaVu Sans。
"""
from __future__ import annotations

import os

PLOT_CYCLE = ["#2563eb", "#e4572e", "#17a398", "#f2a541", "#7c3aed", "#ef476f",
              "#118ab2", "#8d6a9f", "#06d6a0", "#5c6b73"]
_CJK_PREF = ["Microsoft JhengHei", "Microsoft YaHei", "PMingLiU", "PingFang TC", "Noto Sans CJK TC",
             "Noto Sans CJK JP", "Noto Sans CJK SC", "Source Han Sans TC", "Arial Unicode MS"]
_applied = False


def _windows_cjk_fonts():
    from matplotlib import font_manager
    fonts_dir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    names = []
    if not os.path.isdir(fonts_dir):
        return names
    for fn in ("msjh.ttc", "msjhbd.ttc", "msjh.ttf", "msyh.ttc", "mingliu.ttc"):
        path = os.path.join(fonts_dir, fn)
        if os.path.exists(path):
            try:
                font_manager.fontManager.addfont(path)
                name = font_manager.FontProperties(fname=path).get_name()
                if name not in names:
                    names.append(name)
            except Exception:
                pass
    return names


def cjk_fonts():
    from matplotlib import font_manager
    found = _windows_cjk_fonts()
    have = {f.name for f in font_manager.fontManager.ttflist}
    return found + [f for f in _CJK_PREF if f in have and f not in found]


def apply(force=False):
    """設定字型、配色、格線。重複呼叫沒有影響。"""
    global _applied
    if _applied and not force:
        return
    import matplotlib
    from cycler import cycler
    rc = matplotlib.rcParams
    cjk = cjk_fonts()
    order = ["DejaVu Sans"] + cjk
    rc["font.sans-serif"] = order
    rc["font.family"] = order
    rc["axes.unicode_minus"] = False
    rc.update({
        "figure.facecolor": "white", "axes.facecolor": "white",
        "axes.edgecolor": "#a3acb9", "axes.linewidth": 0.9,
        "axes.labelcolor": "#374151", "axes.labelsize": 11, "axes.titlesize": 11,
        "axes.titleweight": "bold", "axes.titlecolor": "#1f2937",
        "axes.grid": True, "grid.color": "#e8ecf2", "grid.linewidth": 0.8,
        "axes.prop_cycle": cycler(color=PLOT_CYCLE),
        "xtick.color": "#4b5563", "ytick.color": "#4b5563",
        "xtick.direction": "in", "ytick.direction": "in",
        "lines.linewidth": 1.4, "legend.frameon": False, "legend.fontsize": 8,
        "font.size": 10, "figure.dpi": 100, "savefig.facecolor": "white",
    })
    _applied = True


DEFAULT_STYLE = dict(grid=True, xlabel=12, ylabel=12, cbar=12, ticks=10, legend=8, title=11)


def colorbar_axes(fig):
    out = set()
    for ax in fig.axes:
        for coll in list(ax.collections) + list(ax.images):
            cb = getattr(coll, "colorbar", None)
            if cb is not None:
                out.add(cb.ax)
    return out


def apply_style(fig, st=None):
    """把格線、各種字體大小套到圖上（畫完之後套用，改設定時不必重新計算）。"""
    st = {**DEFAULT_STYLE, **(st or {})}
    cbars = colorbar_axes(fig)
    for ax in fig.axes:
        if ax in cbars:
            ax.yaxis.label.set_size(st["cbar"])
            ax.xaxis.label.set_size(st["cbar"])
            ax.tick_params(labelsize=st["ticks"])
            continue
        if not ax.axison:
            continue
        ax.grid(bool(st["grid"]))
        ax.xaxis.label.set_size(st["xlabel"])
        ax.yaxis.label.set_size(st["ylabel"])
        ax.tick_params(labelsize=st["ticks"])
        if ax.get_title():
            ax.title.set_size(st["title"])
        for t in (getattr(ax, "_left_title", None), getattr(ax, "_right_title", None)):
            if t is not None and t.get_text():
                t.set_size(min(st["title"], st["title"] * 0.8 if "\n" in t.get_text() else st["title"]))
        leg = ax.get_legend()
        if leg is not None:
            for t in leg.get_texts():
                t.set_fontsize(st["legend"])
            if leg.get_title() is not None:
                leg.get_title().set_fontsize(st["legend"] + 1)
    for leg in getattr(fig, "legends", []):
        for t in leg.get_texts():
            t.set_fontsize(st["legend"])
