"""SQUID：M–H 迴線（依磁場掃描方向分段、可扣除線性背景、找 |M| 最大處與回到 10% 的磁場）。"""
import numpy as np
import pandas as pd

from ..core import qd
from ..core.registry import P, Result, analysis
from ..core.units import in_range


def _side(H, M, sign):
    """H 的某一側（sign = +1 / −1）：|M| 最大的位置，與比它更大的 |H| 中 |M| 第一次低於 10% 的位置。"""
    m = (np.sign(H) == sign) & np.isfinite(M)
    if m.sum() < 3:
        return np.nan, np.nan, np.nan
    h, mm = H[m], M[m]
    k = int(np.argmax(np.abs(mm)))
    h_pk, m_pk = float(h[k]), float(mm[k])
    beyond = np.abs(h) > abs(h_pk)
    small = beyond & (np.abs(mm) < 0.1 * abs(m_pk))
    h_c = float(np.min(np.abs(h[small]))) * sign if small.any() else np.nan
    return h_pk, m_pk, h_c


def _compute(items, p, progress):
    out = []
    for k, it in enumerate(items):
        warns = []
        xc, yc, H, M = qd.get_xy(it.data, p["x"], p["y"], warn=warns.append)
        ok = np.isfinite(H) & np.isfinite(M)
        slope = 0.0
        if p["bg_field"] is not None:
            fit = ok & (np.abs(H) >= abs(p["bg_field"]))
            if fit.sum() >= 4:
                slope, icpt = np.polyfit(H[fit], M[fit], 1)
            else:
                warns.append(f"|H| ≥ {p['bg_field']:g} 的點太少，沒有扣除背景")
        Mc = M - slope * H
        segs = []
        for seg, name in qd.segments(it.data, H, p["segments"], "H"):
            hs, ms = H[seg.slice], Mc[seg.slice]
            m = in_range(hs, p["x_range"])
            hs, ms = hs[m], ms[m]
            pos = _side(hs, ms, +1)
            neg = _side(hs, ms, -1)
            segs.append(dict(seg=seg, name=name, H=hs, M=ms, pos=pos, neg=neg))
        out.append(dict(item=it, segs=segs, slope=slope, xcol=xc, ycol=yc, warn=warns))
        progress(k + 1, len(items), it.label)
    return out


@analysis("SQUID", "M–H 迴線", group="參數萃取", icon="⟲", order=20,
          params=[
              P("x", "磁場欄位", "Magnetic Field (Oe)", kind="column"),
              P("y", "磁矩欄位", "Moment (emu)", kind="column"),
              P("segments", "掃描段落", qd.SEG_CHOICES[0], choices=qd.SEG_CHOICES,
                tip="依磁場掃描方向分段（上掃 / 下掃）"),
              P("x_range", "磁場範圍", "", kind="range"),
              P("bg_field", "扣除線性背景：|H| ≥", None, kind="optfloat",
                tip="用 |H| 大於這個值的點擬合直線（順磁 / 抗磁背景）後扣除；空白 = 不扣"),
              P("x_unit", "磁場單位", "自動", choices=["自動", "原始單位"]),
              P("y_unit", "磁矩單位", "自動", choices=["自動", "原始單位"]),
          ],
          compute=_compute,
          help="依掃描方向分段畫 M–H。每一段在 H > 0、H < 0 各找 |M| 最大的磁場（H_peak），"
               "以及更高磁場處 |M| 回到峰值 10% 以下的磁場（H_c,10%，第一類超導體約等於 Hc）。")
def squid_mh(fig, items, p, data=None):
    rows = data or []
    ax = fig.add_subplot()
    warns, recs, lines = [], [], []
    if not rows:
        return Result(text="沒有資料")
    allH = np.concatenate([s["H"] for r in rows for s in r["segs"]] or [np.array([1.0])])
    allM = np.concatenate([s["M"] for r in rows for s in r["segs"]] or [np.array([1.0])])
    _, xl, fx = qd.scaled(allH, rows[0]["xcol"], p["x_unit"])
    _, yl, fy = qd.scaled(allM, rows[0]["ycol"], p["y_unit"])
    multi = len(rows) > 1
    for r in rows:
        it = r["item"]
        warns += r["warn"]
        for i, s in enumerate(r["segs"]):
            color = it.color if multi else f"C{i % 10}"
            ls = qd.LINESTYLES.get(s["seg"].direction, "-") if multi else "-"
            label = f"{it.label}｜{s['name']}" if multi else s["name"]
            ax.plot(s["H"] / fx, s["M"] / fy, ".", ls=ls, ms=2.5, lw=1, color=color, label=label)
            for side, (hp, mp, hc) in (("H>0", s["pos"]), ("H<0", s["neg"])):
                if np.isfinite(hp):
                    ax.plot([hp / fx], [mp / fy], "o", mfc="none", mec=color, ms=8, mew=1.5, gid="nohover")
                if np.isfinite(hc):
                    ax.axvline(hc / fx, color=color, ls=":", lw=0.8)
                recs.append({"檔案": it.label, "段落": s["name"], "側": side, "H_peak (Oe)": hp,
                             "M_peak (emu)": mp, "H_c,10% (Oe)": hc})
            lines.append(f"{it.label}｜{s['name']}：H>0 峰 {qd.fmt(s['pos'][0])} Oe、回到 10% {qd.fmt(s['pos'][2])} Oe；"
                         f"H<0 峰 {qd.fmt(s['neg'][0])} Oe、回到 10% {qd.fmt(s['neg'][2])} Oe")
        if r["slope"]:
            lines.append(f"{it.label}：已扣除線性背景 {r['slope']:.4g} emu/Oe")
    ax.axhline(0, color="#9ca3af", lw=0.8)
    ax.axvline(0, color="#9ca3af", lw=0.8)
    ax.set_xlabel(xl)
    ax.set_ylabel(yl + ("（已扣背景）" if p["bg_field"] is not None else ""))
    if len(ax.lines) <= 40:
        ax.legend(fontsize=8)
    return Result(text="\n".join(lines), tables={"MH_fields": pd.DataFrame(recs)},
                  summary={"rows": recs}, warnings=list(dict.fromkeys(warns)),
                  hint="○ = |M| 最大處；虛線 = |M| 回到 10% 的磁場")
