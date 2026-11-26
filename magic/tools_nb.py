"""發佈前的保護：清掉 notebook 的輸出、找出不應該上傳的資料檔。

notebook 的輸出（圖、印出來的數值、表格）可能是真實量測結果；程式碼可以公開，輸出不行。
不需要安裝 nbstripout，只用標準函式庫。

    python -m magic strip-notebooks        手動清除 notebooks\\ 的輸出
"""
from __future__ import annotations

import json
import os

DATA_EXT = {".dat", ".db", ".spe", ".wdf", ".spc", ".sif", ".h5", ".hdf5", ".xlsx", ".xls", ".tif", ".tiff",
            ".jpg", ".jpeg", ".opj", ".opju"}
ALLOWED_DIRS = ("assets/",)


def strip_notebook(path):
    """清掉一個 .ipynb 的輸出與執行次數。有修改回傳 True。"""
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    nb = json.loads(raw)
    for cell in nb.get("cells", []):
        if cell.get("cell_type") == "code":
            cell["outputs"] = []
            cell["execution_count"] = None
        cell.get("metadata", {}).pop("execution", None)
    nb.get("metadata", {}).pop("widgets", None)
    new = json.dumps(nb, ensure_ascii=False, indent=1) + "\n"
    if new != raw:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(new)
        return True
    return False


def strip_folder(folder):
    out = []
    if not os.path.isdir(folder):
        return out
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d != ".ipynb_checkpoints"]
        for fn in files:
            if fn.endswith(".ipynb") and strip_notebook(os.path.join(root, fn)):
                out.append(fn)
    return out


def suspicious(paths):
    """git 要上傳的檔案裡，看起來像量測資料的（副檔名）。"""
    bad = []
    for p in paths:
        q = p.replace("\\", "/").strip('"')
        if any(q.startswith(d) for d in ALLOWED_DIRS):
            continue
        if os.path.splitext(q)[1].lower() in DATA_EXT:
            bad.append(q)
    return bad
