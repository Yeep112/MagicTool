"""PPMS 快速檢視：任選兩欄畫圖（R–T、R–H、任何欄位）。"""
from ..core import quick
from ..core.registry import analysis


@analysis("PPMS", "曲線檢視", group="快速檢視", icon="∿", order=10,
          params=quick.params("Temperature (K)", "Bridge 1 Resistance (Ohms)"),
          help="任選 X / Y 欄位畫圖。依 X 軸的掃描方向自動分段（降溫、升溫分開畫）。多個檔案會疊在一起。")
def ppms_quick(fig, items, p, data=None):
    return quick.draw(fig, items, p, data)
