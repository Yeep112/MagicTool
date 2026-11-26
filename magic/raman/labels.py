"""Raman 峰標註：每個峰代表什麼（G、2D、hBN、Si…），文字、顏色、大小、字型都可以自己改。

標註設定（list of dict）存在介面的 gui_state，所有 Raman 圖共用：

    {"id": "G", "text": "G", "x": 1580, "follow": "G", "color": "#e4572e", "size": 10,
     "font": "", "bold": False, "italic": False, "show": True, "pos": True}

  follow：跟著擬合到的峰（G / 2D / hBN / D）；有擬合結果的圖放在擬合到的位置，其他圖放在 x
          「—」= 固定位置 x（例如 Si 520.7）
  pos   ：文字下面加上峰位數值
  always：（跟隨擬合的標註）沒有擬合到這個峰的圖，也放在 x 的位置；關掉 = 只在擬合到時顯示
畫在 X 軸是 Raman shift 的每一張圖上；標註可以用滑鼠拖曳（位置會記住）。
"""
from __future__ import annotations

import copy

import numpy as np

FIXED = "—（固定位置）"
FOLLOW = [FIXED, "G", "2D", "hBN", "D"]
WINDOW = 12.0                     # 沒有擬合結果的標註：在 ±12 cm⁻¹ 內找光譜的最高點放標註（數值也是那一點）

DEFAULTS = [
    dict(id="G", text="G", x=1580.0, follow="G", color="#e4572e", always=True),
    dict(id="2D", text="2D", x=2690.0, follow="2D", color="#2563eb", always=True),
    dict(id="hBN", text="hBN", x=1366.0, follow="hBN", color="#17a398", always=False),
    dict(id="D", text="D", x=1350.0, follow="D", color="#7c3aed", always=False),
]
STYLE_DEFAULTS = dict(size=10.0, font="", bold=False, italic=False, show=True, pos=True, always=True)

# 常見的 Raman 峰（新增標註時的選單）
PRESETS = [
    ("石墨烯 / 碳", [("G", 1580.0, "G"), ("2D", 2690.0, "2D"), ("D（缺陷）", 1350.0, "D"), ("D'", 1620.0, None),
                   ("D+D'", 2940.0, None), ("2D'", 3240.0, None)]),
    ("hBN", [("hBN（E₂g）", 1366.0, "hBN")]),
    ("基板", [("Si", 520.7, None), ("Si 2TO", 960.0, None)]),
    ("TMD", [("MoS₂ E¹₂g", 383.0, None), ("MoS₂ A₁g", 408.0, None), ("WSe₂ A₁g", 250.0, None),
             ("WS₂ 2LA", 352.0, None), ("MoSe₂ A₁g", 241.0, None)]),
]


def full(d):
    return {**STYLE_DEFAULTS, **d}


def defaults():
    return [full(copy.deepcopy(d)) for d in DEFAULTS]


def new_id(defs, base):
    ids = {d["id"] for d in defs}
    k, out = 1, base
    while out in ids:
        k += 1
        out = f"{base}_{k}"
    return out


def make(defs, text, x, follow=None, color="#374151"):
    return full(dict(id=new_id(defs, f"L{len(defs) + 1}"), text=text, x=float(x), follow=follow or FIXED,
                     color=color))


def is_raman_axes(ax):
    return ax.axison and "raman shift" in (ax.get_xlabel() or "").lower()


def register_peak(ax, key, pos, top, series=0):
    """分析函式擬合到峰時呼叫：告訴標註系統峰在哪裡（不直接畫文字）。"""
    if not hasattr(ax, "magic_peaks"):
        ax.magic_peaks = []
    ax.magic_peaks.append((key, float(pos), float(top), int(series)))


def _data_lines(ax):
    for ln in ax.lines:
        if ln.get_gid() == "nohover" or not ln.get_visible() or ln.get_transform() is not ax.transData:
            continue
        lab = ln.get_label() or ""
        if lab.startswith("_child") and len(ln.get_xdata()) < 5:
            continue
        yield ln


def _peak_near(ax, x0, win=WINDOW):
    """±win 內所有看得到的光譜的最高點 → (x, y)；沒有資料回傳 None。"""
    best = None
    for ln in _data_lines(ax):
        x, y = (np.asarray(a, float) for a in ln.get_data())
        if x.size < 5:
            continue
        m = (x >= x0 - win) & (x <= x0 + win) & np.isfinite(y)
        if m.any():
            i = int(np.argmax(np.where(m, y, -np.inf)))
            if best is None or y[i] > best[1]:
                best = (float(x[i]), float(y[i]))
    return best


def snap_to_peak(ax, x0, win=15.0):
    """點選位置附近（±win）光譜最高的那一點的 x。"""
    best = None
    for ln in _data_lines(ax):
        x, y = (np.asarray(a, float) for a in ln.get_data())
        m = (x >= x0 - win) & (x <= x0 + win) & np.isfinite(y)
        if m.any():
            i = int(np.argmax(np.where(m, y, -np.inf)))
            if best is None or y[i] > best[1]:
                best = (float(x[i]), float(y[i]))
    return best[0] if best else float(x0)


def _text(d, pos):
    t = d.get("text", "")
    if d.get("pos", True) and pos is not None:
        t = f"{t}\n{pos:.1f}" if t else f"{pos:.1f}"
    return t


def draw(fig, defs):
    """在每一張 Raman shift 的圖上畫標註。回傳畫了幾個。"""
    n = 0
    for ai, ax in enumerate(fig.axes):
        if not is_raman_axes(ax):
            continue
        xlo, xhi = sorted(ax.get_xlim())
        peaks = getattr(ax, "magic_peaks", [])
        tops = []
        for d in defs:
            d = full(d)
            if not d.get("show", True):
                continue
            fol = d.get("follow") or FIXED
            places = [(pos, top, s, pos) for key, pos, top, s in peaks if key == fol] if fol != FIXED else []
            if not places:
                if fol != FIXED and (peaks or not d.get("always", True)):
                    continue              # 這張圖有擬合、但沒找到這個峰（或設定只在擬合到時顯示）
                x0 = float(d.get("x", np.nan))
                if not np.isfinite(x0) or not (xlo <= x0 <= xhi):
                    continue
                hit = _peak_near(ax, x0)          # 放在附近光譜的最高點，顯示的數值也是那一點的位置
                if hit is None:
                    continue
                places = [(hit[0], hit[1], 0, hit[0])]
            for x0, y0, s, shown in places:
                if not (xlo <= x0 <= xhi):
                    continue
                ann = ax.annotate(
                    _text(d, shown), xy=(x0, y0), xytext=(0, 8), textcoords="offset points", ha="center", va="bottom",
                    color=d.get("color") or "#374151", fontsize=float(d.get("size", 10)),
                    fontweight="bold" if d.get("bold") else "normal", fontstyle="italic" if d.get("italic") else "normal",
                    annotation_clip=False, zorder=20,
                    arrowprops=dict(arrowstyle="-", color=d.get("color") or "#374151", lw=0.7, shrinkA=0, shrinkB=2))
                if d.get("font"):
                    try:
                        ann.set_fontfamily([d["font"], "DejaVu Sans"])
                    except Exception:
                        pass
                ann.magic_key = f"peak:{d['id']}:{ai}:{s}"
                tops.append(y0)
                n += 1
        if tops:
            lo, hi = ax.get_ylim()
            need = max(tops) + 0.16 * ((hi - lo) or 1.0)
            if need > hi:
                ax.set_ylim(lo, need)
    return n
