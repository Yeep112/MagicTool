"""Etching 圖共用：欄位選項、數字解析、分組顏色。"""
import re

import numpy as np

Y_CHOICES = ["R_hBN(nm/sec)", "R_SiO2(nm/sec)", "兩個都畫", "選擇比 R_hBN / R_SiO2"]
GROUPS = ["不分組", "Method", "Gas", "Power", "Pressure", "Bias", "Name", "Type"]
X_CHOICES = ["紀錄編號 #", "日期", "Power", "T (sec)", "Pressure", "Bias"]
PALETTE = ["#2563eb", "#e4572e", "#17a398", "#f2a541", "#7c3aed", "#ef476f", "#118ab2", "#8d6a9f",
           "#06d6a0", "#5c6b73"]


def number(s):
    """「60W」→ 60、「1Pa」→ 1、「」→ nan"""
    m = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", str(s))
    return float(m.group(0)) if m else np.nan


def y_series(df, choice):
    if choice == Y_CHOICES[3]:
        a = df["R_hBN(nm/sec)"].to_numpy(float)
        b = df["R_SiO2(nm/sec)"].to_numpy(float)
        with np.errstate(divide="ignore", invalid="ignore"):
            return [("選擇比 R_hBN / R_SiO2", np.where(b > 0, a / b, np.nan))]
    if choice == Y_CHOICES[2]:
        return [("R_hBN(nm/sec)", df["R_hBN(nm/sec)"].to_numpy(float)),
                ("R_SiO2(nm/sec)", df["R_SiO2(nm/sec)"].to_numpy(float))]
    return [(choice, df[choice].to_numpy(float))]


def groups(df, col):
    if col in (None, "", GROUPS[0]) or col not in df.columns:
        return [("全部", np.ones(len(df), bool))]
    vals = [v if str(v).strip() else "（空白）" for v in df[col].astype(str)]
    order = list(dict.fromkeys(vals))
    arr = np.asarray(vals)
    return [(g, arr == g) for g in order]
