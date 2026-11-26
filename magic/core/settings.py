"""這台電腦的設定與資料夾位置。

所有「每台電腦不一樣」的東西都放在使用者資料夾，不放在工具資料夾（更新、上傳 GitHub 都不會碰到）：
    Windows：%LOCALAPPDATA%\\MagicTool\\
        settings.toml        資料夾、輸出位置、蝕刻紀錄、Google Sheet（可以用記事本改，也可以在 ⚙ 設定 改）
        gui_state.json       介面狀態：上次的資料夾、功能、參數、分隔線位置
        secrets\\             金鑰（service_account.json）；不會被同步或上傳
        logs\\                app.log、error.log、crash.log
    macOS  ：~/Library/Application Support/MagicTool/（同樣的檔案）
    其他系統：~/.magictool/

測試或攜帶式使用時，可以用環境變數 MAGIC_DATA 指定別的位置。
"""
from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path

APP_FOLDER = "MagicTool"
TOOL_ROOT = Path(__file__).resolve().parents[2]

DEFAULTS = {
    # 每台機台預設開啟的資料夾（空白 = 第一次使用時自己選）
    "folders": {"PPMS": "", "SQUID": "", "Raman": ""},
    # 分析結果（圖、CSV、result.json）存放位置；空白 = 文件\MagicTool 輸出
    "output_root": "",
    "fig_format": "png",
    "dpi": 200,
    "etching": {
        "csv_path": "",              # 空白 = %LOCALAPPDATA%\MagicTool\etching\etch_rate_log.csv
        "xlsx_mirror": False,        # True = 每次寫入也更新同名 .xlsx
        "gsheet_enabled": False,     # True = 也寫到 Google Sheet（需要 gspread 與金鑰）
        "gsheet_key": "",            # 試算表網址或 key
        "gsheet_worksheet": "",      # 工作表名稱；空白 = 第一張
        "service_account": "",       # 金鑰路徑；空白 = secrets\service_account.json
    },
}


def data_dir() -> Path:
    env = os.environ.get("MAGIC_DATA")
    if env:
        p = Path(env)
    elif os.environ.get("LOCALAPPDATA"):
        p = Path(os.environ["LOCALAPPDATA"]) / APP_FOLDER
    elif sys.platform == "darwin":
        p = Path.home() / "Library" / "Application Support" / APP_FOLDER
    else:
        p = Path.home() / ".magictool"
    p.mkdir(parents=True, exist_ok=True)
    return p


def secrets_dir() -> Path:
    p = data_dir() / "secrets"
    p.mkdir(parents=True, exist_ok=True)
    return p


def log_dir() -> Path:
    p = data_dir() / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def settings_path() -> Path:
    return data_dir() / "settings.toml"


def _merge(base, extra):
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def _load_toml(path):
    try:
        import tomllib
    except ModuleNotFoundError:          # Python 3.10 以前
        try:
            import tomli as tomllib
        except ModuleNotFoundError:
            return _load_toml_fallback(path)
    with open(path, "rb") as f:
        return tomllib.load(f)


def _load_toml_fallback(path):
    """沒有 tomllib / tomli 時，只讀得懂這個程式自己寫出來的簡單格式。"""
    out, table = {}, None
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            table = out.setdefault(line[1:-1].strip(), {})
            continue
        if "=" not in line:
            continue
        k, v = (s.strip() for s in line.split("=", 1))
        (table if table is not None else out)[k] = _parse_scalar(v)
    return out


def _parse_scalar(v):
    if v.startswith("'") and v.endswith("'"):
        return v[1:-1]
    if v.startswith('"') and v.endswith('"'):
        return json.loads(v)
    if v in ("true", "false"):
        return v == "true"
    if v.startswith("["):
        try:
            return json.loads(v.replace("'", '"'))
        except ValueError:
            return []
    try:
        return int(v)
    except ValueError:
        try:
            return float(v)
        except ValueError:
            return v


def _toml_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    s = "" if v is None else str(v)
    if "'" not in s and "\n" not in s:
        return f"'{s}'"                      # 單引號：Windows 路徑的反斜線不用寫兩次
    return json.dumps(s, ensure_ascii=False)


HEADER = """# ============================================================
#  Magic Tool 這台電腦的設定（也可以在軟體的 ⚙ 設定 裡修改）
#  Windows 路徑請用單引號 '...'，反斜線就不用寫兩次
# ============================================================
"""


def dumps(data: dict) -> str:
    lines = [HEADER]
    scalars = {k: v for k, v in data.items() if not isinstance(v, dict)}
    for k, v in scalars.items():
        lines.append(f"{k} = {_toml_value(v)}")
    for name, table in data.items():
        if isinstance(table, dict):
            lines.append(f"\n[{name}]")
            for k, v in table.items():
                if not isinstance(v, dict):
                    lines.append(f"{k} = {_toml_value(v)}")
    return "\n".join(lines) + "\n"


def load_settings() -> dict:
    path = settings_path()
    if not path.exists():
        return copy.deepcopy(DEFAULTS)
    try:
        return _merge(DEFAULTS, _load_toml(path))
    except Exception:
        return copy.deepcopy(DEFAULTS)


def save_settings(data: dict) -> Path:
    path = settings_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(dumps(_merge(DEFAULTS, data)), encoding="utf-8")
    os.replace(tmp, path)
    return path


def documents_dir() -> Path:
    home = Path.home()
    for cand in (home / "Documents", home / "文件", home / "My Documents"):
        if cand.is_dir():
            return cand
    return home


def output_root(settings=None) -> Path:
    s = settings or load_settings()
    p = s.get("output_root") or ""
    return Path(os.path.expandvars(os.path.expanduser(p))) if p else documents_dir() / "MagicTool 輸出"


def etching_csv(settings=None) -> Path:
    s = settings or load_settings()
    p = (s.get("etching") or {}).get("csv_path") or ""
    return Path(os.path.expandvars(os.path.expanduser(p))) if p else data_dir() / "etching" / "etch_rate_log.csv"


def service_account_path(settings=None) -> Path:
    s = settings or load_settings()
    p = (s.get("etching") or {}).get("service_account") or ""
    return Path(os.path.expandvars(os.path.expanduser(p))) if p else secrets_dir() / "service_account.json"


# ---------------------------------------------------------------------------
# 介面狀態（JSON，程式自己讀寫）
# ---------------------------------------------------------------------------
def gui_state_path() -> Path:
    return data_dir() / "gui_state.json"


def load_gui_state() -> dict:
    try:
        return json.loads(gui_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_gui_state(data: dict) -> None:
    path = gui_state_path()
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass
