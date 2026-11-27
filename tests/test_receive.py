"""收更新（magic.updater.receive）：用本機的 bare repo 假裝是 GitHub，走完整個流程。

    pending 不存在 → 沒有更新
    雲端測試還在跑 / 沒通過 → 不套用、資料夾不變
    通過 → 套用 → 發佈（這裡用假的 publish：直接 push）
    發佈前檢查沒過 → 資料夾恢復原狀
    你的資料夾有沒發佈的修改 → 不收
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="需要 git")


def git(cwd, *args):
    r = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=main", *args],
                       cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def write_release(folder, version, notes):
    with open(os.path.join(folder, "release.json"), "w", encoding="utf-8") as f:
        json.dump({"version": version, "repo": "Yeep112/MagicTool", "branch": "main", "notes": notes}, f,
                  ensure_ascii=False)


@pytest.fixture
def repos(tmp_path):
    """origin（假的 GitHub）、mine（你電腦上的開發資料夾）、claude（我推 pending 用的）。"""
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "--bare", str(origin))
    git(origin, "symbolic-ref", "HEAD", "refs/heads/main")
    mine = tmp_path / "mine"
    git(tmp_path, "clone", str(origin), str(mine))
    write_release(mine, "1.0.0", ["first"])
    (mine / "a.py").write_text("x = 1\n", encoding="utf-8")
    git(mine, "add", "-A")
    git(mine, "commit", "-m", "v1.0.0")
    git(mine, "push", "origin", "HEAD:main")
    claude = tmp_path / "claude"
    git(tmp_path, "clone", str(origin), str(claude))
    return str(origin), str(mine), str(claude)


def push_pending(claude, version="1.0.1"):
    write_release(claude, version, ["新功能"])
    with open(os.path.join(claude, "a.py"), "a", encoding="utf-8") as f:
        f.write("y = 2\n")
    git(claude, "add", "-A")
    git(claude, "commit", "-m", f"v{version}")
    git(claude, "push", "origin", "HEAD:pending")
    return git(claude, "rev-parse", "HEAD")


def fake_publish(ok=True):
    def run(root, log=print, ask=None, test=True):
        if ok:
            git(root, "push", "origin", "main")
        return ok
    return run


def receive(mine, ci=("success", "全部通過"), publish_ok=True, answer=""):
    from magic import updater
    logs = []
    ok = updater.receive(log=logs.append, ask=lambda q: answer, root=mine,
                         ci=lambda repo, sha: ci, do_publish=fake_publish(publish_ok))
    return ok, "\n".join(logs)


def test_no_pending(repos):
    _, mine, _ = repos
    ok, log = receive(mine)
    assert ok and "沒有待發佈" in log


def test_success_publishes(repos):
    origin, mine, claude = repos
    sha = push_pending(claude)
    ok, log = receive(mine)
    assert ok, log
    assert "v1.0.1" in log and "新功能" in log
    assert git(origin, "rev-parse", "main") == sha
    assert git(mine, "rev-parse", "HEAD") == sha
    ok, log = receive(mine)                                 # 再按一次：已經發佈過
    assert ok and "已經發佈過" in log


@pytest.mark.parametrize("state", ["running", "failure"])
def test_ci_not_green_keeps_folder(repos, state):
    origin, mine, claude = repos
    before = git(mine, "rev-parse", "HEAD")
    push_pending(claude)
    ok, log = receive(mine, ci=(state, "x"))
    assert not ok
    assert git(mine, "rev-parse", "HEAD") == before
    assert git(origin, "rev-parse", "main") == before


def test_no_ci_asks(repos):
    origin, mine, claude = repos
    before = git(mine, "rev-parse", "HEAD")
    sha = push_pending(claude)
    ok, log = receive(mine, ci=("none", "沒有紀錄"), answer="")
    assert not ok and git(mine, "rev-parse", "HEAD") == before
    ok, log = receive(mine, ci=("none", "沒有紀錄"), answer="y")
    assert ok and git(origin, "rev-parse", "main") == sha


def test_publish_check_fails_restores(repos):
    origin, mine, claude = repos
    before = git(mine, "rev-parse", "HEAD")
    push_pending(claude)
    ok, log = receive(mine, publish_ok=False)
    assert not ok and "恢復" in log
    assert git(mine, "rev-parse", "HEAD") == before
    assert git(origin, "rev-parse", "main") == before


def test_dirty_folder_refuses(repos):
    origin, mine, claude = repos
    push_pending(claude)
    with open(os.path.join(mine, "a.py"), "a", encoding="utf-8") as f:
        f.write("mine = 3\n")
    ok, log = receive(mine)
    assert not ok and "還沒發佈的修改" in log
    assert "mine = 3" in open(os.path.join(mine, "a.py"), encoding="utf-8").read()


def test_pending_on_old_base_refuses(repos):
    origin, mine, claude = repos
    push_pending(claude)
    # 你自己又發佈了一版（pending 沒有接在它上面）
    write_release(mine, "1.0.2", ["我自己改的"])
    git(mine, "add", "-A")
    git(mine, "commit", "-m", "v1.0.2")
    git(mine, "push", "origin", "main")
    before = git(mine, "rev-parse", "HEAD")
    ok, log = receive(mine)
    assert not ok and "重新接在最新的 main" in log
    assert git(mine, "rev-parse", "HEAD") == before


def test_local_behind_catches_up(repos, tmp_path):
    """你的資料夾比 GitHub 舊（例如在另一台電腦發佈過）→ 先跟上，再套用 pending。"""
    origin, mine, claude = repos
    git(claude, "pull", "origin", "main")
    write_release(claude, "1.0.1", ["另一台電腦發佈的"])
    git(claude, "commit", "-am", "v1.0.1")
    git(claude, "push", "origin", "HEAD:main")
    sha = push_pending(claude, "1.0.2")
    ok, log = receive(mine)
    assert ok, log
    assert git(origin, "rev-parse", "main") == sha
