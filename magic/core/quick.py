"""PPMS / SQUID 的「快速檢視」：任選 X / Y 欄位、自動分段、多檔疊圖。"""
from __future__ import annotations

import numpy as np

from .qd import LINESTYLES, SEG_CHOICES, get_xy, scaled, segments
from .registry import P, Result
from .units import decimate, in_range


def params(x_default, y_default):
    return [
        P("x", "X 軸", x_default, kind="column"),
        P("y", "Y 軸", y_default, kind="column"),
        P("segments", "掃描段落", SEG_CHOICES[0], choices=SEG_CHOICES,
          tip="依 X 軸的掃描方向分段（降溫 / 升溫、上掃 / 下掃），分開畫，不會在兩段之間來回跳"),
        P("x_range", "X 範圍", "", kind="range", tip="例如「2, 10」；空白 = 全部"),
        P("x_unit", "X 單位", "自動", choices=["自動", "原始單位"]),
        P("y_unit", "Y 單位", "自動", choices=["自動", "原始單位"]),
        P("points", "顯示資料點", True),
        P("log_y", "Y 軸對數", False),
    ]


def draw(fig, items, p, data=None):
    ax = fig.add_subplot()
    warns, lines = [], []
    seg_kind = "T" if "temp" in str(p["x"]).lower() else "H"
    # 所有檔案用同一個單位
    blocks = []
    for it in items:
        xc, yc, x, y = get_xy(it.data, p["x"], p["y"], warn=warns.append)
        blocks.append((it, xc, yc, x, y))
    if not blocks:
        return Result(text="沒有資料")
    allx = np.concatenate([b[3] for b in blocks])
    ally = np.concatenate([b[4] for b in blocks])
    _, xlabel, fx = scaled(allx, blocks[0][1], p["x_unit"])
    _, ylabel, fy = scaled(ally, blocks[0][2], p["y_unit"])
    multi = len(blocks) > 1
    n_total = 0
    for it, xc, yc, x, y in blocks:
        segs = segments(it.data, x, p["segments"], seg_kind)
        for i, (seg, name) in enumerate(segs):
            xs, ys = x[seg.slice], y[seg.slice]
            m = in_range(xs, p["x_range"]) & np.isfinite(ys)
            if not m.any():
                continue
            xs, ys = decimate(xs[m] / fx, ys[m] / fy)
            color = it.color if multi else f"C{i % 10}"
            ls = LINESTYLES.get(seg.direction, "-") if multi else "-"
            fmt = (".", ls) if p["points"] else ("", ls)
            ax.plot(xs, ys, marker=fmt[0], ms=2.5, ls=fmt[1], lw=1.1, color=color,
                    label=(f"{it.label}｜{name}" if multi else name))
            n_total += int(m.sum())
            lines.append(f"{it.label}｜{name}：{int(m.sum())} 點")
        if len(segs) == 0:
            warns.append(f"{it.label}：沒有有效的數據")
    if p["log_y"]:
        if np.nanmin(ally) > 0:
            ax.set_yscale("log")
        else:
            warns.append("Y 有 0 或負值，不能用對數座標")
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    if len(ax.lines) <= 12:
        ax.legend(fontsize=8)
    if multi:
        lines.insert(0, "實線 = 降溫 / 下掃，虛線 = 升溫 / 上掃，顏色 = 檔案\n")
    return Result(text="\n".join(lines), warnings=list(dict.fromkeys(warns)),
                  summary={"points": n_total})
