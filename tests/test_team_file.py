"""團隊設定檔（team_sheet_secret.txt）：放在工具資料夾，同事打開軟體就自動接上實驗室的蝕刻紀錄表單。"""
import os
import subprocess
import shutil
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from magic.etching import gsync  # noqa: E402

CFG = {"etching": {"gsheet_key": "https://docs.google.com/spreadsheets/d/TEST/edit#gid=0",
                   "gsheet_worksheet": "etching rate", "gsheet_token": "tok123",
                   "gsheet_script_url": "https://script.google.com/macros/s/TEST/exec"}}


def test_write_and_read(tmp_path):
    assert gsync.read_team_file(tmp_path) is None
    p = gsync.write_team_file(CFG, tmp_path)
    assert os.path.basename(p) == gsync.TEAM_FILE
    text = open(p, encoding="utf-8").read()
    assert text.startswith("#") and gsync.CODE_PREFIX in text
    d = gsync.read_team_file(tmp_path)
    assert d["gsheet_token"] == "tok123" and d["gsheet_worksheet"] == "etching rate"


def test_defaults_only_when_not_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("MAGIC_DATA", str(tmp_path / "appdata"))
    gsync.write_team_file(CFG, tmp_path)
    new = gsync.team_defaults({"etching": {"gsheet_key": "mine"}}, {}, tmp_path)
    assert new["etching"]["gsheet_token"] == "tok123" and new["etching"]["gsheet_enabled"] is True
    assert gsync.team_defaults({}, {"etch_team_file": "applied"}, tmp_path) is None
    assert gsync.team_defaults(new, {}, tmp_path) is None
    assert gsync.team_defaults({"etching": {"gsheet_script_url": "https://x/exec"}}, {}, tmp_path) is None


def test_broken_file_is_ignored(tmp_path):
    (tmp_path / gsync.TEAM_FILE).write_text("# 註解\n亂打的\n", encoding="utf-8")
    assert gsync.read_team_file(tmp_path) is None
    assert gsync.team_defaults({}, {}, tmp_path) is None


@pytest.mark.skipif(shutil.which("git") is None, reason="需要 git")
def test_never_uploaded(tmp_path):
    """.gitignore 會排除團隊設定檔（裡面有通行碼，GitHub 是公開的）。"""
    from magic import updater
    assert gsync.TEAM_FILE in updater.PERSONAL_FILES
    r = subprocess.run(["git", "check-ignore", "-q", gsync.TEAM_FILE], cwd=ROOT)
    assert r.returncode == 0, "team_sheet_secret.txt 沒有被 .gitignore 排除"
