"""命令列入口。通常從 run_magic.bat 呼叫，也可以直接打：

  python -m magic app [檔案或資料夾]   開啟軟體（載入畫面 → 主視窗）
  python -m magic install / uninstall  建立 / 移除 開始功能表與桌面捷徑
  python -m magic selftest [--no-gui]  自我測試（合成資料，不會碰到真實資料）
  python -m magic selftest --release   發佈前檢查：一定要實際開視窗、量切換 / 計算 / 動畫的流暢度
  python -m magic publish              開發者：一鍵發佈到 GitHub
  python -m magic receive              開發者：收 Claude 推到 pending 的更新 → 測試 → 發佈
  python -m magic update               檢查並安裝新版
  python -m magic demo [資料夾]        產生範例資料（合成資料）
  python -m magic strip-notebooks      清掉 notebooks\\ 的輸出
  python -m magic list                 列出所有分析功能
  python -m magic diag                 顯示診斷資訊
"""
from __future__ import annotations

import sys

# 軟體模式：先出現載入畫面，再載入其他東西
if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] in ("app", "gui"):
    from .gui.launcher import main as _launch
    sys.exit(_launch(sys.argv[2].strip('"') if len(sys.argv) > 2 else None))


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "app"
    rest = argv[1:]
    if cmd in ("app", "gui"):
        from .gui.launcher import main as launch
        return launch(rest[0] if rest else None)
    if cmd == "selftest":
        from .selftest import main as st
        return 0 if st(gui="--no-gui" not in rest, require_gui="--release" in rest) else 1
    if cmd == "publish":
        from .updater import publish
        return 0 if publish() else 1
    if cmd == "receive":
        from .updater import receive
        return 0 if receive() else 1
    if cmd == "update":
        from . import updater
        info = updater.check()
        print(f"目前 v{info['current']}，GitHub 上 v{info.get('latest')}")
        if info.get("newer"):
            if input("要更新嗎？(y/N)：").strip().lower().startswith("y"):
                updater.apply_update(info)
        else:
            print("已經是最新版")
        return 0
    if cmd == "install":
        from .install import install
        install()
        return 0
    if cmd == "uninstall":
        from .install import uninstall
        uninstall()
        return 0
    if cmd == "demo":
        import os
        from .core.settings import data_dir
        from .testdata import write_all
        folder = rest[0] if rest else os.path.join(str(data_dir()), "demo")
        for k, v in write_all(folder).items():
            print(f"{k:13s} {v}")
        return 0
    if cmd == "strip-notebooks":
        import os
        from .core.settings import TOOL_ROOT
        from .tools_nb import strip_folder
        done = strip_folder(os.path.join(str(TOOL_ROOT), "notebooks"))
        print("已清除：" + ("、".join(done) if done else "（沒有需要清除的）"))
        return 0
    if cmd == "list":
        from .runner import list_analyses
        for inst, names in list_analyses().items():
            print(inst)
            for n in names:
                print(f"  ‧ {n}")
        return 0
    if cmd == "diag":
        import platform
        from . import __version__
        from .core import settings as S
        print(f"Magic Tool v{__version__}")
        print(f"Python {platform.python_version()}  {sys.executable}")
        print(f"工具資料夾：{S.TOOL_ROOT}")
        print(f"設定與紀錄：{S.data_dir()}")
        for mod in ("numpy", "scipy", "pandas", "matplotlib", "openpyxl", "gspread", "tkinter"):
            try:
                m = __import__(mod)
                print(f"  ✓ {mod} {getattr(m, '__version__', getattr(m, 'TkVersion', ''))}")
            except Exception as e:
                print(f"  ✗ {mod}：{e}")
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
