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


LAUNCHER_MARK = "magic-launcher v3"


def refresh_mac_app():
    """macOS：已經裝好的 Magic Tool.app 是舊版的啟動腳本 → 換成新版（程式更新後自動做，不用重新 install）。"""
    if sys.platform != "darwin":
        return False
    app = mac_paths()["應用程式"]
    exe = os.path.join(app, "Contents", "MacOS", "MagicTool")
    try:
        text = open(exe, encoding="utf-8").read()
    except OSError:
        return False
    if LAUNCHER_MARK in text and TOOL_ROOT in text:
        return False
    import re
    m = re.search(r"^PY=(.+)$", text, flags=re.M)
    py = m.group(1).strip().strip("'\"") if m else sys.executable
    if not os.path.exists(py):
        py = sys.executable
    make_mac_app(app, python=py)
    return True


def mac_launcher_script(tool, python):
    """App 裡真正執行的腳本。

    ‧ 程式的輸出、錯誤都寫進 ~/Library/Application Support/MagicTool/logs/app_launch.log
    ‧ 先用 pythonw（Anaconda 的 GUI 版 Python）開；如果一開就失敗，自動改用 python 再試一次
    ‧ 還是失敗 → 跳出視窗顯示錯誤的最後幾行，可以直接打開紀錄檔（不會再「閃一下就不見」）
    ‧ 程式資料夾、Python 找不到或沒有權限讀取時，也會跳出說明
    """
    import shlex
    return f"""#!/bin/bash
# {LAUNCHER_MARK}
# Magic Tool 啟動（由 install 產生；程式資料夾搬家後，重新執行一次 install.command 即可）
TOOL={shlex.quote(tool)}
PY={shlex.quote(python)}
DATA="$HOME/Library/Application Support/MagicTool"
LOGD="$DATA/logs"
mkdir -p "$LOGD" 2>/dev/null
LOG="$LOGD/app_launch.log"
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

alert() {{
    # $1 = 訊息；有 osascript（macOS）就跳視窗，按「打開紀錄」用文字編輯打開 log
    # （MAGIC_NO_ALERT=1：自我測試用，只印出訊息、不跳視窗，避免沒人按而卡住）
    if [ -z "$MAGIC_NO_ALERT" ] && command -v osascript >/dev/null 2>&1; then
        local btn
        btn=$(osascript - "$1" <<'OSA' 2>/dev/null
on run argv
    activate
    set r to display alert "Magic Tool" message (item 1 of argv) as critical buttons {{"打開紀錄", "好"}} default button "好"
    return button returned of r
end run
OSA
)
        if [ "$btn" = "打開紀錄" ]; then open -e "$LOG" 2>/dev/null || open "$LOGD"; fi
    else
        echo "ALERT: $1" >&2
    fi
}}

touch "$LOG" 2>/dev/null
LOG0=$(wc -l < "$LOG" 2>/dev/null || echo 0)      # 這一次啟動從第幾行開始（錯誤視窗只顯示這一次的訊息）
{{ echo; echo "===== $(date '+%Y-%m-%d %H:%M:%S') 啟動"; echo "TOOL=$TOOL"; echo "PY=$PY"; sw_vers 2>/dev/null; uname -m; }} >> "$LOG" 2>&1

if [ ! -f "$TOOL/magic/__main__.py" ] && [ -f "$DATA/tool_path.txt" ]; then TOOL="$(head -n 1 "$DATA/tool_path.txt")"; fi
if [ ! -x "$PY" ] && [ -f "$DATA/python_path.txt" ]; then PY="$(head -n 1 "$DATA/python_path.txt")"; fi
if [ ! -d "$TOOL" ]; then
    alert "找不到程式資料夾：$TOOL

資料夾搬家或改名了嗎？或是 macOS 不讓 App 讀這個位置（文件 / 桌面 / 下載項目）？
請到 Magic Tool 資料夾，用終端機再執行一次 install.command。"
    exit 1
fi
if ! cd "$TOOL" 2>>"$LOG" || ! head -c 1 "$TOOL/magic/__main__.py" >/dev/null 2>>"$LOG" \\
   || ! ls "$TOOL/magic" >/dev/null 2>>"$LOG"; then
    alert "沒有權限讀取程式資料夾：$TOOL

macOS 不讓這個 App 讀「文件 / 桌面 / 下載項目」裡的檔案。請到：
系統偏好設定 → 安全性與隱私 → 隱私權 → 檔案與檔案夾（或「完整磁碟取用權」），允許 Magic Tool；
或把 MagicTool 資料夾搬到家目錄（例如 ~/MagicTool），再執行一次 install.command。"
    exit 1
fi
if [ ! -x "$PY" ]; then
    alert "找不到 Python：$PY

請在 Magic Tool 資料夾再執行一次 install.command（需要 Anaconda）。"
    exit 1
fi

# Finder 舊版會多傳一個 -psn_… 參數：拿掉
ARGS=()
for a in "$@"; do case "$a" in -psn_*) ;; *) ARGS+=("$a") ;; esac; done

export PYTHONUTF8=1 PYTHONIOENCODING=utf-8 MAGIC_LAUNCHER=macapp
export PYTHONPATH="$TOOL${{PYTHONPATH:+:$PYTHONPATH}}"
run() {{
    echo "--- $1 -m magic app" >> "$LOG"
    "$1" -m magic app "${{ARGS[@]}}" >> "$LOG" 2>&1
}}
start=$(date +%s)
code=0
PYW="$(dirname "$PY")/pythonw"
if [ -x "$PYW" ] && [ "$PYW" != "$PY" ]; then
    run "$PYW"; code=$?
    # 一開就失敗（不是使用者強制結束）→ 改用 python 再試一次
    if [ $code -ne 0 ] && [ $code -ne 130 ] && [ $code -ne 137 ] && [ $code -ne 143 ] \\
       && [ $(( $(date +%s) - start )) -lt 30 ]; then
        echo "pythonw 結束碼 $code，改用 python 再試一次" >> "$LOG"
        run "$PY"; code=$?
    fi
else
    run "$PY"; code=$?
fi
echo "結束碼 $code" >> "$LOG"
if [ $code -ne 0 ] && [ $code -ne 130 ] && [ $code -ne 137 ] && [ $code -ne 143 ]; then
    last=$(tail -n +$((LOG0 + 1)) "$LOG" | grep -v '^[[:space:]]*$' | grep -v -E '^(=====|TOOL=|PY=|ProductName|ProductVersion|BuildVersion|x86_64$|arm64$)' | tail -n 12)
    hint=""
    if grep -q "No module named magic" <(tail -n +$((LOG0 + 1)) "$LOG"); then
        hint="

看起來是 macOS 不讓 App 讀程式資料夾（放在「文件 / 桌面 / 下載項目」時會這樣）。
請到程式資料夾，用終端機再執行一次 install.command：新版會把程式複製到不受限制的位置。"
    fi
    alert "Magic Tool 沒有正常開啟（結束碼 $code）。$hint

最後的訊息：
$last

完整紀錄：$LOG
可以按「打開紀錄」，或到 Magic Tool 資料夾執行 bash run_magic.command debug 看詳細原因。"
fi
exit $code
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
            "LSUIElement": True,          # 這個殼本身不佔 Dock；真正的視窗（Python）會有自己的 Dock 圖示
            "CFBundleGetInfoString": DESCRIPTION}
    with open(os.path.join(app_path, "Contents", "Info.plist"), "wb") as f:
        plistlib.dump(info, f)
    return app_path


MAC_PROTECTED = ("Documents", "Desktop", "Downloads", os.path.join("Library", "Mobile Documents"))
COPY_IGNORE = (".git", "__pycache__", "*.pyc", "_backup", "_update_tmp", ".pytest_cache", "MagicTool 輸出", ".DS_Store")


def mac_protected(path):
    """在「文件 / 桌面 / 下載項目 / iCloud」裡？（macOS 不讓從 Finder 開的 App 讀這些地方，除非另外允許）"""
    home = os.path.realpath(os.path.expanduser("~"))
    p = os.path.realpath(path)
    return any(p == os.path.join(home, d) or p.startswith(os.path.join(home, d) + os.sep) for d in MAC_PROTECTED)


def mac_program_dir():
    from .core.settings import data_dir
    return os.path.join(str(data_dir()), "program")


def copy_program(src, dst, log=print):
    """把程式複製到 dst（先複製到暫存、成功後才換掉舊的，失敗時舊的還在）。"""
    import shutil
    src, dst = os.path.realpath(src), os.path.abspath(dst)
    if src == os.path.realpath(dst):
        return dst
    tmp, old = dst + ".new", dst + ".old"
    for p in (tmp, old):
        if os.path.exists(p):
            shutil.rmtree(p, ignore_errors=True)
    shutil.copytree(src, tmp, ignore=shutil.ignore_patterns(*COPY_IGNORE), symlinks=True)
    if os.path.exists(dst):
        os.rename(dst, old)
    os.rename(tmp, dst)
    shutil.rmtree(old, ignore_errors=True)
    from .updater import make_executable
    make_executable(dst)
    return dst


def install_mac(where=("應用程式", "桌面"), log=print):
    from .gui.launcher import register_paths
    register_paths()
    paths = mac_paths()
    log(f"程式資料夾：{TOOL_ROOT}")
    log(f"Python：{sys.executable}")
    tool = TOOL_ROOT
    if mac_protected(TOOL_ROOT):
        # macOS 不讓 App 讀「文件 / 桌面 / 下載項目」：把程式複製到 ~/Library/Application Support/MagicTool/program
        prog = mac_program_dir()
        log("程式放在「文件 / 桌面 / 下載項目」裡，macOS 不讓 App 直接讀這些地方；")
        log(f"把程式複製到：{prog}")
        try:
            tool = copy_program(TOOL_ROOT, prog, log)
            from .core.settings import data_dir
            with open(os.path.join(str(data_dir()), "tool_path.txt"), "w", encoding="utf-8") as f:
                f.write(tool + "\n")
            log("  ✓ 複製完成（之後 App 用這一份；軟體內的「檢查更新」也會更新這一份）")
        except Exception as e:
            log(f"  ✗ 複製失敗：{e}（改用原本的資料夾）")
            tool = TOOL_ROOT
    ok = []
    app = paths["應用程式"]
    try:
        os.makedirs(os.path.dirname(app), exist_ok=True)
        make_mac_app(app, tool=tool)
        log(f"  ✓ 應用程式：{app}")
        ok.append(app)
    except Exception as e:
        log(f"  ✗ 應用程式：{e}")
        return ok
    if "桌面" in where and os.path.isdir(os.path.dirname(paths["桌面"])):
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
    if tool != TOOL_ROOT:
        log(f"App 用的是複製過去的那一份（{tool}）；下載的資料夾之後可以刪掉或搬走。")
    else:
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
