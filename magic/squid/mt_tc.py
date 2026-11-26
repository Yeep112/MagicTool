"""SQUID：M–T 與超導轉變溫度 Tc（ZFC / FC 分開）。"""
from ..core import qd
from ..core.registry import Result, analysis


def _compute(items, p, progress):
    return qd.tc_compute(items, p, progress)


@analysis("SQUID", "M–T 與 Tc", group="參數萃取", icon="Tc", order=10,
          params=qd.common_tc_params("Moment (emu)"),
          compute=_compute,
          help="ZFC（升溫）、FC（降溫）分開算 Tc：90%（onset）、50%、10% 與最大斜率 dM/dT。"
               "不會再因為 setpoint 附近溫度幾乎相同的兩點，誤判成斜率最大。")
def squid_mt_tc(fig, items, p, data=None):
    rows = data or []
    warns = qd.draw_tc(fig, rows, p, "Moment")
    return Result(text=qd.tc_text(rows, p["method"]), tables={"Tc": qd.tc_table(rows, p["method"], "M")},
                  summary={f"{r['item'].label}｜{r['name']}": r["tc"] for r in rows}, warnings=warns)
