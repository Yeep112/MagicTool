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
    def __init__(self, width=W):
        self.W = width
        self.cols = [[] for _ in range(N)]
        self.notes = []          # 每一步的說明（動畫字幕）
        self.missing = []        # 切線模式：有步驟但沒有輪廓檔（剖面沒有畫那一步）
        self.cut = None          # 切線模式：((x1, y1), (x2, y2))

    def _rng(self, x0, x1):
        if not isinstance(x0, (int, float)):            # 直接給格子（切線模式：輪廓裡面的格子）
            return x0
        i0 = max(0, int(round(x0 / self.W * N)))
        i1 = min(N, int(round(x1 / self.W * N)))
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
                    out.append((x0 / N * self.W, i / N * self.W, y0, y1, m, s))
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


def build_section(rec, upto=None, lang="zh", outlines=None):
    """回傳 Section（做到第 upto 步為止，包含那一步；None = 全部）。
    有 digitalize 的 flake 輪廓 → 照切線（實際形狀）畫；沒有 → 示意版面。"""
    flakes = [o for o in (outlines or []) if not o.get("electrode")]
    if flakes:
        return build_section_cut(rec, outlines, cut_line(rec, outlines), upto, lang)
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
# 切線模式：沿著俯視圖上的一條線 A → A'，哪裡有 flake / 電極輪廓就疊哪一層
# ---------------------------------------------------------------------------
def _norm(name):
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def electrode_target(name):
    """輪廓檔名 → (步驟種類, 第幾次)：contact2 → ("contact", 2)；marker → ("marker", 1)；gate → ("top_gate", 1)。"""
    n = _norm(name)
    m = re.search(r"(\d+)$", n)
    k = int(m.group(1)) if m else 1
    if "marker" in n:
        return "marker", k
    if "gate" in n:
        return "top_gate", k
    return "contact", k


def inside(poly, xs, ys):
    """點 (xs[i], ys[i]) 在多邊形裡面嗎（射線法，numpy 一次算完）。"""
    import numpy as np
    px = np.asarray([p[0] for p in poly], float)
    py = np.asarray([p[1] for p in poly], float)
    xs = np.asarray(xs, float)
    ys = np.asarray(ys, float)
    res = np.zeros(xs.shape, bool)
    j = len(px) - 1
    for i in range(len(px)):
        yi, yj = py[i], py[j]
        cond = (yi > ys) != (yj > ys)
        with np.errstate(divide="ignore", invalid="ignore"):
            xint = (px[j] - px[i]) * (ys - yi) / (yj - yi) + px[i]
        res ^= cond & (xs < xint)
        j = i
    return res


def _centroid(pts):
    if len(pts) > 3 and tuple(pts[0]) == tuple(pts[-1]):     # 封閉的輪廓：最後一點和第一點重複，不要算兩次
        pts = pts[:-1]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def _bbox(outlines):
    xs = [x for o in outlines for x, _ in o["pts"]]
    ys = [y for o in outlines for _, y in o["pts"]]
    return min(xs), min(ys), max(xs), max(ys)


def auto_cut(outlines):
    """自動切線：兩個以上電極 → 穿過距離最遠的兩個電極中心；一個電極 → 電極中心穿過樣品中心；
    沒有電極 → 沿著樣品 flake 的長軸。線的兩端延伸到所有輪廓外面一點。"""
    import math
    flakes = [o for o in outlines if not o.get("electrode")]
    elec = [o for o in outlines if o.get("electrode")]
    sample = next((o for o in flakes if "hbn" not in _norm(o["name"])), flakes[0] if flakes else None)
    if sample is None:
        return None
    sc = _centroid(sample["pts"])
    cs = [_centroid(o["pts"]) for o in elec]
    if len(cs) >= 2:
        a, b = max(((p, q) for i, p in enumerate(cs) for q in cs[i + 1:]),
                   key=lambda pq: (pq[0][0] - pq[1][0]) ** 2 + (pq[0][1] - pq[1][1]) ** 2)
    elif len(cs) == 1 and math.dist(cs[0], sc) > 1e-9:
        a, b = cs[0], sc
    else:                                                # 長軸（主成分）
        xs = [p[0] - sc[0] for p in sample["pts"]]
        ys = [p[1] - sc[1] for p in sample["pts"]]
        sxx, syy, sxy = sum(x * x for x in xs), sum(y * y for y in ys), sum(x * y for x, y in zip(xs, ys))
        ang = 0.5 * math.atan2(2 * sxy, sxx - syy)
        a, b = sc, (sc[0] + math.cos(ang), sc[1] + math.sin(ang))
    x0, y0, x1, y1 = _bbox(outlines)
    pad = 0.06 * max(x1 - x0, y1 - y0)
    dx, dy = b[0] - a[0], b[1] - a[1]
    ln = math.hypot(dx, dy) or 1.0
    ux, uy = dx / ln, dy / ln
    # 把線延伸到外框（加一點邊）
    ts = []
    for px, py in ((x0 - pad, y0 - pad), (x1 + pad, y0 - pad), (x1 + pad, y1 + pad), (x0 - pad, y1 + pad)):
        ts.append((px - a[0]) * ux + (py - a[1]) * uy)
    t0, t1 = min(ts), max(ts)
    # 只留下有東西的那一段（線上取樣，看哪裡碰到輪廓）
    import numpy as np
    tt = np.linspace(t0, t1, 600)
    xs, ys = a[0] + tt * ux, a[1] + tt * uy
    hit = np.zeros(tt.shape, bool)
    for o in outlines:
        hit |= inside(o["pts"], xs, ys)
    if hit.any():
        i0, i1 = int(np.argmax(hit)), len(hit) - 1 - int(np.argmax(hit[::-1]))
        span = tt[i1] - tt[i0]
        t0, t1 = tt[i0] - 0.08 * span, tt[i1] + 0.08 * span
    return ((a[0] + t0 * ux, a[1] + t0 * uy), (a[0] + t1 * ux, a[1] + t1 * uy))


def cut_line(rec, outlines):
    c = (rec.get("visual") or {}).get("cut")
    if c and len(c) == 2:
        return (tuple(c[0]), tuple(c[1]))
    return auto_cut(outlines)


def _match_flakes(layers, flakes, extras=True):
    """轉移的堆疊（由下往上）對到輪廓檔。回傳 [(材料, 厚度, 輪廓 / None)]，多出來的輪廓插在上層 hBN 下面。"""
    used = set()
    hbn_idx = [i for i, (m, _) in enumerate(layers) if _is_hbn(m)]
    out = []
    for i, (m, t) in enumerate(layers):
        if _is_hbn(m):
            top = len(hbn_idx) > 1 and i == hbn_idx[-1]
            want = ("tophbn", "thbn", "uhbn") if top else ("bottomhbn", "bhbn", "hbn")
            cand = [k for k, o in enumerate(flakes) if k not in used and _norm(o["name"]) in want]
        else:
            nm = _norm(m)
            cand = [k for k, o in enumerate(flakes) if k not in used and _norm(o["name"]) == nm]
            if not cand and nm == "sample":                # 樣品類型沒寫材料：用輪廓檔的名稱（石墨烯排後面）
                cand = sorted((k for k, o in enumerate(flakes) if k not in used and "hbn" not in _norm(o["name"])),
                              key=lambda k: _norm(flakes[k]["name"]) in ("graphene", "graphite", "gr"))
        if cand:
            used.add(cand[0])
            o = flakes[cand[0]]
            out.append((o["name"] if _norm(m) == "sample" else m, t, o))
        else:
            out.append((m, t, None))
    extra = [(o["name"], None, o) for k, o in enumerate(flakes) if k not in used] if extras else []
    if extra:
        top_i = next((i for i in range(len(out) - 1, -1, -1) if _is_hbn(out[i][0]) and out[i][2] is not None
                      and "top" in out[i][2]["name"].lower()), len(out))
        out[top_i:top_i] = extra
    return out


def build_section_cut(rec, outlines, cut, upto=None, lang="zh"):
    import math

    import numpy as np
    (ax_, ay_), (bx_, by_) = cut
    length = math.hypot(bx_ - ax_, by_ - ay_) or 1.0
    sec = Section(length)
    sec.cut = cut
    tt = (np.arange(N) + 0.5) / N
    xs, ys = ax_ + (bx_ - ax_) * tt, ay_ + (by_ - ay_) * tt
    masks = {}

    def cells(o):
        key = id(o)
        if key not in masks:
            masks[key] = [int(i) for i in np.nonzero(inside(o["pts"], xs, ys))[0]]
        return masks[key]

    flakes = [o for o in outlines if not o.get("electrode")]
    elec = [o for o in outlines if o.get("electrode")]
    steps = rec.get("steps", [])
    last = len(steps) - 1 if upto is None else min(upto, len(steps) - 1)
    n_transfer = 0
    for idx, st in enumerate(steps[:last + 1]):
        k = st.get("kind")
        p = st.get("params") or {}
        if k == "transfer":
            layers = p.get("layers") or K.stack_from_type(rec.get("type", ""))
            if n_transfer == 0:
                top_hbn = _afm_after(rec, idx)
                for j, (m, t, o) in enumerate(_match_flakes(layers, flakes, not p.get("_partial"))):
                    if o is not None:
                        is_top = o is not None and "top" in o["name"].lower()
                        sec.add(m, _thick(m, t, top_hbn if is_top else None), cells(o), None, idx)
            n_transfer += 1
        elif k in ("marker", "contact", "top_gate"):
            n = st.get("n", 1)
            mine = [o for o in elec if electrode_target(o["name"]) == (k, n)]
            if not mine:
                sec.missing.append(K.step_name(st, lang))
            for o in mine:
                c = cells(o)
                if k == "contact":
                    rie = _sub(st, "rie") or _sub(st, "icp")
                    if rie is not None:
                        sec.etch_until(c, None, lambda m: not _is_hbn(m) and not _is_metal(m),
                                       _num((rie.get("params") or {}).get("oe_nm"), 0.0))
                    if _sub(st, "ion_mill") is not None:
                        sec.etch(1.5, c, None)
                default = [("Cr", 10.0), ("Au", 50.0)] if k == "marker" else [("Cr", 10.0), ("Au", 70.0)]
                for m, t in _metal_layers(st, default):
                    sec.add(m, t, c, None, idx)
        sec.notes.append(K.step_name(st, lang))
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
    if k in TOP_ALIASES:
        return TOP_ALIASES[k]
    if "hbn" in k:                                         # hBN_top、top-hBN、hBN_bottom、bot hBN…
        if "top" in k or k.startswith(("t", "u")) or k.endswith(("t", "up")):
            return "top hBN"
        if "bot" in k or k.startswith("b") or k.endswith("b"):
            return "bottom hBN"
    return stem


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
            kind, n = electrode_target(o["name"])
            if sum(1 for d in done if d == kind) >= n:
                vis.append(o)
        elif "transfer" in done or not any(s.get("kind") == "transfer" for s in steps):
            if "top" in o["name"].lower() and done.count("transfer") < 1:
                continue
            vis.append(o)
    return sorted(vis, key=lambda o: _z(o["name"]))


# ---------------------------------------------------------------------------
# 畫圖
# ---------------------------------------------------------------------------
def draw_section(ax, rec, upto=None, lang="zh", title=True, highlight=True, outlines=None):
    """highlight = 這一步新加的層用實色、之前的層淡一點（動畫用）。outlines = digitalize 輪廓（有就照切線畫）。"""
    from matplotlib.patches import Rectangle
    sec = build_section(rec, upto, lang, outlines)
    W = sec.W
    steps = rec.get("steps", [])
    cur = len(steps) - 1 if upto is None else min(upto, len(steps) - 1)
    ax.add_patch(Rectangle((0, -SUB_H), W, SUB_H * 0.72, facecolor=K.material_color("SiO2"), edgecolor="none"))
    ax.add_patch(Rectangle((0, -SUB_H), W, SUB_H * 0.22, facecolor=K.material_color("Si"), edgecolor="none"))
    ax.text(0.008 * W, -SUB_H * 0.42, f"SiO2 {SIO2_NM} nm" if lang != "zh" else f"SiO2 {SIO2_NM} nm（截斷）", fontsize=7,
            color="#475569", va="center")
    ax.text(0.008 * W, -SUB_H * 0.89, "Si", fontsize=7, color="#f8fafc", va="center")
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
    if sec.cut:                                          # 切線模式：標 A、A'，沒有輪廓檔的步驟寫出來
        ax.text(0, -SUB_H, "A", fontsize=9, fontweight="bold", color="#be185d", ha="left", va="top")
        ax.text(W, -SUB_H, "A'", fontsize=9, fontweight="bold", color="#be185d", ha="right", va="top")
        cur_name = sec.notes[-1] if sec.notes else ""
        if cur_name in sec.missing and upto is not None:
            nm = "contact" if "contact" in cur_name.lower() else cur_name.split()[0].lower()
            num = re.findall(r"#(\d+)", cur_name)
            ax.text(0.99, 0.985, (f"{cur_name}：沒有 {nm}{num[0] if num and num[0] != '1' else ''}.csv 輪廓，剖面沒有畫這一步"
                                  if lang == "zh" else f"{cur_name}: no outline file, not drawn"),
                    transform=ax.transAxes, ha="right", va="top", fontsize=8, color="#b45309")
    ax.set_ylabel("nm", fontsize=8)
    ax.tick_params(labelsize=7)
    for sp in ("top", "right", "bottom"):
        ax.spines[sp].set_visible(False)
    ax.axhline(0, color="#94a3b8", lw=0.5)
    if title:
        cut = ("（A–A' 切線）" if lang == "zh" else " (cut A–A')") if sec.cut else ""
        if upto is None:
            ax.set_title(("剖面（全部步驟）" if lang == "zh" else "Cross-section (all steps)") + cut, fontsize=9, loc="left")
        else:
            name = sec.notes[-1] if sec.notes else ("（還沒有步驟）" if lang == "zh" else "(no steps)")
            lab = "剖面　做完：" if lang == "zh" else "Cross-section after: "
            ax.set_title(lab + name + cut, fontsize=9, loc="left")
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
    cut = cut_line(rec, outlines)
    if cut and any(not o.get("electrode") for o in outlines):
        (x1, y1), (x2, y2) = cut
        ax.plot([x1, x2], [y1, y2], ls="--", lw=1.2, color="#be185d", zorder=9)
        ax.text(x1, y1, " A", color="#be185d", fontsize=9, fontweight="bold", zorder=10, ha="right", va="center")
        ax.text(x2, y2, " A'", color="#be185d", fontsize=9, fontweight="bold", zorder=10, ha="left", va="center")
        xs += [x1, x2]
        ys += [y1, y2]
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
        draw_section(fig.add_subplot(gs[0]), rec, upto, lang, highlight=upto is not None, outlines=outlines)
        draw_top(fig.add_subplot(gs[1]), rec, outlines or [], upto, lang)
    elif what == "section":
        draw_section(fig.add_subplot(111), rec, upto, lang, highlight=upto is not None, outlines=outlines)
    else:
        draw_top(fig.add_subplot(111), rec, outlines or [], upto, lang)
    fig.tight_layout()
    fig.savefig(path, dpi=dpi, facecolor="white")
    return path


# ---------------------------------------------------------------------------
# 分段插圖（PPT 的步驟頁）：一步拆成幾個階段，例如 contact = 旋塗光阻 → 曝光顯影 → RIE → 鍍膜 → Lift-off
# ---------------------------------------------------------------------------
# PPT 用的配色（跟「樣品製程報告」模板一樣）
PPT_COLORS = {"si": "#7C8BA1", "sio2": "#A59CEA", "hbn": "#9ED3EE", "tas2": "#1FA79A", "graphene": "#334155",
              "graphite": "#334155", "au": "#D9A21B", "cr": "#B7BCC8", "ti": "#9AA3AF", "nbti": "#231E57",
              "nb": "#3B3577", "al": "#C9CED6", "pd": "#CBD5E1", "nbse2": "#2BB673", "mos2": "#E8664F",
              "resist": "#F2BDB5"}
RESIST = "resist"


def color_of(m, palette=None):
    k = _norm(m)
    if palette:
        if k in palette:
            return palette[k]
        for key, col in palette.items():
            if key in k:
                return col
    return K.material_color(m)


def _regions(sec, st, n_contact, elec):
    """這一組步驟的光阻開口（open）與蝕刻範圍（etch）：格子的 index。"""
    k = st.get("kind")
    if sec.cut is not None:
        import numpy as np
        (ax_, ay_), (bx_, by_) = sec.cut
        tt = (np.arange(N) + 0.5) / N
        xs, ys = ax_ + (bx_ - ax_) * tt, ay_ + (by_ - ay_) * tt
        cells = set()
        for o in elec:
            if electrode_target(o["name"]) == (k, st.get("n", 1)):
                cells |= {int(i) for i in np.nonzero(inside(o["pts"], xs, ys))[0]}
        c = sorted(cells)
        return c, c
    rng = sec._rng
    if k == "marker":
        c = list(rng(0.25, 1.15)) + list(rng(8.85, 9.75))
        return c, c
    if k == "top_gate":
        c = list(rng(4.45, 5.55))
        return c, c
    (la, lb), (ra, rb) = WINDOWS[min(n_contact, len(WINDOWS) - 1)]
    out_l, out_r = (0.75, 9.25) if n_contact == 0 else (la - 0.45, rb + 0.45)
    return list(rng(out_l, lb)) + list(rng(ra, out_r)), list(rng(la, lb)) + list(rng(ra, rb))


def _liftoff(sec):
    for col in sec.cols:
        i = next((j for j, (m, _, _) in enumerate(col) if m == RESIST), None)
        if i is not None:
            del col[i:]


def _maxtop(sec):
    return max((sec.top(i) for i in range(N)), default=0.0)


def stage_sections(rec, idx, outlines=None, lang="zh"):
    """回傳 [{label, sec, arrows: [格子], arrow_color, text}]；沒有形狀變化的步驟回傳 []。"""
    out = _stage_sections(rec, idx, outlines, lang)
    if len(out) > 1 and len({repr(sorted(x["sec"].rects())) for x in out}) == 1:
        return []                                         # 每個階段都一樣（例如切線上沒有這一層）→ 不畫
    return out


def _stage_sections(rec, idx, outlines=None, lang="zh"):
    import copy as _copy
    steps = rec.get("steps", [])
    if not 0 <= idx < len(steps):
        return []
    st = steps[idx]
    k = st.get("kind")
    en = lang == "en"
    base = build_section(rec, idx - 1, lang, outlines)
    out = []

    def add(label, sec, arrows=None, color="#E8664F", text=""):
        out.append({"label": label, "sec": _copy.deepcopy(sec), "arrows": arrows or [], "arrow_color": color,
                    "text": text})

    if k in K.GROUP_KINDS:
        elec = [o for o in (outlines or []) if o.get("electrode")]
        n_contact = sum(1 for x in steps[:idx] if x.get("kind") == "contact")
        opened, etch = _regions(base, st, n_contact, elec)
        if base.cut is not None and not opened:            # 切線模式但沒有這一步的電極輪廓 → 用示意版面畫
            return stage_sections(rec, idx, None, lang)
        sec = _copy.deepcopy(base)
        level = _maxtop(sec) + max(40.0, 0.35 * _maxtop(sec))      # 旋塗的光阻上表面是平的
        for i in range(N):
            sec.cols[i].append([RESIST, level - sec.top(i), idx])
        add("Spin-coat resist" if en else "旋塗光阻", sec, text="PMMA" if not en else "PMMA")
        for i in opened:
            col = sec.cols[i]
            if col and col[-1][0] == RESIST:
                col.pop()
        add("Expose & develop" if en else "曝光、顯影", sec, opened, "#231E57",
            "Open the contact pattern" if en else "電子阻劑開出接觸窗")
        rie = _sub(st, "rie") or _sub(st, "icp")
        if rie is not None:
            p = rie.get("params") or {}
            sec.etch_until(etch, None, lambda m: not _is_hbn(m) and not _is_metal(m) and m != RESIST,
                           _num(p.get("oe_nm"), 0.0))
            plasma = _sub(st, "plasma")
            name = ("Plasma + " if plasma and en else "電漿清潔 + " if plasma else "") + rie["kind"].upper()
            txt = "\n".join(t for t in ((_ptext(plasma) if plasma else ""), _ptext(rie)) if t)
            add(name, sec, etch, "#E8664F", txt)
        ion = _sub(st, "ion_mill")
        if ion is not None:
            sec.etch(1.5, etch, None)
            add("Ion milling" if en else "離子研磨", sec, etch, "#231E57", _ptext(ion))
        dep = _sub(st, "deposit")
        metals = _metal_layers(st, [("Cr", 10.0), ("Au", 70.0)] if k != "marker" else [("Cr", 10.0), ("Au", 50.0)])
        for m, t in metals:
            for i in range(N):
                sec.cols[i].append([m, t, idx])
        mname = "/".join(m for m, _ in metals)
        add((f"Deposit {mname}" if en else f"鍍 {mname}"), sec, opened, "#D9A21B",
            _ptext(dep) if dep else K.format_layers([[m, t] for m, t in metals]))
        _liftoff(sec)
        add("Lift-off", sec, text="")
        return out
    if k in ("transfer", "cover"):
        p = st.get("params") or {}
        layers = p.get("layers") or (K.stack_from_type(rec.get("type", "")) if k == "transfer" else [["hBN", None]])
        if len(layers) > 1 and k == "transfer":
            for j in range(1, len(layers) + 1):
                r2 = _copy.deepcopy(rec)
                r2["steps"][idx].setdefault("params", {})["layers"] = layers[:j]
                r2["steps"][idx]["params"]["_partial"] = j < len(layers)
                sec = build_section(r2, idx, lang, outlines)
                m = layers[j - 1][0]
                add((f"Stack {m}" if en else f"疊上 {m}"), sec)
            return out
        add("Before" if en else "之前", base)
        add("After" if en else "之後", build_section(rec, idx, lang, outlines))
        return out
    if k in ("rie", "icp", "deposit", "ion_mill"):
        add("Before" if en else "之前", base)
        add(K.label(k, "en" if en else "zh"), build_section(rec, idx, lang, outlines))
        return out
    return []


def _ptext(sub):
    if not sub:
        return ""
    return "　".join(f"{a} {b}" for a, b in K.params_text(sub.get("kind"), sub.get("params")))


def draw_clean(ax, sec, palette=None, arrows=None, arrow_color="#E8664F", ymax=None):
    """PPT 用的乾淨插圖：沒有座標軸、標題、圖例；基板畫成兩條色帶。"""
    from matplotlib.patches import Rectangle
    W = sec.W
    H = ymax or max(_maxtop(sec), 30.0)
    s2, si = 0.45 * H, 0.38 * H
    ax.add_patch(Rectangle((0, -s2 - si), W, si, facecolor=color_of("Si", palette), edgecolor="none"))
    ax.add_patch(Rectangle((0, -s2), W, s2, facecolor=color_of("SiO2", palette), edgecolor="none"))
    for x0, x1, y0, y1, m, _ in sec.rects():
        ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, facecolor=color_of(m, palette), edgecolor="none"))
    if arrows:
        groups, cur = [], [arrows[0]]
        for i in arrows[1:]:
            if i == cur[-1] + 1:
                cur.append(i)
            else:
                groups.append(cur)
                cur = [i]
        groups.append(cur)
        for g in groups[:6]:
            x = (g[0] + g[-1] + 1) / 2 / N * W
            for dx in (-0.12 * W / 10, 0.12 * W / 10):
                ax.annotate("", xy=(x + dx, H * 1.08), xytext=(x + dx, H * 1.42),
                            arrowprops=dict(arrowstyle="-|>", color=arrow_color, lw=1.4, mutation_scale=9))
    ax.set_xlim(0, W)
    ax.set_ylim(-s2 - si, H * 1.5)
    ax.set_axis_off()


def render_stages(paths, stages, palette=None, size=(2.6, 1.9), dpi=170):
    """每個階段存一張 PNG（同一步的幾張用同一個高度刻度）。"""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    H = max([max(_maxtop(s["sec"]), 30.0) for s in stages] or [30.0])
    for path, s in zip(paths, stages):
        fig = Figure(figsize=size, dpi=dpi)
        FigureCanvasAgg(fig)
        ax = fig.add_axes([0.02, 0.02, 0.96, 0.96])
        draw_clean(ax, s["sec"], palette, s["arrows"], s["arrow_color"], H)
        fig.savefig(path, dpi=dpi, facecolor="none", transparent=True)
    return paths


def render_clean(path, rec, outlines=None, upto=None, palette=None, size=(4.6, 2.6), dpi=170):
    """整個元件的乾淨剖面（封面、比較用），回傳 (路徑, 出現的材料)。"""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    sec = build_section(rec, upto, "zh", outlines)
    fig = Figure(figsize=size, dpi=dpi)
    FigureCanvasAgg(fig)
    ax = fig.add_axes([0.02, 0.02, 0.96, 0.96])
    draw_clean(ax, sec, palette)
    fig.savefig(path, dpi=dpi, facecolor="none", transparent=True)
    mats = []
    for x0, x1, y0, y1, m, _ in sec.rects():
        if m not in mats:
            mats.append(m)
    return path, mats
