"""光譜峰值與背景（Raman 用）。

和原本 notebook / yeep_lab.raman 的差別：
  ‧ 峰只在指定範圍內找（例如 G：1560–1610 cm⁻¹），不是「全光譜裡最靠近 1580 的峰」
  ‧ 用 Lorentzian 擬合求峰位、高度、FWHM、面積；擬合失敗才退回取最大值
  ‧ 背景擬合不會被峰拉高：多項式只用沒有峰的點（ModPoly 迭代）、或用 ALS
  ‧ 舊方法「平均強度交點寬度」保留為 width_at_mean，方便和以前的紀錄比較
"""
from __future__ import annotations

import numpy as np

from .units import in_range


# ---------------------------------------------------------------------------
# 峰
# ---------------------------------------------------------------------------
def lorentzian(x, A, x0, fwhm, c):
    g = 0.5 * fwhm
    return A * g * g / ((x - x0) ** 2 + g * g) + c


def fit_peak(x, y, window, min_points=7, fit=True):
    """在 window=(lo, hi) 內找一個峰。回傳 dict：
        ok, method（'Lorentzian' / '最大值'）, pos, height（扣掉擬合常數後的高度）, peak（原始最高點）,
        fwhm, area, offset, r2, x_fit, y_fit, reason"""
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    m = in_range(x, window) & np.isfinite(y)
    out = dict(ok=False, method="", pos=np.nan, height=np.nan, peak=np.nan, fwhm=np.nan, area=np.nan,
               offset=np.nan, r2=np.nan, x_fit=np.array([]), y_fit=np.array([]), reason="")
    if m.sum() < min_points:
        out["reason"] = f"{window[0]:g}–{window[1]:g} cm⁻¹ 內資料點太少（{int(m.sum())} 點）"
        return out
    xs, ys = x[m], y[m]
    order = np.argsort(xs)
    xs, ys = xs[order], ys[order]
    i = int(np.argmax(ys))
    edge = np.concatenate([ys[:max(2, ys.size // 10)], ys[-max(2, ys.size // 10):]])
    c0 = float(np.median(edge))
    A0 = float(ys[i] - c0)
    out.update(pos=float(xs[i]), peak=float(ys[i]), height=A0, offset=c0, method="最大值", ok=A0 > 0)
    if A0 <= 0:
        out["reason"] = "範圍內沒有高於背景的峰"
        out["ok"] = False
        return out
    half = ys >= c0 + A0 / 2
    step = float(np.median(np.diff(xs))) if xs.size > 1 else 1.0
    w0 = max(float(half.sum()) * step, 2 * step)
    out["fwhm"] = w0
    if i in (0, ys.size - 1):
        out["reason"] = "最高點在範圍邊緣，峰可能不在這個範圍內"
    if not fit:
        return out
    try:
        from scipy.optimize import curve_fit
        lo, hi = float(xs[0]), float(xs[-1])
        p0 = [A0, float(xs[i]), min(w0, hi - lo), c0]
        bounds = ([0, lo, step * 0.5, -np.inf], [A0 * 5 + abs(c0), hi, (hi - lo) * 2, np.inf])
        popt, _ = curve_fit(lorentzian, xs, ys, p0=p0, bounds=bounds, maxfev=20000)
        A, x0, fw, c = (float(v) for v in popt)
        yf = lorentzian(xs, *popt)
        ss_res = float(np.sum((ys - yf) ** 2))
        ss_tot = float(np.sum((ys - ys.mean()) ** 2)) or 1.0
        r2 = 1 - ss_res / ss_tot
        xf = np.linspace(lo, hi, 400)
        out.update(ok=True, method="Lorentzian", pos=x0, height=A, fwhm=abs(fw), offset=c,
                   area=float(np.pi * A * abs(fw) / 2), r2=r2, x_fit=xf, y_fit=lorentzian(xf, *popt))
        noise = float(np.std(np.diff(ys - yf)) / np.sqrt(2)) if ys.size > 3 else 0.0
        if A < 5 * noise or abs(fw) < 1.5 * step or r2 < 0.5:
            out.update(ok=False, reason=f"範圍內沒有明顯的峰（高度 {A:.3g}、雜訊約 {noise:.2g}、R² = {r2:.2f}）")
        elif r2 < 0.8:
            out["reason"] = f"擬合品質偏低（R² = {r2:.2f}），請確認範圍或背景"
    except Exception as e:          # 擬合失敗 → 保留最大值的結果
        out["reason"] = f"Lorentzian 擬合失敗，改用最大值：{e}"
    return out


def width_at_mean(x, y, window=(2660.0, 2720.0)):
    """舊方法（原 notebook）：在 window 內取平均強度，找曲線穿過該強度的兩個位置，回傳寬度 Δ。

    這個 Δ 會隨 window 改變，不是 FWHM；只用來和以前的紀錄比較。"""
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    m = in_range(x, window)
    xs, ys = x[m], y[m]
    order = np.argsort(xs)
    xs, ys = xs[order], ys[order]
    if ys.size < 2:
        return {"mean": np.nan, "crossings": [], "delta": np.nan}
    target = float(np.mean(ys))
    cross = []
    for i in range(ys.size - 1):
        y1, y2 = ys[i], ys[i + 1]
        if (y1 - target) * (y2 - target) < 0:
            cross.append(float(xs[i] + (target - y1) * (xs[i + 1] - xs[i]) / (y2 - y1)))
    delta = (max(cross) - min(cross)) if len(cross) >= 2 else np.nan
    return {"mean": target, "crossings": cross, "delta": delta}


# ---------------------------------------------------------------------------
# 背景
# ---------------------------------------------------------------------------
BASELINES = ["無", "多項式（只用無峰區）", "ALS（自動）", "指數（只用無峰區）"]


def _mask_out(x, exclude):
    keep = np.isfinite(x)
    for lo, hi in exclude or []:
        keep &= ~((x >= lo) & (x <= hi))
    return keep


def baseline_poly(x, y, degree=3, exclude=(), iterations=30):
    """ModPoly：先排除已知的峰範圍，反覆「擬合 → 高於擬合線的點壓回擬合線」，背景不會被峰拉高。"""
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    keep = _mask_out(x, exclude)
    if keep.sum() < degree + 2:
        keep = np.isfinite(x)
    xs, ys = x[keep], y[keep].copy()
    xm, xsd = float(np.mean(xs)), float(np.std(xs)) or 1.0     # 正規化 x，高階多項式才不會數值不穩
    u = (xs - xm) / xsd
    coef = np.polyfit(u, ys, degree)
    for _ in range(iterations):
        fit = np.polyval(coef, u)
        new = np.minimum(ys, fit)
        if np.allclose(new, ys, rtol=0, atol=1e-9 * (np.abs(ys).max() or 1)):
            break
        ys = new
        coef = np.polyfit(u, ys, degree)
    return np.polyval(coef, (x - xm) / xsd)


def baseline_als(y, lam=1e5, p=0.01, niter=10):
    """Asymmetric Least Squares（Eilers & Boelens 2005）。lam 越大越平滑；p 越小越貼近底部。"""
    from scipy import sparse
    from scipy.sparse.linalg import spsolve
    y = np.asarray(y, float)
    n = y.size
    if n < 5:
        return np.full_like(y, np.nanmin(y) if n else 0.0)
    D = sparse.diags([1.0, -2.0, 1.0], [0, -1, -2], shape=(n, n - 2), dtype=float)
    DDT = lam * D.dot(D.transpose())
    w = np.ones(n)
    z = y
    for _ in range(niter):
        W = sparse.spdiags(w, 0, n, n)
        z = spsolve((W + DDT).tocsc(), w * y)
        w = p * (y > z) + (1 - p) * (y < z)
    return np.asarray(z)


def baseline_exp(x, y, exclude=()):
    """a·exp(b·(x − x0)) + c，只用沒有峰的點擬合（螢光背景常見的形狀）。"""
    from scipy.optimize import curve_fit
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    keep = _mask_out(x, exclude)
    xs, ys = x[keep], y[keep]
    x0 = float(xs.min()) if xs.size else 0.0

    def f(t, a, b, c):
        return a * np.exp(b * (t - x0)) + c
    span = float(xs.max() - xs.min()) or 1.0
    p0 = [float(ys[0] - ys[-1]) or 1.0, -3.0 / span, float(ys[-1])]
    try:
        popt, _ = curve_fit(f, xs, ys, p0=p0, maxfev=20000)
        return f(x, *popt)
    except Exception:
        return baseline_poly(x, y, 2, exclude)


def baseline(x, y, method, degree=3, exclude=(), lam=1e5, p=0.01):
    if method in (None, "", BASELINES[0]):
        return np.zeros_like(np.asarray(y, float))
    if method == BASELINES[1]:
        return baseline_poly(x, y, degree, exclude)
    if method == BASELINES[2]:
        order = np.argsort(x)
        z = np.empty_like(np.asarray(y, float))
        z[order] = baseline_als(np.asarray(y, float)[order], lam=lam, p=p)
        return z
    if method == BASELINES[3]:
        return baseline_exp(x, y, exclude)
    raise ValueError(f"不認得的背景方法：{method}")
