"""RIE / ICP 時間建議：hBN 厚度 + 想要的 OE（多蝕刻）→ 建議時間。

蝕刻率從兩個地方來（越像這次的條件越好）
  1. 過去樣品的紀錄：同一種步驟（RIE / ICP）有 hBN 厚度、時間（和 OE）→ 蝕刻率 = (hBN + OE) / 時間
     hBN 厚度沒有寫在 RIE 那一格時，用同一個樣品前面最近一次 AFM 的厚度
  2. Etching 頁的蝕刻紀錄（本機 CSV）：Method 是 RIE / ICP、材料 hBN 的 R_hBN
建議時間 = (hBN + OE) / 蝕刻率中位數，四捨五入到整數秒；另外給一個範圍（蝕刻率的 25%–75%）。
"""
from __future__ import annotations

import re
import statistics


def _num(v):
    try:
        x = float(str(v).strip())
    except (TypeError, ValueError):
        return None
    return x if x == x and x not in (float("inf"), float("-inf")) else None


def _time(v):
    """「20」「10+10」→ 秒（加起來）。"""
    if v in (None, ""):
        return None
    parts = re.findall(r"[\d.]+", str(v))
    try:
        t = sum(float(p) for p in parts)
    except ValueError:
        return None
    return t if t > 0 else None


def history(records, kind="rie"):
    """[{label, date, hbn_nm, oe_nm, time_s, rate}] 過去樣品的蝕刻。"""
    out = []
    for rec in records:
        if not rec:
            continue
        last_afm = None
        for st in rec.get("steps", []):
            if st.get("kind") == "afm" and _num((st.get("params") or {}).get("hbn_nm")) is not None:
                last_afm = _num(st["params"]["hbn_nm"])
            subs = list(st.get("substeps") or [])
            if st.get("kind") == kind:
                subs.append({"kind": kind, "params": st.get("params") or {}})
            for sub in subs:
                if sub.get("kind") != kind:
                    continue
                p = sub.get("params") or {}
                t = _time(p.get("time_s"))
                h = _num(p.get("hbn_nm"))
                h = h if h is not None else last_afm
                if t is None or h is None or h <= 0:
                    continue
                oe = _num(p.get("oe_nm")) or 0.0
                out.append({"label": rec.get("label", ""), "date": st.get("date") or rec.get("start", ""),
                            "hbn_nm": h, "oe_nm": oe, "time_s": t, "rate": (h + oe) / t})
    return out


def from_log(df, kind="rie"):
    """Etching 紀錄（store.read_log 的 DataFrame）→ [{label, date, rate}]。"""
    out = []
    if df is None or len(df) == 0:
        return out
    want = kind.upper()
    for _, r in df.iterrows():
        method = str(r.get("Method", "")).upper()
        if want not in method:
            continue
        mat = str(r.get("Material", "") or "hBN").lower()
        if mat and "hbn" not in mat:
            continue
        rate = _num(r.get("R_material (nm/sec)")) or _num(r.get("R_hBN(nm/sec)"))
        if rate and rate > 0:
            out.append({"label": f"蝕刻紀錄 {r.get('Name', '')}".strip(), "date": str(r.get("DateTime", ""))[:10],
                        "rate": rate})
    return out


def suggest(hbn_nm, oe_nm, rates, source=""):
    """回傳 {time_s, rate, n, low, high, target, text} 或 None（沒有資料）。"""
    h = _num(hbn_nm)
    oe = _num(oe_nm) or 0.0
    rs = sorted(x["rate"] for x in rates if x.get("rate"))
    if h is None or h <= 0 or not rs:
        return None
    med = statistics.median(rs)
    if len(rs) >= 4:
        q = statistics.quantiles(rs, n=4)
        lo_r, hi_r = q[0], q[2]
    else:
        lo_r, hi_r = rs[0], rs[-1]
    target = h + oe
    t = max(1, round(target / med))
    return {"time_s": t, "rate": med, "n": len(rs), "target": target,
            "low": max(1, round(target / hi_r)), "high": max(1, round(target / lo_r)), "source": source,
            "text": (f"建議 {t} s（hBN {h:g} + OE {oe:g} = {target:g} nm ÷ {med:.2f} nm/s）\n"
                     f"蝕刻率：{source}{len(rs)} 筆的中位數，範圍 {lo_r:.2f}–{hi_r:.2f} nm/s → {round(target / hi_r)}–"
                     f"{round(target / lo_r)} s")}


def rates_for(records, log_df=None, kind="rie"):
    """先用過去樣品（同一種步驟），沒有再用蝕刻紀錄。回傳 (rates, 來源說明)。"""
    h = history(records, kind)
    if h:
        return h, f"過去樣品的 {kind.upper()} "
    lg = from_log(log_df, kind)
    if lg:
        return lg, f"Etching 蝕刻紀錄（{kind.upper()}、hBN）"
    return [], ""
