"""樣品示意圖（v0.8）：剖面圖（依步驟自動堆疊）、俯視圖（digitalize 的 flake 輪廓）、逐步動畫用的狀態。

剖面圖是「示意」：橫向位置是固定的版面（flake 在中間、marker 在兩側、contact 從蝕刻窗口接出去），
縱向用實際厚度（nm）；SiO2 / Si 基板太厚，畫成固定高度並標示截斷。
  轉移：params.layers（由下往上，例如 hBN 20 / TaS2 / hBN 40）；沒寫 → 依樣品類型猜 hBN / 材料 / hBN；
        厚度不知道 → 頂層 hBN 用後面 AFM 量到的厚度，其他用預設值
  marker：兩側鍍金屬（鍍膜子步驟的 Cr/Au…）
  contact：RIE 在窗口把上面的 hBN 蝕刻掉（加 OE 吃進下面一點），鍍膜填進窗口並往外接到 marker
  離子研磨：窗口表面再磨掉一點；top gate：中間鍍一條金屬；cover：上面再蓋一層 hBN
俯視圖：樣品資料夾裡（任何一層）副檔名 .csv、第一列是「x,Curve1」或兩欄數字的檔案；檔名 = 材料
  （graphene、hBN、thBN = 上層 hBN、bhBN、Ta / TaS2、contact、marker…）。轉移那一步出現 flake，
  檔名有 contact / electrode / marker / gate 的在對應的步驟出現。
"""
from __future__ import annotations

import csv
import os
import re

from . import steps as K

W = 10.0                 # 剖面圖寬度（版面單位）
N = 400                  # 橫向切成幾格
SUB_H = 40.0             # 基板畫多高（nm 刻度上）
SIO2_NM = 285


# ---------------------------------------------------------------------------
# 剖面：每一格是一疊 [材料, 厚度, 第幾步加的]
# ---------------------------------------------------------------------------
class Section:
    def __init__(self):
        self.cols = [[] for _ in range(N)]
        self.notes = []          # 每一步的說明（動畫字幕）

    def _rng(self, x0, x1):
        i0 = max(0, int(round(x0 / W * N)))
        i1 = min(N, int(round(x1 / W * N)))
        return range(i0, i1)

    def top(self, i):
        return sum(t for _, t, _ in self.cols[i])

    def add(self, mat, t, x0, x1, step):
        if not t or t <= 0:
            return
        for i in self._rng(x0, x1):
            self.cols[i].append([mat, float(t), step])

    def etch(self, depth, x0, x1, step=None):
        for i in self._rng(x0, x1):
            d = depth
            col = self.cols[i]
            while d > 1e-9 and col:
                if col[-1][1] <= d:
                    d -= col[-1][1]
                    col.pop()
                else:
                    col[-1][1] -= d
                    d = 0

    def etch_until(self, x0, x1, stop, oe=0.0):
        """蝕刻掉上面的層直到遇到 stop(材料) 為止，再多吃 oe nm（最多吃掉那一層的一半）。"""
        for i in self._rng(x0, x1):
            col = self.cols[i]
            while col and not stop(col[-1][0]):
                col.pop()
            if col and oe:
                col[-1][1] = max(col[-1][1] * 0.5, col[-1][1] - oe)

    def rects(self):
        """合併相鄰、同材料、同高度的格子 → [(x0, x1, y0, y1, 材料, 步驟)]"""
        out = []
        cur = {}
        for i in range(N + 1):
            here = {}
            if i < N:
                y = 0.0
                for k, (m, t, s) in enumerate(self.cols[i]):
                    here[(k, m, round(y, 3), round(y + t, 3), s)] = True
                    y += t
            for key in list(cur):
                if key not in here:
                    x0 = cur.pop(key)
                    k, m, y0, y1, s = key
                    out.append((x0 / N * W, i / N * W, y0, y1, m, s))
            for key in here:
                if key not in cur:
                    cur[key] = i
        return out


def _is_hbn(m):
    return "hbn" in str(m).lower()


def _is_metal(m):
    return re.sub(r"[^a-z]", "", str(m).lower()) in ("au", "cr", "ti", "nb", "nbti", "pd", "al", "pt", "ag", "cu", "ni",
                                                     "mo", "w", "ta", "v")


def _afm_after(rec, idx):
    for st in rec.get("steps", [])[idx + 1:]:
        if st.get("kind") == "afm" and (st.get("params") or {}).get("hbn_nm") is not None:
            return float(st["params"]["hbn_nm"])
        if st.get("kind") in ("contact", "rie"):
            for sub in st.get("substeps") or [st]:
                p = sub.get("params") or {}
                if sub.get("kind", st.get("kind")) == "rie" and p.get("hbn_nm") is not None:
                    return float(p["hbn_nm"])
    return None


def _thick(mat, t, default_hbn=None):
    if t is not None:
        try:
            return float(t)
        except (TypeError, ValueError):
            pass
    k = re.sub(r"[^a-z0-9]", "", str(mat).lower())
    if "hbn" in k:
        return default_hbn or K.DEFAULT_THICK["hbn"]
    return K.DEFAULT_THICK.get(k, 5.0 if k not in ("graphene",) else 1.0)


def _metal_layers(step, default):
    for sub in step.get("substeps") or []:
        if sub.get("kind") == "deposit" and (sub.get("params") or {}).get("layers"):
            return [(m, float(t) if t is not None else 20.0) for m, t in sub["params"]["layers"]]
    if step.get("kind") == "deposit" and (step.get("params") or {}).get("layers"):
        return [(m, float(t) if t is not None else 20.0) for m, t in step["params"]["layers"]]
    return default


def _sub(step, kind):
    return next((x for x in step.get("substeps") or [] if x.get("kind") == kind), None)


def _num(v, d=0.0):
    try:
        return float(re.findall(r"[\d.]+", str(v))[0]) if isinstance(v, str) else float(v)
    except (TypeError, ValueError, IndexError):
        return d


WINDOWS = [((2.95, 3.65), (6.35, 7.05)), ((3.75, 4.3), (5.7, 6.25)), ((4.35, 4.7), (5.3, 5.65))]


def build_section(rec, upto=None, lang="zh"):
    """回傳 Section（做到第 upto 步為止，包含那一步；None = 全部）。"""
    sec = Section()
    steps = rec.get("steps", [])
    last = len(steps) - 1 if upto is None else min(upto, len(steps) - 1)
    n_transfer = n_contact = 0
    for idx, st in enumerate(steps[:last + 1]):
        k = st.get("kind")
        p = st.get("params") or {}
        note = K.step_name(st, lang)
        if k == "transfer":
            layers = p.get("layers") or K.stack_from_type(rec.get("type", ""))
            top_hbn = _afm_after(rec, idx)
            if n_transfer == 0:
                for j, (m, t) in enumerate(layers):
                    last_layer = j == len(layers) - 1
                    hw = 2.8 if (_is_hbn(m) and last_layer and j > 0) else 3.0 - 0.45 * j
                    sec.add(m, _thick(m, t, top_hbn if last_layer else None), W / 2 - hw, W / 2 + hw, idx)
            else:
                for j, (m, t) in enumerate(layers):
                    hw = 1.7 - 0.3 * j
                    sec.add(m, _thick(m, t), W / 2 - hw, W / 2 + hw, idx)
            n_transfer += 1
        elif k == "cover":
            for m, t in (p.get("layers") or [["hBN", None]]):
                sec.add(m, _thick(m, t, _afm_after(rec, idx)), 1.9, 8.1, idx)
        elif k == "marker":
            for m, t in _metal_layers(st, [("Cr", 10.0), ("Au", 50.0)]):
                for a, b in ((0.25, 1.15), (8.85, 9.75)):
                    sec.add(m, t, a, b, idx)
        elif k in ("contact", "top_gate"):
            if k == "top_gate":
                for m, t in _metal_layers(st, [("Cr", 5.0), ("Au", 60.0)]):
                    sec.add(m, t, 4.45, 5.55, idx)
            else:
                win = WINDOWS[min(n_contact, len(WINDOWS) - 1)]
                rie = _sub(st, "rie") or _sub(st, "icp")
                if rie is not None:
                    oe = _num((rie.get("params") or {}).get("oe_nm"), 0.0)
                    for a, b in win:
                        sec.etch_until(a, b, lambda m: not _is_hbn(m) and not _is_metal(m), oe)
                ion = _sub(st, "ion_mill")
                if ion is not None:
                    for a, b in win:
                        sec.etch(1.5, a, b)
                metals = _metal_layers(st, [("Cr", 10.0), ("Au", 70.0)] if not ion else [("NbTi", 70.0)])
                (la, lb), (ra, rb) = win
                out_l, out_r = (0.75, 9.25) if n_contact == 0 else (la - 0.45, rb + 0.45)
                for m, t in metals:
                    sec.add(m, t, out_l, lb, idx)         # 左邊的電極：窗口 → 往外接（第一次 contact 接到 marker）
                    sec.add(m, t, ra, out_r, idx)         # 右邊
                n_contact += 1
        elif k == "rie":
            sec.etch(_num(p.get("hbn_nm"), 10) + _num(p.get("oe_nm"), 0), 2.0, 8.0)
        elif k == "deposit":
            for m, t in _metal_layers(st, []):
                sec.add(m, t, 2.0, 8.0, idx)
        elif k == "ion_mill":
            sec.etch(1.5, 2.0, 8.0)
        sec.notes.append(note)
    return sec


# ---------------------------------------------------------------------------
# 俯視圖：digitalize 的輪廓 CSV
# ---------------------------------------------------------------------------
TOP_ALIASES = {"thbn": "top hBN", "tophbn": "top hBN", "uhbn": "top hBN", "bhbn": "bottom hBN", "bottomhbn": "bottom hBN",
               "hbn": "hBN", "ta": "TaS2", "tas2": "TaS2", "graphene": "graphene", "gr": "graphene",
               "graphite": "graphite", "nbse2": "NbSe2"}
ELECTRODE = re.compile(r"contact|electrode|marker|gate|lead|au\b", re.I)


def read_outline(path):
    """回傳 [(x, y)]；不是輪廓檔 → None。"""
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))
    except (OSError, UnicodeDecodeError):
        return None
    pts = []
    for r in rows:
        if len(r) < 2:
            continue
        try:
            pts.append((float(r[0]), float(r[1])))
        except ValueError:
            if pts:
                return None
    return pts if len(pts) >= 3 else None


def outline_name(path):
    stem = os.path.splitext(os.path.basename(path))[0]
    k = re.sub(r"[^a-z0-9]", "", stem.lower())
    return TOP_ALIASES.get(k, stem)


def find_outlines(sample_dir, max_depth=3, limit=40):
    """樣品資料夾裡的輪廓檔 → [{name, path, pts, electrode}]"""
    out = []
    if not sample_dir or not os.path.isdir(sample_dir):
        return out

    def walk(d, depth):
        try:
            ents = sorted(os.scandir(d), key=lambda e: e.name.lower())
        except OSError:
            return
        for e in ents:
            if len(out) >= limit:
                return
            if e.is_file() and e.name.lower().endswith(".csv") and e.stat().st_size < 2_000_000:
                with open(e.path, encoding="utf-8-sig", errors="replace") as f:
                    head = f.readline().strip().lower().replace(" ", "")
                if not (head.startswith("x,curve") or re.fullmatch(r"-?[\d.e+-]+,-?[\d.e+-]+", head)):
                    continue
                pts = read_outline(e.path)
                if pts:
                    nm = outline_name(e.path)
                    out.append({"name": nm, "path": e.path, "pts": pts, "electrode": bool(ELECTRODE.search(nm))})
            elif e.is_dir() and depth < max_depth and not e.name.startswith("."):
                walk(e.path, depth + 1)
    walk(sample_dir, 1)
    return out


def _z(name):
    k = name.lower()
    if "bottom" in k:
        return 1
    if "top" in k:
        return 4
    if "hbn" in k:
        return 2
    if ELECTRODE.search(k):
        return 6
    return 3


def outlines_at(rec, outlines, upto=None):
    """做到第 upto 步時看得到的輪廓。flake：第一次轉移之後；電極：檔名對應的那一種步驟做完之後。"""
    steps = rec.get("steps", [])
    last = len(steps) - 1 if upto is None else upto
    done = [s.get("kind") for s in steps[:last + 1]]
    vis = []
    for o in outlines:
        if o["electrode"]:
            n = o["name"].lower()
            need = "marker" if "marker" in n else "top_gate" if "gate" in n else "contact"
            if need in done:
                vis.append(o)
        elif "transfer" in done or not any(s.get("kind") == "transfer" for s in steps):
            if "top" in o["name"].lower() and done.count("transfer") < 1:
                continue
            vis.append(o)
    return sorted(vis, key=lambda o: _z(o["name"]))


# ---------------------------------------------------------------------------
# 畫圖
# ---------------------------------------------------------------------------
def draw_section(ax, rec, upto=None, lang="zh", title=True, highlight=True):
    """highlight = 這一步新加的層用實色、之前的層淡一點（動畫用）。"""
    from matplotlib.patches import Rectangle
    sec = build_section(rec, upto, lang)
    steps = rec.get("steps", [])
    cur = len(steps) - 1 if upto is None else min(upto, len(steps) - 1)
    ax.add_patch(Rectangle((0, -SUB_H), W, SUB_H * 0.72, facecolor=K.material_color("SiO2"), edgecolor="none"))
    ax.add_patch(Rectangle((0, -SUB_H), W, SUB_H * 0.22, facecolor=K.material_color("Si"), edgecolor="none"))
    ax.text(0.08, -SUB_H * 0.42, f"SiO2 {SIO2_NM} nm" if lang != "zh" else f"SiO2 {SIO2_NM} nm（截斷）", fontsize=7,
            color="#475569", va="center")
    ax.text(0.08, -SUB_H * 0.89, "Si", fontsize=7, color="#f8fafc", va="center")
    ymax = 10.0
    seen = {}
    for x0, x1, y0, y1, m, s in sec.rects():
        new = s == cur
        ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, facecolor=K.material_color(m), edgecolor="none",
                               linewidth=0, alpha=1.0 if new or not highlight else 0.45))
        ymax = max(ymax, y1)
        seen.setdefault(m, 0.0)
        seen[m] = max(seen[m], y1 - y0)
    # 圖例：材料 + 最厚的地方
    from matplotlib.patches import Patch
    handles = [Patch(facecolor=K.material_color(m), label=f"{m} {t:.3g} nm") for m, t in seen.items()]
    if handles:
        ax.legend(handles=handles, loc="upper left", fontsize=7, frameon=False, ncol=min(3, len(handles)),
                  bbox_to_anchor=(0, 1.0))
    ax.grid(False)
    ax.set_xlim(0, W)
    ax.set_ylim(-SUB_H, max(ymax * 1.55, 60))
    ax.set_xticks([])
    ax.set_ylabel("nm", fontsize=8)
    ax.tick_params(labelsize=7)
    for sp in ("top", "right", "bottom"):
        ax.spines[sp].set_visible(False)
    ax.axhline(0, color="#94a3b8", lw=0.5)
    if title:
        if upto is None:
            ax.set_title("剖面（全部步驟）" if lang == "zh" else "Cross-section (all steps)", fontsize=9, loc="left")
        else:
            name = sec.notes[-1] if sec.notes else ("（還沒有步驟）" if lang == "zh" else "(no steps)")
            lab = "剖面　做完：" if lang == "zh" else "Cross-section after: "
            ax.set_title(lab + name, fontsize=9, loc="left")
    return sec


def draw_top(ax, rec, outlines, upto=None, lang="zh", title=True):
    from matplotlib.patches import Polygon
    vis = outlines_at(rec, outlines, upto)
    if not outlines:
        ax.text(0.5, 0.5, "沒有 digitalize 的輪廓檔\n（把 graphene.csv、hBN.csv… 放進樣品資料夾）" if lang == "zh" else
                "No outline files (graphene.csv, hBN.csv…)", ha="center", va="center", fontsize=8, color="#6b7280",
                transform=ax.transAxes)
        ax.set_axis_off()
        return vis
    xs = [x for o in outlines for x, _ in o["pts"]]
    ys = [y for o in outlines for _, y in o["pts"]]
    for o in vis:
        col = K.material_color("Au" if o["electrode"] else o["name"].replace("top ", "").replace("bottom ", ""))
        top = "top" in o["name"].lower()
        ax.add_patch(Polygon(o["pts"], closed=True, facecolor=col, edgecolor=col if not top else "#0369a1",
                             alpha=0.35 if top else (0.85 if o["electrode"] else 0.6), linewidth=1.0,
                             zorder=_z(o["name"]), label=o["name"]))
    ax.grid(False)
    dx, dy = (max(xs) - min(xs)) or 1, (max(ys) - min(ys)) or 1
    pad = 0.08 * max(dx, dy)
    ax.set_xlim(min(xs) - pad, max(xs) + pad)
    ax.set_ylim(min(ys) - pad, max(ys) + pad)
    ax.set_aspect("equal", adjustable="box")
    ax.tick_params(labelsize=7)
    if vis:
        ax.legend(loc="upper right", fontsize=7, frameon=False)
    if title:
        ax.set_title("俯視（digitalize 輪廓）" if lang == "zh" else "Top view (digitized outlines)", fontsize=9, loc="left")
    return vis


def render_png(path, rec, outlines=None, upto=None, lang="zh", what="both", size=(8, 5.2), dpi=170):
    """存成 PNG（PPT、存圖用）。what = "section" / "top" / "both"。"""
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from ..core import plotstyle
    plotstyle.apply()
    fig = Figure(figsize=size, dpi=dpi)
    FigureCanvasAgg(fig)
    if what == "both":
        gs = fig.add_gridspec(1, 2, width_ratios=[1.35, 1])
        draw_section(fig.add_subplot(gs[0]), rec, upto, lang, highlight=upto is not None)
        draw_top(fig.add_subplot(gs[1]), rec, outlines or [], upto, lang)
    elif what == "section":
        draw_section(fig.add_subplot(111), rec, upto, lang, highlight=upto is not None)
    else:
        draw_top(fig.add_subplot(111), rec, outlines or [], upto, lang)
    fig.tight_layout()
    fig.savefig(path, dpi=dpi, facecolor="white")
    return path
