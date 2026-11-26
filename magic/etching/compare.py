"""Etching 批次比較：依條件分組，比較平均蝕刻速率（± 標準差）與選擇比。"""
import numpy as np
import pandas as pd

from ..core.registry import P, Result, analysis
from ._common import GROUPS, PALETTE, R_MAT, R_SIO2, fmt_group, material_name

GROUP2 = ["（無）"] + GROUPS[1:]


@analysis("Etching", "條件比較（平均 ± 標準差）", group="批次比較", icon="▥", order=10,
          params=[
              P("by", "分組欄位", "Power", choices=GROUPS[1:]),
              P("by2", "第二個分組欄位", "Gas", choices=GROUP2),
              P("skip_through", "排除蝕穿的紀錄", True, tip="蝕穿的紀錄只是下限，平均時通常要排除"),
          ],
          help="依 Power、Gas、Material、線寬… 分組，畫出每組的平均材料蝕刻率與 SiO2 蝕刻率"
               "（誤差棒 = 組內標準差，上方數字 = 筆數），表格另外列出選擇比。")
def etch_compare(fig, items, p, data=None):
    if not items or items[0].data.df.empty:
        return Result(text="沒有紀錄")
    df = items[0].data.df.copy()
    notes = []
    if p["skip_through"] and "Etched through" in df and df["Etched through"].any():
        notes.append(f"已排除 {int(df['Etched through'].sum())} 筆蝕穿的紀錄")
        df = df[~df["Etched through"]]
    if df.empty:
        return Result(text="排除蝕穿的紀錄後沒有資料")
    mat = material_name(df)
    keys = [p["by"]] + ([p["by2"]] if p["by2"] not in ("（無）", p["by"]) else [])
    for k in keys:
        df[k] = df[k].map(fmt_group)
    with np.errstate(divide="ignore", invalid="ignore"):
        df["選擇比"] = np.where(df[R_SIO2] > 0, df[R_MAT] / df[R_SIO2], np.nan)
    g = df.groupby(keys, sort=False)
    table = g.agg(筆數=(R_MAT, "count"),
                  R_材料_平均=(R_MAT, "mean"), R_材料_標準差=(R_MAT, "std"),
                  R_SiO2_平均=(R_SIO2, "mean"), R_SiO2_標準差=(R_SIO2, "std"),
                  選擇比_平均=("選擇比", "mean")).reset_index()
    labels = [" / ".join(str(row[k]) for k in keys) for _, row in table.iterrows()]
    x = np.arange(len(table))
    w = 0.38
    ax = fig.add_subplot()
    for j, (col, sd, name) in enumerate((("R_材料_平均", "R_材料_標準差", f"R_{mat}"),
                                        ("R_SiO2_平均", "R_SiO2_標準差", "R_SiO2"))):
        ax.bar(x + (j - 0.5) * w, table[col], w, yerr=table[sd].fillna(0), capsize=3,
               color=PALETTE[j], alpha=0.85, label=name)
    for i, n in enumerate(table["筆數"]):
        top = np.nanmax([table["R_材料_平均"].iloc[i] + (table["R_材料_標準差"].fillna(0).iloc[i]), 0])
        ax.text(i - 0.5 * w, top, f"n={n}", ha="center", va="bottom", fontsize=8, color="#6b7280")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=25, ha="right")
    ax.set_ylabel("蝕刻速率 (nm/s)")
    ax.set_xlabel(" / ".join(keys))
    ax.legend(fontsize=9)
    lines = notes + [f"{lab}：R_{mat} {r.R_材料_平均:.4g} ± {0 if pd.isna(r.R_材料_標準差) else r.R_材料_標準差:.2g}，"
                     f"R_SiO2 {r.R_SiO2_平均:.4g}，選擇比 {r.選擇比_平均:.3g}（{r.筆數} 筆）"
                     for lab, r in zip(labels, table.itertuples())]
    return Result(text="\n".join(lines), tables={"etch_compare": table}, summary={"groups": len(table)})
