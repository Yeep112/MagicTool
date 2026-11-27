"""讀試算表、把舊的「一格一步」製程文字解析成步驟。

試算表格式（目前的 Sample Tracking）：
  Status | Label | Type | Start Time | Process（之後每一格一步，沒有標題）… | 備註
例：transfer | marker | Cr/Au_10/50 (E) | contact | plasma 40W 30sccm 30s | RIE_20s OE_3nm | Cr/Au_10/70 (E) | …

解析規則
  ‧ marker / contact / top gate 開始一組；後面的 plasma、RIE、ICP、離子研磨、鍍膜都是這一組的子步驟
  ‧ AFM、Raman 是獨立的一步，但不會結束目前這一組（例如鍍 marker 金屬之前先量 Raman）
  ‧ 子步驟的順序倒退（例如鍍完膜又出現 plasma）→ 推測少寫了一個 contact，先當成新的一組並列入待確認
  ‧ 「-」= 樣品停在這裡；「N/A」= 這一步跳過
  ‧ 看不懂的文字 → 「其他」並列入待確認（不會丟掉）
"""
from __future__ import annotations

import csv
import io
import os
import re
import urllib.request
from datetime import date

from . import steps as K


class SheetError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# 一格文字 → (種類, 參數)
# ---------------------------------------------------------------------------
_RE = {
    "marker": re.compile(r"(?:(raith|evap)\.?\s*)?marker", re.I),
    "afm": re.compile(r"afm(?:\s+hbn_?([\d.]+)\s*(?:nm)?)?", re.I),
    "plasma": re.compile(r"plasma\s+([\d.]+)\s*w\s+([\d.]+)\s*sccm\s+([\d.]+)\s*s", re.I),
    "rie": re.compile(r"(?:hbn_?([\d.]+)\s*(?:nm)?\s*)?rie_?\s*([\d.+]+)\s*s(?:\s*oe_?\s*([\d.]+)\s*(?:nm)?)?", re.I),
    "icp": re.compile(r"icp_?\s*([\d.]+\s*s?(?:\s*\+\s*[\d.]+\s*s?)*)", re.I),
    "ion_mill": re.compile(r"ion\s*mil+ing\s+([\d.]+)\s*ma\s+([\d.]+)\s*height_?\s*([\d.+]+)\s*s?", re.I),
    "deposit": re.compile(r"([A-Za-z]+(?:/[A-Za-z]+)*)_\s*([\d.]+(?:/[\d.]+)*)\s*(?:nm)?\s*(?:\(\s*([ESes])\s*\))?"),
}


def _f(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return v
    return int(x) if x.is_integer() else x


def classify(text):
    """一格 → (kind, params)。kind 另外有 "stop"（-）、"skip"（N/A）、"empty"。"""
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    low = t.lower()
    if not t:
        return "empty", {}
    if t in ("-", "—", "–"):
        return "stop", {}
    if low in ("n/a", "na"):
        return "skip", {}
    if low == "transfer":
        return "transfer", {}
    if low in ("cover hbn", "cover"):
        return "cover", {}
    if low == "contact":
        return "contact", {}
    if low in ("top gate", "topgate", "top_gate"):
        return "top_gate", {}
    m = _RE["marker"].fullmatch(t)
    if m:
        tool = {"raith": "Raith", "evap": "蒸鍍"}.get((m.group(1) or "").lower(), "")
        return "marker", ({"tool": tool} if tool else {})
    if low.startswith("raman"):
        note = re.sub(r"^raman\s*", "", t, flags=re.I).strip(" ()（）")
        return "raman", ({"note": note} if note else {})
    m = _RE["afm"].fullmatch(t)
    if m:
        return "afm", ({"hbn_nm": _f(m.group(1))} if m.group(1) else {})
    m = _RE["plasma"].fullmatch(t)
    if m:
        return "plasma", {"power_w": _f(m.group(1)), "flow_sccm": _f(m.group(2)), "time_s": _f(m.group(3))}
    m = _RE["rie"].fullmatch(t)
    if m:
        p = {"time_s": _f(m.group(2)) if "+" not in m.group(2) else m.group(2)}
        if m.group(1):
            p["hbn_nm"] = _f(m.group(1))
        if m.group(3):
            p["oe_nm"] = _f(m.group(3))
        return "rie", p
    m = _RE["icp"].fullmatch(t)
    if m:
        return "icp", {"time_s": re.sub(r"[\ss]", "", m.group(1))}
    m = _RE["ion_mill"].fullmatch(t)
    if m:
        tm = m.group(3)
        return "ion_mill", {"current_ma": _f(m.group(1)), "height": _f(m.group(2)),
                            "time_s": _f(tm) if "+" not in tm else tm}
    m = _RE["deposit"].fullmatch(t)
    if m:
        metals = m.group(1).split("/")
        th = m.group(2).split("/")
        if len(metals) == len(th) and not metals[0].lower().startswith(("rie", "icp", "hbn")):
            p = {"layers": [[mt, _f(x)] for mt, x in zip(metals, th)]}
            if m.group(3):
                p["method"] = m.group(3).upper()
            return "deposit", p
    return "other", {"text": t}


# ---------------------------------------------------------------------------
# 一列的製程 → 步驟
# ---------------------------------------------------------------------------
def parse_process(cells):
    """回傳 (steps, issues, stopped)。steps 是紀錄檔格式（沒有 id / 資料夾）。"""
    steps, issues = [], []
    cur = None
    stopped = False
    counts = {}

    def new_group(kind, params=None, raw="", implied=False):
        counts[kind] = counts.get(kind, 0) + 1
        g = {"kind": kind, "params": dict(params or {}), "substeps": [], "raw": [raw] if raw else [],
             "source": ["sheet"], "n": counts[kind]}
        if implied:
            g["implied"] = True
        steps.append(g)
        return g

    for pos, text in enumerate(cells):
        kind, params = classify(text)
        raw = re.sub(r"\s+", " ", str(text or "")).strip()
        if kind == "empty":
            continue
        if kind == "stop":
            stopped = True
            rest = [c for c in cells[pos + 1:] if str(c or "").strip()]
            if rest:
                issues.append(f"「-」後面還有內容：{'、'.join(map(str, rest))}")
            break
        if kind == "skip":
            continue
        if kind in K.GROUP_KINDS:
            cur = new_group(kind, params, raw)
            continue
        if kind in K.SUB_KINDS:
            if cur is None:
                issues.append(f"「{raw}」前面沒有 marker / contact，先單獨列成一步")
                steps.append({"kind": kind, "params": params, "substeps": [], "raw": [raw], "source": ["sheet"]})
                continue
            last = cur["substeps"][-1]["kind"] if cur["substeps"] else None
            if last and K.SUB_ORDER[kind] < K.SUB_ORDER[last]:
                issues.append(f"{K.label(cur['kind'])} #{cur['n']} 鍍完膜後又出現「{raw}」，"
                              f"推測少寫了一個 {K.label(cur['kind'])}，先當成新的一次")
                cur = new_group(cur["kind"], implied=True)
            cur["substeps"].append({"kind": kind, "params": params, "raw": raw})
            cur["raw"].append(raw)
            continue
        if kind in ("transfer", "cover"):
            cur = None
        if kind == "other":
            issues.append(f"看不懂「{raw}」，先列成「其他」")
        steps.append({"kind": kind, "params": params, "substeps": [], "raw": [raw], "source": ["sheet"]})
    for s in steps:
        s.pop("n", None)
    return steps, issues, stopped


# ---------------------------------------------------------------------------
# 狀態欄 → 狀態與結果
# ---------------------------------------------------------------------------
def parse_date(text):
    s = re.sub(r"\D", "", str(text or ""))
    if len(s) == 8:
        try:
            return date(int(s[:4]), int(s[4:6]), int(s[6:])).isoformat()
        except ValueError:
            return ""
    return ""


def _md_date(m, d, start):
    """「(8/7)」→ 開始日期之後最近的 8/7。"""
    try:
        y = int(start[:4]) if start else date.today().year
        dt = date(y, m, d)
        if start and dt.isoformat() < start:
            dt = date(y + 1, m, d)
        return dt.isoformat()
    except ValueError:
        return ""


def parse_status(text, start=""):
    """回傳 {state, reason, next, next_date, results:{r_ohm, sc_contact, sc_on}, review}"""
    raw = re.sub(r"\s+", " ", str(text or "")).strip()
    low = raw.lower()
    out = {"state": "active", "reason": "", "next": "", "next_date": "",
           "results": {"r_ohm": None, "sc_contact": None, "sc_on": "", "tc_k": None}, "review": []}
    m = re.search(r"[（(]\s*(\d{1,2})\s*/\s*(\d{1,2})\s*[)）]", raw)
    if m:
        out["next_date"] = _md_date(int(m.group(1)), int(m.group(2)), start)
    if not raw:
        return out
    if raw in ("-", "—", "–"):
        out.update(state="abandoned", reason="試算表標記「-」")
        out["review"].append("試算表狀態是「-」，先當成「放棄」，請確認")
        return out
    r = re.search(r"\bR_\s*([\d.]+)", raw, re.I)
    if r:
        out["results"]["r_ohm"] = _f(r.group(1))
    if re.search(r"\(\s*sc\b", low):
        out["results"]["sc_contact"] = True
        on = re.search(r"sc\s+on\s+([A-Za-z0-9-]+)", raw, re.I)
        if on:
            out["results"]["sc_on"] = on.group(1)
    if "擱置" in raw:
        out.update(state="hold", reason=raw)
    elif low.startswith("measure") or r:
        out["state"] = "measured"
    else:
        out["next"] = re.sub(r"[（(]\s*\d{1,2}\s*/\s*\d{1,2}\s*[)）]", "", raw).strip(" .")
    return out


# ---------------------------------------------------------------------------
# 整張表 → 樣品
# ---------------------------------------------------------------------------
def _find(head, *names):
    low = [str(h).strip().lower() for h in head]
    for n in names:
        if n.lower() in low:
            return low.index(n.lower())
    return None


def parse_table(values):
    """values = 二維陣列（第一列是標題）。回傳 [{label, type, start, status, steps, issues, raw}]。"""
    if not values:
        raise SheetError("試算表是空的")
    head = [str(c).strip() for c in values[0]]
    ci = {"status": _find(head, "Status", "狀態"), "label": _find(head, "Label", "編號", "樣品"),
          "type": _find(head, "Type", "類型"), "start": _find(head, "Start Time", "Start", "開始"),
          "process": _find(head, "Process", "製程"), "remark": _find(head, "備註", "Note", "Notes", "Remark")}
    if ci["label"] is None or ci["process"] is None:
        raise SheetError("找不到「Label」或「Process」欄（第一列要有欄位名稱）")
    out = []
    for r, row in enumerate(values[1:], start=2):
        row = [("" if c is None else str(c)) for c in row]
        get = lambda k: row[ci[k]].strip() if ci[k] is not None and ci[k] < len(row) else ""   # noqa: E731
        lab = get("label")
        if not lab:
            continue
        end = ci["remark"] if ci["remark"] is not None and ci["remark"] > ci["process"] else len(row)
        cells = row[ci["process"]:end]
        start = parse_date(get("start"))
        st = parse_status(get("status"), start)
        stp, issues, stopped = parse_process(cells)
        issues = st.pop("review") + issues
        if not start:
            issues.append("試算表沒有開始日期")
        out.append({"label": lab, "type": get("type").strip(), "start": start, "status": st, "results": st.pop("results"),
                    "steps": stp, "issues": issues, "stopped": stopped, "row": r,
                    "raw": {"status": get("status"), "process": [c.strip() for c in cells if c.strip()],
                            "remark": get("remark")}})
    return out


# ---------------------------------------------------------------------------
# 讀取來源：Google Sheet（服務帳號 → 公開連結 CSV）或本機 .xlsx / .csv
# ---------------------------------------------------------------------------
def sheet_key(text):
    s = (text or "").strip()
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", s)
    return m.group(1) if m else s


def sheet_gid(text):
    m = re.search(r"[#&?]gid=(\d+)", text or "")
    return m.group(1) if m else "0"


def read_file(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook
        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb.worksheets[0]
        vals = [["" if v is None else (str(int(v)) if isinstance(v, float) and v.is_integer() else str(v))
                 for v in row] for row in ws.iter_rows(values_only=True)]
        wb.close()
        return vals
    with open(path, encoding="utf-8-sig", newline="") as f:
        text = f.read()
    delim = "\t" if ext == ".tsv" or text.count("\t") > text.count(",") else ","
    return [row for row in csv.reader(io.StringIO(text), delimiter=delim)]


def fetch(source, service_account=None, timeout=20, log=None):
    """source：試算表網址 / key，或本機檔案路徑。回傳二維陣列。"""
    source = (source or "").strip()
    if not source:
        raise SheetError("還沒有設定試算表（網址，或下載成 .xlsx / .csv 的檔案）")
    if os.path.isfile(source):
        return read_file(source)
    key = sheet_key(source)
    errors = []
    if service_account and os.path.isfile(str(service_account)):
        try:
            import gspread
            from google.oauth2.service_account import Credentials
            creds = Credentials.from_service_account_file(str(service_account), scopes=[
                "https://www.googleapis.com/auth/spreadsheets.readonly"])
            sh = gspread.authorize(creds).open_by_key(key)
            gid = int(sheet_gid(source))
            ws = next((w for w in sh.worksheets() if w.id == gid), sh.get_worksheet(0))
            return ws.get_all_values()
        except Exception as e:                       # 沒裝 gspread、沒有共用給服務帳號…
            errors.append(f"服務帳號：{e}")
    url = f"https://docs.google.com/spreadsheets/d/{key}/export?format=csv&gid={sheet_gid(source)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MagicTool"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ctype = r.headers.get("Content-Type", "")
            data = r.read()
        if "text/html" in ctype:
            raise SheetError("試算表沒有公開（需要登入）")
        return [row for row in csv.reader(io.StringIO(data.decode("utf-8-sig")))]
    except Exception as e:
        errors.append(f"公開連結：{e}")
    raise SheetError("讀不到試算表。\n" + "\n".join(errors) +
                     "\n\n可以：①把試算表共用給服務帳號的 email（檢視者即可），或 ②在 Google Sheet 選「檔案 → 下載 → "
                     ".xlsx」，再用「選檔案」匯入。")
