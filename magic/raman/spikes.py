"""找宇宙射線尖峰：又窄（1～3 個點）又高、兩邊一下子掉回背景的尖峰。

真的 Raman 峰（G、2D、hBN）再窄也有好幾個點寬，而且峰頂旁邊的點還很高；
宇宙射線是一兩個點突然衝上去、旁邊的點就回到背景。判斷方式：
  1. 和「中位數濾波」（寬 2×最大寬度+1 個點）比，高出雜訊很多的點 → 候選
  2. 連續的候選點不能超過「最大寬度」個
  3. 候選區兩邊緊鄰的點要掉回背景附近（低於 背景 + 35% 尖峰高度）
雜訊用 MAD 估計（不會被尖峰本身拉高）。
"""
from __future__ import annotations

import numpy as np


def _rolling_median(y, w):
    h = w // 2
    pad = np.pad(y, h, mode="edge")
    win = np.lib.stride_tricks.sliding_window_view(pad, w)
    return np.median(win, axis=1)


def find_spikes(y, k=6.0, max_width=3, drop=0.35):
    """回傳 [(i0, i1), …]：每個尖峰涵蓋的索引（含兩端）。y 要依 x 排序。
    k = 靈敏度（高出雜訊幾倍才算；越小越敏感），max_width = 最多幾個點寬。"""
    y = np.asarray(y, float)
    n = y.size
    if n < 4 * max_width + 3:
        return []
    w = 2 * max_width + 1
    resid = y - _rolling_median(y, w)
    mad = np.median(np.abs(resid - np.median(resid)))
    sigma = 1.4826 * mad
    if not np.isfinite(sigma) or sigma <= 0:
        sigma = np.std(resid) or 1.0
    cand = resid > k * sigma
    out = []
    i = 0
    while i < n:
        if not cand[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and cand[j + 1]:
            j += 1
        a, b = i, j
        i = j + 1
        if b - a + 1 > max_width or a == 0 or b == n - 1:
            continue
        outside = np.r_[y[max(0, a - 2 - 2 * max_width):a - 1], y[b + 2:b + 3 + 2 * max_width]]
        if outside.size < 2:
            continue
        base = float(np.median(outside))
        h = float(y[a:b + 1].max()) - base
        if h < k * sigma:
            continue
        if y[a - 1] - base > drop * h or y[b + 1] - base > drop * h:
            continue                                # 旁邊的點還很高 → 是真的峰（或峰頂），不是尖峰
        out.append((a, b))
    return out


def spike_mask(y, **kw):
    m = np.zeros(np.asarray(y).size, bool)
    for a, b in find_spikes(y, **kw):
        m[a:b + 1] = True
    return m


# 預設靈敏度 6：純雜訊（高斯）的光譜，200 張大約誤判 1 個；改成 5 會比較敏感（約 10 個），7 幾乎不會誤判。
# 峰寬（FWHM）只有 3 個點以內的真峰和宇宙射線分不出來，所以找到的尖峰一定先標出來給人確認，再擦掉。
