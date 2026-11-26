"""把一次量測切成「單向掃描」的段落：降溫 / 升溫（ZFC / FC）、磁場上掃 / 下掃。

原本的 notebook 把降溫與升溫的點混在一起依溫度排序，有遲滯時曲線會在兩段之間來回跳，
而且兩段接縫處（溫度幾乎一樣、數值差很多）會被誤判成斜率最大的地方。
這裡先切段，之後每一段各自分析。

演算法：沿著量測順序追蹤目前方向的極值；往反方向退回超過 tol 才算換方向。
溫度在 setpoint 附近小幅抖動（< tol）不會被切成新的段落。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Segment:
    start: int              # 原始資料的索引（含）
    stop: int               # 原始資料的索引（不含）
    direction: int          # +1 上升（升溫 / 上掃）、-1 下降、0 幾乎不變
    x_from: float
    x_to: float
    number: int = 0         # 第幾段（從 1 開始）

    @property
    def slice(self):
        return slice(self.start, self.stop)

    @property
    def n(self):
        return self.stop - self.start

    def label(self, kind="T", unit="K"):
        if kind == "T":
            word = {1: "升溫", -1: "降溫", 0: "持溫"}[self.direction]
        else:
            word = {1: "上掃", -1: "下掃", 0: "固定"}[self.direction]
        return f"第{self.number}段 {word} {self.x_from:.4g}→{self.x_to:.4g} {unit}"


def split_sweeps(x, tol=None, rel_tol=0.02, min_points=5):
    """回傳 [Segment, ...]（依量測順序）。

    tol：換方向的門檻（與 x 同單位）；None = 全部範圍 × rel_tol。
    min_points：點數比這個少的段落（例如換方向時的幾個點）會被丟掉。"""
    x = np.asarray(x, float)
    good = np.flatnonzero(np.isfinite(x))
    if good.size < 2:
        if good.size == 0:
            return []
        v = float(x[good[0]])
        return [Segment(int(good[0]), int(good[0]) + 1, 0, v, v, 1)]
    xr = x[good]
    span = float(np.max(xr) - np.min(xr))
    if tol is None:
        tol = span * rel_tol
    tol = max(float(tol), 1e-12)

    cuts = []                       # (起點, 終點(含), 方向)，索引是 xr 的
    seg_start, direction, ext = 0, 0, 0
    for k in range(1, xr.size):
        v = xr[k]
        if direction == 0:
            if v - xr[seg_start] > tol:
                direction, ext = 1, k
            elif xr[seg_start] - v > tol:
                direction, ext = -1, k
        elif direction == 1:
            if v >= xr[ext]:
                ext = k
            elif xr[ext] - v > tol:
                cuts.append((seg_start, ext, 1))
                seg_start, direction, ext = ext, -1, k
        else:
            if v <= xr[ext]:
                ext = k
            elif v - xr[ext] > tol:
                cuts.append((seg_start, ext, -1))
                seg_start, direction, ext = ext, 1, k
    cuts.append((seg_start, xr.size - 1, direction))

    out = []
    for a, b, d in cuts:
        if b - a + 1 < min_points:
            continue
        start, stop = int(good[a]), int(good[b]) + 1
        seg_x = xr[a:b + 1]
        if d == 0:
            x_from, x_to = float(seg_x[0]), float(seg_x[-1])
        else:
            x_from = float(seg_x[0])
            x_to = float(np.max(seg_x) if d > 0 else np.min(seg_x))
        out.append(Segment(start, stop, d, x_from, x_to))
    if not out:                     # 全部都太短：當成一段
        out = [Segment(int(good[0]), int(good[-1]) + 1, 0, float(xr[0]), float(xr[-1]))]
    for i, s in enumerate(out, 1):
        s.number = i
    return out


SEGMENT_CHOICES = ["每段分開", "全部（不分段）", "只用降溫段", "只用升溫段", "最長的一段"]


def pick(segments, choice):
    """依使用者選的方式挑段落。'第N段' 也可以。"""
    if not segments:
        return []
    if choice in (None, "", SEGMENT_CHOICES[0]):
        return list(segments)
    if choice == SEGMENT_CHOICES[1]:
        return [Segment(segments[0].start, segments[-1].stop, 0,
                        min(s.x_from for s in segments), max(s.x_to for s in segments), 0)]
    if choice == SEGMENT_CHOICES[2]:
        return [s for s in segments if s.direction < 0]
    if choice == SEGMENT_CHOICES[3]:
        return [s for s in segments if s.direction > 0]
    if choice == SEGMENT_CHOICES[4]:
        return [max(segments, key=lambda s: (abs(s.x_to - s.x_from), s.n))]
    if isinstance(choice, str) and choice.startswith("第") and choice.endswith("段"):
        try:
            n = int(choice[1:-1])
            return [s for s in segments if s.number == n]
        except ValueError:
            pass
    return list(segments)
