"""Etching 圖共用：欄位選項、數字解析、分組、配方（其他參數固定）判斷。"""
import re

import numpy as np

R_MAT = "R_hBN(nm/sec)"            # v2 起是「所選材料」的蝕刻率（欄位名稱沿用，Google Sheet 才對得上）
R_SIO2 = "R_SiO2(nm/sec)"
SIG = {R_MAT: "σ R_material (nm/sec)", R_SIO2: "σ R_SiO2 (nm/sec)"}
Y_CHOICES = ["材料蝕刻率", "SiO2 蝕刻率", "兩個都畫", "選擇比（材料 / SiO2）"]
GROUPS = ["不分組", "Material", "Method", "Gas", "Power", "ICP power (W)", "RF power (W)", "Pressure",
          "Line width (nm)", "Resist", "Name", "Type"]
X_CHOICES = ["紀錄編號 #", "日期", "T (sec)", "Line width (nm)", "ICP power (W)", "RF power (W)", "Pressure (Pa)",
             "Power（文字取數字）"]
PALETTE = ["#2563eb", "#e4572e", "#17a398", "#f2a541", "#7c3aed", "#ef476f", "#118ab2", "#8d6a9f",
           "#06d6a0", "#5c6b73"]
# 「其他參數固定」：這些欄位都一樣才算同一個配方（線寬、時間另外看）
RECIPE_COLS = ["Material", "Method", "Gas", "Flow 1 (sccm)", "Flow 2 (sccm)", "Flow 3 (sccm)", "ICP power (W)",
               "RF power (W)", "Power", "DC bias (V)", "Bias", "Pressure (Pa)", "Pressure", "Resist"]


def number(s):
    """「60W」→ 60、「1Pa」→ 1、「」→ nan"""
    m = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", str(s))
    return float(m.group(0)) if m else np.nan


def material_name(df):
    mats = [m for m in dict.fromkeys(df.get("Material", [])) if str(m).strip()]
    return mats[0] if len(mats) == 1 else "材料"


def y_series(df, choice):
    """回傳 [(標籤, 值, 誤差)]。"""
    mat = material_name(df)
    a = df[R_MAT].to_numpy(float)
    b = df[R_SIO2].to_numpy(float)
    sa = df[SIG[R_MAT]].to_numpy(float) if SIG[R_MAT] in df else np.full(len(df), np.nan)
    sb = df[SIG[R_SIO2]].to_numpy(float) if SIG[R_SIO2] in df else np.full(len(df), np.nan)
    if choice == Y_CHOICES[3]:
        with np.errstate(divide="ignore", invalid="ignore"):
            return [(f"選擇比 {mat} / SiO2", np.where(b > 0, a / b, np.nan), np.full(len(df), np.nan))]
    if choice == Y_CHOICES[2]:
        return [(f"R_{mat} (nm/s)", a, sa), ("R_SiO2 (nm/s)", b, sb)]
    if choice == Y_CHOICES[1]:
        return [("R_SiO2 (nm/s)", b, sb)]
    return [(f"R_{mat} (nm/s)", a, sa)]


def x_values(df, choice):
    if choice == "日期":
        return df["DateTime_parsed"], "日期"
    if choice == "紀錄編號 #":
        return df["#"].to_numpy(float), "紀錄編號 #"
    if choice == "Power（文字取數字）":
        return np.array([number(v) for v in df["Power"]]), "Power（取數字）"
    labels = {"T (sec)": "蝕刻時間 t (s)", "Line width (nm)": "線寬 (nm)"}
    return df[choice].to_numpy(float), labels.get(choice, choice)


def fmt_group(v):
    if isinstance(v, float):
        return "（空白）" if v != v else f"{v:g}"
    return str(v) if str(v).strip() else "（空白）"


def groups(df, col):
    if col in (None, "", GROUPS[0]) or col not in df.columns:
        return [("全部", np.ones(len(df), bool))]
    vals = [fmt_group(v) for v in df[col]]
    order = list(dict.fromkeys(vals))
    arr = np.asarray(vals, dtype=object)
    return [(g, arr == g) for g in order]


def recipe_key(row, exclude=()):
    parts = []
    for c in RECIPE_COLS:
        if c in exclude or c not in row:
            continue
        parts.append(fmt_group(row[c]) if str(row[c]).strip() else "")
    return tuple(parts)


def recipe_label(row):
    """配方的簡短名稱：「hBN｜ICP-RIE｜SF6 40｜RF 30W｜10 mTorr」"""
    bits = [str(row.get("Material", "")).strip(), str(row.get("Method", "")).strip()]
    gases = []
    for i in (1, 2, 3):
        g = str(row.get(f"Gas {i}", "")).strip()
        f = row.get(f"Flow {i} (sccm)")
        if g:
            gases.append(g + (f" {f:g}" if isinstance(f, float) and f == f else ""))
    bits.append("+".join(gases) if gases else str(row.get("Gas", "")).strip())
    icp, rf = row.get("ICP power (W)"), row.get("RF power (W)")
    pw = " ".join(x for x in (f"ICP {icp:g}W" if isinstance(icp, float) and icp == icp else "",
                              f"RF {rf:g}W" if isinstance(rf, float) and rf == rf else "") if x)
    bits.append(pw or str(row.get("Power", "")).strip())
    bits.append(str(row.get("Pressure", "")).strip())
    return "｜".join(b for b in bits if b)


def recipe_groups(df, exclude=()):
    """[(配方名稱, mask)]，依「其他參數都一樣」分組。"""
    keys = [recipe_key(r, exclude) for _, r in df.iterrows()]
    out = []
    for k in dict.fromkeys(keys):
        mask = np.array([kk == k for kk in keys])
        first = df[mask].iloc[0]
        out.append((recipe_label(first), mask))
    return out


def different_columns(df, cols=RECIPE_COLS):
    """選到的紀錄裡，哪些「應該固定」的參數其實不一樣。"""
    out = []
    for c in cols:
        if c in df.columns:
            vals = {fmt_group(v) for v in df[c]}
            if len(vals) > 1:
                out.append(f"{c}（{'、'.join(sorted(vals))}）" if len(vals) <= 3 else c)
    return out


def recipe_tag(i, n):
    """圖例用的短代號：只有一個配方時不用代號，多個配方用 A、B、C…（完整條件寫在圖的標題）。"""
    if n <= 1:
        return ""
    return chr(ord("A") + i) if i < 26 else f"R{i + 1}"


def recipe_title(ax, labels, fontsize=8):
    """把每個配方的完整條件寫在圖的上方（圖例只放短代號，圖才不會被擠窄）。"""
    if not labels:
        return
    if len(labels) == 1:
        ax.set_title(labels[0], fontsize=fontsize, loc="left")
    else:
        ax.set_title("\n".join(f"{recipe_tag(i, len(labels))} = {lb}" for i, lb in enumerate(labels)),
                     fontsize=fontsize, loc="left")
