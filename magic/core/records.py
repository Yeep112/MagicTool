"""匯出分析結果：圖、表格（CSV）、result.json（來源檔、參數、軟體版本），方便日後重現。

輸出位置：<output_root>\\<機台>\\<日期_時間>_<分析>\\ ；不會寫進原始資料夾。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path


def safe_name(text, limit=60):
    s = re.sub(r'[\\/:*?"<>|\s]+', "_", str(text)).strip("_.")
    return s[:limit] or "result"


def file_info(path, hash_limit=200 * 1024 * 1024):
    p = Path(path)
    info = {"path": str(p), "name": p.name}
    try:
        st = p.stat()
        info.update(size=st.st_size, modified=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)))
        if st.st_size <= hash_limit:
            h = hashlib.sha256()
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            info["sha256"] = h.hexdigest()
    except OSError:
        pass
    return info


def _jsonable(v):
    try:
        import numpy as np
        if isinstance(v, np.generic):
            return v.item()
        if isinstance(v, np.ndarray):
            return v.tolist()
    except ImportError:
        pass
    if isinstance(v, float) and v != v:
        return None
    if isinstance(v, (tuple, set)):
        return list(v)
    return str(v)


def export_result(out_root, instrument, analysis_name, fig, result, params, sources, version,
                  fig_format="png", dpi=200, extra=None):
    """回傳輸出資料夾。sources：來源檔路徑清單（或 dict 描述，例如 Etching 的紀錄）。"""
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out = Path(out_root) / safe_name(instrument) / f"{stamp}_{safe_name(analysis_name, 40)}"
    k = 1
    while out.exists():
        k += 1
        out = out.with_name(f"{stamp}_{safe_name(analysis_name, 40)}_{k}")
    out.mkdir(parents=True)
    files = []
    if fig is not None:
        fp = out / f"figure.{fig_format}"
        fig.savefig(fp, dpi=dpi, bbox_inches="tight")
        files.append(fp.name)
    for name, df in (getattr(result, "tables", None) or {}).items():
        fp = out / f"{safe_name(name)}.csv"
        df.to_csv(fp, index=False, encoding="utf-8-sig")
        files.append(fp.name)
    if getattr(result, "text", ""):
        (out / "result.txt").write_text(result.text, encoding="utf-8")
        files.append("result.txt")
    record = {
        "software": "Magic Tool", "version": version,
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "instrument": instrument, "analysis": analysis_name,
        "params": params,
        "sources": [file_info(s) if isinstance(s, (str, os.PathLike)) else s for s in sources],
        "summary": getattr(result, "summary", {}) or {},
        "warnings": getattr(result, "warnings", []) or [],
        "files": files,
    }
    if extra:
        record.update(extra)
    (out / "result.json").write_text(json.dumps(record, ensure_ascii=False, indent=2, default=_jsonable),
                                     encoding="utf-8")
    return out
