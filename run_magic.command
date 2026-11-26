#!/bin/bash
# ============================================================
#  Magic Tool for macOS (and Linux) — same as run_magic.bat on Windows.
#  Double-click in Finder, or run in Terminal:
#
#    ./run_magic.command                 open the program
#    ./run_magic.command some.dat        open the program with that file or folder
#    ./run_magic.command install         make "Magic Tool.app" (Applications + Desktop)
#    ./run_magic.command selftest        run the self test (synthetic data only)
#    ./run_magic.command diag            show diagnostics
#    ./run_magic.command debug           open the program here and show every message (when it won't start)
#    ./run_magic.command update          check GitHub for a new version
#    ./run_magic.command publish         developer: upload this version to GitHub
#
#  If double-click says "cannot be opened": open Terminal, type  bash  and a space,
#  drag this file into the Terminal window, press Enter.
# ============================================================
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ "$(uname)" = "Darwin" ]; then
    MT_DATA="${MAGIC_DATA:-$HOME/Library/Application Support/MagicTool}"
else
    MT_DATA="${MAGIC_DATA:-$HOME/.magictool}"
fi

# ---- tool folder: next to this file, otherwise the remembered one ----
TOOL=""
if [ -f "$HERE/magic/__main__.py" ]; then
    TOOL="$HERE"
elif [ -f "$MT_DATA/tool_path.txt" ]; then
    TOOL="$(head -n 1 "$MT_DATA/tool_path.txt" | tr -d '\r')"
    [ -f "$TOOL/magic/__main__.py" ] || TOOL=""
fi
if [ -z "$TOOL" ]; then
    echo
    echo "  [錯誤] 找不到 Magic Tool 資料夾。"
    echo "  請先把整個資料夾解壓縮，再從那個資料夾裡執行一次這個檔案。"
    echo
    read -r -p "  按 Enter 關閉…" _
    exit 1
fi
cd "$TOOL" || exit 1

pause() { echo; read -r -p "  按 Enter 關閉…" _; }

# shellcheck source=magic_env.sh
if ! source "$TOOL/magic_env.sh"; then
    pause
    exit 1
fi

close_terminal_window() {
    # 雙擊開啟時 Terminal 會留一個「程序已完成」的視窗：程式啟動後把它關掉
    [ "$(uname)" = "Darwin" ] || return 0
    [ -t 1 ] || return 0
    ( sleep 1; osascript -e 'tell application "Terminal" to close (every window whose name contains "run_magic")' \
        >/dev/null 2>&1 ) &
}

case "${1:-gui}" in
    gui|app)
        nohup "$PYW" -m magic app >/dev/null 2>&1 &
        close_terminal_window
        ;;
    selftest) "$PYEXE" -m magic selftest "${@:2}"; pause ;;
    install) "$PYEXE" -m magic install; pause ;;
    uninstall) "$PYEXE" -m magic uninstall; pause ;;
    update) "$PYEXE" -m magic update; pause ;;
    diag) "$PYEXE" -m magic diag; pause ;;
    debug)
        echo "  用 $PYEXE 開啟程式（所有訊息都顯示在這裡；關掉程式後這裡會顯示結束碼）"
        echo
        MAGIC_LAUNCHER=debug "$PYEXE" -X faulthandler -m magic app
        echo; echo "  結束碼：$?"
        tail -n 30 "$MT_DATA/logs/error.log" 2>/dev/null
        pause ;;
    publish) "$PYEXE" -m magic publish; pause ;;
    *)
        nohup "$PYW" -m magic app "$1" >/dev/null 2>&1 &
        close_terminal_window
        ;;
esac
exit 0
