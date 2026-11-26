"""PPMS / SQUID 共用：取欄位、分段、單位、Tc 計算與畫圖小工具。"""
from __future__ import annotations

import numpy as np

from .columns import resolve
from .segments import SEGMENT_CHOICES, pick, split_sweeps
from .transition import METHOD_NAMES, pick_tc, transition
from .units import FIELD_OE, MOMENT, RESISTANCE, auto_unit, in_range

SEG_CHOICES = SEGMENT_CHOICES + ["第1段", "第2段", "第3段", "第4段"]
LINESTYLES = {-1: "-", 1: "--", 0: ":"}


def unit_table(colname):
    """依欄位名稱的單位決定可以換算的單位表。回傳 (表, 原始單位) 或 (None, '')。"""
    c = str(colname).lower()
    if "(ohm" in c or "(ω" in c or "resistance" in c:
        return RESISTANCE, "Ω"
    if "(emu)" in c:
        return MOMENT, "emu"
    if "(oe)" in c:
        return FIELD_OE, "Oe"
    return None, ""


def base_label(colname):
    """「Bridge 1 Resistance (Ohms)」→「Bridge 1 Resistance」"""
    s = str(colname)
    return s[:s.rfind("(")].strip() if "(" in s else s


def scaled(values, colname, wanted="auto"):
    """回傳 (換算後的值, 軸標籤, 換算係數)；顯示值 = 原始值 / 係數。"""
    table, _ = unit_table(colname)
    if table is None or wanted in ("原始單位", "raw"):
        return np.asarray(values, float), str(colname), 1.0
    unit, f = auto_unit(values, table, "auto" if wanted in ("auto", "自動", None, "") else wanted)
    return np.asarray(values, float) / f, f"{base_label(colname)} ({unit})", f


def get_xy(ds, xname, yname, warn=None):
    xc = resolve(ds.df, xname, warn=warn)
    yc = resolve(ds.df, yname, warn=warn)
    x = ds.df[xc].to_numpy(dtype=float, na_value=np.nan)
    y = ds.df[yc].to_numpy(dtype=float, na_value=np.nan)
    return xc, yc, x, y


def segment_name(ds, seg, kind="T"):
    """段落名稱；Comment 欄寫了 ZFC / FC 時一併顯示。"""
    base = seg.label(kind, "K" if kind == "T" else "Oe")
    if "Comment" in ds.df.columns and seg.number:
        txt = " ".join(str(v) for v in ds.df["Comment"].iloc[seg.start:seg.stop] if str(v).strip())
        up = txt.upper()
        tag = "ZFC" if "ZFC" in up else ("FCW" if "FCW" in up else ("FC" if "FC" in up else ""))
        if tag:
            base += f"（{tag}）"
    return base


def segments(ds, x, choice, kind="T"):
    segs = pick(split_sweeps(x), choice)
    return [(s, segment_name(ds, s, kind) if s.number else "全部") for s in segs]


def auto_window(T, y):
    """溫度範圍空白時自動選：先找整段裡 |dy/dT| 最大的溫度 T*，再取 [最低溫, 2 × T*]。

    這樣正常態的參考值取在轉變上方附近，而不是 300 K（金屬的電阻會隨溫度上升，會把 Tc 算歪）。"""
    from .units import derivative
    ok = np.isfinite(T) & np.isfinite(y)
    if ok.sum() < 8:
        return (None, None)
    Tg, d = derivative(T[ok], y[ok], smooth_window=5)
    if Tg.size < 5 or not np.isfinite(d).any():
        return (None, None)
    t_star = float(Tg[int(np.nanargmax(np.abs(d)))])
    lo = float(np.nanmin(T[ok]))
    hi = max(2 * t_star, t_star + 5 * (Tg[1] - Tg[0]))
    return (lo, min(hi, float(np.nanmax(T[ok]))))


def tc_compute(items, p, progress, ycol_key="y"):
    """每個檔案、每一段算 Tc。回傳 [{item, seg, name, res, tc, xcol, ycol, warn}]。"""
    out = []
    n = len(items)
    for k, it in enumerate(items):
        warns = []
        xc, yc, x, y = get_xy(it.data, p["x"], p[ycol_key], warn=warns.append)
        for seg, name in segments(it.data, x, p["segments"], "T"):
            xs, ys = x[seg.slice], y[seg.slice]
            rng = p["T_range"]
            auto = rng is None or tuple(rng) == (None, None)
            if auto:
                rng = auto_window(xs, ys)
            m = in_range(xs, rng) & np.isfinite(ys)
            res = transition(xs[m], ys[m], normal_range=p.get("normal_range") or (None, None),
                             sc_range=p.get("sc_range") or (None, None), smooth_window=p.get("smooth", 0))
            res["window"] = rng
            res["auto_window"] = auto
            out.append(dict(item=it, seg=seg, name=name, res=res, tc=pick_tc(res, p["method"]),
                            xcol=xc, ycol=yc, warn=warns, x=xs, y=ys))
        progress(k + 1, n, it.label)
    return out


def tc_table(rows, method_name, value_label="y_n"):
    import pandas as pd
    recs = []
    for r in rows:
        res = r["res"]
        recs.append({
            "檔案": r["item"].label, "段落": r["name"],
            f"Tc（{method_name}）(K)": r["tc"],
            "T 90% (K)": res["T90"], "T 50% (K)": res["T50"], "T 10% (K)": res["T10"],
            "寬度 T90−T10 (K)": res["width"], "最大斜率處 (K)": res["T_deriv"],
            f"正常態 {value_label}": res["y_n"], f"低溫端 {value_label}": res["y_s"],
            "說明": res["reason"],
        })
    return pd.DataFrame(recs)


def fmt(v, nd=4):
    return "—" if v is None or not np.isfinite(v) else f"{v:.{nd}g}"


def tc_text(rows, method_name):
    lines = [f"Tc 定義：{method_name}（90% / 50% / 10% 為正規化數值 (y − y_低溫) / (y_正常 − y_低溫)）", ""]
    for r in rows:
        res = r["res"]
        lines.append(f"{r['item'].label}｜{r['name']}")
        if not res["ok"]:
            lines.append(f"  ✗ {res['reason']}")
            continue
        lines.append(f"  Tc = {fmt(r['tc'])} K　（90%: {fmt(res['T90'])}　50%: {fmt(res['T50'])}　"
                     f"10%: {fmt(res['T10'])}　寬度: {fmt(res['width'], 3)} K　最大斜率: {fmt(res['T_deriv'])} K）")
        if res.get("auto_window"):
            lo, hi = res["window"]
            lines.append(f"  （溫度範圍自動選 {fmt(lo)}–{fmt(hi)} K；不對的話在參數面板指定）")
    return "\n".join(lines)


def common_tc_params(y_default, T_range=""):
    from .registry import P
    return [
        P("x", "溫度欄位", "Temperature (K)", kind="column"),
        P("y", "數值欄位", y_default, kind="column"),
        P("T_range", "溫度範圍 (K)", T_range, kind="range",
          tip="只用這個範圍算 Tc（要包含轉變上下兩端的平台），例如「2, 12」；空白 = 自動（最低溫到 2 × 轉變溫度）"),
        P("segments", "掃描段落", SEGMENT_CHOICES[0], choices=SEG_CHOICES,
          tip="降溫 / 升溫（ZFC / FC）分開分析，避免兩段混在一起"),
        P("method", "Tc 定義", METHOD_NAMES[0], choices=METHOD_NAMES),
        P("normal_range", "正常態溫度區間", "", kind="range", tip="空白 = 自動取範圍內最高溫那一端"),
        P("sc_range", "低溫端溫度區間", "", kind="range", tip="空白 = 自動取範圍內最低溫那一端"),
        P("smooth", "微分平滑點數", 0, tip="0 = 不平滑；資料雜訊大時可設 7–21"),
        P("y_unit", "Y 單位", "自動", choices=["自動", "原始單位"]),
    ]


def draw_tc(fig, rows, p, ylabel_hint=""):
    """左：完整曲線（各段）；右：Tc 附近放大 + 標記 + 微分。回傳警告清單。"""
    ax_full = fig.add_subplot(1, 2, 1)
    ax = fig.add_subplot(1, 2, 2)
    ax_d = ax.twinx()
    warns = []
    ylabel, fac = ylabel_hint, 1.0
    if rows:
        _, ylabel, fac = scaled(np.concatenate([r["y"] for r in rows]), rows[0]["ycol"], p.get("y_unit", "自動"))
    f = 1.0 / fac
    multi_file = len({id(r["item"]) for r in rows}) > 1
    for i, r in enumerate(rows):
        it, seg, res = r["item"], r["seg"], r["res"]
        color = it.color if multi_file else f"C{i % 10}"
        ls = LINESTYLES.get(seg.direction, "-") if multi_file else "-"
        label = f"{it.label}｜{r['name']}" if multi_file else r["name"]
        yv = r["y"] * f
        ax_full.plot(r["x"], yv, ls, color=color, lw=1.2, label=label)
        if res["T"].size:
            ax.plot(res["T"], res["y"] * f, ".-", color=color, ms=3, lw=1, label=label)
            if res["dydT"].size:
                ax_d.plot(res["Tg"], res["dydT"] * f, color=color, lw=0.8, alpha=0.35)
        if res["ok"]:
            for key, mk in (("T90", "^"), ("T50", "o"), ("T10", "v")):
                tv = res[key]
                if np.isfinite(tv):
                    ax.plot([tv], [np.interp(tv, res["T"], res["y"]) * f], mk, color=color, mec="black",
                            ms=7, zorder=5, gid="nohover")
            if np.isfinite(r["tc"]):
                ax.axvline(r["tc"], color=color, ls=":", lw=1)
                ax_full.axvline(r["tc"], color=color, ls=":", lw=0.8)
        else:
            warns.append(f"{label}：{res['reason']}")
        warns += r["warn"]
    lo, hi = p["T_range"]
    if (lo is None and hi is None) and rows:
        lo = min((r["res"]["window"][0] for r in rows if r["res"]["window"][0] is not None), default=None)
        hi = max((r["res"]["window"][1] for r in rows if r["res"]["window"][1] is not None), default=None)
    if lo is not None or hi is not None:
        ax_full.axvspan(lo if lo is not None else ax_full.get_xlim()[0],
                        hi if hi is not None else ax_full.get_xlim()[1], color="#facc15", alpha=0.12, lw=0)
    ax_full.set_xlabel("Temperature (K)")
    ax_full.set_ylabel(ylabel)
    ax_full.set_title("完整曲線（黃色 = 分析範圍）")
    ax.set_xlabel("Temperature (K)")
    ax.set_ylabel(ylabel)
    ax_d.set_ylabel("d/dT（淡色）", color="#9ca3af")
    ax_d.tick_params(axis="y", colors="#9ca3af")
    ax_d.grid(False)
    ax.set_title("Tc 附近（▲90% ●50% ▼10%）")
    ax.legend(fontsize=8, loc="best")
    ax.set_zorder(ax_d.get_zorder() + 1)
    ax.patch.set_visible(False)
    return list(dict.fromkeys(warns))


NORMALIZE = ["除以正常態數值", "除以低溫端數值的絕對值", "不正規化"]


def draw_compare(fig, rows, p, value_name="R"):
    """批次比較：左邊正規化疊圖，右邊每個樣品、每一段的 Tc 長條圖。回傳警告清單。"""
    ax = fig.add_subplot(1, 2, 1)
    ax2 = fig.add_subplot(1, 2, 2)
    warns, labels, tcs, colors = [], [], [], []
    norm = p.get("normalize", NORMALIZE[0])
    for r in rows:
        res, it = r["res"], r["item"]
        m = in_range(r["x"], p["T_range"])
        y = r["y"][m]
        if norm == NORMALIZE[0] and np.isfinite(res["y_n"]) and res["y_n"] != 0:
            y = y / res["y_n"]
        elif norm == NORMALIZE[1] and np.isfinite(res["y_s"]) and res["y_s"] != 0:
            y = y / abs(res["y_s"])
        ls = LINESTYLES.get(r["seg"].direction, "-")
        ax.plot(r["x"][m], y, ls, color=it.color, lw=1.2, label=f"{it.label}｜{r['name']}")
        labels.append(f"{it.label}\n{r['name']}")
        tcs.append(r["tc"])
        colors.append(it.color)
        if not res["ok"]:
            warns.append(f"{it.label}｜{r['name']}：{res['reason']}")
        warns += r["warn"]
    ax.set_xlabel("Temperature (K)")
    ax.set_ylabel({NORMALIZE[0]: f"{value_name} / {value_name}(正常態)",
                   NORMALIZE[1]: f"{value_name} / |{value_name}(低溫)|"}.get(norm, rows[0]["ycol"] if rows else value_name))
    ax.set_title("實線 = 降溫，虛線 = 升溫")
    if len(rows) <= 12:
        ax.legend(fontsize=7)
    xs = np.arange(len(tcs))
    ax2.bar(xs, [t if np.isfinite(t) else 0 for t in tcs], color=colors, alpha=0.85)
    for i, t in enumerate(tcs):
        if np.isfinite(t):
            ax2.text(i, t, fmt(t), ha="center", va="bottom", fontsize=8)
    ax2.set_xticks(xs)
    ax2.set_xticklabels(labels, fontsize=7, rotation=30, ha="right")
    ax2.set_ylabel(f"Tc（{p['method']}）(K)")
    ax2.set_title("Tc 比較")
    finite = [t for t in tcs if np.isfinite(t)]
    if finite:
        ax2.set_ylim(min(finite) * 0.9, max(finite) * 1.06)
    return list(dict.fromkeys(warns))
