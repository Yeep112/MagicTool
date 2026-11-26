"""蝕刻速率 v2：依「怎麼量」選公式、多點平均 ± 誤差、蝕穿偵測、分段時間、線寬與製程參數。

幾何（見手稿）：SiO2 基板上有要蝕刻的材料（hBN 或其他）和 marker（Cr/Au），上面是光阻圖案。
蝕刻 t 秒、去光阻後用 AFM（或膜厚儀）量：

  名稱         意思                                         手稿
  T            材料蝕刻前厚度（塗光阻前量）                  淺綠 h
  T'           材料蝕刻後、沒被光阻蓋住處的厚度              深綠 h'
  S_mat        材料上「光阻保護區 − 蝕刻區」的台階 = T − T'
  H_out        從蝕刻後的 SiO2 表面量到材料頂端 = T' + d_SiO2   紅 h_hBN
  T_m          marker 蝕刻前厚度                              淺橘 h
  T'_m         marker 蝕刻後自身厚度（金屬通常不會被蝕刻 = T_m） 深橘 h'
  H_m,out      從蝕刻後的 SiO2 表面量到 marker 頂端 = T'_m + d_SiO2   紅 h_marker
  d_SiO2       SiO2 被蝕刻掉的深度                            黑 h − h'

SiO2 蝕刻深度 d_SiO2（四種）：
  AFM 台階     光阻保護的 SiO2 與蝕刻區之間的台階            d = S_SiO2
  膜厚儀       橢偏儀 / 反射式膜厚儀量蝕刻前、後絕對厚度       d = h − h'
  從 marker    d = H_m,out − T'_m（T'_m 沒填 = T_m，假設 marker 不會被蝕刻）
  沒有量       不算 SiO2；材料只能用「圖案內台階」

材料蝕刻深度 d_mat（兩種）：
  圖案內台階   d = S_mat（= T − T'）                           直接量
  從基板量     d = T + d_SiO2 − H_out                          間接算，需要 d_SiO2

速率 r = d / t（t = 所有分段的電漿時間加總）。誤差：多點量測取平均 ± 標準差，
加減法的誤差平方相加，σ_r = σ_d / t。
蝕穿：剩下的材料 T' ≤ 容許值（0.5 nm 或 2σ）時，只能得到下限 r ≥ T / t。

交叉檢查（cross_check = True）：同一個樣品如果也用其他量法量了（例如 marker 和 AFM 台階都有），
每一種都算一次 d_SiO2（或 d_材料），和主要量法比較；差超過 max(1 nm, 2σ) 會提醒。
光阻蝕刻率：有填光阻蝕刻前、後厚度 → r_光阻 = (h_光阻 − h'_光阻) / t、選擇比 r_材料 / r_光阻，
並估計光阻最多撐多久（h_光阻 / r_光阻）。
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

MATERIALS = ["hBN", "graphite / graphene", "MoS2", "WSe2", "WS2", "NbSe2", "SiO2", "Si", "Si3N4"]
RESISTS = ["PMMA", "S1813", "ZEP", "AZ", "HSQ", "ma-N"]
INSTRUMENTS = ["ICP-RIE", "RIE"]
GASES = ["SF6", "CHF3", "O2", "Ar", "CF4", "C4F8", "N2", "He", "Cl2", "BCl3"]

SIO2_METHODS = {
    "afm_step": "AFM 台階（光阻保護區 vs 蝕刻區）",
    "ellipsometer": "膜厚儀 / 橢偏儀（蝕刻前、後厚度）",
    "marker": "從 marker 量（H_m,out − T'_m）",
    "none": "沒有量 SiO2",
}
MAT_METHODS = {
    "inside": "圖案內台階（直接量 T − T'）",
    "outside": "從基板量（T + d_SiO2 − H_out）",
}
THROUGH_TOL_NM = 0.5
CROSS_TOL_NM = 1.0           # 交叉檢查：兩種量法相差超過 max(1 nm, 2σ) 才提醒
RESIST_LOW = 0.2             # 光阻剩不到 20% 就提醒
PA_PER = {"Pa": 1.0, "mTorr": 0.133322, "Torr": 133.322, "mbar": 100.0}


class EtchInputError(ValueError):
    pass


# ---------------------------------------------------------------------------
# 量測值：可以輸入好幾個點，取平均 ± 標準差
# ---------------------------------------------------------------------------
@dataclass
class Measure:
    values: list

    @property
    def n(self):
        return len(self.values)

    @property
    def mean(self):
        return sum(self.values) / self.n if self.n else float("nan")

    @property
    def std(self):
        if self.n < 2:
            return 0.0
        m = self.mean
        return math.sqrt(sum((v - m) ** 2 for v in self.values) / (self.n - 1))

    def text(self, nd=2):
        if not self.n:
            return "—"
        if self.n == 1:
            return f"{self.mean:.{nd}f}（單點）"
        return f"{self.mean:.{nd}f} ± {self.std:.{nd}f}（{self.n} 點）"


_NUM = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def parse_values(text, label="", required=False):
    """「92.7, 93.1 92.5」→ Measure([92.7, 93.1, 92.5])。空白 → None（required 時丟出錯誤）。"""
    if text is None:
        text = ""
    if isinstance(text, (int, float)):
        return Measure([float(text)])
    if isinstance(text, (list, tuple)):
        return Measure([float(v) for v in text]) if text else (None if not required else _missing(label))
    s = str(text).strip()
    if not s:
        if required:
            _missing(label)
        return None
    parts = [p for p in re.split(r"[,\s;，、]+", s) if p]
    vals = []
    for p in parts:
        if not _NUM.fullmatch(p):
            raise EtchInputError(f"「{label}」看不懂：{p!r}（多個值請用逗號或空白分開）")
        vals.append(float(p))
    return Measure(vals)


def _missing(label):
    raise EtchInputError(f"請填「{label}」")


def parse_steps(text):
    """蝕刻時間：「30」、「20+20+20」、「3x20」、「20, 25」→ [秒, ...]。也接受 min（例如 1.5min）。"""
    s = str(text or "").strip().lower().replace("×", "x").replace("＊", "*").replace("，", ",")
    if not s:
        raise EtchInputError("請填「蝕刻時間」（分段請寫 20+20+20 或 3x20）")
    out = []
    for part in re.split(r"[+,;\s]+", s):
        if not part:
            continue
        m = re.fullmatch(r"(\d+)\s*[x*]\s*([\d.]+)\s*(s|sec|min|m)?", part)
        if m:
            n, v, unit = int(m.group(1)), float(m.group(2)), m.group(3)
            out += [v * (60 if unit in ("min", "m") else 1)] * n
            continue
        m = re.fullmatch(r"([\d.]+)\s*(s|sec|min|m)?", part)
        if not m:
            raise EtchInputError(f"蝕刻時間看不懂：{part!r}（例如 30、20+20+20、3x20、1.5min）")
        out.append(float(m.group(1)) * (60 if m.group(2) in ("min", "m") else 1))
    if not out or any(v <= 0 for v in out):
        raise EtchInputError("每一段蝕刻時間都要大於 0")
    return out


def parse_length_nm(text):
    """線寬：「500」→ 500 nm；「0.5 um」「0.5µm」→ 500 nm；空白 → None。"""
    s = str(text or "").strip().lower().replace("μ", "u").replace("µ", "u")
    if not s:
        return None
    m = re.fullmatch(r"([\d.]+)\s*(nm|um|mm)?", s)
    if not m:
        raise EtchInputError(f"線寬看不懂：{text!r}（例如 500、500 nm、0.5 um）")
    v = float(m.group(1))
    return v * {"nm": 1, None: 1, "um": 1e3, "mm": 1e6}[m.group(2)]


def parse_pressure_pa(text, unit="Pa"):
    """壓力：「1」+ 單位、或「10 mTorr」「1Pa」→ Pa；空白 → None。"""
    s = str(text or "").strip()
    if not s:
        return None
    m = re.fullmatch(r"([\d.]+)\s*([a-zA-Z]*)", s)
    if not m:
        raise EtchInputError(f"壓力看不懂：{text!r}")
    u = m.group(2) or unit
    key = next((k for k in PA_PER if k.lower() == u.lower()), None)
    if key is None:
        raise EtchInputError(f"壓力單位看不懂：{u!r}（Pa、mTorr、Torr、mbar）")
    return float(m.group(1)) * PA_PER[key]


def _opt_float(text, label):
    s = str(text if text is not None else "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        raise EtchInputError(f"「{label}」需要數字，收到：{text!r}")


# ---------------------------------------------------------------------------
# 輸入與結果
# ---------------------------------------------------------------------------
@dataclass
class EtchInput:
    # 樣品
    material: str = "hBN"
    resist: str = "PMMA"
    resist_thickness: str = ""
    line_width: str = ""
    sample_type: str = ""
    name: str = ""
    # 製程
    instrument: str = "ICP-RIE"
    gases: list = field(default_factory=lambda: [("SF6", "")])     # [(氣體, sccm 文字)]
    icp_power: str = ""
    rf_power: str = ""
    dc_bias: str = ""
    pressure: str = ""
    pressure_unit: str = "Pa"
    steps: str = "30"
    # SiO2
    sio2_method: str = "marker"
    sio2_step: str = ""
    sio2_before: str = ""
    sio2_after: str = ""
    marker_before: str = ""
    marker_out: str = ""
    marker_after_own: str = ""
    # 材料
    mat_method: str = "outside"
    mat_before: str = ""
    mat_step: str = ""
    mat_out: str = ""
    # 交叉檢查、光阻
    cross_check: bool = False
    resist_after: str = ""
    notes: str = ""

    def gas_text(self):
        names = [g for g, _ in self.gases if str(g).strip()]
        return "+".join(names)

    def flow_text(self):
        flows = [str(f).strip() for g, f in self.gases if str(g).strip()]
        return "/".join(f or "?" for f in flows) if any(flows) else ""


@dataclass
class EtchResult:
    t_steps: list
    t_total: float
    line_width_nm: float | None
    pressure_pa: float | None
    d_sio2: float | None = None
    s_sio2: float | None = None
    r_sio2: float | None = None
    sr_sio2: float | None = None
    d_mat: float | None = None
    s_mat: float | None = None
    r_mat: float | None = None
    sr_mat: float | None = None
    remaining: float | None = None          # 蝕刻後剩下的材料厚度 T'
    through: bool = False                   # 蝕穿
    lower_bound: bool = False               # r_mat 只是下限
    selectivity: float | None = None
    s_selectivity: float | None = None
    marker_etched: float | None = None      # marker 自己被蝕刻的厚度（有填 T'_m 才有）
    sio2_label: str = ""
    mat_label: str = ""
    warnings: list = field(default_factory=list)
    checks: list = field(default_factory=list)      # (True/False, 文字)
    explain: list = field(default_factory=list)     # 代入數字的算式
    measures: dict = field(default_factory=dict)    # 欄位 → Measure（寫進紀錄的原始值）
    sio2_cross: list = field(default_factory=list)  # [(量法, d, σ, 差, 容許, ok)]
    mat_cross: list = field(default_factory=list)
    d_resist: float | None = None
    s_resist: float | None = None
    r_resist: float | None = None
    sr_resist: float | None = None
    sel_resist: float | None = None
    resist_through: bool = False
    resist_life: float | None = None                # 光阻最多撐幾秒（h_光阻 / r_光阻）


def _q(*sigmas):
    return math.sqrt(sum((s or 0.0) ** 2 for s in sigmas))


SIO2_FIELDS = {"afm_step": ("sio2_step",), "ellipsometer": ("sio2_before", "sio2_after"),
               "marker": ("marker_before", "marker_out")}
SIO2_SHORT = {"afm_step": "AFM 台階", "ellipsometer": "膜厚儀", "marker": "marker", "none": "—"}
MAT_SHORT = {"inside": "圖案內台階", "outside": "從基板量"}


def _filled(inp, keys):
    return all(str(getattr(inp, k, "") or "").strip() for k in keys)


def _sio2(m, inp, res, primary=True):
    """用量法 m 算 d_SiO2 → (d, σ, 算式文字)。primary = 主要量法（才會記錄 measures、檢查 marker）。"""
    if m == "afm_step":
        st = parse_values(inp.sio2_step, "SiO2 台階（AFM）", True)
        if primary:
            res.measures["sio2_step"] = st
        return st.mean, st.std, f"d_SiO2 = AFM 台階 = {st.text()} nm"
    if m == "ellipsometer":
        b = parse_values(inp.sio2_before, "SiO2 蝕刻前厚度", True)
        a = parse_values(inp.sio2_after, "SiO2 蝕刻後厚度", True)
        if primary:
            res.measures.update(sio2_before=b, sio2_after=a)
        d = b.mean - a.mean
        return d, _q(b.std, a.std), f"d_SiO2 = h − h' = {b.mean:.2f} − {a.mean:.2f} = {d:.2f} nm"
    tm = parse_values(inp.marker_before, "marker 蝕刻前厚度 T_m", True)
    hm = parse_values(inp.marker_out, "從 SiO2 量到 marker 頂端 H_m,out", True)
    own = parse_values(inp.marker_after_own, "marker 蝕刻後自身厚度 T'_m")
    if primary:
        res.measures.update(marker_before=tm, marker_out=hm)
    if own is not None:
        tpm, s_tpm = own.mean, own.std
        if primary:
            res.measures["marker_after_own"] = own
            res.marker_etched = tm.mean - own.mean
            ok = res.marker_etched >= -max(THROUGH_TOL_NM, 2 * _q(tm.std, own.std))
            res.checks.append((ok, f"marker 自己被蝕刻 {res.marker_etched:.2f} nm（T_m − T'_m，應該 ≥ 0）"))
            if not ok:
                res.warnings.append("marker 蝕刻後反而比較厚：請確認 T_m、T'_m 有沒有填反，或有殘膠")
        src = "T'_m（有量）"
    else:
        tpm, s_tpm = tm.mean, tm.std
        src = "T_m（假設 marker 沒被蝕刻）"
        if primary:
            res.checks.append((True, "假設 marker（Cr/Au）在這個製程不會被蝕刻"))
    d = hm.mean - tpm
    return d, _q(hm.std, s_tpm), (f"d_SiO2 = H_m,out − T'_m = {hm.mean:.2f} − {tpm:.2f} = {d:.2f} nm"
                                  f"　（T'_m 用 {src}）")


def _cross(res, out, what, name1, name2, key2, d1, s1, d2, s2):
    """兩種量法比對：差超過 max(1 nm, 2σ) 就提醒。"""
    diff = d2 - d1
    tol = max(CROSS_TOL_NM, 2 * _q(s1, s2))
    ok = abs(diff) <= tol
    out.append((key2, d2, s2, diff, tol, ok))
    res.checks.append((ok, f"交叉檢查 {what}：{name1} {d1:.2f} vs {name2} {d2:.2f} ± {s2 or 0:.2f} nm"
                           f"，差 {diff:+.2f} nm（容許 ±{tol:.2f}）"))
    res.explain.append(f"　交叉檢查：d_{what}（{name2}）= {d2:.2f} ± {s2 or 0:.2f} nm，和{name1}差 {diff:+.2f} nm"
                       f" {'✓' if ok else '⚠'}")
    if not ok:
        res.warnings.append(f"{what} 兩種量法差 {diff:+.2f} nm（超過容許 ±{tol:.2f} nm）：請確認量測位置、"
                            f"是否有殘膠或 marker 被蝕刻，或欄位有沒有填錯")


def cross_text(items, short):
    """寫進 CSV 的交叉檢查文字。"""
    return "；".join(f"{short.get(k, k)} {d:.3g}±{s or 0:.2g} (Δ{diff:+.3g}{'' if ok else ' ⚠'})"
                     for k, d, s, diff, tol, ok in items)


def compute(inp: EtchInput, clamp_negative_sio2=True) -> EtchResult:
    steps = parse_steps(inp.steps)
    t = sum(steps)
    res = EtchResult(steps, t, parse_length_nm(inp.line_width), parse_pressure_pa(inp.pressure, inp.pressure_unit))
    parse_values(inp.resist_thickness, "光阻厚度")
    for label, v in (("ICP 功率", inp.icp_power), ("RF 功率", inp.rf_power),
                     ("DC bias", inp.dc_bias)):
        _opt_float(v, label)
    for g, f in inp.gases:
        if str(g).strip():
            _opt_float(f, f"{g} 流量")
    step_txt = f"{len(steps)} 段 {' + '.join(f'{s:g}' for s in steps)} = {t:g} s" if len(steps) > 1 else f"{t:g} s"

    # ---------------- SiO2 ----------------
    m = inp.sio2_method
    if m not in SIO2_METHODS:
        raise EtchInputError(f"SiO2 量法只能是 {list(SIO2_METHODS)}")
    res.sio2_label = SIO2_METHODS[m]
    if m != "none":
        res.d_sio2, res.s_sio2, text = _sio2(m, inp, res, primary=True)
        res.explain.append(text)
        if inp.cross_check:
            for other in ("afm_step", "ellipsometer", "marker"):
                if other == m or not _filled(inp, SIO2_FIELDS[other]):
                    continue
                try:
                    d2, s2, _ = _sio2(other, inp, EtchResult([], 1.0, None, None), primary=False)
                except EtchInputError:
                    continue
                _cross(res, res.sio2_cross, "SiO2", SIO2_SHORT[m], SIO2_SHORT[other], other, res.d_sio2,
                       res.s_sio2, d2, s2)
    if res.d_sio2 is not None:
        tol = max(THROUGH_TOL_NM, 2 * (res.s_sio2 or 0))
        if res.d_sio2 < -tol:
            res.warnings.append(f"SiO2 蝕刻深度是負的（{res.d_sio2:.2f} nm）：通常是量測誤差、殘膠，或前後填反")
        if res.d_sio2 < 0 and clamp_negative_sio2:
            res.explain.append("　d_SiO2 < 0 視為 0（量測誤差範圍內）")
            res.d_sio2 = 0.0
        res.r_sio2, res.sr_sio2 = res.d_sio2 / t, (res.s_sio2 or 0) / t
        res.explain.append(f"r_SiO2 = d_SiO2 / t = {res.d_sio2:.2f} / {t:g} = {res.r_sio2:.4f} ± {res.sr_sio2:.4f} nm/s")

    # ---------------- 材料 ----------------
    mm = inp.mat_method
    if mm not in MAT_METHODS:
        raise EtchInputError(f"材料量法只能是 {list(MAT_METHODS)}")
    res.mat_label = MAT_METHODS[mm]
    mat = inp.material or "材料"
    T = parse_values(inp.mat_before, f"{mat} 蝕刻前厚度 T", required=(mm == "outside"))
    if T is not None:
        res.measures["mat_before"] = T
    if mm == "inside":
        S = parse_values(inp.mat_step, f"{mat} 圖案內台階 S（= T − T'）", True)
        res.measures["mat_step"] = S
        d, sd = S.mean, S.std
        res.explain.append(f"d_{mat} = 圖案內台階 = {S.text()} nm")
        if T is not None:
            res.remaining = T.mean - d
            s_rem = _q(T.std, sd)
        else:
            s_rem = None
            res.warnings.append(f"沒有填 {mat} 蝕刻前厚度 T，無法判斷有沒有蝕穿")
    else:
        if res.d_sio2 is None:
            raise EtchInputError("「從基板量」需要 SiO2 的蝕刻深度：請選一種 SiO2 量法（不能選「沒有量」）")
        H = parse_values(inp.mat_out, f"從 SiO2 量到 {mat} 頂端 H_out", True)
        res.measures["mat_out"] = H
        res.remaining = H.mean - res.d_sio2
        s_rem = _q(H.std, res.s_sio2)
        d = T.mean - res.remaining
        sd = _q(T.std, H.std, res.s_sio2)
        res.explain.append(f"d_{mat} = T + d_SiO2 − H_out = {T.mean:.2f} + {res.d_sio2:.2f} − {H.mean:.2f} = {d:.2f} nm")
    if inp.cross_check:
        if mm == "outside" and str(inp.mat_step).strip():
            try:
                S2 = parse_values(inp.mat_step, "圖案內台階 S")
                _cross(res, res.mat_cross, mat, MAT_SHORT[mm], MAT_SHORT["inside"], "inside", d, sd, S2.mean, S2.std)
            except EtchInputError:
                pass
        elif mm == "inside" and res.d_sio2 is not None and T is not None and str(inp.mat_out).strip():
            try:
                H2 = parse_values(inp.mat_out, "H_out")
                d2 = T.mean + res.d_sio2 - H2.mean
                _cross(res, res.mat_cross, mat, MAT_SHORT[mm], MAT_SHORT["outside"], "outside", d, sd, d2,
                       _q(T.std, H2.std, res.s_sio2))
            except EtchInputError:
                pass
    if d < 0:
        res.warnings.append(f"{mat} 的蝕刻深度是負的（{d:.2f} nm）：請確認前後有沒有填反、或是否有殘膠")
    if res.remaining is not None:
        tol = max(THROUGH_TOL_NM, 2 * (s_rem or 0))
        if res.remaining <= tol:
            res.through = True
            res.lower_bound = True
            res.warnings.append(f"{mat} 已經蝕穿（剩下 {res.remaining:.2f} nm ≤ {tol:.2f} nm）：只能得到下限 r ≥ T / t；"
                                f"縮短時間再做一次才能得到真正的速率")
            d, sd = T.mean, T.std
            res.remaining = 0.0
        res.checks.append((not res.through, f"{mat} 沒有蝕穿（剩下 {max(res.remaining, 0):.2f} nm）"
                           if not res.through else f"{mat} 已蝕穿"))
    res.d_mat, res.s_mat = d, sd
    res.r_mat, res.sr_mat = d / t, sd / t
    bound = "≥ " if res.lower_bound else ""
    res.explain.append(f"r_{mat} = d / t = {d:.2f} / {t:g} = {bound}{res.r_mat:.4f} ± {res.sr_mat:.4f} nm/s　（t = {step_txt}）")
    if res.r_sio2:
        res.selectivity = res.r_mat / res.r_sio2
        rel = _q((res.sr_mat / res.r_mat) if res.r_mat else 0, (res.sr_sio2 / res.r_sio2) if res.r_sio2 else 0)
        res.s_selectivity = abs(res.selectivity) * rel
        res.explain.append(f"選擇比 r_{mat} / r_SiO2 = {res.selectivity:.3g}")
    _resist(inp, res, t)
    for key, meas in res.measures.items():
        if meas.n == 1:
            res.checks.append((True, f"{FIELD_NAMES.get(key, key)}：單點量測，誤差以 0 計（建議量 3 條以上 line profile）"))
            break
    return res


def _resist(inp, res, t):
    """光阻蝕刻率（有填蝕刻前、後光阻厚度才算）。"""
    rb = parse_values(inp.resist_thickness, "光阻蝕刻前厚度")
    ra = parse_values(inp.resist_after, "光阻蝕刻後厚度")
    if ra is None:
        return
    if rb is None:
        res.warnings.append("有填光阻蝕刻後厚度，但沒有填蝕刻前厚度（① 樣品 → 光阻厚度），算不出光阻蝕刻率")
        return
    res.measures.update(resist_thickness=rb, resist_after=ra)
    d, sd = rb.mean - ra.mean, _q(rb.std, ra.std)
    tol = max(THROUGH_TOL_NM, 2 * _q(ra.std))
    res.resist_through = ra.mean <= tol
    res.d_resist, res.s_resist = d, sd
    res.r_resist, res.sr_resist = d / t, sd / t
    bound = "≥ " if res.resist_through else ""
    res.explain.append(f"r_光阻 = (h_光阻 − h'_光阻) / t = ({rb.mean:.1f} − {ra.mean:.1f}) / {t:g} = "
                       f"{bound}{res.r_resist:.4f} ± {res.sr_resist:.4f} nm/s")
    if res.r_resist > 0 and res.r_mat is not None:
        res.sel_resist = res.r_mat / res.r_resist
        res.resist_life = rb.mean / res.r_resist
        res.explain.append(f"選擇比 r_材料 / r_光阻 = {res.sel_resist:.3g}；這個光阻厚度最多撐約 {res.resist_life:.0f} s")
    frac = ra.mean / rb.mean if rb.mean else 0.0
    if res.resist_through:
        res.warnings.append("光阻已經被蝕刻完：被保護的區域也可能被蝕刻，r_光阻 只是下限；請用更厚的光阻或縮短時間")
        res.checks.append((False, "光阻已經被蝕刻完"))
    elif frac < RESIST_LOW:
        res.warnings.append(f"光阻只剩 {frac * 100:.0f}%（{ra.mean:.1f} nm）：再蝕刻久一點就會被蝕穿")
        res.checks.append((False, f"光阻只剩 {frac * 100:.0f}%"))
    else:
        res.checks.append((True, f"光阻還剩 {frac * 100:.0f}%（{ra.mean:.1f} nm）"))
    if res.resist_life is not None and res.lower_bound is False and res.r_mat and res.measures.get("mat_before"):
        need = res.measures["mat_before"].mean / res.r_mat
        if need > res.resist_life:
            res.warnings.append(f"要蝕刻穿整層材料約需 {need:.0f} s，但光阻只撐約 {res.resist_life:.0f} s：光阻不夠厚")


FIELD_NAMES = {
    "sio2_step": "SiO2 台階", "sio2_before": "SiO2 蝕刻前厚度", "sio2_after": "SiO2 蝕刻後厚度",
    "marker_before": "marker 蝕刻前 T_m", "marker_out": "H_m,out", "marker_after_own": "marker 蝕刻後 T'_m",
    "mat_before": "材料蝕刻前 T", "mat_step": "材料台階 S", "mat_out": "H_out",
    "resist_thickness": "光阻蝕刻前厚度", "resist_after": "光阻蝕刻後厚度",
}
