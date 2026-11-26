"""Etching 快速檢視：蝕刻速率趨勢（取代原本寫死 row_indices 的 cell）。"""
import numpy as np

from ..core.registry import P, Result, analysis
from ._common import GROUPS, PALETTE, X_CHOICES, Y_CHOICES, groups, number, y_series


@analysis("Etching", "蝕刻速率趨勢", group="快速檢視", icon="↘", order=10,
          params=[
              P("y", "Y 軸", Y_CHOICES[0], choices=Y_CHOICES),
              P("x", "X 軸", X_CHOICES[0], choices=X_CHOICES),
              P("group", "依哪一欄分顏色", "Gas", choices=GROUPS),
              P("connect", "連線", False),
              P("labels", "標上紀錄編號", True),
          ],
          help="中間的紀錄表選哪幾筆就畫哪幾筆（沒選 = 篩選後的全部）。滑鼠移到點上可以看數值。")
def etch_trend(fig, items, p, data=None):
    if not items or items[0].data.df.empty:
        return Result(text="沒有紀錄。按中間的「＋ 新增紀錄」，或到 ⚙ 設定 指定紀錄 CSV。")
    df = items[0].data.df
    ax = fig.add_subplot()
    if p["x"] == "日期":
        x = df["DateTime_parsed"]
        xlabel = "日期"
    elif p["x"] == "紀錄編號 #":
        x = df["#"].to_numpy(float)
        xlabel = "紀錄編號 #"
    elif p["x"] == "T (sec)":
        x = df["T (sec)"].to_numpy(float)
        xlabel = "蝕刻時間 T (sec)"
    else:
        x = np.array([number(v) for v in df[p["x"]]])
        xlabel = p["x"] + "（取數字）"
    markers = ["o", "s"]
    lines = []
    for si, (yname, y) in enumerate(y_series(df, p["y"])):
        for gi, (gname, mask) in enumerate(groups(df, p["group"])):
            color = PALETTE[gi % len(PALETTE)]
            xs = x[mask] if not hasattr(x, "iloc") else x[mask]
            ax.plot(xs, y[mask], marker=markers[si % 2], ls="-" if p["connect"] else "none", ms=7,
                    color=color, mfc=color if si == 0 else "white", mew=1.5,
                    label=(f"{gname}" if len(y_series(df, p["y"])) == 1 else f"{gname}｜{yname}"))
            if p["labels"]:
                for xi, yi, n in zip(np.asarray(xs), y[mask], df["#"][mask]):
                    if np.isfinite(yi):
                        ax.annotate(str(n), (xi, yi), xytext=(4, 4), textcoords="offset points", fontsize=7,
                                    color="#6b7280")
    ax.set_xlabel(xlabel)
    ax.set_ylabel(p["y"] if p["y"] != Y_CHOICES[2] else "蝕刻速率 (nm/sec)（實心 hBN、空心 SiO2）")
    ax.legend(fontsize=8, title=p["group"] if p["group"] != GROUPS[0] else None)
    if p["x"] == "日期":
        fig.autofmt_xdate()
    for yname, y in y_series(df, p["y"]):
        f = y[np.isfinite(y)]
        if f.size:
            lines.append(f"{yname}：{f.size} 筆，平均 {f.mean():.4g}，標準差 {f.std(ddof=1) if f.size > 1 else 0:.3g}，"
                         f"範圍 {f.min():.4g}–{f.max():.4g}")
    return Result(text="\n".join(lines), tables={"records": df.drop(columns=["DateTime_parsed"], errors="ignore")},
                  summary={"records": int(len(df))})
