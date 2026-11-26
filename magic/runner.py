"""不開介面直接執行分析（Jupyter、自我測試、之後的批次功能共用；結果和介面完全一樣）。

    from magic.runner import run
    fig, res = run("PPMS", "R–T 與 Tc", [r"...\\300K_10K_4K_to_10K_300K.dat"], T_range="2, 12")
    print(res.text)
    res.tables["Tc"]            # pandas DataFrame
    fig                          # matplotlib Figure（在 notebook 會直接顯示）

Etching 的分析：sources 給紀錄 CSV 的路徑（或 DataFrame）。
"""
from __future__ import annotations

import os

PLOT_CYCLE = ["#2563eb", "#e4572e", "#17a398", "#f2a541", "#7c3aed", "#ef476f",
              "#118ab2", "#8d6a9f", "#06d6a0", "#5c6b73"]


def list_analyses(instrument=None):
    from .core.registry import load_analyses
    a = load_analyses()
    if instrument:
        return [x.name for x in a.get(instrument, [])]
    return {k: [x.name for x in v] for k, v in a.items()}


def make_items(instrument, sources, colors=None):
    from .core.registry import INSTRUMENTS, Item
    from .readers import Dataset, load
    colors = colors or PLOT_CYCLE
    inst = INSTRUMENTS[instrument]
    if inst.source == "records":
        import pandas as pd
        from .etching.store import normalize, read_log
        src = sources[0] if isinstance(sources, (list, tuple)) else sources
        if isinstance(src, pd.DataFrame):
            df = src if "#" in src.columns else normalize(src)
            path = "(DataFrame)"
        else:
            df, path = read_log(src), os.fspath(src)
        return [Item(path, "紀錄", colors[0], Dataset(path, "Etching", df))]
    items = []
    for k, s in enumerate(sources):
        ds = load(s)
        items.append(Item(ds.path, os.path.splitext(ds.name)[0], colors[k % len(colors)], ds))
    return items


def parse_params(analysis, overrides=None):
    """預設值 + overrides（可以是文字或已經轉好的值）→ 分析用的參數 dict。"""
    p = {}
    overrides = overrides or {}
    for q in analysis.params:
        raw = overrides.get(q.key, q.default)
        if q.kind == "range" and isinstance(raw, (list, tuple)):
            p[q.key] = tuple(raw)
        else:
            p[q.key] = q.parse(raw)
    unknown = set(overrides) - {q.key for q in analysis.params}
    if unknown:
        raise KeyError(f"「{analysis.name}」沒有參數 {sorted(unknown)}；可用：{[q.key for q in analysis.params]}")
    return p


def run(instrument, name, sources, fig=None, progress=None, edits=True, **params):
    """edits：Raman 是否套用介面裡做的橡皮擦與手動背景（True = 套用，False = 用原始資料，
    或直接給 {路徑: 編修} dict）。"""
    from .core.registry import find
    a = find(instrument, name)
    if a is None:
        raise KeyError(f"{instrument} 沒有「{name}」；可用：{list_analyses(instrument)}")
    items = make_items(instrument, sources)
    if instrument == "Raman" and edits:
        from .raman.edits import EditStore, apply_all
        snap = edits if isinstance(edits, dict) else EditStore().snapshot([it.path for it in items])
        snap = {os.path.normcase(os.path.abspath(k)): v for k, v in snap.items()}
        apply_all(items, snap)
    p = parse_params(a, params)
    from .core import plotstyle
    plotstyle.apply()
    if fig is None:
        from matplotlib.figure import Figure
        fig = Figure(figsize=(11, 5.5), layout="constrained")
    data = a.compute(items, dict(p), progress or (lambda k, n, t="": None)) if a.compute else None
    res = a.func(fig, items, p, data)
    return fig, res
