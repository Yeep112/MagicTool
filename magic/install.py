"""（取自 LowTempAnalysis 的 install.py）安裝成「軟體」：在開始功能表與桌面建立捷徑。

捷徑內容：
  目標      <Anaconda>\\pythonw.exe -m magic app   （pythonw = 不會出現黑色命令列視窗）
  起始位置  這個工具的資料夾
  圖示      assets\\icon.ico
  AppID     Yeep.MagicTool                        （工作列圖示與釘選才會正確）

    python -m magic install       安裝（開始功能表 + 桌面）
    python -m magic uninstall     移除捷徑（不會刪除任何資料或程式）

不會修改登錄檔、不需要系統管理員權限；程式仍然是資料夾裡的 Python 原始檔，改了就生效。
"""
from __future__ import annotations

import os
import subprocess
import sys

from .gui.launcher import APP_ID, APP_NAME, TOOL_ROOT

ICON = os.path.join(TOOL_ROOT, "assets", "icon.ico")
DESCRIPTION = "Magic Tool 實驗分析（PPMS、SQUID、Raman、Etching）"


def pythonw_path():
    exe = sys.executable
    cand = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return cand if os.path.exists(cand) else exe


def shortcut_paths():
    appdata = os.environ.get("APPDATA", "")
    start = os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs", APP_NAME + ".lnk")
    desktop = os.path.join(_desktop_dir(), APP_NAME + ".lnk")
    return {"開始功能表": start, "桌面": desktop}


def _desktop_dir():
    try:
        from win32com.shell import shell, shellcon
        return shell.SHGetFolderPath(0, shellcon.CSIDL_DESKTOPDIRECTORY, None, 0)
    except Exception:
        pass
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "[Environment]::GetFolderPath('Desktop')"],
                             capture_output=True, text=True, timeout=20)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), "Desktop")


def _make_with_pywin32(path, target, args):
    """pywin32（Anaconda 內建）：可以寫入 AppUserModelID。"""
    import pythoncom
    from win32com.shell import shell
    from win32com.propsys import propsys, pscon
    link = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER,
                                      shell.IID_IShellLink)
    link.SetPath(target)
    link.SetArguments(args)
    link.SetWorkingDirectory(TOOL_ROOT)
    link.SetIconLocation(ICON, 0)
    link.SetDescription(DESCRIPTION)
    try:
        store = link.QueryInterface(propsys.IID_IPropertyStore)
        try:
            value = propsys.PROPVARIANTType(APP_ID, pythoncom.VT_LPWSTR)
        except Exception:
            value = propsys.PROPVARIANTType(APP_ID)
        store.SetValue(pscon.PKEY_AppUserModel_ID, value)
        store.Commit()
        appid_ok = True
    except Exception:
        appid_ok = False                     # 沒有 AppID 也能用，只是釘選時可能出現兩個圖示
    link.QueryInterface(pythoncom.IID_IPersistFile).Save(path, 0)
    return appid_ok


def _make_with_powershell(path, target, args):
    """沒有 pywin32 時的備案（沒有 AppID，釘選到工作列時可能顯示成兩個圖示）。"""
    def q(s):
        return "'" + s.replace("'", "''") + "'"
    ps = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut(" + q(path) + "); "
          f"$s.TargetPath = {q(target)}; $s.Arguments = {q(args)}; "
          f"$s.WorkingDirectory = {q(TOOL_ROOT)}; $s.IconLocation = {q(ICON + ',0')}; "
          f"$s.Description = {q(DESCRIPTION)}; $s.Save()")
    out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                         capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "PowerShell 失敗")


def install(where=("開始功能表", "桌面"), log=print):
    if os.name != "nt":
        raise SystemExit("安裝捷徑只支援 Windows")
    from .gui.launcher import register_paths
    register_paths()
    target, args = pythonw_path(), "-m magic app"
    log(f"程式資料夾：{TOOL_ROOT}")
    log(f"Python：{target}")
    ok = []
    for label, path in shortcut_paths().items():
        if label not in where:
            continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            try:
                how = "" if _make_with_pywin32(path, target, args) else "（未設定 AppID）"
            except ImportError:
                _make_with_powershell(path, target, args)
                how = "（沒有 pywin32，未設定 AppID）"
            log(f"  ✓ {label}：{path} {how}")
            ok.append(path)
        except Exception as e:
            log(f"  ✗ {label}：{e}")
    if ok:
        log("")
        log(f"完成！之後可以從「開始」搜尋「{APP_NAME}」或雙擊桌面圖示開啟，")
        log("開啟後在工作列的圖示上按右鍵 →「釘選到工作列」。")
        log("程式資料夾請不要搬走；要搬的話，搬完重新執行一次安裝即可。")
    return ok


def uninstall(log=print):
    removed = 0
    for label, path in shortcut_paths().items():
        if os.path.exists(path):
            os.remove(path)
            log(f"  已移除 {label}：{path}")
            removed += 1
    if not removed:
        log("沒有找到已安裝的捷徑")
    log("（程式與資料都沒有刪除）")
