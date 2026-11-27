"""蝕刻紀錄 ↔ Google Sheet（團隊共用紀錄）。

讀取（依序試，成功一個就好）
  1. Apps Script 網頁應用程式（網址 + 通行碼；試算表可以不公開）
  2. 服務帳號金鑰（service_account.json）
  3. 公開連結（試算表設成「知道連結的人可以檢視」就不需要任何設定）

寫入（新增 / 修改 / 刪除、☁ 同步）
  ‧ Apps Script（推薦）：同事只要貼上「團隊設定碼」，不需要金鑰、不需要 Google 帳號權限
  ‧ 服務帳號金鑰：試算表要共用給服務帳號的 email（編輯者）

欄位用「名稱」對應，不看位置
  ‧ 試算表原本的欄位（包括自己加的 note 之類）一律不改名、不刪、不搬
  ‧ 名稱對得上的才寫（大小寫、空白不計；note / 備註 → Notes）
  ‧ 缺的欄位加在最後面；認不得的欄位不碰（公式、顏色都留著）
  ‧ 新紀錄寫在「最後一筆有資料的列」下一列（只有空白或空格的列不算）
  ‧ 修改 / 刪除前會再確認那一列還是同一筆（Record ID 或日期、操作者、時間、厚度），對不上就停下來
"""
from __future__ import annotations

import base64
import csv
import io
import json
import math
import re
import urllib.request
from pathlib import Path

from .store import HEADERS, V1, SheetError, _cell, normalize, open_worksheet, parse_sheet_key

ALIASES = {"note": "Notes", "notes": "Notes", "備註": "Notes", "remark": "Notes", "remarks": "Notes",
           "comment": "Notes", "comments": "Notes", "date": "DateTime", "日期": "DateTime",
           "operator": "Name", "操作者": "Name"}
# 判斷「這一列有資料」用的欄位（公式算出來的 Δ、R 不算，避免公式拉到下面的空白列被當成資料）
KEY_INPUTS = ["DateTime", "Method", "Name", "H_hBN_before (nm)", "H_hBN_after (nm)", "H_marker_before (nm)",
              "H_marker_after (nm)", "H_SiO2_before (nm)", "H_SiO2_after (nm)", "T (sec)", "Record ID"]
# 寫成文字（前面加 ' ），避免 Google Sheet 把它當成數字、日期或公式
TEXT_COLS = {"Record ID", "Raw inputs", "Etch steps (s)", "OM before", "OM after"}
SCRIPT_VERSION = 1
SCRIPT_FILE = Path(__file__).with_name("apps_script.gs")
CODE_PREFIX = "MAGIC-SHEET:"


def _k(s):
    return re.sub(r"\s+", "", str(s)).lower()


_CANON = {_k(c): c for c in HEADERS}
_ALIAS = {_k(a): c for a, c in ALIASES.items()}


def canonical(name):
    """試算表的欄位名稱 → 軟體的欄位名稱（認不得回傳 None）。"""
    k = _k(name)
    return _CANON.get(k) or _ALIAS.get(k)


def _blank(v):
    return not str(v if v is not None else "").strip()


# ---------------------------------------------------------------------------
# 欄位對應
# ---------------------------------------------------------------------------
def plan(head):
    """標題列 → (對應 {軟體欄位: 第幾欄(0 起算)}, 原本有幾欄, 要加在最後面的欄位)。"""
    head = [str(h) for h in (head or [])]
    width = max((j + 1 for j, h in enumerate(head) if not _blank(h)), default=0)
    if width == 0:
        return {c: j for j, c in enumerate(HEADERS)}, 0, list(HEADERS)
    m = {}
    for j, h in enumerate(head[:width]):
        c = canonical(h)
        if c and c not in m:
            m[c] = j
    if "DateTime" not in m or sum(c in m for c in V1) < 6:
        raise SheetError("Google Sheet 第一列看起來不是蝕刻紀錄的欄位名稱（至少要有 DateTime 和幾個 H_…、T (sec) 欄位），"
                         "為了不寫錯位置，沒有寫入。工作表名稱設對了嗎？")
    missing = [c for c in HEADERS if c not in m]
    for i, c in enumerate(missing):
        m[c] = width + i
    return m, width, missing


# 每個欄位的說明與 AppSheet 建議型別（「測試連線」後列給使用者，方便在 AppSheet 那邊先對好欄位）
COLUMN_HELP = {
    "DateTime": ("寫入時間", "DateTime"), "Method": ("機台（ICP / RIE…）", "Text"),
    "Power": ("功率（文字，例如 ICP 300W / RF 30W）", "Text"), "Bias": ("DC bias（文字）", "Text"),
    "Pressure": ("壓力（文字）", "Text"), "Type": ("量法（direct…）", "Text"), "Name": ("操作者", "Text"),
    "H_hBN_before (nm)": ("材料蝕刻前高度", "Decimal"), "H_hBN_after (nm)": ("材料蝕刻後高度", "Decimal"),
    "H_marker_before (nm)": ("marker 蝕刻前高度", "Decimal"), "H_marker_after (nm)": ("marker 蝕刻後高度", "Decimal"),
    "H_SiO2_before (nm)": ("SiO2 蝕刻前高度", "Decimal"), "H_SiO2_after (nm)": ("SiO2 蝕刻後高度", "Decimal"),
    "T (sec)": ("總蝕刻時間", "Decimal"), "Δ_marker (nm)": ("= d_SiO2", "Decimal"),
    "Δ_hBN (nm)": ("= d_材料 − d_SiO2", "Decimal"), "Δ_SiO2 (nm)": ("= d_SiO2", "Decimal"),
    "R_SiO2(nm/sec)": ("SiO2 蝕刻率", "Decimal"), "R_hBN(nm/sec)": ("材料蝕刻率", "Decimal"),
    "Gas": ("氣體（文字，例如 CHF3+O2）", "Text"),
    "Schema": ("紀錄格式版本", "Text"), "Material": ("蝕刻的材料", "Text"), "Resist": ("光阻", "Text"),
    "Resist thickness (nm)": ("光阻厚度", "Decimal"), "Line width (nm)": ("線寬", "Decimal"),
    "Gas 1": ("氣體 1", "Text"), "Flow 1 (sccm)": ("流量 1", "Decimal"),
    "Gas 2": ("氣體 2", "Text"), "Flow 2 (sccm)": ("流量 2", "Decimal"),
    "Gas 3": ("氣體 3", "Text"), "Flow 3 (sccm)": ("流量 3", "Decimal"),
    "ICP power (W)": ("ICP 功率", "Decimal"), "RF power (W)": ("RF 功率", "Decimal"),
    "DC bias (V)": ("DC bias", "Decimal"), "Pressure (Pa)": ("壓力", "Decimal"),
    "Etch steps (s)": ("分段時間（例如 20+20+5）", "Text"), "N steps": ("分幾段", "Number"),
    "SiO2 method": ("SiO2 量法", "Text"), "Material method": ("材料量法", "Text"),
    "d_SiO2 (nm)": ("SiO2 被蝕刻掉的厚度", "Decimal"), "σ d_SiO2 (nm)": ("誤差", "Decimal"),
    "d_material (nm)": ("材料被蝕刻掉的厚度", "Decimal"), "σ d_material (nm)": ("誤差", "Decimal"),
    "σ R_SiO2 (nm/sec)": ("SiO2 蝕刻率誤差", "Decimal"), "σ R_material (nm/sec)": ("材料蝕刻率誤差", "Decimal"),
    "Selectivity": ("選擇比（材料 / SiO2）", "Decimal"), "Etched through": ("是否蝕穿", "Text"),
    "Raw inputs": ("原始輸入（JSON，軟體用）", "LongText"), "Notes": ("備註", "LongText"),
    "Resist after (nm)": ("光阻蝕刻後厚度", "Decimal"), "d_resist (nm)": ("光阻被蝕刻掉的厚度", "Decimal"),
    "R_resist (nm/sec)": ("光阻蝕刻率", "Decimal"), "σ R_resist (nm/sec)": ("光阻蝕刻率誤差", "Decimal"),
    "Selectivity (material/resist)": ("選擇比（材料 / 光阻）", "Decimal"),
    "SiO2 cross-check": ("SiO2 交叉檢查", "Text"), "Material cross-check": ("材料交叉檢查", "Text"),
    "Record ID": ("紀錄編號（修改 / 刪除用，不要改）", "Text"), "Revision": ("修改次數", "Number"),
    "Modified at": ("最後修改時間", "DateTime"), "OM before": ("蝕刻前 OM 照片（路徑）", "Text"),
    "OM after": ("蝕刻後 OM 照片（路徑）", "Text"),
}


def col_letter(j):
    """0 → A、25 → Z、26 → AA。"""
    s = ""
    j += 1
    while j:
        j, r = divmod(j - 1, 26)
        s = chr(65 + r) + s
    return s


def columns_report(head):
    """試算表目前的欄位、Magic Tool 第一次寫入時會加的欄位。

    回傳 {"current": [(欄, 試算表標題, 對應的軟體欄位或 None)], "added": [(欄, 欄位)], "width": 原本幾欄}；
    標題列不是蝕刻紀錄 → SheetError。"""
    m, width, missing = plan(head)
    head = [str(h) for h in (head or [])][:width]
    inv = {j: c for c, j in m.items() if j < width}
    cur = [(col_letter(j), h, inv.get(j)) for j, h in enumerate(head)]
    added = [(col_letter(m[c]), c) for c in missing]
    return {"current": cur, "added": added, "width": width}


def columns_text(rep):
    """欄位對照的文字（可以直接貼給別人或對照 AppSheet）。"""
    lines = [f"試算表目前的欄位（{rep['width']} 欄，Magic Tool 不會改名、不會搬動）："]
    for col, h, c in rep["current"]:
        if not str(h).strip():
            lines.append(f"  {col:>3}  （空白）")
            continue
        if c is None:
            lines.append(f"  {col:>3}  {h}　← Magic Tool 不使用（不會動）")
        else:
            desc = COLUMN_HELP.get(c, ("", ""))[0]
            same = "" if c == h else f" = {c}"
            lines.append(f"  {col:>3}  {h}{same}" + (f"　{desc}" if desc else ""))
    if rep["added"]:
        lines.append("")
        lines.append(f"第一次寫入時加在最後面（{rep['added'][0][0]} 欄起，共 {len(rep['added'])} 欄）"
                     "　AppSheet 要到 Data → 這張表按「Regenerate structure」才看得到：")
        for col, c in rep["added"]:
            desc, typ = COLUMN_HELP.get(c, ("", "Text"))
            lines.append(f"  {col:>3}  {c}　{desc}　［AppSheet：{typ}］")
    else:
        lines.append("")
        lines.append("Magic Tool 需要的欄位都已經有了，寫入時不會再加欄位。")
    return "\n".join(lines)


def sheet_value(col, v):
    """一格要寫進 Google Sheet 的文字（空白回傳 ""）。"""
    v = _cell(v)
    if isinstance(v, float):
        v = repr(v)
    s = str(v).strip() if v is not None else ""
    if not s:
        return ""
    if col in TEXT_COLS or s[0] in "=+@":
        return "'" + s
    return s


def _cells(rec, m, existing=None):
    """要寫的格子 [(欄, 值)]。新增：只寫有值的格子；修改：原本有值、現在變空白的也清掉。"""
    out = []
    for c, j in sorted(m.items(), key=lambda kv: kv[1]):
        s = sheet_value(c, rec.get(c, ""))
        if s:
            out.append((j, s))
        elif existing is not None and j < len(existing) and not _blank(existing[j]):
            out.append((j, ""))
    return out


def _key_idx(m):
    return [m[c] for c in KEY_INPUTS if c in m]


def last_content_row(values, key_cols):
    """最後一筆有資料的列（1 起算；只有標題列 → 1）。"""
    for i in range(len(values) - 1, 0, -1):
        r = values[i]
        if any(j < len(r) and not _blank(r[j]) for j in key_cols):
            return i + 1
    return 1


def _norm_dt(s):
    """各種日期寫法 → 'YYYY-MM-DD HH:MM'（比對用；看不懂回傳原字串）。"""
    s = str(s or "").strip()
    if not s:
        return ""
    t = s.replace("/", "-").replace("T", " ")
    pm = "下午" in t or re.search(r"\bpm\b", t, re.I)
    am = "上午" in t or re.search(r"\bam\b", t, re.I)
    t = re.sub(r"上午|下午|\b[ap]m\b", " ", t, flags=re.I)
    m = re.match(r"\s*(\d{4})-(\d{1,2})-(\d{1,2})(?:\s+(\d{1,2}):(\d{2}))?", t)
    if not m:
        return s
    y, mo, d, hh, mm = m.groups()
    h = int(hh or 0)
    if pm and h < 12:
        h += 12
    if am and h == 12:
        h = 0
    return f"{int(y):04d}-{int(mo):02d}-{int(d):02d} {h:02d}:{int(mm or 0):02d}"


def _numkey(v):
    try:
        f = float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return str(v or "").strip().lower()
    return "" if f != f else f"{round(f, 3):g}"


LEGACY_KEY = ["Name", "T (sec)", "H_hBN_before (nm)", "H_hBN_after (nm)", "H_marker_before (nm)",
              "H_marker_after (nm)"]


def legacy_key(rec):
    """沒有 Record ID 的舊紀錄用「日期到分鐘 + 操作者 + 時間 + 厚度」當作身分。"""
    dt = _norm_dt(rec.get("DateTime", ""))
    if not dt:
        return None
    return (dt,) + tuple(_numkey(rec.get(c, "")) for c in LEGACY_KEY)


def _rid(v):
    return str(v or "").strip().lstrip("'")


def find_row(values, m, rid, old=None):
    """這筆紀錄在 Google Sheet 第幾列（1 起算）。先找 Record ID，再用 legacy_key；找到不只一列也算找不到。"""
    if rid and "Record ID" in m:
        j = m["Record ID"]
        hits = [i + 1 for i, r in enumerate(values[1:], 1) if j < len(r) and _rid(r[j]) == _rid(rid)]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            return None
    if old:
        want = legacy_key(old)
        if want:
            hits = []
            for i, r in enumerate(values[1:], 1):
                row = {c: (r[j] if j < len(r) else "") for c, j in m.items()}
                if legacy_key(row) == want and (not rid or _blank(row.get("Record ID"))):
                    hits.append(i + 1)
            if len(hits) == 1:
                return hits[0]
    return None


def _expect(values, row, m):
    r = values[row - 1]
    return [(j, r[j]) for j in _key_idx(m) if j < len(r) and not _blank(r[j])]


# ---------------------------------------------------------------------------
# 兩種寫入方式（介面相同）
# ---------------------------------------------------------------------------
def _a1(row, col0):
    n, s = col0 + 1, ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return f"{s}{row}"


def _runs(cells):
    """[(欄, 值)] → 連續的幾段 [(起始欄, [值…])]，中間沒寫的格子不會被蓋掉。"""
    runs = []
    for j, v in sorted(cells):
        if runs and runs[-1][0] + len(runs[-1][1]) == j:
            runs[-1][1].append(v)
        else:
            runs.append((j, [v]))
    return runs


class GspreadSheet:
    """用服務帳號（gspread）寫。"""
    kind = "服務帳號"

    def __init__(self, ws):
        self.ws = ws
        self.title = getattr(ws, "title", "")

    def values(self):
        return self.ws.get_all_values()

    def _grow(self, rows=0, cols=0):
        rc, cc = getattr(self.ws, "row_count", None), getattr(self.ws, "col_count", None)
        if rc is not None and rows > rc:
            self.ws.add_rows(rows - rc)
        if cc is not None and cols > cc:
            self.ws.add_cols(cols - cc)

    def _write(self, row, cells):
        if not cells:
            return
        self._grow(rows=row, cols=max(j for j, _ in cells) + 1)
        for j, vals in _runs(cells):
            self.ws.update(range_name=_a1(row, j), values=[vals], value_input_option="USER_ENTERED")

    def header(self, start, names, values=None):
        head = (values or self.values() or [[]])[0]
        for i, n in enumerate(names):
            j = start + i
            if j < len(head) and not _blank(head[j]) and head[j].strip() != n:
                raise SheetError(f"標題列第 {j + 1} 欄已經有別的名稱（{head[j]}），為了不寫錯位置，沒有寫入")
        self._grow(cols=start + len(names))
        self.ws.update(range_name=_a1(1, start), values=[list(names)], value_input_option="USER_ENTERED")

    def append(self, rows, key_cols, header=None, values=None):
        values = values if values is not None else self.values()
        if header and header[1]:
            self.header(header[0], header[1], values)
        start = last_content_row(values, key_cols) + 1
        for k, cells in enumerate(rows):
            self._write(start + k, cells)
        return list(range(start, start + len(rows)))

    def _check(self, row, expect):
        r = self.values()
        cur = r[row - 1] if row - 1 < len(r) else []
        for j, v in expect:
            if (cur[j] if j < len(cur) else "").strip() != str(v).strip():
                raise SheetError(f"Google Sheet 第 {row} 列剛剛被別人改過，為了不改錯列，沒有寫入。請按 ↻ 再試一次")

    def update(self, row, cells, expect, header=None, values=None):
        if header and header[1]:
            self.header(header[0], header[1], values)
        self._check(row, expect)
        self._write(row, cells)
        return row

    def delete(self, row, expect):
        self._check(row, expect)
        self.ws.delete_rows(row)
        return row

    def insert_cols(self, before, count, expect_header=""):
        """在第 before 欄（0 起算）前面插入 count 個空白欄（整欄插入）。"""
        head = (self.values() or [[]])[0]
        if (head[before] if before < len(head) else "").strip() != expect_header:
            raise SheetError("標題列和預期的不一樣，為了不插錯位置，沒有插入")
        self.ws.insert_cols([[""]] * count, col=before + 1)
        if getattr(self.ws, "col_count", None) is not None and not hasattr(self.ws, "grid"):
            self.ws.col_count += count


class ScriptSheet:
    """用 Apps Script 網頁應用程式寫（magic/etching/apps_script.gs）。"""
    kind = "Apps Script"

    def __init__(self, url, token, worksheet="", gid="", timeout=40):
        self.url, self.token, self.worksheet, self.gid, self.timeout = url.strip(), token.strip(), worksheet, gid, timeout
        self.title = ""
        if not re.match(r"https://script\.google(usercontent)?\.com/", self.url):
            raise SheetError("Apps Script 網址應該長得像 https://script.google.com/macros/s/…/exec")
        if not self.token:
            raise SheetError("還沒有填 Apps Script 的通行碼")

    def call(self, action, **kw):
        body = dict(kw, action=action, token=self.token, sheet=self.worksheet, gid=self.gid, client=SCRIPT_VERSION)
        req = urllib.request.Request(self.url, data=json.dumps(body).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "text/plain;charset=utf-8", "User-Agent": "MagicTool"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:     # Google 會轉址一次（POST → GET），urllib 會自己跟過去
                ctype = r.headers.get("Content-Type", "")
                text = r.read().decode("utf-8", errors="replace")
        except OSError as e:
            raise SheetError(f"連不到 Apps Script：{e}")
        try:
            res = json.loads(text)
        except ValueError:
            hint = "（部署時「誰可以存取」要選「所有人」）" if "html" in ctype.lower() else ""
            raise SheetError(f"Apps Script 回應的不是資料{hint}。網址是不是 …/exec 結尾？")
        if not res.get("ok"):
            raise SheetError(f"Apps Script：{res.get('error', '不明的錯誤')}")
        self.title = res.get("title", self.title)
        return res

    def values(self):
        return self.call("read").get("values") or []

    def append(self, rows, key_cols, header=None, values=None):
        res = self.call("append", rows=[[list(c) for c in cells] for cells in rows], key_cols=key_cols,
                        header=list(header) if header and header[1] else None)
        return res.get("rows", [])

    def update(self, row, cells, expect, header=None, values=None):
        self.call("update", row=row, cells=[list(c) for c in cells], expect=[list(e) for e in expect],
                  header=list(header) if header and header[1] else None)
        return row

    def delete(self, row, expect):
        self.call("delete", row=row, expect=[list(e) for e in expect])
        return row

    def insert_cols(self, before, count, expect_header=""):
        self.call("insert_cols", before=before, count=count, expect_header=expect_header)


# ---------------------------------------------------------------------------
# 設定 → 要用哪一種
# ---------------------------------------------------------------------------
def _et(settings):
    return (settings or {}).get("etching", {}) or {}


def _gid(et):
    m = re.search(r"[#&?]gid=(\d+)", et.get("gsheet_key", "") or "")
    return m.group(1) if m else ""


def _sa(settings):
    from ..core import settings as S
    return S.service_account_path(settings)


def writer(settings):
    """能寫入的那一種（Apps Script 優先）。都沒設定 → SheetError。"""
    et = _et(settings)
    if (et.get("gsheet_script_url") or "").strip():
        return ScriptSheet(et["gsheet_script_url"], et.get("gsheet_token", ""), et.get("gsheet_worksheet", ""), _gid(et))
    sa = _sa(settings)
    if sa.is_file():
        return GspreadSheet(_open_ws(et, sa))
    raise SheetError("還沒有設定寫入方式：⚙ 設定 → 蝕刻紀錄，貼上「團隊設定碼」（Apps Script），或指定服務帳號金鑰")


def _open_ws(et, sa):
    ws_name = et.get("gsheet_worksheet", "")
    if ws_name or not _gid(et):
        return open_worksheet(et.get("gsheet_key", ""), sa, ws_name)
    import gspread
    from google.oauth2.service_account import Credentials
    from .store import SCOPES
    sh = gspread.authorize(Credentials.from_service_account_file(str(sa), scopes=SCOPES)).open_by_key(
        parse_sheet_key(et.get("gsheet_key", "")))
    gid = int(_gid(et))
    return next((w for w in sh.worksheets() if w.id == gid), sh.get_worksheet(0))


def can_write(settings):
    et = _et(settings)
    return bool((et.get("gsheet_script_url") or "").strip() and (et.get("gsheet_token") or "").strip()) or \
        _sa(settings).is_file()


def _public_csv(et, timeout=20):
    key = parse_sheet_key(et.get("gsheet_key", ""))
    if not key:
        raise SheetError("還沒有設定 Google Sheet 的網址（⚙ 設定 → 蝕刻紀錄）")
    gid = _gid(et)
    if gid or not et.get("gsheet_worksheet"):
        url = f"https://docs.google.com/spreadsheets/d/{key}/export?format=csv" + (f"&gid={gid}" if gid else "")
    else:
        from urllib.parse import quote
        url = f"https://docs.google.com/spreadsheets/d/{key}/gviz/tq?tqx=out:csv&sheet={quote(et['gsheet_worksheet'])}"
    req = urllib.request.Request(url, headers={"User-Agent": "MagicTool"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        ctype = r.headers.get("Content-Type", "")
        data = r.read()
    if "text/html" in ctype:
        raise SheetError("試算表沒有公開（需要登入）")
    return [row for row in csv.reader(io.StringIO(data.decode("utf-8-sig")))]


def read_values(settings):
    """回傳 (二維陣列, 從哪裡讀的)。"""
    et = _et(settings)
    errors = []
    if (et.get("gsheet_script_url") or "").strip():
        try:
            sh = writer(settings)
            return sh.values(), "Apps Script"
        except SheetError as e:
            errors.append(str(e))
    sa = _sa(settings)
    if sa.is_file():
        try:
            return _open_ws(et, sa).get_all_values(), "服務帳號"
        except Exception as e:
            errors.append(f"服務帳號：{e}")
    try:
        return _public_csv(et), "公開連結"
    except Exception as e:
        errors.append(f"公開連結：{e}")
    raise SheetError("讀不到 Google Sheet：\n" + "\n".join(errors))


def rows_to_df(values):
    """二維陣列 → 紀錄 DataFrame。欄位用名稱對應；空白列略過；認不得的欄位保留原名。"""
    import pandas as pd
    if not values:
        return normalize(pd.DataFrame(columns=HEADERS))
    head = [str(h).strip() for h in values[0]]
    names, used = [], set()
    for j, h in enumerate(head):
        c = canonical(h)
        name = c if c and c not in used else (h or f"欄 {j + 1}")
        while name in used:
            name += "_"
        used.add(name)
        names.append(name)
    keys = [names.index(c) for c in KEY_INPUTS if c in names]
    rid_j = names.index("Record ID") if "Record ID" in names else -1
    body = []
    for i, r in enumerate(values[1:], 2):
        r = list(r) + [""] * (len(names) - len(r))
        if any(not _blank(r[j]) for j in keys):
            vals = [str(x).strip() for x in r[:len(names)]]
            if rid_j >= 0:
                vals[rid_j] = vals[rid_j].lstrip("'")
            body.append(vals + [str(i)])
    df = pd.DataFrame(body, columns=names + ["Sheet row"])
    return normalize(df)


def read(settings):
    """讀整張 Google Sheet → (DataFrame, 從哪裡讀的)。"""
    values, how = read_values(settings)
    return rows_to_df(values), how


# ---------------------------------------------------------------------------
# 新增 / 修改 / 刪除
# ---------------------------------------------------------------------------
def append_records(sheet, recs, values=None):
    values = values if values is not None else sheet.values()
    m, width, missing = plan(values[0] if values else [])
    rows = [_cells(r, m) for r in recs]
    return sheet.append(rows, _key_idx(m), header=(width, missing) if missing else None, values=values)


def update_record(sheet, rid, new, old=None):
    values = sheet.values()
    m, width, missing = plan(values[0] if values else [])
    i = find_row(values, m, rid, old)
    if i is None:
        raise SheetError("Google Sheet 裡找不到對應的那一列（本機 CSV 已改好；Google Sheet 請手動修改）")
    cells = _cells(new, m, existing=values[i - 1])
    return sheet.update(i, cells, _expect(values, i, m), header=(width, missing) if missing else None, values=values)


def delete_record(sheet, rid, old=None):
    values = sheet.values()
    m, _, _ = plan(values[0] if values else [])
    i = find_row(values, m, rid, old)
    if i is None:
        raise SheetError("Google Sheet 裡找不到對應的那一列（本機 CSV 已刪除；Google Sheet 請手動刪除）")
    return sheet.delete(i, _expect(values, i, m))


def append(rec, settings):
    return append_records(writer(settings), [rec])


def update(rid, new, old, settings):
    return update_record(writer(settings), rid, new, old)


def delete(rid, old, settings):
    return delete_record(writer(settings), rid, old)


# ---------------------------------------------------------------------------
# ☁ 同步：本機 CSV ↔ Google Sheet 比對
# ---------------------------------------------------------------------------
def _records(df):
    if df is None or not len(df):
        return []
    cols = [c for c in df.columns if c in HEADERS]
    out = []
    for r in df[cols].to_dict("records"):
        out.append({c: ("" if (isinstance(v, float) and math.isnan(v)) else v) for c, v in r.items()})
    return out


def diff(local_df, sheet_df):
    """回傳 (只有 Google Sheet 有的紀錄, 只有本機有的紀錄)。同一筆的判斷：Record ID，或日期到分鐘 + 操作者 + 時間 + 厚度。"""
    loc, sh = _records(local_df), _records(sheet_df)

    def idx(recs):
        ids = {_rid(r.get("Record ID")) for r in recs if _rid(r.get("Record ID"))}
        keys = {k for k in (legacy_key(r) for r in recs) if k}
        return ids, keys

    lid, lkey = idx(loc)
    sid, skey = idx(sh)

    def missing(recs, ids, keys):
        out = []
        for r in recs:
            rid = _rid(r.get("Record ID"))
            if rid and rid in ids:
                continue
            k = legacy_key(r)
            if k and k in keys:
                continue
            out.append(r)
        return out
    return missing(sh, lid, lkey), missing(loc, sid, skey)


def import_to_local(recs, path):
    """把 Google Sheet 的紀錄加進本機 CSV（先備份），再依日期排序。回傳 (加了幾筆, 備份檔)。"""
    import shutil
    import time
    from . import store
    path = Path(path)
    if not recs:
        return 0, None
    backup = None
    if path.exists() and path.stat().st_size:
        sch = store.file_schema(path)
        if sch in ("v1", "v2old"):
            store.upgrade_file(path)
        elif sch == "other":
            raise store.NeedsUpgrade("紀錄檔的欄位和預期不同，請確認是不是蝕刻紀錄 CSV")
        backup = path.with_name(f"{path.stem}.匯入前備份_{time.strftime('%Y%m%d_%H%M%S')}{path.suffix}")
        shutil.copy2(path, backup)
        rows = store._read_rows(path)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = []
    for r in recs:
        r = store.fill_legacy({c: r.get(c, "") for c in HEADERS})
        if not _rid(r.get("Record ID")):
            r["Record ID"] = store.new_id()
            r["Revision"] = r.get("Revision") or 1
        rows.append(r)
    dts = [_norm_dt(r.get("DateTime", "")) for r in rows]
    order = sorted(range(len(rows)), key=lambda i: (not re.match(r"\d{4}-", dts[i]), dts[i] if re.match(r"\d{4}-", dts[i]) else "", i))
    store._write_rows(path, [rows[i] for i in order])
    return len(recs), backup


# ---------------------------------------------------------------------------
# 團隊設定碼（給同事貼上；裡面有通行碼，不要公開張貼）
# ---------------------------------------------------------------------------
def make_code(settings):
    et = _et(settings)
    d = {k: et.get(k, "") for k in ("gsheet_key", "gsheet_worksheet", "gsheet_script_url", "gsheet_token")}
    if not d["gsheet_key"] and not d["gsheet_script_url"]:
        raise SheetError("先填好 Google Sheet 網址（和 Apps Script 網址、通行碼）再產生設定碼")
    raw = json.dumps(d, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return CODE_PREFIX + base64.urlsafe_b64encode(raw).decode("ascii")


def parse_code(text):
    s = re.sub(r"\s+", "", str(text or ""))
    if CODE_PREFIX in s:
        s = s.split(CODE_PREFIX, 1)[1]
    try:
        d = json.loads(base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)).decode("utf-8"))
    except Exception:
        raise SheetError("看不懂這個設定碼（要整段複製，開頭是 MAGIC-SHEET:）")
    if not isinstance(d, dict) or not (d.get("gsheet_key") or d.get("gsheet_script_url")):
        raise SheetError("這個設定碼裡沒有 Google Sheet 的資料")
    return {k: str(d.get(k, "") or "") for k in ("gsheet_key", "gsheet_worksheet", "gsheet_script_url", "gsheet_token")}


def script_code():
    return SCRIPT_FILE.read_text(encoding="utf-8")
