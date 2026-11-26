"""SQUID 快速檢視：任選兩欄畫圖（M–T、M–H、任何欄位）。"""
from ..core import quick
from ..core.registry import analysis


@analysis("SQUID", "曲線檢視", group="快速檢視", icon="∿", order=10,
          params=quick.params("Temperature (K)", "Moment (emu)"),
          help="任選 X / Y 欄位畫圖。依 X 軸的掃描方向自動分段（ZFC 升溫、FC 降溫分開畫）。單位自動換算（emu → μemu…）。")
def squid_quick(fig, items, p, data=None):
    return quick.draw(fig, items, p, data)
