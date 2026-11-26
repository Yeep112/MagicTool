"""蝕刻速率計算（取自 yeep_lab.etching，修正三個問題）。

  1. Δ_SiO2 的正負號：以前存的是 after − before，計算時用的卻是 before − after，兩者相反。
     現在所有 Δ 都定義成「被蝕刻掉的厚度」（正值 = 變薄）：Δ_SiO2 = before − after。
  2. 選了 marker（或 SiO2）當參考、高度卻沒填時，以前會出現看不懂的 TypeError；現在會說明缺哪一格。
  3. 參考層的變化是負值時，以前默默改成 0；現在一樣視為 0（和舊紀錄一致），但會在 warnings 提醒。

計算方式（和原本 notebook 相同）：
    參考層被蝕刻掉的厚度 d_ref：marker = after − before；SiO2 = before − after
    R_SiO2 = d_ref / t
    R_hBN  = (Δ_hBN + d_ref) / t     （hBN 高度是相對 SiO2 表面量的，SiO2 也被蝕刻時要加回來）
"""
from __future__ import annotations

from datetime import datetime

HEADERS = [
    "DateTime", "Method", "Power", "Bias", "Pressure", "Type", "Name",
    "H_hBN_before (nm)", "H_hBN_after (nm)",
    "H_marker_before (nm)", "H_marker_after (nm)",
    "H_SiO2_before (nm)", "H_SiO2_after (nm)",
    "T (sec)", "Δ_marker (nm)", "Δ_hBN (nm)", "Δ_SiO2 (nm)",
    "R_SiO2(nm/sec)", "R_hBN(nm/sec)", "Gas",
]
# 判斷「重複紀錄」用的欄位（使用者輸入的部分）
INPUT_COLUMNS = ["Method", "Power", "Bias", "Pressure", "Type", "Name", "H_hBN_before (nm)", "H_hBN_after (nm)",
                 "H_marker_before (nm)", "H_marker_after (nm)", "H_SiO2_before (nm)", "H_SiO2_after (nm)",
                 "T (sec)", "Gas"]
REFERENCES = ["auto", "marker", "SiO2"]


class EtchInputError(ValueError):
    pass


def _num(v, label, required=False):
    if v is None or (isinstance(v, str) and v.strip() == ""):
        if required:
            raise EtchInputError(f"請填「{label}」")
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        raise EtchInputError(f"「{label}」需要數字，收到：{v!r}")


def compute_rates(hbn_before, hbn_after, t, marker_before=None, marker_after=None,
                  sio2_before=None, sio2_after=None, reference="auto", clamp_negative=True):
    """回傳 dict：reference（實際使用的參考）、delta_marker、delta_hBN、delta_SiO2、R_SiO2、R_hBN、warnings。"""
    hb = _num(hbn_before, "hBN 蝕刻前高度", True)
    ha = _num(hbn_after, "hBN 蝕刻後高度", True)
    t = _num(t, "蝕刻時間 T（秒）", True)
    if t <= 0:
        raise EtchInputError("蝕刻時間 T 需要大於 0")
    mb, ma = _num(marker_before, "marker 蝕刻前高度"), _num(marker_after, "marker 蝕刻後高度")
    sb, sa = _num(sio2_before, "SiO2 蝕刻前高度"), _num(sio2_after, "SiO2 蝕刻後高度")
    has_marker = mb is not None and ma is not None
    has_sio2 = sb is not None and sa is not None
    warnings = []

    ref = reference or "auto"
    if ref == "auto":
        if has_marker:
            ref = "marker"
        elif has_sio2:
            ref = "SiO2"
        else:
            raise EtchInputError("需要 marker 或 SiO2 的蝕刻前、後高度（兩格都要填）才能算速率")
    if ref == "marker":
        if not has_marker:
            miss = "、".join(n for n, v in (("蝕刻前", mb), ("蝕刻後", ma)) if v is None)
            raise EtchInputError(f"選了 marker 當參考，但 marker 的{miss}高度沒有填")
        d_ref = ma - mb
    elif ref == "SiO2":
        if not has_sio2:
            miss = "、".join(n for n, v in (("蝕刻前", sb), ("蝕刻後", sa)) if v is None)
            raise EtchInputError(f"選了 SiO2 當參考，但 SiO2 的{miss}高度沒有填")
        d_ref = sb - sa
    else:
        raise EtchInputError(f"參考只能是 {REFERENCES}，收到：{reference!r}")

    if d_ref < 0:
        if clamp_negative:
            warnings.append(f"{ref} 的變化是負的（{d_ref:.2f} nm），通常是 AFM 量測誤差，已視為 0")
            d_ref = 0.0
        else:
            warnings.append(f"{ref} 的變化是負的（{d_ref:.2f} nm）")
    d_hbn = hb - ha
    if d_hbn < 0:
        warnings.append(f"hBN 蝕刻後反而比較高（Δ_hBN = {d_hbn:.2f} nm），請確認前後有沒有填反")
    d_sio2 = (sb - sa) if has_sio2 else None
    return {
        "reference": ref, "delta_marker": d_ref, "delta_hBN": d_hbn, "delta_SiO2": d_sio2,
        "R_SiO2": d_ref / t, "R_hBN": (d_hbn + d_ref) / t, "warnings": warnings,
    }


def make_row(rates, *, hbn_before, hbn_after, t, marker_before=None, marker_after=None,
             sio2_before=None, sio2_after=None, method="", power="", bias="", pressure="",
             sample_type="", name="", gas="", when=None):
    """依 HEADERS 的順序組成一列紀錄（和原本的 CSV / Google Sheet 欄位相同）。"""
    when = when or datetime.now()

    def n(v):
        return None if v is None or (isinstance(v, str) and not v.strip()) else float(v)
    return [
        when.strftime("%Y-%m-%d %H:%M:%S"), method, power, bias, pressure, sample_type, name,
        n(hbn_before), n(hbn_after), n(marker_before), n(marker_after), n(sio2_before), n(sio2_after),
        n(t), rates["delta_marker"], rates["delta_hBN"], rates["delta_SiO2"],
        rates["R_SiO2"], rates["R_hBN"], gas,
    ]
