"""PPMS：R–T 與超導轉變溫度 Tc。"""
from ..core import qd
from ..core.registry import Result, analysis


def _compute(items, p, progress):
    return qd.tc_compute(items, p, progress)


@analysis("PPMS", "R–T 與 Tc", group="參數萃取", icon="Tc", order=10,
          params=qd.common_tc_params("Bridge 1 Resistance (Ohms)"),
          compute=_compute,
          help="降溫、升溫分開算 Tc：90%（onset）、50%（中點）、10%（零電阻）與最大斜率 dR/dT。"
               "左圖是完整曲線，右圖是 Tc 附近放大。")
def ppms_rt_tc(fig, items, p, data=None):
    rows = data or []
    warns = qd.draw_tc(fig, rows, p, "Resistance")
    table = qd.tc_table(rows, p["method"], "R")
    summary = {f"{r['item'].label}｜{r['name']}": r["tc"] for r in rows}
    return Result(text=qd.tc_text(rows, p["method"]), tables={"Tc": table}, summary=summary, warnings=warns)
