#!/bin/bash
# ============================================================
#  macOS one-time setup: makes "Magic Tool.app" in Applications (~/Applications)
#  and on the Desktop. Afterwards open it from Launchpad / Spotlight / the Desktop.
#
#  If double-click says "cannot be opened": open Terminal, type  bash  and a space,
#  drag this file into the Terminal window, press Enter.
# ============================================================
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ ! -f "$HERE/magic/__main__.py" ]; then
    echo
    echo "  [錯誤] 找不到 Magic Tool 資料夾。請先把整個資料夾解壓縮，再從資料夾裡執行這個檔案。"
    echo
    read -r -p "  按 Enter 關閉…" _
    exit 1
fi
# 從網路下載的檔案會被 macOS 標記「隔離」，雙擊時被擋下；這裡一次解除，並讓其他啟動檔可以執行
if [ "$(uname)" = "Darwin" ]; then
    xattr -dr com.apple.quarantine "$HERE" 2>/dev/null
fi
chmod +x "$HERE"/*.command "$HERE"/*.sh 2>/dev/null
exec bash "$HERE/run_magic.command" install
