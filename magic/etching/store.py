"""蝕刻紀錄的存放：本機 CSV 是主要資料來源；Excel 與 Google Sheet 是選用的副本。

‧ 本機 CSV：⚙ 設定 → 蝕刻紀錄 指定位置（可以指向原本的 etch_rate_log.csv，欄位相同）
‧ Excel：勾選後每次寫入也更新同名 .xlsx
‧ Google Sheet：需要 gspread、google-auth 與服務帳號金鑰（放在 %LOCALAPPDATA%\\MagicTool\\secrets\\）；
  寫入失敗不會影響本機 CSV，只會提示
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

from .calc import HEADERS, INPUT_COLUMNS

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]        # 只需要試算表權限，不需要整個雲端硬碟


def read_log(path):
    """讀紀錄 CSV → DataFrame（檔案不存在時回傳只有欄位名稱的空表）。數值欄位轉成數字。"""
    import pandas as pd
    path = Path(path)
    if not path.exists():
        return pd.DataFrame(columns=HEADERS)
    df = pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    return normalize(df)


def normalize(df):
    import pandas as pd
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    for c in HEADERS:
        if c not in df.columns:
            df[c] = ""
    num_cols = [c for c in HEADERS if "(nm" in c or "(sec)" in c or "nm/sec" in c]
    for c in num_cols:
        df[c] = pd.to_numeric(df[c].replace("", None), errors="coerce")
    for c in df.columns:
        if c not in num_cols:
            df[c] = df[c].fillna("").astype(str)
    df["DateTime_parsed"] = pd.to_datetime(df["DateTime"], errors="coerce")
    df.insert(0, "#", range(1, len(df) + 1))
    return df.reset_index(drop=True)


def header_mismatch(path):
    """現有 CSV 的欄位和 HEADERS 不同時，回傳說明文字（相同回傳空字串）。"""
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return ""
    with open(path, encoding="utf-8-sig", newline="") as f:
        first = next(csv.reader(f), [])
    first = [c.strip() for c in first]
    if first == HEADERS:
        return ""
    missing = [c for c in HEADERS if c not in first]
    extra = [c for c in first if c not in HEADERS]
    return f"CSV 欄位和預期不同（缺少：{missing or '無'}；多出：{extra or '無'}），新的一列仍依標準欄位順序寫入"


def append_csv(row, csv_path):
    """附加到 CSV（第一次會先寫欄位名稱）。"""
    csv_path = Path(csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    new = not csv_path.exists() or csv_path.stat().st_size == 0
    with open(csv_path, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if new:
            w.writerow(HEADERS)
        w.writerow(["" if v is None else v for v in row])
    return csv_path


def append_xlsx(row, xlsx_path):
    from openpyxl import Workbook, load_workbook
    xlsx_path = Path(xlsx_path)
    xlsx_path.parent.mkdir(parents=True, exist_ok=True)
    if xlsx_path.exists():
        wb = load_workbook(xlsx_path)
        ws = wb.active
    else:
        wb = Workbook()
        ws = wb.active
        ws.title = "etch_rate_log"
        ws.append(HEADERS)
    ws.append(row)
    wb.save(xlsx_path)
    return xlsx_path


def export_xlsx(df, xlsx_path):
    """把整份紀錄（或篩選後的）存成 Excel。"""
    out = df[[c for c in HEADERS if c in df.columns]]
    out.to_excel(xlsx_path, index=False)
    return Path(xlsx_path)


def _empty(v):
    return v is None or (isinstance(v, str) and not v.strip()) or (isinstance(v, float) and v != v)


def _same(a, b):
    try:
        if _empty(a) or _empty(b):
            return _empty(a) and _empty(b)
        return abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError):
        return str(a).strip() == str(b).strip()


def find_duplicates(df, row, last=300):
    """和最近 last 筆比較使用者輸入的欄位，回傳一樣的那幾筆的「#」編號。"""
    if df is None or len(df) == 0:
        return []
    rec = dict(zip(HEADERS, row))
    tail = df.tail(last)
    hits = []
    for _, r in tail.iterrows():
        if all(_same(r.get(c, ""), rec.get(c, "")) for c in INPUT_COLUMNS):
            hits.append(int(r["#"]) if "#" in r else -1)
    return hits


# ---------------------------------------------------------------------------
# Google Sheet（選用）
# ---------------------------------------------------------------------------
def parse_sheet_key(text):
    """接受整個網址或 key。"""
    s = (text or "").strip()
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", s)
    return m.group(1) if m else s


class SheetError(RuntimeError):
    pass


def open_worksheet(key, service_account, worksheet=""):
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        raise SheetError("沒有安裝 gspread / google-auth。請在 Anaconda Prompt 執行：pip install gspread google-auth")
    sa = Path(service_account)
    if not sa.is_file():
        raise SheetError(f"找不到金鑰檔：{sa}\n請把 service_account.json 放到這裡（⚙ 設定 → 蝕刻紀錄 可以改位置）")
    key = parse_sheet_key(key)
    if not key:
        raise SheetError("還沒有設定 Google Sheet 的網址或 key（⚙ 設定 → 蝕刻紀錄）")
    creds = Credentials.from_service_account_file(str(sa), scopes=SCOPES)
    client = gspread.authorize(creds)
    sh = client.open_by_key(key)
    if worksheet:
        return sh.worksheet(worksheet)
    return sh.get_worksheet(0)


def gsheet_append(row, key, service_account, worksheet=""):
    ws = open_worksheet(key, service_account, worksheet)
    if not ws.acell("A1").value:
        ws.append_row(HEADERS, value_input_option="USER_ENTERED")
    ws.append_row(["" if v is None else v for v in row], value_input_option="USER_ENTERED")
    return True


def gsheet_read(key, service_account, worksheet=""):
    import pandas as pd
    ws = open_worksheet(key, service_account, worksheet)
    rows = ws.get_all_values()
    if not rows:
        return normalize(pd.DataFrame(columns=HEADERS))
    head, body = rows[0], rows[1:]
    width = len(head)
    body = [r + [""] * (width - len(r)) for r in body]
    return normalize(pd.DataFrame(body, columns=head))
