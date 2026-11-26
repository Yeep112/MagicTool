# Magic Tool：直接啟動軟體（工作列上釘選的圖示會執行這個檔案，不需要 run_magic.bat）
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from magic.gui.launcher import main  # noqa: E402

main(sys.argv[1] if len(sys.argv) > 1 else None)
