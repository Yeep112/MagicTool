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


@pytest.fixture(autouse=True)
def appdata(tmp_path, monkeypatch):
    monkeypatch.setenv("MAGIC_DATA", str(tmp_path / "appdata"))
    os.makedirs(tmp_path / "appdata", exist_ok=True)


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


def test_result_file_written(repos):
    """收完會寫 receive_result.json，開著的軟體靠它知道要不要提示重新開啟。"""
    from magic import updater
    origin, mine, claude = repos
    push_pending(claude, "1.0.1")
    ok, _ = receive(mine)
    r = updater.read_receive_result()
    assert ok and r["ok"] and r["version"] == "1.0.1" and r["finished"] >= r["started"]
    push_pending(claude, "1.0.2")
    ok, _ = receive(mine, publish_ok=False)
    r = updater.read_receive_result()
    assert not ok and not r["ok"] and r["version"] == "1.0.1"        # 沒發佈：資料夾還是 1.0.1


def test_pending_info():
    """軟體上方的「有新版本待發佈」：用假的 GitHub API 回應。"""
    import urllib.error
    from magic import updater

    def api(responses):
        def get(url):
            for key, val in responses.items():
                if key in url:
                    if isinstance(val, Exception):
                        raise val
                    return val
            raise AssertionError(url)
        return get

    ci = lambda repo, sha: ("success", "全部通過")
    info = updater.pending_info("o/r", "main", get_json=api({
        "/compare/": {"status": "ahead", "ahead_by": 2, "commits": [{"sha": "a"}, {"sha": "b"}]},
        "release.json": {"version": "0.5.5", "notes": ["加快切換", "待發佈提示"]}}), ci=ci)
    assert info["ahead"] == 2 and info["sha"] == "b" and info["version"] == "0.5.5"
    assert info["notes"] == ["加快切換", "待發佈提示"] and info["ci"] == ("success", "全部通過")
    same = updater.pending_info("o/r", "main", get_json=api({"/compare/": {"status": "identical", "ahead_by": 0}}),
                                ci=ci)
    assert same is None
    gone = urllib.error.HTTPError("u", 404, "Not Found", {}, None)
    assert updater.pending_info("o/r", "main", get_json=api({"/compare/": gone}), ci=ci) is None


def test_perf_history(tmp_path):
    """流暢度紀錄：存檔、讀回、和上一次比較（明顯變慢會標出來）。"""
    from magic.core import perfhist
    assert perfhist.last(tmp_path) is None
    lines, slower = perfhist.compare(None, {})
    assert "第一次" in lines[0] and not slower
    a = perfhist.append({"switch_med": 30, "switch_max": 50, "bg_gap": 200, "draw_max": 80, "anim_max": 20},
                        "0.5.4", tmp_path)
    assert perfhist.last(tmp_path)["switch_max"] == "50.0"
    b = perfhist.append({"switch_med": 40, "switch_max": 90, "bg_gap": 210, "draw_max": 50, "anim_max": 22},
                        "0.5.5", tmp_path)
    lines, slower = perfhist.compare(a, b)
    assert slower == ["切換機台最慢"], (lines, slower)              # 50 → 90：慢 80% 而且多 40 ms
    assert any("變快" in l and "單張圖" in l for l in lines)         # 80 → 50
    assert len(perfhist.read_all(tmp_path)) == 2


def test_find_spikes():
    """宇宙射線尖峰：1～3 點寬的尖峰要找到；真的 Raman 峰（G、2D、hBN，再窄也好幾個點寬）不能被當成尖峰。"""
    import numpy as np
    from magic.raman.spikes import find_spikes, spike_mask
    from magic.testdata import _lor
    rng = np.random.default_rng(3)
    x = np.arange(900.0, 3000.0, 1.05)
    y = 280 + _lor(x, 1582, 14, 550) + _lor(x, 2690, 30, 300) + _lor(x, 1366, 9, 400) + rng.normal(0, 4, x.size)
    clean = y.copy()
    assert find_spikes(clean) == [], "沒有尖峰的光譜不應該找到東西（G / 2D / hBN 峰不是尖峰）"
    spikes = {400: [60], 900: [45, 55], 1500: [40, 90, 45], 1800: [300]}     # 1、2、3 點寬，還有一個很高的
    for i, hs in spikes.items():
        y[i:i + len(hs)] += hs
    found = find_spikes(y)
    assert [a for a, b in found] == sorted(spikes), found
    assert all(b - a + 1 == len(spikes[a]) for a, b in found), found
    m = spike_mask(y)
    assert m.sum() == sum(len(v) for v in spikes.values())
    # 尖峰剛好在 G 峰旁邊也要找到；4 點寬的不算（超過最大寬度）
    y2 = clean.copy()
    g = int(np.argmin(np.abs(x - 1582)))
    y2[g + 12] += 120
    y2[2200:2204] += 100
    found2 = find_spikes(y2)
    assert (g + 12, g + 12) in found2 and not any(a >= 2200 and a < 2204 for a, b in found2), found2


def test_stale_old_pending_is_dropped(repos):
    """上次收更新沒發佈又把視窗關掉：資料夾停在舊的 pending（只有 Claude 的 commit）→ 先回到 main 再收新的。"""
    origin, mine, claude = repos
    old = push_pending(claude, "1.0.1")
    git(mine, "fetch", "origin", "pending")
    git(mine, "merge", "--ff-only", "origin/pending")          # 停在舊的 pending
    subprocess.run(["git", "-C", mine, "commit", "--amend", "--no-edit", "--reset-author"], capture_output=True,
                   env=dict(os.environ, GIT_AUTHOR_EMAIL="noreply@anthropic.com", GIT_AUTHOR_NAME="Claude",
                            GIT_COMMITTER_EMAIL="noreply@anthropic.com", GIT_COMMITTER_NAME="Claude"))
    git(claude, "reset", "--hard", "origin/main")               # 我把 pending 重做一次（舊的不再是祖先）
    with open(os.path.join(claude, "b.py"), "w", encoding="utf-8") as f:
        f.write("z = 3\n")
    write_release(claude, "1.0.2", ["重做"])
    git(claude, "add", "-A")
    git(claude, "commit", "-m", "v1.0.2")
    git(claude, "push", "-f", "origin", "HEAD:pending")
    new = git(claude, "rev-parse", "HEAD")
    assert old != new
    ok, log = receive(mine)
    assert ok, log
    assert git(origin, "rev-parse", "main") == new


def test_own_commits_are_kept(repos):
    """你自己的 commit（不是 Claude 的）不會被丟掉：照舊請 Claude 重新接。"""
    origin, mine, claude = repos
    (open(os.path.join(mine, "mine.py"), "w")).write("m = 1\n")
    git(mine, "add", "-A")
    git(mine, "commit", "-m", "my own")
    mine_head = git(mine, "rev-parse", "HEAD")
    push_pending(claude)
    ok, log = receive(mine)
    assert not ok and "重新接在最新的 main" in log
    assert git(mine, "rev-parse", "HEAD") == mine_head
