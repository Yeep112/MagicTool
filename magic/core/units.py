"""單位換算與共用的數據前處理（取自 yeep_lab.units，加上電阻、磁矩、磁場）。"""
from __future__ import annotations

import numpy as np

CURRENT = {"A": 1.0, "mA": 1e-3, "uA": 1e-6, "nA": 1e-9}
VOLTAGE = {"V": 1.0, "mV": 1e-3, "uV": 1e-6}
RESISTANCE = {"MΩ": 1e6, "kΩ": 1e3, "Ω": 1.0, "mΩ": 1e-3}
MOMENT = {"emu": 1.0, "memu": 1e-3, "μemu": 1e-6, "nemu": 1e-9}
FIELD_OE = {"Oe": 1.0, "kOe": 1e3, "T": 1e4, "mT": 10.0}     # 數值的原始單位是 Oe
PRETTY = {"uA": "μA", "uV": "μV"}


def auto_unit(values, table, wanted="auto"):
    """wanted="auto" 時依數值大小挑單位（數字落在 1–1000 之間），回傳 (單位名稱, 換算係數)。

    顯示值 = 原始值 / 換算係數。"""
    if wanted not in (None, "", "auto"):
        return wanted, table[wanted]
    v = np.asarray(values, float)
    v = v[np.isfinite(v)]
    m = float(np.nanmax(np.abs(v))) if v.size else 1.0
    if m == 0:
        m = 1.0
    for name, f in sorted(table.items(), key=lambda kv: kv[1]):
        if m / f < 1000:
            return name, f
    name = max(table, key=table.get)
    return name, table[name]


def pretty(unit):
    return PRETTY.get(unit, unit)


def sorted_unique(x, y):
    """去除非數值、依 x 排序、相同 x 取平均。"""
    x = np.asarray(x, float).ravel()
    y = np.asarray(y, float).ravel()
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    if x.size == 0:
        return x, y
    order = np.argsort(x, kind="stable")
    x, y = x[order], y[order]
    ux, inv = np.unique(x, return_inverse=True)
    uy = np.bincount(inv, weights=y) / np.bincount(inv)
    return ux, uy


def uniform_grid(x, y, max_points=4000):
    """把不等間距的資料內插到等間距格點（之後才能用 Savitzky–Golay 平滑與微分）。

    間距取相鄰點間距的中位數；點太多時放寬間距。回傳 (x_grid, y_grid)。"""
    x, y = sorted_unique(x, y)
    if x.size < 3:
        return x, y
    step = float(np.median(np.diff(x)))
    span = float(x[-1] - x[0])
    if step <= 0 or not np.isfinite(step):
        step = span / max(x.size - 1, 1)
    n = int(span / step) + 1
    if n > max_points:
        n = max_points
    xg = np.linspace(x[0], x[-1], max(n, 3))
    return xg, np.interp(xg, x, y)


def smooth(y, window=0, polyorder=2):
    """Savitzky–Golay 平滑；window <= polyorder 時不平滑。"""
    from scipy.signal import savgol_filter
    y = np.asarray(y, float)
    w = int(window or 0)
    if w <= polyorder or y.size <= polyorder + 2:
        return y
    w = min(w | 1, y.size - (1 - y.size % 2))
    if w <= polyorder:
        return y
    return savgol_filter(y, w, polyorder)


def derivative(x, y, smooth_window=0, polyorder=2):
    """dy/dx（先內插到等間距格點、可選擇平滑）。回傳 (x_grid, dy/dx)。"""
    xg, yg = uniform_grid(x, y)
    if xg.size < 3:
        return xg, np.full_like(xg, np.nan)
    yg = smooth(yg, smooth_window, polyorder)
    return xg, np.gradient(yg, xg)


def decimate(x, y, max_points=20000):
    """畫圖用：點太多時平均抽樣（分析數值仍用完整資料），讓繪圖與滑鼠讀值保持流暢。"""
    x = np.asarray(x)
    if x.size <= max_points:
        return x, y
    k = int(np.ceil(x.size / max_points))
    return x[::k], np.asarray(y)[::k]


def parse_range(text):
    """「2, 10」→ (2.0, 10.0)；空白或 None → (None, None)；只寫一個數字 → (數字, None)。"""
    if text is None:
        return (None, None)
    if isinstance(text, (list, tuple)):
        vals = list(text) + [None, None]
        return tuple(None if v in ("", None) else float(v) for v in vals[:2])
    s = str(text).replace("～", ",").replace("~", ",").replace("–", ",").replace("，", ",").strip()
    if not s:
        return (None, None)
    parts = [p.strip() for p in s.replace(" ", ",").split(",") if p.strip()]
    vals = []
    for p in parts[:2]:
        if p.lower() in ("none", "auto", "自動"):
            vals.append(None)
        else:
            vals.append(float(p))
    while len(vals) < 2:
        vals.append(None)
    lo, hi = vals
    if lo is not None and hi is not None and lo > hi:
        lo, hi = hi, lo
    return (lo, hi)


def in_range(x, rng):
    lo, hi = rng
    x = np.asarray(x, float)
    m = np.isfinite(x)
    if lo is not None:
        m &= x >= lo
    if hi is not None:
        m &= x <= hi
    return m
