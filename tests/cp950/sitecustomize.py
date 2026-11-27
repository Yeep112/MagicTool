"""模擬繁體中文 Windows（cp950）：讀寫文字檔沒寫 encoding 時用 cp950。

同事從捷徑直接開 MagicTool.pyw 時沒有 UTF-8 模式，Python 會用系統編碼 cp950；
程式裡只要有一個 open() 忘了寫 encoding="utf-8"，遇到中文就會出錯。這裡在任何電腦上重現那個情況：

    PYTHONPATH=tests/cp950 python -X utf8=0 -m magic selftest --no-gui

（只換「檔案內容」的預設編碼；檔名不受影響，和 Windows 一樣。）
"""
import builtins
import io
import locale

_open = builtins.open


def _cp950_open(file, mode="r", buffering=-1, encoding=None, *args, **kwargs):
    if "b" not in mode and encoding is None:
        encoding = "cp950"
    return _open(file, mode, buffering, encoding, *args, **kwargs)


builtins.open = io.open = _cp950_open
locale.getpreferredencoding = lambda do_setlocale=True: "cp950"
if hasattr(locale, "getencoding"):
    locale.getencoding = lambda: "cp950"
