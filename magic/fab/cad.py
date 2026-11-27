"""DXF / GDS / DWG 用哪個程式開：預設 KLayout，可以選 AutoCAD（設定裡可以指定程式位置）。"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys

CAD_EXT = {".dxf", ".dwg", ".gds", ".gds2", ".gdsii", ".oas"}
APPS = {"klayout": "KLayout", "autocad": "AutoCAD"}


def _env(name):
    return os.environ.get(name) or ""


def candidates(app):
    """可能的安裝位置（依序找，第一個存在的就用）。"""
    if os.name == "nt":
        pf = [_env("ProgramFiles"), _env("ProgramFiles(x86)"), _env("ProgramW6432")]
        if app == "klayout":
            out = [os.path.join(_env("APPDATA"), "KLayout", "klayout_app.exe"),
                   os.path.join(_env("LOCALAPPDATA"), "Programs", "KLayout", "klayout_app.exe"),
                   os.path.join(_env("USERPROFILE"), "AppData", "Roaming", "KLayout", "klayout_app.exe")]
            out += [os.path.join(p, "KLayout", "klayout_app.exe") for p in pf if p]
            for p in pf:
                if p:
                    out += sorted(glob.glob(os.path.join(p, "KLayout*", "klayout_app.exe")), reverse=True)
            return out
        out = []
        for p in pf:
            if p:
                out += sorted(glob.glob(os.path.join(p, "Autodesk", "AutoCAD*", "acad.exe")), reverse=True)
                out += sorted(glob.glob(os.path.join(p, "Autodesk", "AutoCAD LT*", "acadlt.exe")), reverse=True)
        return out
    if sys.platform == "darwin":
        if app == "klayout":
            return (["/Applications/KLayout/klayout.app", "/Applications/klayout.app"] +
                    sorted(glob.glob("/Applications/*/klayout*.app")) + sorted(glob.glob("/Applications/klayout*.app")))
        return (sorted(glob.glob("/Applications/Autodesk/AutoCAD*/AutoCAD*.app"), reverse=True) +
                sorted(glob.glob("/Applications/AutoCAD*.app"), reverse=True))
    return []


def find_app(app, custom=""):
    """回傳程式路徑；找不到 → ""。custom = 設定裡指定的位置（優先）。"""
    if custom and os.path.exists(custom):
        return custom
    for c in candidates(app):
        if c and os.path.exists(c):
            return c
    names = ["klayout_app", "klayout"] if app == "klayout" else ["acad", "acadlt"]
    for n in names:
        w = shutil.which(n)
        if w:
            return w
    return ""


def default_app(path, preferred="klayout"):
    """這個檔案預設用哪個：DWG 只能 AutoCAD；其他照設定（預設 KLayout）。"""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".dwg":
        return "autocad"
    return preferred if preferred in APPS else "klayout"


def command(app_path, path):
    """開檔的指令（Mac 的 .app 用 open -a）。"""
    if sys.platform == "darwin" and app_path.endswith(".app"):
        return ["open", "-a", app_path, path]
    return [app_path, path]


def open_with(app_path, path):
    subprocess.Popen(command(app_path, path))
    return True
