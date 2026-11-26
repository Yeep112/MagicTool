"""讀檔：自動判斷檔案種類，讀過的檔案會快取（同一個檔案沒改過就不重讀）。

    from magic.readers import load, detect
    ds = load(path)            # Dataset：ds.kind（PPMS / SQUID / QD / Raman）、ds.df、ds.header、ds.notes
    detect(path)               # 只讀檔頭判斷種類（很快，列檔案清單用）
"""
from __future__ import annotations

import os
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

KIND_LABELS = {"PPMS": "PPMS", "SQUID": "SQUID", "QD": "QD .dat", "Raman": "光譜", "?": "未知"}


@dataclass
class Dataset:
    path: str
    kind: str                       # PPMS / SQUID / QD / Raman
    df: Any                         # pandas DataFrame
    header: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)     # 讀檔時的提醒（編碼、略過的行、文字欄位…）

    @property
    def name(self):
        return os.path.basename(self.path)

    @property
    def columns(self):
        return list(self.df.columns)

    @property
    def numeric_columns(self):
        import pandas as pd
        return [c for c in self.df.columns if pd.api.types.is_numeric_dtype(self.df[c])
                and self.df[c].notna().any()]


def detect(path, head_bytes=8192):
    """只讀檔案開頭判斷種類：'PPMS'、'SQUID'、'QD'、'Raman' 或 '?'。"""
    try:
        with open(path, "rb") as f:
            raw = f.read(head_bytes)
    except OSError:
        return "?"
    text = raw.decode("utf-8", errors="replace")
    low = text.lower()
    if "[header]" in low or "[data]" in low:
        from .qd_dat import guess_kind
        return guess_kind(low, low)
    from .raman_txt import looks_like_spectrum
    return "Raman" if looks_like_spectrum(text) else "?"


_CACHE: "OrderedDict[tuple, Dataset]" = OrderedDict()
_LOCK = threading.Lock()
CACHE_SIZE = 64


def _key(path):
    st = os.stat(path)
    return (os.path.abspath(path), st.st_mtime_ns, st.st_size)


def load(path, use_cache=True) -> Dataset:
    """讀檔（自動判斷格式）。檔案正在被寫入或同步時，會稍等重試幾次。"""
    import time
    path = os.fspath(path)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"找不到檔案：{path}")
    key = _key(path)
    if use_cache:
        with _LOCK:
            if key in _CACHE:
                _CACHE.move_to_end(key)
                return _CACHE[key]
    last = None
    for attempt in range(3):
        try:
            ds = _read(path)
            break
        except PermissionError as e:            # Synology / 量測程式正在寫入
            last = e
            time.sleep(0.4 * (attempt + 1))
    else:
        raise PermissionError(f"檔案正在被其他程式使用，稍後再試：{path}（{last}）")
    if use_cache:
        with _LOCK:
            _CACHE[key] = ds
            while len(_CACHE) > CACHE_SIZE:
                _CACHE.popitem(last=False)
    return ds


def _read(path):
    with open(path, "rb") as f:
        head = f.read(8192).decode("utf-8", errors="replace").lower()
    if "[header]" in head or "[data]" in head:
        from .qd_dat import read_qd_dat
        return read_qd_dat(path)
    from .raman_txt import read_spectrum
    return read_spectrum(path)


def clear_cache():
    with _LOCK:
        _CACHE.clear()
