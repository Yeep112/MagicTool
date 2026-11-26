"""蝕刻紀錄的存放（v2 格式）。本機 CSV 是主要資料來源；Excel 與 Google Sheet 是選用的副本。

欄位相容的做法
  ‧ 原本的 20 個欄位（v1）一個都不刪、不改順序、意義不變 → Google Sheet 的舊欄位仍然對得上
  ‧ 新欄位（材料、線寬、ICP / RF、氣體流量、分段時間、量法、誤差…）一律加在最後面
  ‧ 舊格式的 CSV 第一次寫入新紀錄前會先備份（etch_rate_log.v1備份_日期.csv），再把標題列加長、
    舊紀錄的新欄位自動補上（材料 = hBN、量法 = 從基板量 + marker…）
  ‧ Google Sheet 的第一列如果是舊標題，會在後面補上新欄位名稱（資料列不動）

舊欄位在 v2 的填法（讓舊公式 R_hBN = (Δ_hBN + Δ_marker) / T 仍然成立）
  Method = 機台、Power = 「ICP 300W / RF 30W」、Bias = DC bias、Gas = 「CHF3+O2」
  Δ_marker = d_SiO2、Δ_hBN = d_材料 − d_SiO2、Δ_SiO2 = d_SiO2（正值 = 被蝕刻掉）
  R_hBN = 所選材料的蝕刻率（材料名稱在新欄位 Material）
"""
from __future__ import annotations

import csv
import json
import re
import shutil
import time
from pathlib import Path

from .calc import HEADERS as V1

EXTRA = [
    "Schema", "Material", "Resist", "Resist thickness (nm)", "Line width (nm)",
    "Gas 1", "Flow 1 (sccm)", "Gas 2", "Flow 2 (sccm)", "Gas 3", "Flow 3 (sccm)",
    "ICP power (W)", "RF power (W)", "DC bias (V)", "Pressure (Pa)",
    "Etch steps (s)", "N steps", "SiO2 method", "Material method",
    "d_SiO2 (nm)", "σ d_SiO2 (nm)", "d_material (nm)", "σ d_material (nm)",
    "σ R_SiO2 (nm/sec)", "σ R_material (nm/sec)", "Selectivity", "Etched through",
    "Raw inputs", "Notes",
]
HEADERS = V1 + EXTRA
SCHEMA = "2"
NUMERIC = [c for c in HEADERS if any(k in c for k in ("(nm", "(sec)", "nm/sec", "(W)", "(V)", "(Pa)", "(sccm)"))] + \
          ["N steps", "Selectivity"]
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]        # 只需要試算表權限，不需要整個雲端硬碟


class NeedsUpgrade(RuntimeError):
    """紀錄檔還是舊格式（v1），寫入新紀錄前要先升級。"""


# ---------------------------------------------------------------------------
# 讀檔與舊紀錄補欄位
# ---------------------------------------------------------------------------
def file_schema(path):
    """'missing'、'empty'、'v1'、'v2' 或 'other'。"""
    path = Path(path)
    if not path.exists():
        return "missing"
    if path.stat().st_size == 0:
        return "empty"
    with open(path, encoding="utf-8-sig", newline="") as f:
        head = [c.strip() for c in next(csv.reader(f), [])]
    if head == HEADERS:
        return "v2"
    if head == V1:
        return "v1"
    if head[:len(V1)] == V1:
        return "v2" if all(c in head for c in EXTRA) else "v1"
    return "other"


def read_log(path):
    """讀紀錄 CSV → DataFrame（檔案不存在時回傳只有欄位名稱的空表）。舊紀錄的新欄位會自動補上（只在記憶體裡）。"""
    import pandas as pd
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return normalize(pd.DataFrame(columns=HEADERS))
    df = pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    return normalize(df)


def _num(v):
    try:
        f = float(str(v).strip())
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _pressure_pa(text):
    from .model import EtchInputError, parse_pressure_pa
    try:
        return parse_pressure_pa(str(text).replace(" ", ""), "Pa") if str(text).strip() else None
    except EtchInputError:
        return None


def fill_legacy(rec: dict) -> dict:
    """v1 紀錄 → 補上 v2 的新欄位（推得出來的才補，推不出來的留空）。"""
    if str(rec.get("Schema", "")).strip():
        return rec
    rec = dict(rec)
    rec["Schema"] = "1"
    rec["Material"] = rec.get("Material") or "hBN"
    b, a = _num(rec.get("H_SiO2_before (nm)")), _num(rec.get("H_SiO2_after (nm)"))
    if b is not None and a is not None:
        rec["Δ_SiO2 (nm)"] = b - a                    # 舊版存成 after − before（正負號相反），統一成被蝕刻掉的厚度
    dm, dh = _num(rec.get("Δ_marker (nm)")), _num(rec.get("Δ_hBN (nm)"))
    if dm is not None:
        rec["d_SiO2 (nm)"] = dm
    if dh is not None:
        rec["d_material (nm)"] = dh + (dm or 0.0)
    has_marker = _num(rec.get("H_marker_before (nm)")) is not None and _num(rec.get("H_marker_after (nm)")) is not None
    rec["SiO2 method"] = "marker" if has_marker else ("ellipsometer" if b is not None and a is not None else "")
    rec["Material method"] = "outside" if _num(rec.get("H_hBN_after (nm)")) is not None else ""
    t = _num(rec.get("T (sec)"))
    if t is not None:
        rec["Etch steps (s)"] = f"{t:g}"
        rec["N steps"] = 1
    gases = [g for g in re.split(r"[+/,\s]+", str(rec.get("Gas", ""))) if g]
    for i, g in enumerate(gases[:3], 1):
        rec[f"Gas {i}"] = g
    rec["Pressure (Pa)"] = _pressure_pa(rec.get("Pressure", ""))
    return rec


def _parse_dates(col):
    """紀錄裡的日期格式可能混在一起（軟體寫的、Excel 改過的、Google Sheet 的），逐筆判斷、看不懂的留空。"""
    import warnings
    import pandas as pd
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        try:
            return pd.to_datetime(col, errors="coerce", format="mixed")
        except (TypeError, ValueError):
            return pd.to_datetime(col, errors="coerce")


def normalize(df):
    import pandas as pd
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    for c in HEADERS:
        if c not in df.columns:
            df[c] = ""
    if len(df):
        df = pd.DataFrame([fill_legacy(r) for r in df.to_dict("records")], columns=list(df.columns))
    for c in NUMERIC:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c].replace("", None), errors="coerce")
    for c in df.columns:
        if c not in NUMERIC:
            df[c] = df[c].fillna("").astype(str)
    df["Etched through"] = df["Etched through"].astype(str).str.lower().isin(["true", "1", "yes"])
    df["DateTime_parsed"] = _parse_dates(df["DateTime"])
    if "#" in df.columns:
        df = df.drop(columns=["#"])
    df.insert(0, "#", range(1, len(df) + 1))
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# 寫入
# ---------------------------------------------------------------------------
def _cell(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float):
        return "" if v != v else repr(round(v, 10))
    return v


def upgrade_file(path):
    """v1 → v2：先備份，再把標題列加長、舊紀錄補上新欄位。回傳備份檔路徑（已經是 v2 回傳 None）。"""
    path = Path(path)
    if file_schema(path) != "v1":
        return None
    backup = path.with_name(f"{path.stem}.v1備份_{time.strftime('%Y%m%d_%H%M%S')}{path.suffix}")
    shutil.copy2(path, backup)
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADERS)
        for r in rows:
            r = fill_legacy({k.strip(): v for k, v in r.items() if k is not None})
            w.writerow([_cell(r.get(c, "")) for c in HEADERS])
    tmp.replace(path)
    return backup


def append_record(rec: dict, path):
    """把一筆 v2 紀錄（dict）加到 CSV。舊格式會丟出 NeedsUpgrade（請先 upgrade_file）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    sch = file_schema(path)
    if sch == "v1":
        raise NeedsUpgrade("紀錄檔是舊格式（v1），要先升級才能寫入新欄位")
    if sch == "other":
        raise NeedsUpgrade("紀錄檔的欄位和預期不同，請確認是不是蝕刻紀錄 CSV")
    new = sch in ("missing", "empty")
    with open(path, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if new:
            w.writerow(HEADERS)
        w.writerow([_cell(rec.get(c, "")) for c in HEADERS])
    return path


def append_csv(row, csv_path):
    """舊版介面（v1 的 20 欄 list）。保留給舊的 notebook 用；新紀錄請用 append_record。"""
    rec = dict(zip(V1, row))
    path = Path(csv_path)
    if file_schema(path) == "v1":
        with open(path, "a", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerow(["" if v is None else v for v in row])
        return path
    return append_record(fill_legacy(rec), path)


def append_xlsx(rec: dict, xlsx_path):
    from openpyxl import Workbook, load_workbook
    xlsx_path = Path(xlsx_path)
    xlsx_path.parent.mkdir(parents=True, exist_ok=True)
    if xlsx_path.exists():
        wb = load_workbook(xlsx_path)
        ws = wb.active
        head = [c.value for c in ws[1]]
        if head[:len(V1)] == V1 and len(head) < len(HEADERS):          # 舊標題 → 補上新欄位
            for j, name in enumerate(HEADERS[len(head):], len(head) + 1):
                ws.cell(row=1, column=j, value=name)
    else:
        wb = Workbook()
        ws = wb.active
        ws.title = "etch_rate_log"
        ws.append(HEADERS)
    ws.append([_cell(rec.get(c, "")) for c in HEADERS])
    wb.save(xlsx_path)
    return xlsx_path


def export_xlsx(df, xlsx_path):
    out = df[[c for c in HEADERS if c in df.columns]].copy()
    out["Etched through"] = out["Etched through"].map(lambda v: "TRUE" if v else "")
    out.to_excel(xlsx_path, index=False)
    return Path(xlsx_path)


# ---------------------------------------------------------------------------
# 由計算結果組成一筆紀錄
# ---------------------------------------------------------------------------
def make_record(inp, res, when=None, version=""):
    """EtchInput + EtchResult → dict（v2 欄位）。"""
    from dataclasses import asdict
    from datetime import datetime
    when = when or datetime.now()

    def mean(key):
        m = res.measures.get(key)
        return m.mean if m is not None else None
    icp, rf, dc = _num(inp.icp_power), _num(inp.rf_power), _num(inp.dc_bias)
    power = " / ".join(x for x in (f"ICP {icp:g}W" if icp is not None else "",
                                   f"RF {rf:g}W" if rf is not None else "") if x)
    d_sio2 = res.d_sio2
    h_after = None
    if res.remaining is not None:
        h_after = res.remaining + (d_sio2 or 0.0)
    if inp.mat_method == "outside":
        h_after = mean("mat_out")
    rec = {
        "DateTime": when.strftime("%Y-%m-%d %H:%M:%S"), "Method": inp.instrument, "Power": power,
        "Bias": f"{dc:g}V" if dc is not None else "",
        "Pressure": f"{inp.pressure} {inp.pressure_unit}".strip() if str(inp.pressure).strip() else "",
        "Type": inp.sample_type, "Name": inp.name,
        "H_hBN_before (nm)": mean("mat_before"), "H_hBN_after (nm)": h_after,
        "H_marker_before (nm)": mean("marker_before"), "H_marker_after (nm)": mean("marker_out"),
        "H_SiO2_before (nm)": mean("sio2_before"), "H_SiO2_after (nm)": mean("sio2_after"),
        "T (sec)": res.t_total, "Δ_marker (nm)": d_sio2,
        "Δ_hBN (nm)": res.d_mat - (d_sio2 or 0.0), "Δ_SiO2 (nm)": d_sio2,
        "R_SiO2(nm/sec)": res.r_sio2, "R_hBN(nm/sec)": res.r_mat, "Gas": inp.gas_text(),
        "Schema": SCHEMA, "Material": inp.material, "Resist": inp.resist,
        "Resist thickness (nm)": _num(inp.resist_thickness), "Line width (nm)": res.line_width_nm,
        "ICP power (W)": icp, "RF power (W)": rf, "DC bias (V)": dc, "Pressure (Pa)": res.pressure_pa,
        "Etch steps (s)": "+".join(f"{s:g}" for s in res.t_steps), "N steps": len(res.t_steps),
        "SiO2 method": inp.sio2_method, "Material method": inp.mat_method,
        "d_SiO2 (nm)": d_sio2, "σ d_SiO2 (nm)": res.s_sio2, "d_material (nm)": res.d_mat,
        "σ d_material (nm)": res.s_mat, "σ R_SiO2 (nm/sec)": res.sr_sio2, "σ R_material (nm/sec)": res.sr_mat,
        "Selectivity": res.selectivity, "Etched through": bool(res.through),
        "Raw inputs": json.dumps({"version": version, **asdict(inp)}, ensure_ascii=False),
        "Notes": inp.notes,
    }
    for i, (g, f) in enumerate([x for x in inp.gases if str(x[0]).strip()][:3], 1):
        rec[f"Gas {i}"] = g
        rec[f"Flow {i} (sccm)"] = _num(f)
    return rec


def _raw_key(raw):
    try:
        d = json.loads(raw)
    except (TypeError, ValueError):
        return None
    for k in ("version", "notes", "name"):
        d.pop(k, None)
    return json.dumps(d, sort_keys=True, ensure_ascii=False)


def find_duplicates(df, rec, last=300):
    """和最近 last 筆比較「所有輸入」，回傳完全一樣的那幾筆的「#」編號。"""
    if df is None or len(df) == 0:
        return []
    key = _raw_key(rec.get("Raw inputs", ""))
    if key is None:
        return []
    hits = []
    for _, r in df.tail(last).iterrows():
        if _raw_key(r.get("Raw inputs", "")) == key:
            hits.append(int(r["#"]))
    return hits


# ---------------------------------------------------------------------------
# Google Sheet（選用）
# ---------------------------------------------------------------------------
def parse_sheet_key(text):
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
    return sh.worksheet(worksheet) if worksheet else sh.get_worksheet(0)


def ensure_sheet_header(ws):
    """第一列是空的 → 寫 v2 標題；是舊標題 → 在後面補新欄位名稱（資料列不動）。回傳做了什麼。"""
    head = [str(c).strip() for c in ws.row_values(1)]
    if not any(head):
        ws.append_row(HEADERS, value_input_option="USER_ENTERED")
        return "new"
    if head[:len(HEADERS)] == HEADERS:
        return "ok"
    if head[:len(V1)] == V1:
        ws.update(range_name="A1", values=[HEADERS])
        return "upgraded"
    raise SheetError("Google Sheet 第一列不是蝕刻紀錄的欄位名稱，為了不寫錯位置，沒有寫入")


def gsheet_append(rec, key, service_account, worksheet="", ws=None):
    ws = ws or open_worksheet(key, service_account, worksheet)
    ensure_sheet_header(ws)
    ws.append_row([_cell(rec.get(c, "")) for c in HEADERS], value_input_option="USER_ENTERED")
    return True


def gsheet_read(key, service_account, worksheet="", ws=None):
    import pandas as pd
    ws = ws or open_worksheet(key, service_account, worksheet)
    rows = ws.get_all_values()
    if not rows:
        return normalize(pd.DataFrame(columns=HEADERS))
    head, body = rows[0], rows[1:]
    width = len(head)
    body = [r + [""] * (width - len(r)) for r in body]
    return normalize(pd.DataFrame(body, columns=head))
