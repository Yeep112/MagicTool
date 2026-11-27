"""步驟庫：每一種製程 / 量測步驟的名稱、類別、子步驟，以及參數怎麼顯示。

marker = 提供後續曝光對準用的標記；contact = 電極；top gate 也算電極的一種。
這三種是「一組」步驟，裡面有可選填的子步驟（微影 → plasma → RIE → 離子研磨 → 鍍膜 → lift-off）。
鍍膜：method = "E"（蒸鍍）或 "S"（濺鍍），layers = [["Cr", 10], ["Au", 70]]（= Cr 10 nm / Au 70 nm）。
RIE：time_s（秒）、oe_nm（over etching，刻意多蝕刻的量）、hbn_nm（蝕刻前 AFM 量到的 hBN 厚度）。
"""
from __future__ import annotations

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


def params_text(kind, p):
    """參數 → [(欄位, 值)]，給介面與報告顯示。"""
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
    for key, val in p.items():                  # 其他自訂欄位
        if key.startswith("x_"):
            out.append((key[2:], str(val)))
    return out


def summary(step, lang="zh"):
    """一行摘要：Contact · Cr 10 nm / Au 70 nm (E) · RIE 20 s OE 3 nm"""
    parts = []
    for sub in step.get("substeps") or []:
        p = sub.get("params") or {}
        k = sub.get("kind")
        if k == "deposit" and p.get("layers"):
            parts.append(layers_text(p["layers"]).replace(" nm", "") + " nm" + (f" ({p['method']})" if p.get("method") else ""))
        elif k == "rie" and p.get("time_s") not in (None, ""):
            parts.append(f"RIE {_num(p['time_s'])} s" + (f" OE {_num(p['oe_nm'])} nm" if p.get("oe_nm") is not None else ""))
        elif k == "ion_mill" and p.get("time_s") not in (None, ""):
            parts.append(f"離子研磨 {p['time_s']} s")
        elif k == "plasma":
            parts.append("plasma")
    for name, val in params_text(step.get("kind"), step.get("params")):
        parts.append(f"{name} {val}")
    return " · ".join(parts)
