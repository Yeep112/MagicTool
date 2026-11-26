"""蝕刻紀錄的存放（v2 格式）。本機 CSV 是主要資料來源；Excel 與 Google Sheet 是選用的副本。

欄位相容的做法
  ‧ 原本的 20 個欄位（v1）一個都不刪、不改順序、意義不變 → Google Sheet 的舊欄位仍然對得上
  ‧ 新欄位（材料、線寬、ICP / RF、氣體流量、分段時間、量法、誤差…）一律加在最後面
  ‧ 舊格式的 CSV 第一次寫入新紀錄前會先備份（etch_rate_log.v1備份_日期.csv），再把標題列加長、
    舊紀錄的新欄位自動補上（材料 = hBN、量法 = 從基板量 + marker…）
  ‧ Google Sheet 的第一列如果是舊標題，會在後面補上新欄位名稱（資料列不動）
  ‧ v0.3 加了光阻蝕刻率、交叉檢查、Record ID 等欄位（一樣加在最後面）；0.2 寫的檔案會自動備份再補欄位

修改 / 刪除紀錄
  ‧ 每筆紀錄有 Record ID；修改時 Revision + 1、記下 Modified at
  ‧ 修改前的舊值、刪除的紀錄都寫進「<檔名>.history.csv」，可以在「修改歷史」裡還原

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
EXTRA_03 = [                                   # v0.3 加的欄位（一樣加在最後面）
    "Resist after (nm)", "d_resist (nm)", "R_resist (nm/sec)", "σ R_resist (nm/sec)", "Selectivity (material/resist)",
    "SiO2 cross-check", "Material cross-check", "Record ID", "Revision", "Modified at",
]
EXTRA_04 = ["OM before", "OM after"]          # v0.4：蝕刻前、後的 OM 照片（相對於 CSV 的路徑）
EXTRA = EXTRA + EXTRA_03 + EXTRA_04
HEADERS = V1 + EXTRA
HISTORY_HEADERS = ["Changed at", "Action", "Record ID", "Revision", "Row #", "Changed fields", "Old record (JSON)",
                   "New record (JSON)"]
SCHEMA = "2"
NUMERIC = [c for c in HEADERS if any(k in c for k in ("(nm", "(sec)", "nm/sec", "(W)", "(V)", "(Pa)", "(sccm)"))] + \
          ["N steps", "Selectivity", "Selectivity (material/resist)"]
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
        if all(c in head for c in EXTRA):
            return "v2"
        if head == HEADERS[:len(head)] and "Schema" in head:
            return "v2old"                      # 舊版寫的 v2：只少了後面的新欄位，自動補上
        return "v1"
    return "other"


def new_id():
    import uuid
    return uuid.uuid4().hex[:12]


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


def _read_rows(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [{(k or "").strip(): (v if v is not None else "") for k, v in r.items()}
                for r in csv.DictReader(f)]


def _write_rows(path, rows):
    path = Path(path)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADERS)
        for r in rows:
            w.writerow([_cell(r.get(c, "")) for c in HEADERS])
    tmp.replace(path)


def upgrade_file(path):
    """舊格式 → 目前的格式：先備份，再把標題列加長、舊紀錄補上新欄位與 Record ID。
    回傳備份檔路徑（已經是最新格式回傳 None）。"""
    path = Path(path)
    sch = file_schema(path)
    if sch not in ("v1", "v2old"):
        return None
    tag = "v1備份" if sch == "v1" else "升級前備份"
    backup = path.with_name(f"{path.stem}.{tag}_{time.strftime('%Y%m%d_%H%M%S')}{path.suffix}")
    shutil.copy2(path, backup)
    rows = []
    for r in _read_rows(path):
        r = fill_legacy(r)
        if not str(r.get("Record ID", "")).strip():
            r["Record ID"] = new_id()
            r["Revision"] = r.get("Revision") or "1"
        rows.append(r)
    _write_rows(path, rows)
    return backup


def ensure_ids(path):
    """還沒有 Record ID 的紀錄補上（修改 / 刪除前用）。回傳補了幾筆。"""
    path = Path(path)
    rows = _read_rows(path)
    n = 0
    for r in rows:
        if not str(r.get("Record ID", "")).strip():
            r["Record ID"] = new_id()
            r["Revision"] = r.get("Revision") or "1"
            n += 1
    if n:
        _write_rows(path, rows)
    return n


def append_record(rec: dict, path):
    """把一筆 v2 紀錄（dict）加到 CSV。舊格式會丟出 NeedsUpgrade（請先 upgrade_file）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    sch = file_schema(path)
    if sch == "v2old":
        upgrade_file(path)                      # 舊版的 v2 只缺後面的欄位：自動備份、補上
        sch = "v2"
    if sch == "v1":
        raise NeedsUpgrade("紀錄檔是舊格式（v1），要先升級才能寫入新欄位")
    if sch == "other":
        raise NeedsUpgrade("紀錄檔的欄位和預期不同，請確認是不是蝕刻紀錄 CSV")
    new = sch in ("missing", "empty")
    rec = dict(rec)
    if not str(rec.get("Record ID", "")).strip():
        rec["Record ID"] = new_id()
        rec["Revision"] = rec.get("Revision") or 1
    with open(path, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if new:
            w.writerow(HEADERS)
        w.writerow([_cell(rec.get(c, "")) for c in HEADERS])
    return rec


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
# OM 照片（複製到 <檔名>_images，CSV 只記相對路徑）
# ---------------------------------------------------------------------------
def images_dir(csv_path):
    p = Path(csv_path)
    return p.parent / f"{p.stem}_images"


def attach_image(csv_path, rid, which, src):
    """把照片複製到紀錄旁邊的 _images 資料夾 → 回傳相對路徑（已經在裡面就直接用）。"""
    src = Path(src)
    if not src.is_file():
        raise FileNotFoundError(f"找不到照片：{src}")
    d = images_dir(csv_path)
    d.mkdir(parents=True, exist_ok=True)
    dst = d / f"{rid}_{which}{src.suffix.lower()}"
    try:
        same = dst.exists() and src.resolve() == dst.resolve()
    except OSError:
        same = False
    if not same:
        for old in d.glob(f"{rid}_{which}.*"):           # 換照片：舊的那張改名留著（修改歷史還找得到）
            if old.resolve() != src.resolve():
                old.rename(old.with_name(f"{old.stem}_old_{time.strftime('%Y%m%d_%H%M%S')}{old.suffix}"))
        shutil.copy2(src, dst)
    return f"{d.name}/{dst.name}"


def resolve_image(csv_path, rel):
    """CSV 裡的相對路徑 → 絕對路徑（找不到回傳 None）。"""
    rel = str(rel or "").strip()
    if not rel:
        return None
    p = Path(rel)
    if not p.is_absolute():
        p = Path(csv_path).parent / rel
    return p if p.is_file() else None


# ---------------------------------------------------------------------------
# 修改 / 刪除（舊值寫進 history，可以還原）
# ---------------------------------------------------------------------------
class RecordNotFound(RuntimeError):
    pass


def history_path(path):
    path = Path(path)
    return path.with_name(f"{path.stem}.history.csv")


def _write_history(path, action, rid, rev, row_no, old, new):
    hp = history_path(path)
    first = not hp.exists() or hp.stat().st_size == 0
    changed = []
    if old and new:
        for c in HEADERS:
            if c in ("Revision", "Modified at", "Raw inputs", "DateTime"):
                continue
            a, b = str(old.get(c, "")), str(_cell(new.get(c, "")))
            na, nb = _num(a), _num(b)
            if na is not None and nb is not None:
                if abs(na - nb) < 1e-9:
                    continue
                a, b = f"{na:.6g}", f"{nb:.6g}"
            if a != b:
                changed.append(f"{c}: {a or '（空）'} → {b or '（空）'}")
    with open(hp, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if first:
            w.writerow(HISTORY_HEADERS)
        w.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), action, rid, rev, row_no, "；".join(changed[:30]),
                    json.dumps(old or {}, ensure_ascii=False),
                    json.dumps({k: _cell(v) for k, v in (new or {}).items()}, ensure_ascii=False)])
    return hp


def read_history(path):
    import pandas as pd
    hp = history_path(path)
    if not hp.exists() or hp.stat().st_size == 0:
        return pd.DataFrame(columns=HISTORY_HEADERS)
    return pd.read_csv(hp, encoding="utf-8-sig", dtype=str, keep_default_na=False)


def _find(rows, rid):
    hits = [i for i, r in enumerate(rows) if str(r.get("Record ID", "")).strip() == str(rid).strip()]
    if len(hits) != 1:
        raise RecordNotFound(f"紀錄檔裡找不到 Record ID = {rid}（可能被別人改過或刪除了）；請按 ↻ 重新讀取")
    return hits[0]


def replace_record(path, rid, new_rec):
    """用 new_rec 取代 Record ID = rid 的那一筆（保留 ID、原本的日期；Revision + 1）。舊值寫進 history。
    回傳 (舊紀錄 dict, 新紀錄 dict)。"""
    path = Path(path)
    if file_schema(path) in ("v1", "v2old"):
        upgrade_file(path)
    rows = _read_rows(path)
    i = _find(rows, rid)
    old = rows[i]
    try:
        rev = int(float(old.get("Revision") or 1)) + 1
    except ValueError:
        rev = 2
    new = dict(new_rec)
    new.update({"Record ID": old["Record ID"], "Revision": rev, "Modified at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "DateTime": old.get("DateTime") or new.get("DateTime", "")})
    _write_history(path, "修改", old["Record ID"], rev, i + 1, old, new)
    rows[i] = {c: _cell(new.get(c, "")) for c in HEADERS}
    _write_rows(path, rows)
    return old, rows[i]


def delete_record(path, rid):
    """刪除 Record ID = rid 的那一筆（整筆寫進 history，可以還原）。回傳刪掉的紀錄。"""
    path = Path(path)
    rows = _read_rows(path)
    i = _find(rows, rid)
    old = rows.pop(i)
    _write_history(path, "刪除", old.get("Record ID", ""), old.get("Revision", ""), i + 1, old, None)
    _write_rows(path, rows)
    return old


def restore_history(path, entry):
    """把 history 裡的一筆還原：「修改」→ 那筆紀錄改回修改前的值；「刪除」→ 放回原來的位置。"""
    path = Path(path)
    old = json.loads(entry["Old record (JSON)"] or "{}")
    if not old:
        raise RecordNotFound("這一筆歷史沒有舊值可以還原")
    rid = entry["Record ID"]
    rows = _read_rows(path)
    if entry["Action"] == "刪除":
        if any(str(r.get("Record ID", "")) == rid for r in rows):
            raise RecordNotFound("這筆紀錄已經在紀錄檔裡了（可能已經還原過）")
        try:
            pos = max(0, min(len(rows), int(entry.get("Row #") or len(rows) + 1) - 1))
        except ValueError:
            pos = len(rows)
        rows.insert(pos, {c: old.get(c, "") for c in HEADERS})
        _write_history(path, "還原刪除", rid, old.get("Revision", ""), pos + 1, None, old)
        _write_rows(path, rows)
        return old
    i = _find(rows, rid)
    cur = rows[i]
    try:
        rev = int(float(cur.get("Revision") or 1)) + 1
    except ValueError:
        rev = 2
    back = {**{c: old.get(c, "") for c in HEADERS}, "Revision": rev,
            "Modified at": time.strftime("%Y-%m-%d %H:%M:%S")}
    _write_history(path, "還原", rid, rev, i + 1, cur, back)
    rows[i] = back
    _write_rows(path, rows)
    return back


def record_to_inputs(row):
    """表格裡的一筆紀錄 → EtchInput 的欄位（修改紀錄用：條件和量測值都帶入）。"""
    raw = row.get("Raw inputs", "")
    try:
        d = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        d = {}
    if d:
        d.pop("version", None)
        if "gases" in d:
            d["gases"] = [tuple(x) for x in d["gases"]]
        return d

    def num(c):
        v = _num(row.get(c))
        return "" if v is None else f"{v:g}"
    d = {"material": row.get("Material") or "hBN", "instrument": row.get("Method", "") or "ICP-RIE",
         "name": row.get("Name", ""), "sample_type": row.get("Type", ""), "steps": num("T (sec)") or "",
         "gases": [(g, "") for g in re.split(r"[+/,\s]+", str(row.get("Gas", ""))) if g],
         "mat_method": "outside", "mat_before": num("H_hBN_before (nm)"), "mat_out": num("H_hBN_after (nm)"),
         "notes": row.get("Notes", "")}
    if num("H_marker_before (nm)") and num("H_marker_after (nm)"):
        d.update(sio2_method="marker", marker_before=num("H_marker_before (nm)"),
                 marker_out=num("H_marker_after (nm)"))
    elif num("H_SiO2_before (nm)") and num("H_SiO2_after (nm)"):
        d.update(sio2_method="ellipsometer", sio2_before=num("H_SiO2_before (nm)"),
                 sio2_after=num("H_SiO2_after (nm)"))
    m = re.search(r"([\d.]+)\s*W", str(row.get("Power", "")))
    if m:
        d["icp_power" if d["instrument"].upper().startswith("ICP") else "rf_power"] = m.group(1)
    m = re.search(r"([-\d.]+)\s*V", str(row.get("Bias", "")))
    if m:
        d["dc_bias"] = m.group(1)
    m = re.match(r"\s*([\d.]+)\s*([A-Za-z]*)", str(row.get("Pressure", "")))
    if m:
        d["pressure"] = m.group(1)
        unit = {"pa": "Pa", "mtorr": "mTorr", "torr": "Torr", "mbar": "mbar"}.get(m.group(2).lower(), "Pa")
        d["pressure_unit"] = unit
    return d


# ---------------------------------------------------------------------------
# 由計算結果組成一筆紀錄
# ---------------------------------------------------------------------------
def make_record(inp, res, when=None, version=""):
    """EtchInput + EtchResult → dict（v2 欄位）。"""
    from dataclasses import asdict
    from .model import MAT_SHORT, SIO2_SHORT, cross_text
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
        "Resist after (nm)": mean("resist_after"), "d_resist (nm)": res.d_resist, "R_resist (nm/sec)": res.r_resist,
        "σ R_resist (nm/sec)": res.sr_resist, "Selectivity (material/resist)": res.sel_resist,
        "SiO2 cross-check": cross_text(res.sio2_cross, SIO2_SHORT), "Material cross-check": cross_text(res.mat_cross,
                                                                                                    MAT_SHORT),
    }
    if mean("resist_thickness") is not None:
        rec["Resist thickness (nm)"] = mean("resist_thickness")
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


def _sheet_row(ws, rid, old=None):
    """Google Sheet 裡這筆紀錄在第幾列（1 起算，含標題列）。先找 Record ID；舊紀錄沒有 ID 時用日期 + 原始輸入比對。"""
    rows = ws.get_all_values()
    if not rows:
        return None
    head = [str(c).strip() for c in rows[0]]
    if "Record ID" in head:
        j = head.index("Record ID")
        hits = [i for i, r in enumerate(rows[1:], 2) if len(r) > j and r[j].strip() == str(rid)]
        if len(hits) == 1:
            return hits[0]
    if old:
        keys = [c for c in ("DateTime", "Name", "Raw inputs", "T (sec)") if c in head and str(old.get(c, "")).strip()]
        if keys and "DateTime" in keys:
            idx = [head.index(c) for c in keys]
            want = [str(old.get(c, "")).strip() for c in keys]
            hits = [i for i, r in enumerate(rows[1:], 2)
                    if all(len(r) > j and str(r[j]).strip() == w for j, w in zip(idx, want))]
            if len(hits) == 1:
                return hits[0]
    return None


def gsheet_update(rid, new_rec, old_rec, key, service_account, worksheet="", ws=None):
    """修改 Google Sheet 裡對應的那一列。找不到（或找到不只一列）就丟出 SheetError，不會改錯列。"""
    ws = ws or open_worksheet(key, service_account, worksheet)
    ensure_sheet_header(ws)
    i = _sheet_row(ws, rid, old_rec)
    if i is None:
        raise SheetError("Google Sheet 裡找不到對應的那一列（本機 CSV 已改好；Google Sheet 請手動修改）")
    ws.update(range_name=f"A{i}", values=[[_cell(new_rec.get(c, "")) for c in HEADERS]],
              value_input_option="USER_ENTERED")
    return i


def gsheet_delete(rid, old_rec, key, service_account, worksheet="", ws=None):
    ws = ws or open_worksheet(key, service_account, worksheet)
    i = _sheet_row(ws, rid, old_rec)
    if i is None:
        raise SheetError("Google Sheet 裡找不到對應的那一列（本機 CSV 已刪除；Google Sheet 請手動刪除）")
    ws.delete_rows(i)
    return i
