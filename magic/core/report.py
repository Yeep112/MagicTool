"""📦 錯誤回報：把 error.log、crash.log、app.log 和環境資訊打包成一個 zip，同事出問題時直接傳給維護的人。

不會放進去的東西：量測資料、蝕刻紀錄、Google Sheet 金鑰；settings.toml 裡的 Google Sheet 網址與金鑰路徑會遮掉。
"""
from __future__ import annotations

import os
import platform
import re
import sys
import time
import zipfile
from pathlib import Path

MAX_LOG = 2 * 1024 * 1024          # 每個 log 最多放最後 2 MB


def _tail(path, limit=MAX_LOG):
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        n = f.tell()
        f.seek(max(n - limit, 0))
        data = f.read()
    if n > limit:
        data = f"（只保留最後 {limit // 1024} KB）\n".encode("utf-8") + data
    return data


def environment():
    from .. import __version__
    lines = [f"Magic Tool v{__version__}", f"時間：{time.strftime('%Y-%m-%d %H:%M:%S')}",
             f"Python {sys.version}", f"執行檔：{sys.executable}", f"系統：{platform.platform()}",
             f"處理器：{platform.machine()}"]
    for mod in ("numpy", "scipy", "pandas", "matplotlib", "PIL", "openpyxl", "gspread"):
        try:
            m = __import__(mod)
            lines.append(f"{mod} {getattr(m, '__version__', '?')}")
        except Exception as e:
            lines.append(f"{mod}：沒有安裝（{type(e).__name__}）")
    try:
        import tkinter
        lines.append(f"Tk {tkinter.TkVersion}")
    except Exception:
        lines.append("Tk：無法載入")
    from .settings import TOOL_ROOT
    lines.append(f"工具資料夾：{TOOL_ROOT}")
    return "\n".join(lines) + "\n"


def _redacted_settings(path):
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return re.sub(r'^(\s*(gsheet_key|gsheet_script_url|gsheet_token|service_account|sa_path|sheet)\s*=\s*).*$', r'\1"（已遮掉）"', text, flags=re.M)


def default_folder():
    home = Path.home()
    for d in (home / "Desktop", home / "桌面", home / "Downloads"):
        if d.is_dir():
            return d
    from .settings import data_dir
    return data_dir()


def make_report(dest=None, note=""):
    """建立錯誤回報 zip，回傳路徑。"""
    from .. import __version__
    from .settings import data_dir, log_dir
    dest = Path(dest) if dest else default_folder()
    dest.mkdir(parents=True, exist_ok=True)
    fp = dest / f"MagicTool_錯誤回報_v{__version__}_{time.strftime('%Y%m%d_%H%M%S')}.zip"
    logs = log_dir()
    with zipfile.ZipFile(fp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("環境.txt", environment())
        if note:
            z.writestr("說明.txt", note)
        found = []
        for name in ("error.log", "crash.log", "app.log"):
            p = logs / name
            if p.is_file() and p.stat().st_size:
                z.writestr(f"logs/{name}", _tail(p))
                found.append(name)
        for old in sorted(logs.glob("*.log.*"))[-3:]:          # 輪替過的舊 log
            z.writestr(f"logs/{old.name}", _tail(old, 512 * 1024))
        ph = data_dir() / "perf_history.csv"
        if ph.is_file():                                   # 流暢度紀錄（最後 50 次）
            rows = ph.read_text(encoding="utf-8").splitlines()
            z.writestr("perf_history.csv", "\n".join(rows[:1] + rows[1:][-50:]) + "\n")
            found.append("perf_history.csv（流暢度紀錄）")
        s = data_dir() / "settings.toml"
        if s.is_file():
            z.writestr("settings（遮掉金鑰）.toml", _redacted_settings(s))
        z.writestr("內容.txt", "這份回報包含：\n" + "\n".join(f"  ‧ {n}" for n in (["環境.txt"] + found)) +
                   "\n\n不包含量測資料、蝕刻紀錄、Google Sheet 金鑰。\n")
    return fp


def open_folder(path):
    path = str(path)
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)                     # noqa: S606
        elif sys.platform == "darwin":
            import subprocess
            subprocess.Popen(["open", path])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass
