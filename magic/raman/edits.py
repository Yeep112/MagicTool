"""Raman 光譜的「編修」：橡皮擦（擦掉雜訊點）與手動背景（錨點）。

**只影響顯示與分析，原始檔完全不會被修改**。編修記錄在
`%LOCALAPPDATA%\\MagicTool\\raman_edits.json`（依檔案路徑），可以隨時復原或清除。

    {"D:\\...\\sample1.txt": {"sig": [1015, 100.2, 3200.5],      # 點數、x 最小、x 最大（檔案換了就不套用）
                              "erase": [1582.31, 1582.95],       # 被擦掉的點（用 x 值記，排序後也找得到）
                              "anchors": [[1100, 230.5], ...],   # 手動背景的錨點 (x, y)
                              "interp": "平滑"}}                  # 錨點之間：平滑（PCHIP）或直線
"""
from __future__ import annotations

import copy
import json
import os
import threading

import numpy as np

INTERPS = ["平滑", "直線"]
ND = 4                       # x 值比對到小數點後 4 位


def _norm(path):
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def signature(x):
    x = np.asarray(x, float)
    return [int(x.size), round(float(np.nanmin(x)), ND), round(float(np.nanmax(x)), ND)] if x.size else [0, 0, 0]


def empty():
    return {"erase": [], "anchors": [], "interp": INTERPS[0]}


def is_empty(ed):
    return not ed or (not ed.get("erase") and not ed.get("anchors"))


class EditStore:
    def __init__(self, path=None):
        if path is None:
            from ..core.settings import data_dir
            path = data_dir() / "raman_edits.json"
        self.path = os.fspath(path)
        self._lock = threading.Lock()
        try:
            with open(self.path, encoding="utf-8") as f:
                self.data = json.load(f)
        except (OSError, ValueError):
            self.data = {}

    def get(self, path):
        with self._lock:
            return copy.deepcopy(self.data.get(_norm(path))) or empty()

    def set(self, path, ed, sig=None):
        key = _norm(path)
        with self._lock:
            if is_empty(ed):
                self.data.pop(key, None)
            else:
                ed = copy.deepcopy(ed)
                if sig is not None:
                    ed["sig"] = sig
                elif key in self.data and "sig" in self.data[key]:
                    ed.setdefault("sig", self.data[key]["sig"])
                self.data[key] = ed
            self._write()

    def _write(self):
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except OSError:
            pass

    def snapshot(self, paths):
        """在主執行緒取一份，背景計算用（之後編修不會影響正在算的那一次）。"""
        with self._lock:
            return {_norm(p): copy.deepcopy(self.data[_norm(p)]) for p in paths if _norm(p) in self.data}

    def count(self, path):
        ed = self.data.get(_norm(path)) or {}
        return len(ed.get("erase", [])), len(ed.get("anchors", []))


def erased_mask(x, erase):
    """x 裡哪些點被擦掉了（True = 擦掉）。"""
    x = np.asarray(x, float)
    if not erase:
        return np.zeros(x.shape, bool)
    return np.isin(np.round(x, ND), np.round(np.asarray(erase, float), ND))


def manual_baseline(x, anchors, interp=INTERPS[0]):
    """經過錨點的背景曲線；錨點範圍以外延用最外側兩點的斜率（直線）或最外側的值（平滑）。"""
    x = np.asarray(x, float)
    pts = sorted((float(a), float(b)) for a, b in (anchors or []))
    if not pts:
        raise ValueError("還沒有設定背景錨點：按「✎ 編修光譜」→「✚ 背景錨點」在光譜上點幾個背景的位置")
    ax = np.array([p[0] for p in pts])
    ay = np.array([p[1] for p in pts])
    ax, idx = np.unique(ax, return_index=True)
    ay = ay[idx]
    if ax.size == 1:
        return np.full_like(x, ay[0])
    if ax.size == 2 or interp == "直線":
        y = np.interp(x, ax, ay)
        lo, hi = x < ax[0], x > ax[-1]                    # 外插：延續最外側那一段的斜率
        y[lo] = ay[0] + (x[lo] - ax[0]) * (ay[1] - ay[0]) / (ax[1] - ax[0])
        y[hi] = ay[-1] + (x[hi] - ax[-1]) * (ay[-1] - ay[-2]) / (ax[-1] - ax[-2])
        return y
    from scipy.interpolate import PchipInterpolator      # 單調、不會在錨點之間亂晃
    f = PchipInterpolator(ax, ay, extrapolate=True)
    return f(x)


def apply(ds, ed):
    """回傳套用編修後的 Dataset（新的物件；快取裡的原始資料不變）。"""
    if is_empty(ed):
        return ds
    from ..readers import Dataset
    from ..readers.raman_txt import SHIFT
    x = ds.df[SHIFT].to_numpy(float)
    notes = list(ds.notes)
    sig = ed.get("sig")
    if sig and sig != signature(x):
        notes.append("⚠ 檔案內容和編修時不同（點數或範圍變了），沒有套用橡皮擦與手動背景")
        return Dataset(ds.path, ds.kind, ds.df, dict(ds.header), notes)
    m = erased_mask(x, ed.get("erase"))
    df = ds.df[~m].reset_index(drop=True) if m.any() else ds.df
    header = dict(ds.header)
    if ed.get("anchors"):
        header["anchors"] = [list(a) for a in ed["anchors"]]
        header["anchor_interp"] = ed.get("interp", INTERPS[0])
    if m.any():
        notes.append(f"已用橡皮擦隱藏 {int(m.sum())} 個點（只影響顯示與分析，原始檔沒有修改）")
    if ed.get("anchors"):
        notes.append(f"手動背景：{len(ed['anchors'])} 個錨點")
    out = Dataset(ds.path, ds.kind, df, header, notes)
    out.edits = copy.deepcopy(ed)
    return out


def apply_all(items, snapshot):
    """Item 清單 → 套用編修（snapshot 來自 EditStore.snapshot）。"""
    for it in items:
        ed = snapshot.get(_norm(it.path))
        if ed:
            it.data = apply(it.data, ed)
    return items
