"""Etching 快速檢視：蝕刻速率趨勢（誤差棒 = 多點量測的標準差；▲ = 蝕穿，只是下限）。"""
import numpy as np

from ..core.registry import P, Result, analysis
from ._common import GROUPS, PALETTE, X_CHOICES, Y_CHOICES, groups, material_name, x_values, y_series


@analysis("Etching", "蝕刻速率趨勢", group="快速檢視", icon="↘", order=10,
          params=[
              P("y", "Y 軸", Y_CHOICES[0], choices=Y_CHOICES),
              P("x", "X 軸", X_CHOICES[0], choices=X_CHOICES),
              P("group", "依哪一欄分顏色", "Gas", choices=GROUPS),
              P("errorbars", "誤差棒", True),
              P("connect", "連線", False),
              P("labels", "標上紀錄編號", True),
          ],
          help="中間的紀錄表選哪幾筆就畫哪幾筆（沒選 = 篩選後的全部）。誤差棒是多點量測的標準差；"
               "空心三角形 = 已蝕穿，只是下限。滑鼠移到點上可以看數值。")
def etch_trend(fig, items, p, data=None):
    if not items or items[0].data.df.empty:
        return Result(text="沒有紀錄。按中間的「＋ 新增紀錄」，或到 ⚙ 設定 指定紀錄 CSV。")
    df = items[0].data.df
    ax = fig.add_subplot()
    x, xlabel = x_values(df, p["x"])
    through = df["Etched through"].to_numpy(bool) if "Etched through" in df else np.zeros(len(df), bool)
    series = y_series(df, p["y"])
    markers = ["o", "s"]
    lines = []
    for si, (yname, y, sy) in enumerate(series):
        for gi, (gname, mask) in enumerate(groups(df, p["group"])):
            color = PALETTE[gi % len(PALETTE)]
            label = gname if len(series) == 1 else f"{gname}｜{yname}"
            for sub, mk, filled in ((mask & ~through, markers[si % 2], si == 0), (mask & through, "^", False)):
                if not sub.any():
                    continue
                xs = x[sub] if not hasattr(x, "iloc") else x[sub]
                ax.plot(xs, y[sub], marker=mk, ls="-" if p["connect"] else "none", ms=7, color=color,
                        mfc=color if filled else "white", mew=1.5,
                        label=label if mk != "^" else f"{label}（蝕穿，下限）")
                if p["errorbars"] and np.isfinite(sy[sub]).any():
                    ax.errorbar(np.asarray(xs), y[sub], yerr=np.nan_to_num(sy[sub]), fmt="none", ecolor=color,
                                elinewidth=1, capsize=3, alpha=0.7, gid="nohover")
            if p["labels"]:
                xs_all = np.asarray(x[mask] if not hasattr(x, "iloc") else x[mask])
                for xi, yi, n in zip(xs_all, y[mask], df["#"][mask]):
                    if np.isfinite(yi):
                        ax.annotate(str(n), (xi, yi), xytext=(4, 4), textcoords="offset points", fontsize=7,
                                    color="#6b7280")
    ax.set_xlabel(xlabel)
    ax.set_ylabel(series[0][0] if len(series) == 1 else "蝕刻速率 (nm/s)（實心 = 材料、空心 = SiO2）")
    ax.legend(fontsize=8, title=p["group"] if p["group"] != GROUPS[0] else None)
    if p["x"] == "日期":
        fig.autofmt_xdate()
    for yname, y, sy in series:
        f = y[np.isfinite(y)]
        if f.size:
            lines.append(f"{yname}：{f.size} 筆，平均 {f.mean():.4g}，標準差 {f.std(ddof=1) if f.size > 1 else 0:.3g}，"
                         f"範圍 {f.min():.4g}–{f.max():.4g}")
    if through.any():
        lines.append(f"其中 {int(through.sum())} 筆已蝕穿（只是下限），編號：{', '.join(map(str, df['#'][through]))}")
    mats = [m for m in dict.fromkeys(df["Material"]) if m]
    if len(mats) > 1:
        lines.append(f"⚠ 選到的紀錄有不同材料（{'、'.join(mats)}），「材料蝕刻率」是各自材料的速率")
    return Result(text="\n".join(lines), tables={"records": df.drop(columns=["DateTime_parsed"], errors="ignore")},
                  summary={"records": int(len(df)), "material": material_name(df)})
