"""機台與分析功能登錄（介面、Jupyter、自我測試共用；格式沿用 LowTempAnalysis 的 @analysis）。

每個功能 = 一個函式 + 參數清單。把檔案放進 magic/<機台>/ 就會自動出現在介面（檔名以 _ 開頭的不會）。
私人的分析或機台：放在 %LOCALAPPDATA%\\MagicTool\\plugins\\ 底下，不會被上傳到 GitHub。

    from magic.core.registry import P, Result, analysis

    @analysis("PPMS", "我的分析", group="參數萃取", icon="★",
              params=[P("window", "平滑點數", 11),
                      P("y", "Y 軸", "Bridge 1 Resistance (Ohms)", kind="column")])
    def my_analysis(fig, items, p, data=None):
        ax = fig.add_subplot()
        for it in items:
            df = it.data.df                      # QD .dat：pandas DataFrame
            ...
        return Result(text="...", tables={"summary": df})

慢的計算寫成 compute=函式(items, p, progress) → data，會在背景執行（介面不會卡住），
畫圖函式再用 data 畫。compute 不可以碰 fig。
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import pkgutil
import sys
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

MODES = ["快速檢視", "參數萃取", "批次比較"]


@dataclass
class Instrument:
    key: str
    title: str
    sub: str
    source: str = "files"               # "files" = 讀資料夾裡的檔案；"records" = 紀錄表（Etching）
    patterns: tuple = ("*",)
    reader: str = ""                    # readers 模組的名稱
    color: str = "#2563eb"
    package: str = ""                   # 分析功能所在的套件
    help: str = ""


INSTRUMENTS: dict[str, Instrument] = {}


def register_instrument(inst: Instrument):
    INSTRUMENTS[inst.key] = inst
    return inst


register_instrument(Instrument("PPMS", "PPMS", "電阻 R–T、R–H", "files", ("*.dat",), "qd_dat",
                               "#2563eb", "magic.ppms", "Quantum Design PPMS 的 .dat 檔"))
register_instrument(Instrument("SQUID", "SQUID", "磁矩 M–T、M–H", "files", ("*.dat",), "qd_dat",
                               "#7c3aed", "magic.squid", "Quantum Design MPMS（SQUID）的 .dat 檔"))
register_instrument(Instrument("Raman", "Raman", "光譜、G / 2D 峰", "files", ("*.txt", "*.csv"), "raman_txt",
                               "#0d9488", "magic.raman", "兩欄文字檔：Raman shift、intensity"))
register_instrument(Instrument("Etching", "Etching", "蝕刻速率紀錄", "records", (), "",
                               "#ea580c", "magic.etching", "AFM 量到的高度 → 蝕刻速率"))


@dataclass
class P:
    """一個參數。kind 沒寫時依 default 的型別判斷：
        float/int → 輸入框、bool → 勾選、choices → 下拉選單、str → 文字框
    特殊 kind：
        "column"   下拉選單，選項是所選檔案的欄位名稱（也可以自己打）
        "range"    兩個數字「最小, 最大」，空白 = 不限制 → (lo, hi)
        "optfloat" 數字或空白（空白 = None）"""
    key: str
    label: str
    default: Any
    choices: list | None = None
    tip: str = ""
    kind: str | None = None

    def __post_init__(self):
        if self.kind is None:
            if self.choices:
                self.kind = "choice"
            elif isinstance(self.default, bool):
                self.kind = "bool"
            elif isinstance(self.default, int):
                self.kind = "int"
            elif isinstance(self.default, float):
                self.kind = "float"
            else:
                self.kind = "text"

    def parse(self, raw):
        from .units import parse_range
        k = self.kind
        if k == "bool":
            if isinstance(raw, str):
                return raw.strip().lower() in ("1", "true", "yes", "是")
            return bool(raw)
        if k in ("int", "float"):
            if isinstance(raw, str):
                raw = raw.strip()
                if raw == "":
                    return self.default
            try:
                return int(float(raw)) if k == "int" else float(raw)
            except (TypeError, ValueError):
                raise ValueError(f"「{self.label}」需要數字，收到：{raw!r}")
        if k == "optfloat":
            if raw is None or str(raw).strip() in ("", "None", "none", "自動"):
                return None
            try:
                return float(raw)
            except (TypeError, ValueError):
                raise ValueError(f"「{self.label}」需要數字或空白，收到：{raw!r}")
        if k == "range":
            try:
                return parse_range(raw)
            except ValueError:
                raise ValueError(f"「{self.label}」格式是「最小, 最大」（空白 = 不限制），收到：{raw!r}")
        return raw if raw is not None else self.default

    def to_text(self, value):
        if isinstance(value, str):                   # 預設值本來就是文字（例如範圍「1550, 1620」）
            return value
        if self.kind == "range":
            lo, hi = value if isinstance(value, (list, tuple)) else (None, None)
            if lo is None and hi is None:
                return ""
            return f"{'' if lo is None else f'{lo:g}'}, {'' if hi is None else f'{hi:g}'}"
        if self.kind == "optfloat":
            return "" if value is None else f"{value:g}"
        if self.kind == "bool":
            return bool(value)
        return "" if value is None else str(value)


@dataclass
class Result:
    text: str = ""
    tables: dict = field(default_factory=dict)     # 名稱 → pandas DataFrame（匯出成 CSV）
    summary: dict = field(default_factory=dict)    # 重要數值（寫進 result.json）
    title: str = ""
    hint: str = ""                                  # 操作提示（顯示在圖的上方）
    warnings: list = field(default_factory=list)


@dataclass
class Item:
    """傳給分析函式的一筆資料（一個檔案，或 Etching 的一份紀錄表）。"""
    path: str
    label: str
    color: str
    data: Any


@dataclass
class Analysis:
    instrument: str
    name: str
    func: Callable
    params: list
    help: str = ""
    group: str = MODES[0]
    icon: str = "•"
    order: int = 100
    multi: bool = True
    compute: Callable | None = None
    module: str = ""

    @property
    def key(self):
        return f"{self.instrument}:{self.name}"

    def defaults(self):
        return {q.key: q.default for q in self.params}


ANALYSES: dict[str, list] = {}
LOAD_ERRORS: dict[str, str] = {}
_loaded = False


def analysis(instrument, name, group=MODES[0], icon="•", params=(), help="", order=100, multi=True,
             compute=None):
    def deco(func):
        a = Analysis(instrument, name, func, list(params), help, group, icon, order, multi, compute,
                     getattr(func, "__module__", ""))
        lst = ANALYSES.setdefault(instrument, [])
        lst[:] = [x for x in lst if x.name != name] + [a]       # 重新載入時取代舊的
        func.analysis = a
        return func
    return deco


def plugin_dir():
    from .settings import data_dir
    return os.path.join(str(data_dir()), "plugins")


def _import_package(pkg):
    try:
        mod = importlib.import_module(pkg)
    except Exception:
        LOAD_ERRORS[pkg] = traceback.format_exc(limit=3)
        return
    for info in pkgutil.iter_modules(mod.__path__):
        if info.name.startswith("_"):
            continue
        name = f"{pkg}.{info.name}"
        try:
            importlib.import_module(name)
        except Exception:                      # 一個壞掉的檔案不影響其他功能
            LOAD_ERRORS[name] = traceback.format_exc(limit=3)


def _import_plugins(folder):
    if not os.path.isdir(folder):
        return
    for fn in sorted(os.listdir(folder)):
        if not fn.endswith(".py") or fn.startswith("_"):
            continue
        path = os.path.join(folder, fn)
        name = f"magic_plugin_{os.path.splitext(fn)[0]}"
        try:
            spec = importlib.util.spec_from_file_location(name, path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)
        except Exception:
            LOAD_ERRORS[path] = traceback.format_exc(limit=3)


def load_analyses(reload=False):
    """回傳 {機台: [Analysis, ...]}，依「快速檢視 → 參數萃取 → 批次比較」、order 排序。"""
    global _loaded
    if not _loaded or reload:
        for inst in list(INSTRUMENTS.values()):
            if inst.package:
                _import_package(inst.package)
        _import_plugins(plugin_dir())
        _loaded = True
    out = {}
    for key in INSTRUMENTS:
        lst = ANALYSES.get(key, [])
        out[key] = sorted(lst, key=lambda a: (MODES.index(a.group) if a.group in MODES else 99, a.order, a.name))
    return out


def find(instrument, name):
    for a in load_analyses().get(instrument, []):
        if a.name == name:
            return a
    return None
