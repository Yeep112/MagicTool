"""樣品紀錄 → 試算表（Sample Tracking）：試算表改成軟體自動更新、只當總覽。

一個樣品 = 一列，用 Label 欄找那一列（找不到就加在最後一筆資料下面）。只寫這幾欄：
  Status（狀態 + 結果）、Type、Start Time、Process 那一段（一格一步）、備註
其他欄位、公式、格式都不碰。寫的格式和原本手寫的一樣，所以匯入程式（sheet.py）讀回來會得到同樣的步驟：
  transfer | marker | Cr/Au_10/60 (E) | contact | AFM hBN_32 | RIE_15s OE_3nm | Cr/Au_10/70 (E) | …
  狀態：measured R_1700 (SC) sc on TaS2 Tc_4.2K ／ 擱置 原因 (8/7) ／ -（放棄）
沒有在軟體裡改過的步驟，照抄試算表原本的文字（不會因為重新產生而改掉原本的寫法）。

寫入方式和 Etching 共用（magic/etching/gsync.py）：Apps Script（推薦，同事不需要金鑰）或服務帳號。
Apps Script 要裝在「這一份」試算表裡（擴充功能 → Apps Script，貼上同一份程式），會有自己的網址和通行碼。
"""
from __future__ import annotations

import re

from . import steps as K

PROCESS_MAX = 60          # 沒有「備註」欄時，Process 最多寫到第幾格
# 試算表原本沒有記的小步驟：只有在軟體裡手動新增的才寫（資料夾裡有 00 Design、OM 照片…不必都列進總覽）
MINOR = {"design", "cleaning", "inspection", "bonding", "measurement", "analysis"}


def _n(v):
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v)


# ---------------------------------------------------------------------------
# 紀錄 → 文字
# ---------------------------------------------------------------------------
def status_text(rec):
    st = rec.get("status") or {}
    res = rec.get("results") or {}
    state = st.get("state", "active")
    if state == "abandoned":
        return "-"
    nd = st.get("next_date") or ""
    md = f" ({int(nd[5:7])}/{int(nd[8:10])})" if re.fullmatch(r"\d{4}-\d{2}-\d{2}", nd) else ""
    parts = []
    if state == "hold":
        reason = re.sub(r"^\s*擱置\s*", "", st.get("reason") or "")
        reason = re.sub(r"[（(]\s*\d{1,2}\s*/\s*\d{1,2}\s*[)）]", "", reason).strip()
        return ("擱置 " + reason).strip() + md
    if state == "measuring":
        parts.append("measuring")
    elif state == "measured":
        parts.append("measured")
    if res.get("r_ohm") is not None:
        parts.append(f"R_{_n(res['r_ohm'])}")
    if res.get("sc_contact"):
        parts.append("(SC)")
        if res.get("sc_on"):
            parts.append(f"sc on {res['sc_on']}")
    if res.get("tc_k") is not None:
        parts.append(f"Tc_{_n(res['tc_k'])}K")
    if state == "active":
        if st.get("next"):
            parts.append(st["next"])
        return (" ".join(parts) + md).strip()
    return " ".join(parts)


def sub_text(kind, p):
    p = p or {}
    if kind == "plasma":
        return f"plasma {_n(p.get('power_w', ''))}W {_n(p.get('flow_sccm', ''))}sccm {_n(p.get('time_s', ''))}s" \
            if all(p.get(k) not in (None, "") for k in ("power_w", "flow_sccm", "time_s")) else "plasma"
    if kind == "rie":
        t = (f"hBN_{_n(p['hbn_nm'])} " if p.get("hbn_nm") not in (None, "") else "") + \
            (f"RIE_{_n(p['time_s'])}s" if p.get("time_s") not in (None, "") else "RIE")
        if p.get("oe_nm") not in (None, ""):
            t += f" OE_{_n(p['oe_nm'])}nm"
        return t
    if kind == "icp":
        return f"ICP_{p['time_s']}s" if p.get("time_s") not in (None, "") else "ICP"
    if kind == "ion_mill":
        if all(p.get(k) not in (None, "") for k in ("current_ma", "height", "time_s")):
            return f"Ion milling {_n(p['current_ma'])}mA {_n(p['height'])}height_{p['time_s']}s"
        return "Ion milling"
    if kind == "deposit":
        ly = p.get("layers") or []
        if ly and all(t is not None for _, t in ly):
            t = "/".join(m for m, _ in ly) + "_" + "/".join(_n(x) for _, x in ly)
            if len(ly) == 1:
                t += "nm"
            return t + (f" ({p['method']})" if p.get("method") else "")
        return "deposit"
    return ""


def step_cells(step):
    """一步 → 試算表的幾格。"""
    k = step.get("kind")
    p = step.get("params") or {}
    if not step.get("edited") and step.get("raw"):          # 沒改過：照抄原文
        return list(step["raw"])
    if k in K.GROUP_KINDS or k == "litho_group":
        head = {"marker": ("Raith marker" if p.get("tool") == "Raith" else "evap marker" if p.get("tool") == "蒸鍍"
                           else "marker"), "contact": "contact", "top_gate": "top gate"}.get(k, "contact")
        cells = [head]
        for sub in step.get("substeps") or []:
            t = sub_text(sub.get("kind"), sub.get("params"))
            if t:
                cells.append(t)
        return cells
    if k in K.SUB_KINDS:
        t = sub_text(k, p)
        return [t] if t else []
    if k == "transfer":
        return ["transfer"]
    if k == "cover":
        return ["cover hBN"]
    if k == "afm":
        return [f"AFM hBN_{_n(p['hbn_nm'])}" if p.get("hbn_nm") not in (None, "") else "AFM"]
    if k == "raman":
        return [f"Raman ({p['note']})" if p.get("note") else "Raman"]
    if k == "other":
        return [p.get("text") or step.get("notes") or "other"]
    return [{"design": "design", "cleaning": "cleaning", "inspection": "OM", "measurement": "measure",
             "bonding": "bonding", "analysis": "analysis"}.get(k, K.label(k, "en"))]


def in_sheet(step):
    src = step.get("source") or []
    return step.get("kind") not in MINOR or "manual" in src or "sheet" in src


def process_cells(rec):
    cells = []
    for s in rec.get("steps", []):
        if in_sheet(s):
            cells += step_cells(s)
    st = rec.get("status") or {}
    if st.get("stopped_at") and st.get("state") != "abandoned" and rec.get("steps") and \
            rec["steps"][-1].get("id") == st["stopped_at"]:
        cells.append("-")
    return [c for c in cells if c]


# ---------------------------------------------------------------------------
# 欄位
# ---------------------------------------------------------------------------
def _find(head, *names):
    low = [str(h).strip().lower() for h in head]
    for n in names:
        if n.lower() in low:
            return low.index(n.lower())
    return None


def columns(head):
    ci = {"status": _find(head, "Status", "狀態"), "label": _find(head, "Label", "編號", "樣品"),
          "type": _find(head, "Type", "類型"), "start": _find(head, "Start Time", "Start", "開始"),
          "process": _find(head, "Process", "製程"), "remark": _find(head, "備註", "Note", "Notes", "Remark")}
    if ci["label"] is None or ci["process"] is None:
        from .sheet import SheetError
        raise SheetError("試算表第一列找不到「Label」或「Process」欄，為了不寫錯位置，沒有寫入")
    end = ci["remark"] if ci["remark"] is not None and ci["remark"] > ci["process"] else ci["process"] + PROCESS_MAX
    ci["process_end"] = end
    return ci


def find_row(values, ci, label):
    """Label 一樣的那一列（1 起算）；沒有 → None。"""
    want = str(label).strip().lower()
    j = ci["label"]
    for i, r in enumerate(values[1:], start=2):
        if j < len(r) and str(r[j]).strip().lower() == want:
            return i
    return None


def row_cells(rec, ci, existing=None):
    """要寫的格子 [(欄, 值)]。修改時，原本有字、現在不需要的 Process 格子會清掉。"""
    out = []
    ex = existing or []

    def put(j, v):
        if j is None:
            return
        v = "" if v is None else str(v)
        if v and v[0] in "=+@":
            v = "'" + v
        old = ex[j] if j < len(ex) else ""
        if v != str(old).strip() or (existing is None and v):
            out.append((j, v))

    put(ci["label"], rec.get("label", ""))
    put(ci["status"], status_text(rec))
    put(ci["type"], rec.get("type", ""))
    put(ci["start"], (rec.get("start") or "").replace("-", ""))
    cells = process_cells(rec)
    span = ci["process_end"] - ci["process"]
    if len(cells) > span:                                   # 格子不夠：剩下的併在最後一格
        cells = cells[:span - 1] + [" | ".join(cells[span - 1:])]
    for k in range(span):
        j = ci["process"] + k
        v = cells[k] if k < len(cells) else ""
        if v or (j < len(ex) and str(ex[j]).strip()):
            put(j, v)
    if ci["remark"] is not None:
        put(ci["remark"], rec.get("notes", ""))
    return out


# ---------------------------------------------------------------------------
# 寫入
# ---------------------------------------------------------------------------
def writer(cfg, service_account=None):
    """cfg = 設定的 samples 那一段。Apps Script 優先，其次服務帳號。"""
    from ..etching import gsync
    from .sheet import SheetError, sheet_gid, sheet_key
    url = (cfg.get("sheet_script_url") or "").strip()
    gid = sheet_gid(cfg.get("sheet", "")) if "gid=" in (cfg.get("sheet") or "") else ""
    if url:
        return gsync.ScriptSheet(url, cfg.get("sheet_token", ""), "", gid)
    sa = cfg.get("service_account") or service_account
    key = sheet_key(cfg.get("sheet", ""))
    if sa and key and not str(cfg.get("sheet", "")).lower().endswith((".xlsx", ".csv", ".tsv")):
        import os
        if os.path.isfile(str(sa)):
            import gspread
            from google.oauth2.service_account import Credentials
            from ..etching.store import SCOPES
            sh = gspread.authorize(Credentials.from_service_account_file(str(sa), scopes=SCOPES)).open_by_key(key)
            ws = next((w for w in sh.worksheets() if str(w.id) == gid), None) if gid else None
            return gsync.GspreadSheet(ws or sh.get_worksheet(0))
    raise SheetError("還沒有設定試算表的寫入方式：⚙ 樣品設定 → 自動更新試算表（Apps Script 網址 + 通行碼，或服務帳號金鑰）")


def push(rec, sheet, values=None):
    """把一個樣品寫進試算表。回傳 ("update" / "append" / "same", 第幾列)。"""
    values = values if values is not None else sheet.values()
    if not values:
        from .sheet import SheetError
        raise SheetError("試算表是空的（第一列要有 Status、Label、Process… 欄位名稱）")
    ci = columns(values[0])
    need = len(process_cells(rec)) - (ci["process_end"] - ci["process"])
    if need > 0 and ci["remark"] is not None and hasattr(sheet, "insert_cols"):
        try:                                               # Process 格子不夠：在「備註」前面插入空白欄
            sheet.insert_cols(ci["remark"], need, str(values[0][ci["remark"]]).strip())
            values = sheet.values()
            ci = columns(values[0])
            sheet._values_dirty = True
        except Exception:
            pass                                           # 舊版 Apps Script 不會插欄 → 剩下的併在最後一格
    row = find_row(values, ci, rec.get("label", ""))
    if row:
        ex = values[row - 1]
        cells = row_cells(rec, ci, ex)
        if not cells:
            return "same", row
        sheet.update(row, cells, [(ci["label"], str(ex[ci["label"]]).strip())])
        return "update", row
    cells = row_cells(rec, ci)
    keys = [j for j in (ci["label"], ci["status"], ci["process"]) if j is not None]
    rows = sheet.append([cells], keys)
    return "append", (rows[0] if rows else None)
