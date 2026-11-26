"""Raman 光譜文字檔：兩欄（Raman shift、intensity）。

和 yeep_lab.raman.load_spectrum（np.loadtxt）的差別：
  ‧ 有標題列、說明文字的檔案也能讀（看不懂的行會略過，並記在 notes）
  ‧ 分隔符號可以是空白、Tab、逗號或分號
  ‧ 超過兩欄時用前兩欄；x 由大到小時自動排序成由小到大
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np

_SPLIT = re.compile(r"[,\t;]+|\s+")
SHIFT = "Raman shift (cm-1)"
INTENSITY = "Intensity"


def _numbers(line):
    parts = [p for p in _SPLIT.split(line.strip()) if p]
    out = []
    for p in parts:
        try:
            out.append(float(p))
        except ValueError:
            return None
    return out


def looks_like_spectrum(text, need=5):
    good = 0
    for line in text.splitlines()[:60]:
        nums = _numbers(line) if line.strip() else None
        if nums is not None and len(nums) >= 2:
            good += 1
            if good >= need:
                return True
    return False


def read_spectrum(fp):
    import pandas as pd
    from . import Dataset

    fp = Path(fp)
    raw = fp.read_bytes()
    notes = []
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
        notes.append("檔案不是 UTF-8 編碼，已用 latin-1 讀取")
    xs, ys, skipped, ncols = [], [], 0, set()
    header_lines = []
    for line in text.splitlines():
        if not line.strip():
            continue
        nums = _numbers(line)
        if nums is None or len(nums) < 2:
            skipped += 1
            if len(header_lines) < 30:
                header_lines.append(line)
            continue
        ncols.add(len(nums))
        xs.append(nums[0])
        ys.append(nums[1])
    if len(xs) < 5:
        raise ValueError(f"{fp.name} 裡找不到兩欄數字（Raman shift、intensity）")
    if skipped:
        notes.append(f"略過 {skipped} 行非數字的內容（標題或說明）")
    if max(ncols) > 2:
        notes.append(f"檔案有 {max(ncols)} 欄，使用前兩欄")
    x = np.asarray(xs, float)
    y = np.asarray(ys, float)
    if x[0] > x[-1]:
        order = np.argsort(x, kind="stable")
        x, y = x[order], y[order]
    df = pd.DataFrame({SHIFT: x, INTENSITY: y})
    return Dataset(str(fp), "Raman", df, {"raw": header_lines}, notes)


def xy(ds):
    return ds.df[SHIFT].to_numpy(float), ds.df[INTENSITY].to_numpy(float)
