#!/bin/bash
# ============================================================
#  macOS / Linux: find a Python that has numpy, scipy, pandas, matplotlib
#  and tkinter (Tk 8.6+). Sourced by run_magic.command. Sets PYEXE and PYW.
#  Same idea as magic_env.bat on Windows. Returns 1 if nothing works.
# ============================================================

if [ "$(uname)" = "Darwin" ]; then
    MT_DATA="${MAGIC_DATA:-$HOME/Library/Application Support/MagicTool}"
else
    MT_DATA="${MAGIC_DATA:-$HOME/.magictool}"
fi
mkdir -p "$MT_DATA" 2>/dev/null
MT_LOG="$MT_DATA/launcher.log"
echo "[$(date)] searching for python" > "$MT_LOG"
PYEXE=""
PYW=""
NEEDPKG=""

_mt_check='
import sys
assert sys.version_info >= (3, 9), "Python 太舊"
import tkinter
v = tkinter.Tcl().eval("info patchlevel")
assert tuple(int(x) for x in v.split(".")[:2]) >= (8, 6), "Tk " + v + " 太舊"
import numpy, scipy, pandas, matplotlib
print(sys.executable)
'
_mt_tk_only='
import sys
assert sys.version_info >= (3, 9)
import tkinter
v = tkinter.Tcl().eval("info patchlevel")
assert tuple(int(x) for x in v.split(".")[:2]) >= (8, 6)
print(sys.executable)
'

_mt_try() {
    local py="$1"
    [ -n "$PYEXE" ] && return 0
    [ -x "$py" ] || return 1
    local out
    out="$("$py" -c "$_mt_check" 2>>"$MT_LOG")"
    if [ $? -eq 0 ] && [ -n "$out" ]; then
        PYEXE="$py"
        echo "OK: $py" >> "$MT_LOG"
        return 0
    fi
    echo "no: $py" >> "$MT_LOG"
    if [ -z "$NEEDPKG" ] && "$py" -c "$_mt_tk_only" >/dev/null 2>&1; then
        NEEDPKG="$py"            # has tkinter but is missing numpy / scipy / ...
    fi
    return 1
}

# ---- 1) the Python that worked last time ----
if [ -f "$MT_DATA/python_path.txt" ]; then
    _mt_try "$(head -n 1 "$MT_DATA/python_path.txt" | tr -d '\r')"
fi

# ---- 2) active conda, 3) common Anaconda / Miniconda / python.org locations ----
[ -n "$CONDA_PREFIX" ] && _mt_try "$CONDA_PREFIX/bin/python"
if [ -n "$CONDA_EXE" ]; then
    _mt_try "$(dirname "$(dirname "$CONDA_EXE")")/bin/python"
fi
for d in "$HOME/anaconda3" "$HOME/miniconda3" "$HOME/miniforge3" "$HOME/mambaforge" \
         "$HOME/opt/anaconda3" "$HOME/opt/miniconda3" "/opt/anaconda3" "/opt/miniconda3" "/opt/miniforge3" \
         "/opt/homebrew/anaconda3" "/opt/homebrew/Caskroom/miniconda/base" "/opt/homebrew/Caskroom/miniforge/base" \
         "/usr/local/anaconda3" "/usr/local/miniconda3" "/usr/local/Caskroom/miniconda/base"; do
    _mt_try "$d/bin/python"
done
for py in /Library/Frameworks/Python.framework/Versions/3.*/bin/python3; do
    _mt_try "$py"
done

# ---- 4) PATH, Homebrew; Apple's /usr/bin/python3 last (its Tk is usually too old) ----
for name in python3 python; do
    p="$(command -v "$name" 2>/dev/null)"
    [ -n "$p" ] && _mt_try "$p"
done
_mt_try /opt/homebrew/bin/python3
_mt_try /usr/local/bin/python3
_mt_try /usr/bin/python3

if [ -z "$PYEXE" ] && [ -n "$NEEDPKG" ]; then
    echo
    echo "  找到 Python（$NEEDPKG），但缺少 numpy / scipy / pandas / matplotlib。"
    printf "  要現在自動安裝嗎？（約 1–3 分鐘）[y/N] "
    read -r ans
    if [ "$ans" = "y" ] || [ "$ans" = "Y" ]; then
        "$NEEDPKG" -m pip install --user numpy scipy pandas matplotlib openpyxl pillow \
            || "$NEEDPKG" -m pip install numpy scipy pandas matplotlib openpyxl pillow
        _mt_try "$NEEDPKG"
    fi
fi

if [ -z "$PYEXE" ]; then
    echo
    echo "  [錯誤] 找不到可以用的 Python（需要 numpy、scipy、pandas、matplotlib 和 tkinter）。"
    echo "  建議安裝 Anaconda（免費，已經包含全部套件）：https://www.anaconda.com/download"
    echo "  裝好之後再雙擊一次這個檔案。詳細紀錄：$MT_LOG"
    echo
    return 1 2>/dev/null || exit 1
fi

# GUI 用 pythonw（Anaconda / python.org 的 macOS 版：視窗才拿得到焦點、Dock 顯示正常）
PYW="$PYEXE"
if [ -x "$(dirname "$PYEXE")/pythonw" ]; then
    PYW="$(dirname "$PYEXE")/pythonw"
fi
printf '%s\n' "$PYEXE" > "$MT_DATA/python_path.txt"
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
return 0 2>/dev/null || true
