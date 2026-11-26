"""超導轉變溫度 Tc（PPMS 的 R–T、SQUID 的 M–T 共用）。

做法（取代原本 notebook「相鄰兩點斜率最大」的定義，那種寫法遇到溫度幾乎相同的兩點會得到假的極大斜率）：
  1. 只用單一方向的一段資料（先用 segments.split_sweeps 切段），依溫度排序、相同溫度取平均
  2. 正常態數值 y_n：最高溫那一端的中位數；超導態數值 y_s：最低溫那一端的中位數
     （也可以自己指定溫度區間）
  3. 正規化 f = (y − y_s) / (y_n − y_s)，從高溫往低溫找 f 第一次低於 90%、50%、10% 的溫度（線性內插）
  4. 另外在等間距格點上平滑後微分，找 |dy/dT| 最大的溫度

R–T：y_n = 正常態電阻、y_s ≈ 0；M–T（抗磁）：y_n ≈ 0、y_s = 最負的磁矩，同一套公式都適用。
"""
from __future__ import annotations

import numpy as np

from .units import sorted_unique, uniform_grid, smooth, in_range

METHODS = {
    "50%（中點）": "mid",
    "90%（onset）": "onset",
    "10%（零電阻 / 完全抗磁）": "zero",
    "最大斜率 |dy/dT|": "deriv",
}
METHOD_NAMES = list(METHODS)


def _crossing_from_top(T, f, level):
    """T 由小到大。從最高溫往下找 f 第一次 < level 的位置，回傳內插的溫度（找不到 = nan）。"""
    above = f >= level
    for i in range(T.size - 1, 0, -1):
        if above[i] and not above[i - 1]:
            t1, t0 = T[i], T[i - 1]
            f1, f0 = f[i], f[i - 1]
            if f1 == f0:
                return float(t1)
            return float(t0 + (level - f0) * (t1 - t0) / (f1 - f0))
    return float("nan")


def transition(T, y, normal_range=(None, None), sc_range=(None, None), edge_fraction=0.12,
               smooth_window=0, levels=(0.9, 0.5, 0.1), min_contrast=5.0):
    """回傳 dict：
        ok, reason（失敗原因）, y_n, y_s, T90, T50, T10, width（T90 − T10）, T_deriv, dydT_max,
        T, y（排序後）, Tg, dydT（微分曲線，畫圖用）, f（正規化）
    min_contrast：|y_n − y_s| 至少要是雜訊的幾倍才算有轉變。"""
    T, y = sorted_unique(T, y)
    out = dict(ok=False, reason="", T=T, y=y, y_n=np.nan, y_s=np.nan,
               T90=np.nan, T50=np.nan, T10=np.nan, width=np.nan, T_deriv=np.nan, dydT_max=np.nan,
               Tg=np.array([]), dydT=np.array([]), f=np.array([]))
    if T.size < 6:
        out["reason"] = f"資料點太少（{T.size} 點）"
        return out
    span = T[-1] - T[0]
    n_edge = max(3, int(round(T.size * edge_fraction)))

    if normal_range and any(v is not None for v in normal_range):
        m = in_range(T, normal_range)
        if m.sum() < 2:
            out["reason"] = f"正常態區間 {normal_range} 內沒有資料"
            return out
        yn_pts = y[m]
    else:
        yn_pts = y[-n_edge:]
    if sc_range and any(v is not None for v in sc_range):
        m = in_range(T, sc_range)
        if m.sum() < 2:
            out["reason"] = f"超導態區間 {sc_range} 內沒有資料"
            return out
        ys_pts = y[m]
    else:
        ys_pts = y[:n_edge]
    y_n, y_s = float(np.median(yn_pts)), float(np.median(ys_pts))
    out.update(y_n=y_n, y_s=y_s)

    # 雜訊估計：相鄰點差的中位數絕對偏差
    noise = float(np.median(np.abs(np.diff(y)))) if y.size > 2 else 0.0
    noise = max(noise, 1e-300)
    if abs(y_n - y_s) < min_contrast * noise:
        out["reason"] = "這個溫度範圍內看不到明顯的轉變（高低溫兩端數值差不多）"
        return out

    f = (y - y_s) / (y_n - y_s)
    out["f"] = f
    t90, t50, t10 = (_crossing_from_top(T, f, lv) for lv in levels)
    out.update(T90=t90, T50=t50, T10=t10, width=(t90 - t10) if np.isfinite(t90) and np.isfinite(t10) else np.nan)

    Tg, yg = uniform_grid(T, y)
    yg = smooth(yg, smooth_window, 2)
    d = np.gradient(yg, Tg)
    out.update(Tg=Tg, dydT=d)
    # 最大斜率只在轉變附近找（避免高溫端的雜訊）
    sign = 1.0 if y_n > y_s else -1.0
    search = np.ones_like(Tg, bool)
    if np.isfinite(t90) and np.isfinite(t10):
        pad = max(abs(t90 - t10), span * 0.02)
        search = (Tg >= min(t10, t90) - pad) & (Tg <= max(t10, t90) + pad)
        if search.sum() < 3:
            search = np.ones_like(Tg, bool)
    idx = np.flatnonzero(search)
    k = idx[int(np.nanargmax(sign * d[idx]))]
    tk = Tg[k]
    if 0 < k < Tg.size - 1:                      # 拋物線內插，讓結果不被格點間距限制
        y0, y1, y2 = sign * d[k - 1], sign * d[k], sign * d[k + 1]
        den = y0 - 2 * y1 + y2
        if den != 0:
            tk = Tg[k] + 0.5 * (y0 - y2) / den * (Tg[1] - Tg[0])
    out.update(T_deriv=float(tk), dydT_max=float(d[k]))
    out["ok"] = bool(np.isfinite(t50) or np.isfinite(tk))
    if not out["ok"]:
        out["reason"] = "找不到 50% 的位置"
    return out


def pick_tc(res, method_name):
    key = METHODS.get(method_name, "mid")
    return {"mid": res["T50"], "onset": res["T90"], "zero": res["T10"], "deriv": res["T_deriv"]}[key]
