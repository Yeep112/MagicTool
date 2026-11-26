"""Quantum Design 的 .dat 檔（PPMS 與 MPMS / SQUID 共用同一種格式）。

格式：[Header] 區段 → 一行 [Data] → 下一行是欄位名稱 → 以逗號分隔的資料。

和 yeep_lab.io_qd 的差別：
  ‧ 文字欄位（例如 Comment）不會因為有一格像數字就整欄變成 NaN：九成以上是數字才轉成數字
  ‧ [Header] 解析成 dict（BYAPP、TITLE、INFO…），用來判斷是 PPMS 還是 SQUID
  ‧ 編碼不是 UTF-8 時（舊版軟體常見），自動改用 cp1252 / latin-1，並在 notes 記下
"""
from __future__ import annotations

import re
from io import StringIO
from pathlib import Path

_DATA_RE = re.compile(r"^\s*\[data\]\s*$", re.I)
_HEADER_RE = re.compile(r"^\s*\[header\]\s*$", re.I)

MOMENT_HINTS = ("moment (emu)", "dc moment", "m. std. err", "moment")
TRANSPORT_HINTS = ("resistance", "resistivity", "bridge", "eto", "electrical transport")


def guess_kind(header_text: str, columns_text: str) -> str:
    """依檔頭與欄位名稱判斷：SQUID（磁矩）、PPMS（電阻）或 QD（看不出來）。"""
    h = header_text.lower()
    c = columns_text.lower()
    if "mpms" in h or "squid" in h or any(k in c for k in MOMENT_HINTS[:3]):
        return "SQUID"
    if any(k in c for k in TRANSPORT_HINTS) or "resistivity" in h or "electrical transport" in h:
        return "PPMS"
    if "ppms" in h:
        return "PPMS"
    if "moment" in c:
        return "SQUID"
    return "QD"


def _decode(raw: bytes, notes: list):
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            if enc != "utf-8-sig":
                notes.append(f"檔案不是 UTF-8 編碼，已用 {enc} 讀取")
            return text
        except UnicodeDecodeError:
            continue
    notes.append("編碼無法辨識，部分字元可能顯示不正確")
    return raw.decode("utf-8", errors="replace")


def parse_header(lines) -> dict:
    """[Header] 的每一行 → dict。INFO 行是「INFO, 值, 名稱」，存成 info[名稱] = 值。"""
    out = {"raw": list(lines), "info": {}, "datatype": {}}
    for line in lines:
        s = line.strip()
        if not s or s.startswith(";") or _HEADER_RE.match(s):
            continue
        parts = [p.strip() for p in s.split(",")]
        key = parts[0].upper()
        rest = parts[1:]
        if key == "INFO":
            if len(rest) >= 2:
                out["info"][rest[-1]] = ", ".join(rest[:-1])
            elif rest:
                out["info"][rest[0]] = ""
        elif key == "DATATYPE" and len(rest) >= 2:
            out["datatype"][rest[0]] = rest[1]
        elif key:
            out[key] = ", ".join(rest)
    return out


def read_qd_dat(fp, numeric_fraction=0.9):
    """讀取 QD .dat，回傳 Dataset（kind = PPMS / SQUID / QD）。"""
    import pandas as pd
    from . import Dataset

    fp = Path(fp)
    notes = []
    text = _decode(fp.read_bytes(), notes)
    lines = text.splitlines()
    marker = next((i for i, line in enumerate(lines) if _DATA_RE.match(line)), None)
    if marker is None:
        raise ValueError(f"找不到 [Data] 標記，這不是 Quantum Design 的 .dat 檔：{fp.name}")
    if marker + 1 >= len(lines):
        raise ValueError(f"{fp.name} 只有檔頭、沒有數據")
    header = parse_header(lines[:marker])
    body = "\n".join(lines[marker + 1:])
    df = pd.read_csv(StringIO(body), sep=",", engine="c", low_memory=False, on_bad_lines="skip",
                     skipinitialspace=True)
    df.columns = [str(c).strip() for c in df.columns]
    df = df.loc[:, [not str(c).startswith("Unnamed:") or df[c].notna().any() for c in df.columns]]
    df = df.dropna(axis=1, how="all")

    text_cols = []
    for c in df.columns:
        col = df[c]
        if pd.api.types.is_numeric_dtype(col):
            continue
        filled = col.notna() & (col.astype(str).str.strip() != "")
        n_filled = int(filled.sum())
        conv = pd.to_numeric(col, errors="coerce")
        n_num = int(conv.notna().sum())
        if n_filled == 0 or n_num >= numeric_fraction * n_filled:
            df[c] = conv
        else:
            text_cols.append(c)
    if text_cols:
        notes.append("保留為文字的欄位：" + "、".join(text_cols))
    df = df.reset_index(drop=True)
    kind = guess_kind("\n".join(header["raw"]), " ".join(map(str, df.columns)))
    return Dataset(str(fp), kind, df, header, notes)
