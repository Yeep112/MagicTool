"""新分析的範本：複製這個檔案（檔名不要以 _ 開頭），改掉下面的內容，重新開啟軟體就會出現在左欄。

‧ 放在 magic/ppms/（或 squid、raman、etching）→ 會跟著軟體上傳到 GitHub、同事也會收到
‧ 放在 %LOCALAPPDATA%\\MagicTool\\plugins\\ → 只有這台電腦看得到（私人分析、私人機台）
"""
import numpy as np

from ..core.qd import get_xy
from ..core.registry import P, Result, analysis


@analysis("PPMS", "我的分析（範本）", group="參數萃取", icon="★", order=999,
          params=[P("x", "X 軸", "Temperature (K)", kind="column"),
                  P("y", "Y 軸", "Bridge 1 Resistance (Ohms)", kind="column"),
                  P("threshold", "門檻", 1.0)])
def my_analysis(fig, items, p, data=None):
    ax = fig.add_subplot()
    rows = []
    for it in items:
        xc, yc, x, y = get_xy(it.data, p["x"], p["y"])
        ax.plot(x, y, color=it.color, label=it.label)
        rows.append(f"{it.label}：{int(np.sum(y > p['threshold']))} 點高於門檻")
    ax.set_xlabel(p["x"])
    ax.set_ylabel(p["y"])
    ax.legend()
    return Result(text="\n".join(rows))
