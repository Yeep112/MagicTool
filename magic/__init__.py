"""magic — Magic Tool 實驗分析（PPMS、SQUID、Raman、Etching）

套件結構
  magic/core/       共用：設定、單位、欄位搜尋、掃描分段、Tc、峰擬合、分析登錄
  magic/readers/    讀檔：Quantum Design .dat（PPMS + SQUID 共用）、Raman 兩欄文字檔
  magic/ppms/       PPMS 分析（一個功能一個檔案；放進資料夾就會自動出現在介面）
  magic/squid/      SQUID 分析
  magic/raman/      Raman 分析
  magic/etching/    蝕刻速率：計算、紀錄（CSV / Google Sheet）、比較
  magic/gui/        軟體介面

在 Jupyter 裡：
    from magic import load
    ds = load(r"...\\300K_10K_4K_to_10K_300K.dat")     # 自動判斷檔案種類
    ds.df, ds.header, ds.kind                          # QD .dat
    from magic.core.transition import transition       # Tc
"""
from __future__ import annotations


def _read_version():
    import json
    import os
    try:
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "release.json")
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("version", "0")
    except Exception:
        return "0"


__version__ = _read_version()          # 版本號只寫在 release.json


def __getattr__(name):
    """延後載入（import magic 不會馬上載入 numpy / pandas，讓軟體的載入畫面先出現）。"""
    if name in ("load", "detect"):
        from . import readers
        return getattr(readers, name)
    raise AttributeError(name)
