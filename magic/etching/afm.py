"""AFM line profile：讀 Gwyddion / NanoScope 匯出的文字檔，自動找台階高度。

讀檔
  ‧ 每一行是數字（空白、Tab、逗號、分號分隔都可以）；標題、說明行自動略過
  ‧ 欄位：2 欄 = (x, z)；偶數欄 = 好幾條 profile 並排 (x1, z1, x2, z2…)（Gwyddion 匯出多條曲線）；
    奇數欄（≥ 3）= 第一欄是 x、後面每欄是一條 z
  ‧ 單位：先看標題（[m]、[µm]、(nm)…）；沒有寫就猜：x 範圍 < 1e-3 → 公尺，≤ 500 → µm，否則 nm；
    z 的絕對值 < 1e-5 → 公尺，否則 nm（猜的單位會寫在提醒裡）

找台階（step_height）
  兩個平台（低、高）＋ 整條的傾斜一起擬合：z = a + b·x + h·[在高的平台上]
  ‧ 平台交界附近（台階邊緣）的點不用，避免邊緣的斜坡、殘膠影響
  ‧ 一條 profile 可以有好幾個邊（例如掃過一條溝槽：高 → 低 → 高），都算同一個 h
  ‧ h 的誤差來自擬合的殘差；也可以手動指定低、高的範圍
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

_SPLIT = re.compile(r"[,\t;]+|\s+")
UNIT_NM = {"m": 1e9, "mm": 1e6, "um": 1e3, "µm": 1e3, "μm": 1e3, "nm": 1.0, "a": 0.1, "å": 0.1, "pm": 1e-3}


@dataclass
class Profile:
    source: str
    name: str
    x: np.ndarray            # nm
    z: np.ndarray            # nm
    notes: list = field(default_factory=list)


def _numbers(line):
    parts = [p for p in _SPLIT.split(line.strip()) if p]
    if not parts:
        return None
    out = []
    for p in parts:
        try:
            out.append(float(p))
        except ValueError:
            return None
    return out


def _header_units(header_lines, ncols):
    """從最後幾行標題找每一欄的單位（找不到回傳 None）。"""
    for line in reversed(header_lines[-5:]):
        found = re.findall(r"[\[(]\s*(m|mm|um|µm|μm|nm|Å|A|pm)\s*[\])]", line, flags=re.I)
        if len(found) >= 2:
            units = [UNIT_NM.get(u.lower().replace("μ", "µ"), UNIT_NM.get(u.lower())) for u in found]
            if len(units) >= ncols or ncols % len(units) == 0 or len(units) == 2:
                return units
    return None


def _guess_x(span):
    if span < 1e-3:
        return 1e9, "m"
    if span <= 500:
        return 1e3, "µm"
    return 1.0, "nm"


def _guess_z(zmax):
    if zmax < 1e-5:
        return 1e9, "m"
    return 1.0, "nm"


def read_profiles(path):
    """讀一個檔案 → [Profile]（x、z 都換成 nm）。"""
    from pathlib import Path
    path = Path(path)
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    header, rows = [], []
    for line in text.splitlines():
        if not line.strip():
            continue
        nums = _numbers(line)
        if nums is None or len(nums) < 2:
            if not rows:
                header.append(line)
            continue
        rows.append(nums)
    if len(rows) < 10:
        raise ValueError(f"{path.name} 裡找不到 profile 數字（至少要 10 行兩欄以上的數字）")
    ncols = max(set(len(r) for r in rows), key=lambda n: sum(len(r) == n for r in rows))
    data = np.array([r[:ncols] + [np.nan] * (ncols - len(r)) for r in rows if len(r) >= 2], float)
    pairs = []
    if ncols == 2 or ncols % 2 == 0:
        pairs = [(2 * i, 2 * i + 1) for i in range(ncols // 2)]
    else:
        pairs = [(0, j) for j in range(1, ncols)]
    units = _header_units(header, ncols)
    out = []
    for k, (ix, iz) in enumerate(pairs):
        x, z = data[:, ix], data[:, iz]
        ok = np.isfinite(x) & np.isfinite(z)
        x, z = x[ok], z[ok]
        if x.size < 10:
            continue
        notes = []
        if units and len(units) > max(ix, iz) and units[ix] and units[iz]:
            fx, fz = units[ix], units[iz]
        elif units and len(units) == 2 and units[0] and units[1]:
            fx, fz = units
        else:
            fx, ux = _guess_x(float(np.ptp(x)))
            fz, uz = _guess_z(float(np.max(np.abs(z))))
            notes.append(f"標題沒有寫單位，猜 x 是 {ux}、高度是 {uz}；如果不對，請在 Gwyddion 匯出時勾選「單位」")
        order = np.argsort(x, kind="stable")
        name = f"{path.stem}" + (f" #{k + 1}" if len(pairs) > 1 else "")
        out.append(Profile(str(path), name, x[order] * fx, z[order] * fz, notes))
    if not out:
        raise ValueError(f"{path.name} 裡沒有可以用的 profile")
    return out


def _fit_levels(x, z, high, use):
    """z = a + b·x + h·high（只用 use 的點）→ (a, b, h, σ_h, 殘差標準差)。"""
    xc = x - x.mean()
    A = np.column_stack([np.ones(use.sum()), xc[use], high[use].astype(float)])
    coef, *_ = np.linalg.lstsq(A, z[use], rcond=None)
    res = z[use] - A @ coef
    dof = max(use.sum() - 3, 1)
    s2 = float(np.sum(res ** 2) / dof)
    try:
        cov = np.linalg.inv(A.T @ A) * s2
        sh = float(np.sqrt(cov[2, 2]))
    except np.linalg.LinAlgError:
        sh = np.nan
    return coef[0], coef[1], coef[2], sh, float(np.sqrt(s2))


def _edges(high):
    return np.flatnonzero(np.diff(high.astype(int)) != 0)


def _transition_mask(x, high, margin):
    """邊緣附近 ±margin 的點不用。"""
    use = np.ones(x.size, bool)
    for i in _edges(high):
        xe = 0.5 * (x[i] + x[i + 1])
        use &= np.abs(x - xe) > margin
    return use


def step_height(x, z, low_range=None, high_range=None, margin_frac=0.04, min_points=5):
    """自動（或依手動範圍）找台階高度。回傳 dict：h、s_h（nm）、低 / 高平台的點、邊緣位置、傾斜、說明。"""
    x, z = np.asarray(x, float), np.asarray(z, float)
    ok = np.isfinite(x) & np.isfinite(z)
    x, z = x[ok], z[ok]
    out = dict(ok=False, h=np.nan, s_h=np.nan, low=None, high=None, edges=[], slope=np.nan, a=np.nan, noise=np.nan,
               reason="", manual=bool(low_range or high_range))
    if x.size < 2 * min_points:
        out["reason"] = "點太少"
        return out
    span = float(np.ptp(x)) or 1.0
    if low_range and high_range:
        lo_m = (x >= min(low_range)) & (x <= max(low_range))
        hi_m = (x >= min(high_range)) & (x <= max(high_range))
        use = lo_m | hi_m
        high = hi_m
    else:
        # 先去掉整體傾斜（用兩端各 10% 的點估計），再用高度分成兩群，反覆修正
        n = x.size
        k = max(n // 10, 3)
        ends = np.r_[0:k, n - k:n]
        b0 = np.polyfit(x[ends], z[ends], 1)[0] if np.ptp(z[ends]) > 0 else 0.0
        zd = z - b0 * (x - x.mean())
        lo_q, hi_q = np.percentile(zd, [10, 90])
        if hi_q - lo_q <= 0:
            out["reason"] = "看不到台階（高度幾乎一樣）"
            return out
        high = zd > 0.5 * (lo_q + hi_q)
        margin = max(margin_frac * span, 3 * span / max(n - 1, 1))
        for _ in range(12):
            use = _transition_mask(x, high, margin)
            if use[high].sum() < min_points or use[~high].sum() < min_points:
                break
            a, b, h, sh, noise = _fit_levels(x, z, high, use)
            zd = z - b * (x - x.mean()) - a
            new = (zd > 0.5 * h) if h > 0 else (zd < 0.5 * h)
            if np.array_equal(new, high):
                break
            high = new
        # 很短的「島」（少於 min_points 點）視為雜訊，併到旁邊
        high = _clean_runs(high, min_points)
        use = _transition_mask(x, high, margin)
    if use[high].sum() < min_points or use[~high].sum() < min_points:
        out["reason"] = "找不到兩個夠長的平台（每邊至少要 5 點）；可以改用手動選範圍"
        return out
    a, b, h, sh, noise = _fit_levels(x, z, high, use)
    if h < 0:                                   # 「高」的那群其實比較低 → 對調
        high = ~high
        a, b, h, sh, noise = _fit_levels(x, z, high, use)
    out.update(ok=True, h=float(h), s_h=float(sh), low=use & ~high, high=use & high, slope=float(b), a=float(a),
               noise=noise, edges=[float(0.5 * (x[i] + x[i + 1])) for i in _edges(high)], x=x, z=z, xm=float(x.mean()))
    if not out["manual"] and h < 3 * noise:
        out["reason"] = f"台階 {h:.2f} nm 和雜訊（{noise:.2f} nm）差不多，結果不可靠；可以改用手動選範圍"
    return out


def _clean_runs(mask, min_len):
    m = mask.copy()
    i = 0
    n = m.size
    while i < n:
        j = i
        while j < n and m[j] == m[i]:
            j += 1
        if j - i < min_len and (i > 0 or j < n):
            m[i:j] = not m[i]
        i = j
    return m
