"""PPMS 批次比較：多個樣品的 R–T 正規化疊圖與 Tc 總表。"""
from ..core import qd
from ..core.registry import P, Result, analysis


def _compute(items, p, progress):
    return qd.tc_compute(items, p, progress)


@analysis("PPMS", "多樣品 R–T 比較", group="批次比較", icon="≋", order=10,
          params=qd.common_tc_params("Bridge 1 Resistance (Ohms)")[:5] + [
              P("normalize", "正規化", qd.NORMALIZE[0], choices=qd.NORMALIZE),
          ],
          compute=_compute,
          help="選好幾個檔案：R–T 正規化疊圖（R / 正常態電阻），右邊是每個樣品、每一段的 Tc。")
def ppms_compare(fig, items, p, data=None):
    rows = data or []
    warns = qd.draw_compare(fig, rows, p, "R")
    return Result(text=qd.tc_text(rows, p["method"]), tables={"Tc_compare": qd.tc_table(rows, p["method"], "R")},
                  summary={f"{r['item'].label}｜{r['name']}": r["tc"] for r in rows}, warnings=warns)
