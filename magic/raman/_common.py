"""Raman 共用：讀光譜、扣背景、找 G / 2D / hBN / D 峰。"""
from __future__ import annotations

import re

import numpy as np

from ..core.peaks import BASELINES, baseline, fit_peak, width_at_mean
from ..core.registry import P
from ..core.units import in_range
from ..readers.raman_txt import xy

PEAKS = [("G", "G_win", True), ("2D", "D2_win", True), ("hBN", "hBN_win", "hbn"), ("D", "D_win", "D")]
LAYER_NOTE = "參考：單層石墨烯通常 2D 是單一 Lorentzian、FWHM ≈ 24–35 cm⁻¹，且 I(2D)/I(G) > 2；多層的 2D 較寬、比值較小。"


def parse_windows(text):
    """「1320-1400, 1540-1630」→ [(1320, 1400), (1540, 1630)]"""
    out = []
    for a, b in re.findall(r"(\d+(?:\.\d+)?)\s*[-–~～]\s*(\d+(?:\.\d+)?)", str(text or "")):
        lo, hi = sorted((float(a), float(b)))
        out.append((lo, hi))
    return out


def peak_params():
    return [
        P("baseline", "背景", BASELINES[1], choices=BASELINES,
          tip="多項式只用沒有峰的點擬合（不會被峰拉高）；ALS 自動貼近底部；手動 = 用「✎ 編修光譜」點的錨點"),
        P("degree", "多項式階數", 3),
        P("G_win", "G 峰範圍 (cm⁻¹)", "1550, 1620", kind="range"),
        P("D2_win", "2D 峰範圍 (cm⁻¹)", "2620, 2760", kind="range"),
        P("hbn", "也找 hBN 峰", False, tip="hBN / 石墨烯混合樣品"),
        P("hBN_win", "hBN 峰範圍 (cm⁻¹)", "1350, 1385", kind="range"),
        P("D", "也找 D 峰（缺陷）", False, tip="D 峰（~1350）和 hBN（~1366）很接近，有 hBN 時通常不要開"),
        P("D_win", "D 峰範圍 (cm⁻¹)", "1320, 1365", kind="range"),
        P("fit", "Lorentzian 擬合", True, tip="關掉 = 直接取範圍內最大值（和以前一樣）"),
        P("legacy", "也算舊方法 Δ（平均強度交點）", True, tip="和以前的紀錄比較用；這個寬度會隨範圍改變，不是 FWHM"),
        P("legacy_win", "舊方法範圍 (cm⁻¹)", "2660, 2720", kind="range"),
    ]


def anchor_kw(ds):
    """手動背景的錨點（沒有編修過就是空的）。"""
    return dict(anchors=ds.header.get("anchors"), interp=ds.header.get("anchor_interp", "平滑"))


def exclude_windows(p):
    wins = [p["G_win"], p["D2_win"], (1320.0, 1400.0)]
    if p.get("hbn"):
        wins.append(p["hBN_win"])
    if p.get("D"):
        wins.append(p["D_win"])
    return [w for w in wins if w[0] is not None and w[1] is not None]


def analyze(ds, p):
    x, y = xy(ds)
    bg = baseline(x, y, p["baseline"], degree=int(p.get("degree", 3)), exclude=exclude_windows(p), **anchor_kw(ds))
    corr = y - bg
    fits = {}
    for name, win_key, enabled in PEAKS:
        on = enabled is True or bool(p.get(enabled))
        if on:
            fits[name] = fit_peak(x, corr, p[win_key], fit=p.get("fit", True))
    G, D2 = fits.get("G"), fits.get("2D")
    ratio = D2["height"] / G["height"] if (G and D2 and G["ok"] and D2["ok"] and G["height"] > 0) else np.nan
    area_ratio = D2["area"] / G["area"] if (G and D2 and np.isfinite(G.get("area", np.nan))
                                             and G["area"] > 0) else np.nan
    legacy = width_at_mean(x, y, p["legacy_win"]) if p.get("legacy") else None
    return dict(x=x, y=y, bg=bg, corr=corr, fits=fits, ratio=ratio, area_ratio=area_ratio, legacy=legacy,
                notes=list(ds.notes))


def compute(items, p, progress):
    out = []
    for k, it in enumerate(items):
        out.append(dict(item=it, **analyze(it.data, p)))
        progress(k + 1, len(items), it.label)
    return out


def fmt(v, nd=1):
    return "—" if v is None or not np.isfinite(v) else f"{v:.{nd}f}"


def summary_rows(rows):
    import pandas as pd
    recs = []
    for r in rows:
        rec = {"檔案": r["item"].label}
        for name, f in r["fits"].items():
            rec[f"{name} 位置 (cm⁻¹)"] = f["pos"]
            rec[f"{name} 高度"] = f["height"]
            rec[f"{name} FWHM (cm⁻¹)"] = f["fwhm"]
            rec[f"{name} 面積"] = f["area"]
            rec[f"{name} 方法"] = f["method"]
        rec["I(2D)/I(G) 高度比"] = r["ratio"]
        rec["A(2D)/A(G) 面積比"] = r["area_ratio"]
        if r["legacy"] is not None:
            rec["舊方法 Δ (cm⁻¹)"] = r["legacy"]["delta"]
        recs.append(rec)
    return pd.DataFrame(recs)


def text_rows(rows):
    lines = []
    for r in rows:
        lines.append(f"{r['item'].label}")
        for name, f in r["fits"].items():
            if f["ok"]:
                lines.append(f"  {name:>3}：位置 {fmt(f['pos'])}　FWHM {fmt(f['fwhm'])}　高度 {f['height']:.4g}"
                             f"　（{f['method']}{'，R² = ' + format(f['r2'], '.3f') if np.isfinite(f['r2']) else ''}）")
            else:
                lines.append(f"  {name:>3}：找不到（{f['reason']}）")
            if f["ok"] and f["reason"]:
                lines.append(f"       ⚠ {f['reason']}")
        lines.append(f"  I(2D)/I(G) = {fmt(r['ratio'], 3)}　A(2D)/A(G) = {fmt(r['area_ratio'], 3)}")
        if r["legacy"] is not None:
            lines.append(f"  舊方法 Δ（平均強度交點）= {fmt(r['legacy']['delta'], 2)} cm⁻¹")
        for n in r["notes"]:
            lines.append(f"  ‧ {n}")
    lines.append("")
    lines.append(LAYER_NOTE)
    return "\n".join(lines)


def mask(x, rng):
    return in_range(x, rng)
