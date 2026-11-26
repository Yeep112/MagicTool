"""（取自 LowTempAnalysis 的 install.py）安裝成「軟體」：

Windows：在開始功能表與桌面建立捷徑。
macOS  ：在「應用程式」（~/Applications）建立「Magic Tool.app」，桌面放一個連結；
         之後從 Launchpad、Spotlight 或桌面開，不會出現終端機視窗。

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
    """開視窗用的 Python：Windows 的 pythonw.exe（沒有黑色視窗）、macOS 的 pythonw（視窗拿得到焦點）。"""
    exe = sys.executable
    name = "pythonw.exe" if os.name == "nt" else "pythonw"
    cand = os.path.join(os.path.dirname(exe), name)
    return cand if os.path.exists(cand) else exe


# ---------------------------------------------------------------------------
# macOS：Magic Tool.app
# ---------------------------------------------------------------------------
MAC_APP_NAME = "Magic Tool.app"
MAC_BUNDLE_ID = "tw.yeep.magictool"
MAC_ICON = os.path.join(TOOL_ROOT, "assets", "icon.icns")


def mac_paths():
    home = os.path.expanduser("~")
    return {"應用程式": os.path.join(home, "Applications", MAC_APP_NAME),
            "桌面": os.path.join(home, "Desktop", MAC_APP_NAME)}


def mac_launcher_script(tool, python):
    """App 裡真正執行的腳本：用記下的 Python 開程式；資料夾搬走時會跳出提示。"""
    import shlex
    return f"""#!/bin/bash
# Magic Tool 啟動（由 install 產生；程式資料夾搬家後，重新執行一次 install.command 即可）
TOOL={shlex.quote(tool)}
PY={shlex.quote(python)}
DATA="$HOME/Library/Application Support/MagicTool"
if [ ! -f "$TOOL/magic/__main__.py" ] && [ -f "$DATA/tool_path.txt" ]; then TOOL="$(head -n 1 "$DATA/tool_path.txt")"; fi
if [ ! -x "$PY" ] && [ -f "$DATA/python_path.txt" ]; then PY="$(head -n 1 "$DATA/python_path.txt")"; fi
if [ ! -f "$TOOL/magic/__main__.py" ] || [ ! -x "$PY" ]; then
    osascript -e 'display alert "Magic Tool" message "找不到程式資料夾或 Python。請到 Magic Tool 資料夾，再執行一次 install.command。"'
    exit 1
fi
PYW="$(dirname "$PY")/pythonw"
[ -x "$PYW" ] || PYW="$PY"
cd "$TOOL" || exit 1
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8
exec "$PYW" -m magic app "$@"
"""


def make_mac_app(app_path, tool=TOOL_ROOT, python=None):
    """建立 .app（只是一個資料夾：Info.plist + 啟動腳本 + 圖示）。回傳 app 路徑。"""
    import plistlib
    import shutil
    python = python or sys.executable
    if os.path.islink(app_path) or os.path.isfile(app_path):
        os.remove(app_path)
    elif os.path.isdir(app_path):
        shutil.rmtree(app_path)
    macos = os.path.join(app_path, "Contents", "MacOS")
    res = os.path.join(app_path, "Contents", "Resources")
    os.makedirs(macos)
    os.makedirs(res)
    exe = os.path.join(macos, "MagicTool")
    with open(exe, "w", encoding="utf-8", newline="\n") as f:
        f.write(mac_launcher_script(tool, python))
    os.chmod(exe, 0o755)
    if os.path.exists(MAC_ICON):
        shutil.copy2(MAC_ICON, os.path.join(res, "icon.icns"))
    from . import __version__
    info = {"CFBundleName": "Magic Tool", "CFBundleDisplayName": "Magic Tool", "CFBundleIdentifier": MAC_BUNDLE_ID,
            "CFBundleExecutable": "MagicTool", "CFBundleIconFile": "icon", "CFBundlePackageType": "APPL",
            "CFBundleShortVersionString": __version__, "CFBundleVersion": __version__,
            "LSMinimumSystemVersion": "10.13", "NSHighResolutionCapable": True,
            "CFBundleGetInfoString": DESCRIPTION}
    with open(os.path.join(app_path, "Contents", "Info.plist"), "wb") as f:
        plistlib.dump(info, f)
    return app_path


def install_mac(where=("應用程式", "桌面"), log=print):
    from .gui.launcher import register_paths
    register_paths()
    paths = mac_paths()
    log(f"程式資料夾：{TOOL_ROOT}")
    log(f"Python：{sys.executable}")
    ok = []
    app = paths["應用程式"]
    try:
        os.makedirs(os.path.dirname(app), exist_ok=True)
        make_mac_app(app)
        log(f"  ✓ 應用程式：{app}")
        ok.append(app)
    except Exception as e:
        log(f"  ✗ 應用程式：{e}")
        return ok
    if "桌面" in where:
        desk = paths["桌面"]
        try:
            if os.path.lexists(desk):
                if os.path.islink(desk):
                    os.remove(desk)
                else:
                    import shutil
                    shutil.rmtree(desk)
            os.symlink(app, desk)
            log(f"  ✓ 桌面：{desk}")
            ok.append(desk)
        except Exception as e:
            log(f"  ✗ 桌面：{e}")
    if sys.platform == "darwin":
        subprocess.run(["touch", app], check=False)            # 讓 Finder 重新讀圖示
    log("")
    log("完成！之後可以從 Launchpad、Spotlight（搜尋 Magic Tool）或桌面開啟。")
    log("開啟後在 Dock 的圖示上按右鍵 →「選項」→「保留在 Dock」。")
    log("程式資料夾請不要搬走；要搬的話，搬完重新執行一次 install.command 即可。")
    return ok


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
    if sys.platform == "darwin":
        return install_mac(log=log)
    if os.name != "nt":
        raise SystemExit("安裝捷徑只支援 Windows 和 macOS（Linux 請用 ./run_magic.command 開啟）")
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
    paths = mac_paths() if sys.platform == "darwin" else shortcut_paths()
    for label, path in paths.items():
        if os.path.islink(path) or os.path.isfile(path):
            os.remove(path)
            log(f"  已移除 {label}：{path}")
            removed += 1
        elif os.path.isdir(path) and path.endswith(".app"):
            import shutil
            shutil.rmtree(path)
            log(f"  已移除 {label}：{path}")
            removed += 1
    if not removed:
        log("沒有找到已安裝的捷徑")
    log("（程式與資料都沒有刪除）")
