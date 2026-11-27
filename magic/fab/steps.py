"""步驟庫：每一種製程 / 量測步驟的名稱、類別、子步驟，以及參數怎麼顯示。

marker = 提供後續曝光對準用的標記；contact = 電極；top gate 也算電極的一種。
這三種是「一組」步驟，裡面有可選填的子步驟（微影 → plasma → RIE → 離子研磨 → 鍍膜 → lift-off）。
鍍膜：method = "E"（蒸鍍）或 "S"（濺鍍），layers = [["Cr", 10], ["Au", 70]]（= Cr 10 nm / Au 70 nm）。
RIE：time_s（秒）、oe_nm（over etching，刻意多蝕刻的量）、hbn_nm（蝕刻前 AFM 量到的 hBN 厚度）。
轉移：layers = [["hBN", 20], ["TaS2", 5], ["hBN", 40]]（由下往上；厚度不知道可以是 None）→ 剖面圖用。
"""
from __future__ import annotations

import re

# 類別：(中文, English, 顏色)
CATEGORIES = {
    "stack": ("堆疊 / 轉移", "Stacking / transfer", "#0d9488"),
    "litho": ("微影 / 鍍膜", "Lithography / deposition", "#d97706"),
    "etch": ("蝕刻 / 清潔", "Etching / cleaning", "#e4572e"),
    "meas": ("量測 / 檢查", "Measurement / inspection", "#7c3aed"),
    "other": ("設計 / 封裝 / 分析", "Design / packaging / analysis", "#64748b"),
}

# 種類：(中文, English, 類別, 圖示)
KINDS = {
    "design": ("設計", "Design", "other", "✎"),
    "transfer": ("轉移", "Transfer", "stack", "≡"),
    "cover": ("Cover hBN", "Cover hBN", "stack", "≡"),
    "cleaning": ("清潔", "Cleaning", "etch", "✧"),
    "marker": ("Marker", "Marker", "litho", "✚"),
    "contact": ("Contact", "Contact", "litho", "⊓"),
    "top_gate": ("Top gate", "Top gate", "litho", "⊤"),
    "litho_group": ("微影 / Lift-off", "Lithography / lift-off", "litho", "◫"),   # 資料夾還沒對到 marker / contact
    "lithography": ("微影（顯影後）", "Lithography (developed)", "litho", "◫"),
    "plasma": ("Plasma 清潔", "Plasma clean", "etch", "✺"),
    "rie": ("RIE", "RIE", "etch", "⌄"),
    "icp": ("ICP", "ICP", "etch", "⌄"),
    "ion_mill": ("離子研磨", "Ion milling", "etch", "⇣"),
    "deposit": ("鍍膜", "Deposition", "litho", "▤"),
    "liftoff": ("Lift-off（鍍完）", "Lift-off", "litho", "⇡"),
    "afm": ("AFM", "AFM", "meas", "△"),
    "raman": ("Raman", "Raman", "meas", "∿"),
    "inspection": ("OM 檢查", "OM inspection", "meas", "◎"),
    "measurement": ("量測", "Measurement", "meas", "↗"),
    "bonding": ("打線", "Wire bonding", "other", "⌇"),
    "analysis": ("數據分析", "Data analysis", "other", "Σ"),
    "other": ("其他", "Other", "other", "•"),
}

GROUP_KINDS = ("marker", "contact", "top_gate")
SUB_KINDS = ("lithography", "plasma", "rie", "icp", "ion_mill", "deposit", "liftoff")
SUB_ORDER = {k: i for i, k in enumerate(SUB_KINDS)}
# 每一組的子步驟（使用者自己選填；沒有紀錄的顯示成「可補填」）
SUBSTEPS = {
    "marker": ["lithography", "deposit", "liftoff"],
    "contact": ["lithography", "plasma", "rie", "ion_mill", "deposit", "liftoff"],
    "top_gate": ["lithography", "deposit", "liftoff"],
    "litho_group": ["lithography", "deposit", "liftoff"],
}

STATES = {
    "active": ("製作中", "In progress", "#2563eb"),
    "hold": ("擱置", "On hold", "#d97706"),
    "measuring": ("量測中", "Measuring", "#7c3aed"),
    "measured": ("已量測", "Measured", "#16a34a"),
    "abandoned": ("放棄", "Abandoned", "#9ca3af"),
}
METHODS = {"E": ("蒸鍍 (E)", "E-beam evaporation"), "S": ("濺鍍 (S)", "Sputtering")}


# 新增步驟時可以選的種類（子步驟也可以單獨當一步，例如只做一次 plasma 清潔）
LIBRARY = ["transfer", "cover", "afm", "raman", "inspection", "marker", "contact", "top_gate", "plasma", "rie", "icp",
           "ion_mill", "deposit", "cleaning", "bonding", "measurement", "analysis", "design", "other"]

# 每一種步驟的參數欄位：(key, 中文, English, 單位, 型別)；型別 num / text / layers / stack / method / tool
PARAMS = {
    "transfer": [("layers", "堆疊（由下往上）", "Stack (bottom → top)", "", "stack")],
    "cover": [("layers", "蓋上的材料", "Cover layers", "", "stack")],
    "afm": [("hbn_nm", "hBN 厚度", "hBN thickness", "nm", "num"), ("x_其他厚度", "其他厚度", "Other", "", "text")],
    "raman": [("note", "備註", "Note", "", "text")],
    "marker": [("tool", "曝光方式", "Exposure", "", "tool")],
    "plasma": [("power_w", "功率", "Power", "W", "num"), ("flow_sccm", "流量", "Flow", "sccm", "num"),
               ("time_s", "時間", "Time", "s", "num")],
    "rie": [("hbn_nm", "hBN 厚度", "hBN thickness", "nm", "num"), ("oe_nm", "OE（多蝕刻）", "Over-etch", "nm", "num"),
            ("time_s", "時間", "Time", "s", "num")],
    "icp": [("time_s", "時間", "Time", "s", "text")],
    "ion_mill": [("current_ma", "電流", "Current", "mA", "num"), ("height", "height", "Height", "", "num"),
                 ("time_s", "時間", "Time", "s", "text")],
    "deposit": [("layers", "金屬 / 厚度", "Metals / thickness", "nm", "layers"), ("method", "方式", "Method", "", "method")],
    "measurement": [("x_機台", "機台", "Instrument", "", "text")],
    "other": [("text", "內容", "Description", "", "text")],
}
TOOLS = ["", "Raith", "蒸鍍"]

# 剖面圖的材料顏色
MATERIAL_COLORS = {"hbn": "#7dd3fc", "graphene": "#334155", "graphite": "#334155", "tas2": "#a855f7",
                   "nbse2": "#22c55e", "mos2": "#f59e0b", "wse2": "#14b8a6", "au": "#f5c542", "cr": "#94a3b8",
                   "ti": "#9ca3af", "nb": "#64748b", "nbti": "#475569", "pd": "#cbd5e1", "al": "#d1d5db",
                   "sio2": "#e5e7eb", "si": "#9ca3af", "pmma": "#fde68a"}
DEFAULT_THICK = {"hbn": 30.0, "graphene": 1.0, "graphite": 5.0}


def material_color(name):
    k = re.sub(r"[^a-z0-9]", "", str(name).lower())
    if k in MATERIAL_COLORS:
        return MATERIAL_COLORS[k]
    for key, col in MATERIAL_COLORS.items():
        if key in k:
            return col
    import hashlib
    h = int(hashlib.md5(k.encode()).hexdigest()[:6], 16)
    return "#%02x%02x%02x" % (120 + h % 100, 120 + (h >> 8) % 100, 140 + (h >> 16) % 90)


def parse_layers(text):
    """「Cr/Au 10/70」「Cr/Au_10/70」「Cr 10 / Au 70」→ [["Cr", 10], ["Au", 70]]；看不懂回傳 None。"""
    t = str(text or "").strip().replace("，", ",")
    if not t:
        return []
    m = re.fullmatch(r"([A-Za-z0-9]+(?:/[A-Za-z0-9]+)*)[\s_]+([\d.]+(?:/[\d.]+)*)\s*(?:nm)?", t)
    if m:
        mats, th = m.group(1).split("/"), m.group(2).split("/")
        if len(mats) == len(th):
            return [[a, _f(b)] for a, b in zip(mats, th)]
    out = []
    for part in re.split(r"\s*[/,+]\s*", t):
        mm = re.fullmatch(r"([A-Za-z][A-Za-z0-9]*)\s*_?\s*([\d.]+)?\s*(?:nm)?", part.strip())
        if not mm:
            return None
        out.append([mm.group(1), _f(mm.group(2)) if mm.group(2) else None])
    return out


def format_layers(layers, style="slash"):
    """[["Cr", 10], ["Au", 70]] → 'Cr/Au 10/70'（style="stack" → 'hBN 20 / TaS2 / hBN 40'）"""
    layers = layers or []
    if style == "slash" and layers and all(t is not None for _, t in layers):
        return "/".join(m for m, _ in layers) + " " + "/".join(_num(t) for _, t in layers)
    return " / ".join(f"{m} {_num(t)}" if t is not None else str(m) for m, t in layers)


def _f(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return v
    return int(x) if x.is_integer() else x


def stack_from_type(type_text):
    """樣品類型（Tri-TaS2、Quad-NbSe2、graphene…）→ 預設的轉移堆疊 hBN / 材料 / hBN。"""
    t = str(type_text or "")
    m = re.search(r"(TaS2|NbSe2|MoS2|WSe2|WS2|MoSe2|graphene|graphite|NbS2|TaSe2|[A-Z][a-z]?[A-Z]?[a-z]?\d?[A-Z][a-z]?\d)", t,
                  re.I)
    mat = m.group(1) if m else "sample"
    return [["hBN", None], [mat, None], ["hBN", None]]


def kind_info(kind):
    return KINDS.get(kind) or KINDS["other"]


def label(kind, lang="zh"):
    k = kind_info(kind)
    return k[1] if lang == "en" else k[0]


def category(kind):
    return kind_info(kind)[2]


def color(kind):
    return CATEGORIES[category(kind)][2]


def icon(kind):
    return kind_info(kind)[3]


def step_name(step, lang="zh"):
    """「Contact #2」「AFM」"""
    k = step.get("kind")
    return label(k, lang) + (f" #{step.get('n', 1)}" if k in GROUP_KINDS else "")


def state_label(state, lang="zh"):
    s = STATES.get(state) or STATES["active"]
    return s[1] if lang == "en" else s[0]


def _num(v):
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def layers_text(layers):
    """[["Cr", 10], ["Au", 70]] → 'Cr 10 nm / Au 70 nm'"""
    return " / ".join(f"{m} {_num(t)} nm" for m, t in (layers or []))


NAME_EN = {"金屬": "Metals", "方式": "Method", "hBN 厚度": "hBN thickness", "時間": "Time", "OE（多蝕刻）": "Over-etch",
           "功率": "Power", "流量": "Flow", "電流": "Current", "備註": "Note", "堆疊（下 → 上）": "Stack (bottom → top)",
           "材料": "Layers", "內容": "Description", "蒸鍍 (E)": "E-beam evaporation (E)", "濺鍍 (S)": "Sputtering (S)",
           "蒸鍍": "Evaporation"}


def params_text(kind, p, lang="zh"):
    """參數 → [(欄位, 值)]，給介面與報告顯示。lang="en" → 英文欄位名稱。"""
    out = _params_text(kind, p)
    if lang == "en":
        out = [(NAME_EN.get(a, a), NAME_EN.get(b, b)) for a, b in out]
    return out


def _params_text(kind, p):
    p = p or {}
    out = []
    if kind == "deposit":
        if p.get("layers"):
            out.append(("金屬", layers_text(p["layers"])))
        if p.get("method"):
            out.append(("方式", METHODS.get(p["method"], (p["method"],))[0]))
    elif kind == "rie":
        if p.get("hbn_nm") is not None:
            out.append(("hBN 厚度", f"{_num(p['hbn_nm'])} nm"))
        if p.get("time_s") not in (None, ""):
            out.append(("時間", f"{_num(p['time_s'])} s"))
        if p.get("oe_nm") is not None:
            out.append(("OE（多蝕刻）", f"{_num(p['oe_nm'])} nm"))
    elif kind == "plasma":
        for key, name, unit in (("power_w", "功率", "W"), ("flow_sccm", "流量", "sccm"), ("time_s", "時間", "s")):
            if p.get(key) not in (None, ""):
                out.append((name, f"{_num(p[key])} {unit}"))
    elif kind == "icp":
        if p.get("time_s") not in (None, ""):
            out.append(("時間", f"{p['time_s']} s"))
    elif kind == "ion_mill":
        for key, name, unit in (("current_ma", "電流", "mA"), ("height", "height", ""), ("time_s", "時間", "s")):
            if p.get(key) not in (None, ""):
                out.append((name, f"{_num(p[key])} {unit}".strip()))
    elif kind == "afm":
        if p.get("hbn_nm") is not None:
            out.append(("hBN 厚度", f"{_num(p['hbn_nm'])} nm"))
    elif kind == "raman":
        if p.get("note"):
            out.append(("備註", p["note"]))
    elif kind == "marker":
        if p.get("tool"):
            out.append(("方式", p["tool"]))
    elif kind in ("transfer", "cover"):
        if p.get("layers"):
            out.append(("堆疊（下 → 上）" if kind == "transfer" else "材料", format_layers(p["layers"], "stack")))
    elif kind == "other":
        if p.get("text"):
            out.append(("內容", p["text"]))
    for key, val in p.items():                  # 其他自訂欄位
        if key.startswith("x_"):
            out.append((key[2:], str(val)))
    return out


def summary(step, lang="zh"):
    """一行摘要：Contact · Cr 10 nm / Au 70 nm (E) · RIE 20 s OE 3 nm（不包含 Contact 本身的名稱）"""
    parts = []
    for sub in step.get("substeps") or []:
        p = sub.get("params") or {}
        k = sub.get("kind")
        if k == "deposit" and p.get("layers"):
            parts.append(layers_text(p["layers"]).replace(" nm", "") + " nm" + (f" ({p['method']})" if p.get("method") else ""))
        elif k == "rie" and p.get("time_s") not in (None, ""):
            parts.append(f"RIE {_num(p['time_s'])} s" + (f" OE {_num(p['oe_nm'])} nm" if p.get("oe_nm") is not None else ""))
        elif k == "ion_mill" and p.get("time_s") not in (None, ""):
            parts.append(("Ion milling" if lang == "en" else "離子研磨") + f" {p['time_s']} s")
        elif k == "plasma":
            parts.append("plasma")
    for name, val in params_text(step.get("kind"), step.get("params"), lang):
        parts.append(f"{name} {val}")
    return " · ".join(parts)
