"""Etching 批次比較：依條件分組，比較平均蝕刻速率（± 標準差）與選擇比。"""
import numpy as np
import pandas as pd

from ..core.registry import P, Result, analysis
from ._common import GROUPS, PALETTE

GROUP2 = ["（無）"] + GROUPS[1:]


@analysis("Etching", "條件比較（平均 ± 標準差）", group="批次比較", icon="▥", order=10,
          params=[
              P("by", "分組欄位", "Power", choices=GROUPS[1:]),
              P("by2", "第二個分組欄位", "Gas", choices=GROUP2),
          ],
          help="依 Power、Gas、Method… 分組，畫出每組的平均 R_hBN、R_SiO2（誤差棒 = 標準差，上方數字 = 筆數），"
               "表格另外列出選擇比 R_hBN / R_SiO2。")
def etch_compare(fig, items, p, data=None):
    if not items or items[0].data.df.empty:
        return Result(text="沒有紀錄")
    df = items[0].data.df.copy()
    keys = [p["by"]] + ([p["by2"]] if p["by2"] not in ("（無）", p["by"]) else [])
    for k in keys:
        df[k] = df[k].astype(str).replace("", "（空白）")
    with np.errstate(divide="ignore", invalid="ignore"):
        df["選擇比"] = np.where(df["R_SiO2(nm/sec)"] > 0, df["R_hBN(nm/sec)"] / df["R_SiO2(nm/sec)"], np.nan)
    g = df.groupby(keys, sort=False)
    table = g.agg(筆數=("R_hBN(nm/sec)", "count"),
                  R_hBN_平均=("R_hBN(nm/sec)", "mean"), R_hBN_標準差=("R_hBN(nm/sec)", "std"),
                  R_SiO2_平均=("R_SiO2(nm/sec)", "mean"), R_SiO2_標準差=("R_SiO2(nm/sec)", "std"),
                  選擇比_平均=("選擇比", "mean")).reset_index()
    labels = [" / ".join(str(row[k]) for k in keys) for _, row in table.iterrows()]
    x = np.arange(len(table))
    w = 0.38
    ax = fig.add_subplot()
    for j, (col, sd, name) in enumerate((("R_hBN_平均", "R_hBN_標準差", "R_hBN"),
                                        ("R_SiO2_平均", "R_SiO2_標準差", "R_SiO2"))):
        ax.bar(x + (j - 0.5) * w, table[col], w, yerr=table[sd].fillna(0), capsize=3,
               color=PALETTE[j], alpha=0.85, label=name)
    for i, n in enumerate(table["筆數"]):
        top = np.nanmax([table["R_hBN_平均"].iloc[i] + (table["R_hBN_標準差"].fillna(0).iloc[i]), 0])
        ax.text(i - 0.5 * w, top, f"n={n}", ha="center", va="bottom", fontsize=8, color="#6b7280")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=25, ha="right")
    ax.set_ylabel("蝕刻速率 (nm/sec)")
    ax.set_xlabel(" / ".join(keys))
    ax.legend(fontsize=9)
    lines = [f"{lab}：R_hBN {r.R_hBN_平均:.4g} ± {0 if pd.isna(r.R_hBN_標準差) else r.R_hBN_標準差:.2g}，"
             f"R_SiO2 {r.R_SiO2_平均:.4g}，選擇比 {r.選擇比_平均:.3g}（{r.筆數} 筆）"
             for lab, r in zip(labels, table.itertuples())]
    return Result(text="\n".join(lines), tables={"etch_compare": table}, summary={"groups": len(table)})
