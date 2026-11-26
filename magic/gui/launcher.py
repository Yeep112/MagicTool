"""軟體啟動器（取自 LowTempAnalysis）：先顯示載入畫面，再載入 numpy / matplotlib / 分析功能，最後打開主視窗。

開始功能表與桌面捷徑執行的是：
    pythonw.exe -m magic app      （pythonw = 沒有黑色命令列視窗）

這個檔案刻意只在最上面匯入標準函式庫，讓載入畫面能在一秒內出現。
"""
from __future__ import annotations

import os
import sys
import time
import traceback

APP_ID = "Yeep.MagicTool"
APP_NAME = "Magic Tool 實驗分析"
TOOL_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ASSETS = os.path.join(TOOL_ROOT, "assets")


def data_dir():
    """和 magic.core.settings.data_dir() 相同（這裡只用標準函式庫，讓載入畫面先出現）。"""
    env = os.environ.get("MAGIC_DATA")
    if env:
        path = env
    elif os.environ.get("LOCALAPPDATA"):
        path = os.path.join(os.environ["LOCALAPPDATA"], "MagicTool")
    elif sys.platform == "darwin":
        path = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "MagicTool")
    else:
        path = os.path.join(os.path.expanduser("~"), ".magictool")
    os.makedirs(path, exist_ok=True)
    return path


def log_dir():
    path = os.path.join(data_dir(), "logs")
    os.makedirs(path, exist_ok=True)
    return path


def register_paths():
    """記下程式資料夾與 Python 的位置，讓任何地方的啟動檔（複製出去的 run_analysis.bat、捷徑）都找得到。
    檔案：%LOCALAPPDATA%\\MagicTool\\tool_path.txt、python_path.txt（系統預設編碼，cmd 讀得懂）"""
    try:
        d = data_dir()
        enc = "mbcs" if os.name == "nt" else "utf-8"
        exe_dir = os.path.dirname(sys.executable)
        py = os.path.join(exe_dir, "python.exe") if os.name == "nt" else sys.executable
        if not os.path.exists(py):
            py = sys.executable
        for name, value in (("tool_path.txt", TOOL_ROOT), ("python_path.txt", py)):
            with open(os.path.join(d, name), "w", encoding=enc, errors="replace") as f:
                f.write(value + "\n")
    except Exception:
        pass


def setup_environment():
    """1) pythonw 沒有 stdout/stderr → 導到 log 檔；
    2) 沒有先「啟用」conda 環境時，補上 DLL 搜尋路徑（numpy、scipy、Tk 需要）；
    3) Windows：高 DPI 不模糊、工作列使用本軟體的圖示。"""
    if sys.stdout is None or sys.stderr is None or os.path.basename(sys.executable).lower() == "pythonw.exe":
        try:
            f = open(os.path.join(log_dir(), "app.log"), "a", encoding="utf-8", buffering=1)
            f.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')}  {sys.executable}\n")
            sys.stdout = sys.stderr = f
        except OSError:
            pass
    try:
        # 程式整個閃退（不是一般錯誤）時，把當時每個執行緒在做什麼寫進 crash.log，方便找原因
        import faulthandler
        global _CRASH_LOG
        _CRASH_LOG = open(os.path.join(log_dir(), "crash.log"), "a", encoding="utf-8")
        _CRASH_LOG.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} 啟動\n")
        _CRASH_LOG.flush()
        faulthandler.enable(file=_CRASH_LOG, all_threads=True)
    except Exception:
        pass
    if os.name == "nt":
        prefix = sys.prefix
        extra = [prefix, os.path.join(prefix, "Library", "mingw-w64", "bin"),
                 os.path.join(prefix, "Library", "usr", "bin"), os.path.join(prefix, "Library", "bin"),
                 os.path.join(prefix, "Scripts"), os.path.join(prefix, "bin")]
        extra = [p for p in extra if os.path.isdir(p)]
        os.environ["PATH"] = os.pathsep.join(extra + [os.environ.get("PATH", "")])
        for p in extra:
            try:
                os.add_dll_directory(p)
            except (OSError, AttributeError):
                pass
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:
            pass
    if TOOL_ROOT not in sys.path:
        sys.path.insert(0, TOOL_ROOT)


def fatal(msg):
    """連 Tk 都起不來時，用 Windows 原生訊息框。"""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, msg, APP_NAME, 0x10)
    except Exception:
        print(msg, file=sys.stderr)


class Splash:
    """啟動載入畫面。"""
    W, H = 560, 300

    def __init__(self, root):
        import tkinter as tk
        self.tk = tk
        self.win = win = tk.Toplevel(root)
        win.overrideredirect(True)
        try:
            win.attributes("-topmost", True)
        except Exception:
            pass
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        win.geometry(f"{self.W}x{self.H}+{(sw - self.W) // 2}+{(sh - self.H) // 2}")
        c = self.c = tk.Canvas(win, width=self.W, height=self.H, highlightthickness=0, bd=0, bg="#18223d")
        c.pack(fill="both", expand=True)
        # 背景：深藍 → 紫 的斜向色帶
        for i in range(0, self.W, 4):
            t = i / self.W
            r = int(0x18 + (0x2b - 0x18) * t)
            g = int(0x22 + (0x1d - 0x22) * t)
            b = int(0x3d + (0x5c - 0x3d) * t)
            c.create_rectangle(i, 0, i + 4, self.H, fill=f"#{r:02x}{g:02x}{b:02x}", width=0)
        self.img = None
        try:
            self.img = tk.PhotoImage(file=os.path.join(ASSETS, "icon_128.png"))
            c.create_image(110, 128, image=self.img)
        except Exception:
            c.create_text(110, 128, text="✦", fill="#5eead4", font=("Segoe UI", 60, "bold"))
        fam = self._font_family()
        c.create_text(205, 98, text=APP_NAME, anchor="w", fill="white", font=(fam, 24, "bold"))
        c.create_text(207, 136, text="PPMS · SQUID · Raman · Etching", anchor="w", fill="#9fb0d6", font=(fam, 11))
        try:
            from .. import __version__
        except Exception:
            __version__ = ""
        c.create_text(207, 162, text=f"版本 {__version__}", anchor="w", fill="#6f80a8", font=(fam, 9))
        self.msg = c.create_text(207, 214, text="啟動中…", anchor="w", fill="#cdd6ee", font=(fam, 10))
        c.create_rectangle(207, 236, 520, 240, fill="#2a3760", width=0)
        self.bar = c.create_rectangle(207, 236, 207, 240, fill="#5eead4", width=0)
        win.update()

    def _font_family(self):
        try:
            from tkinter import font as tkfont
            fams = set(tkfont.families())
            for f in ("Microsoft JhengHei UI", "Microsoft JhengHei", "PingFang TC", "Heiti TC", "Noto Sans CJK TC"):
                if f in fams:
                    return f
        except Exception:
            pass
        return "TkDefaultFont"

    def step(self, text, frac):
        self.c.itemconfigure(self.msg, text=text)
        self.c.coords(self.bar, 207, 236, 207 + int(313 * frac), 240)
        self.win.update()

    def close(self):
        try:
            self.win.destroy()
        except Exception:
            pass


def main(open_path=None, check_updates=True):
    setup_environment()
    try:
        import tkinter as tk
    except Exception as e:
        fatal(f"無法載入 tkinter：{e}\n\n請確認使用的是 Anaconda 的 Python。")
        return 1

    root = tk.Tk()
    root.withdraw()
    root.title(APP_NAME)
    try:
        if os.name == "nt":
            root.iconbitmap(default=os.path.join(ASSETS, "icon.ico"))
        root._magic_icon = tk.PhotoImage(file=os.path.join(ASSETS, "icon_256.png"))
        root.iconphoto(True, root._magic_icon)
    except Exception:
        pass
    splash = Splash(root)
    t0 = time.time()
    try:
        splash.step("載入數值計算（numpy、scipy）…", 0.15)
        import numpy  # noqa: F401
        import scipy.signal  # noqa: F401
        splash.step("載入繪圖（matplotlib）…", 0.40)
        import matplotlib
        matplotlib.use("TkAgg")
        from matplotlib.backends import backend_tkagg  # noqa: F401
        register_paths()                 # 套件都載入成功才記下這個 Python
        splash.step("載入分析功能…", 0.65)
        from .app import App, prepare
        prepare(root)
        splash.step("建立視窗…", 0.85)
        app = App(root, open_path, check_updates=check_updates)
        splash.step("完成", 1.0)
        # 載入畫面至少停留一下，避免一閃而過
        remain = 0.6 - (time.time() - t0)
        if remain > 0:
            time.sleep(remain)
    except Exception:
        tb = traceback.format_exc()
        print(tb, file=sys.stderr)
        splash.close()
        log = os.path.join(log_dir(), "error.log")
        try:
            with open(log, "a", encoding="utf-8") as f:
                f.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')}\n{tb}")
        except OSError:
            pass
        from tkinter import messagebox
        if messagebox.askyesno(APP_NAME, f"啟動失敗：\n\n{tb.strip().splitlines()[-1]}\n\n詳細記錄：{log}\n\n"
                                         "要把錯誤紀錄打包成 zip（放在桌面），方便傳給維護軟體的人嗎？", icon="error"):
            _offer_report(None)
        root.destroy()
        return 1
    splash.close()
    root.deiconify()
    root.lift()
    try:
        root.state("zoomed")            # Windows：最大化開啟
    except Exception:
        pass
    if sys.platform == "darwin":                       # macOS 沒有 zoomed：直接放到螢幕大小（扣掉選單列、Dock）
        try:
            sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
            root.geometry(f"{sw}x{max(sh - 110, 600)}+0+25")
        except Exception:
            pass
    root.focus_force()
    root.report_callback_exception = _report_callback(root)
    root.after(400, lambda: set_taskbar_relaunch(root))
    root.mainloop()
    return 0


def set_taskbar_relaunch(root):
    """讓工作列上「釘選」的圖示能直接啟動本軟體。

    Windows 預設會把 pythonw.exe（沒有參數）釘選上去，點了什麼都不會發生；
    這裡在視窗上寫入 AppUserModel 的 RelaunchCommand → 釘選後執行 MagicTool.pyw。"""
    if os.name != "nt":
        return False
    try:
        import ctypes
        import uuid
        from ctypes import wintypes
        from ..install import pythonw_path  # noqa

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort), ("Data3", ctypes.c_ushort),
                        ("Data4", ctypes.c_ubyte * 8)]

        def guid(text):
            u = uuid.UUID(text)
            g = GUID(u.time_low, u.time_mid, u.time_hi_version)
            for i, b in enumerate(u.bytes[8:]):
                g.Data4[i] = b
            return g

        class PROPERTYKEY(ctypes.Structure):
            _fields_ = [("fmtid", GUID), ("pid", ctypes.c_ulong)]

        class PROPVARIANT(ctypes.Structure):
            _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort),
                        ("r3", ctypes.c_ushort), ("pwszVal", ctypes.c_wchar_p), ("pad", ctypes.c_void_p)]

        hwnd = int(root.wm_frame(), 16) or ctypes.windll.user32.GetParent(root.winfo_id())
        store = ctypes.c_void_p()
        iid = guid("886d8eeb-8cf2-4446-8d02-cdba1dbdcf99")              # IID_IPropertyStore
        hr = ctypes.windll.shell32.SHGetPropertyStoreForWindow(wintypes.HWND(hwnd), ctypes.byref(iid),
                                                               ctypes.byref(store))
        if hr != 0 or not store:
            return False
        vtbl = ctypes.cast(store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        set_value = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(PROPERTYKEY),
                                       ctypes.POINTER(PROPVARIANT))(vtbl[6])
        commit = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(vtbl[7])
        release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[2])
        fmt = guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3")              # PKEY_AppUserModel_*
        pyw = os.path.join(TOOL_ROOT, "MagicTool.pyw")
        values = [(2, f'"{pythonw_path()}" "{pyw}"'),                    # RelaunchCommand
                  (4, APP_NAME),                                          # RelaunchDisplayNameResource
                  (3, os.path.join(ASSETS, "icon.ico")),                  # RelaunchIconResource
                  (5, APP_ID)]                                            # ID
        keep = []
        for pid, text in values:
            key, var = PROPERTYKEY(fmt, pid), PROPVARIANT()
            var.vt = 31                                                   # VT_LPWSTR
            var.pwszVal = text
            keep.append((key, var))
            set_value(store, ctypes.byref(key), ctypes.byref(var))
        commit(store)
        release(store)
        return True
    except Exception as e:
        print(f"設定工作列釘選失敗：{e}", file=sys.stderr)
        return False


def _offer_report(parent):
    from tkinter import messagebox
    try:
        from ..core.report import make_report, open_folder
        fp = make_report()
        messagebox.showinfo(APP_NAME, f"已存好：\n{fp}\n\n把這個 zip 傳給維護軟體的人就可以了。", parent=parent)
        open_folder(fp.parent)
    except Exception as e:
        messagebox.showerror(APP_NAME, f"打包失敗：{e}", parent=parent)


def _report_callback(root):
    """介面操作中發生未預期錯誤時：寫 log + 跳出提示，不會整個關掉。"""
    def handler(exc, val, tb):
        text = "".join(traceback.format_exception(exc, val, tb))
        print(text, file=sys.stderr)
        log = os.path.join(log_dir(), "error.log")
        try:
            with open(log, "a", encoding="utf-8") as f:
                f.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')}\n{text}")
        except OSError:
            pass
        try:
            from tkinter import messagebox
            if messagebox.askyesno(APP_NAME, f"發生錯誤：{val}\n\n詳細記錄：{log}\n\n"
                                             "要把錯誤紀錄打包成 zip（放在桌面），方便傳給維護軟體的人嗎？"
                                             "（也可以之後在 ⚙ 設定 → 更新 打包）", icon="error", parent=root):
                _offer_report(root)
        except Exception:
            pass
    return handler


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
