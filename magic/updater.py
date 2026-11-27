"""透過 GitHub 自動更新（取自 LowTempAnalysis v2.11.0 的 updater.py，只改了名稱與保留的檔案）。

運作方式
  ‧ 工具資料夾裡的 release.json 記錄：目前版本、GitHub 儲存庫（owner/repo）、分支、更新內容
  ‧ 檢查：讀 https://raw.githubusercontent.com/<repo>/<branch>/release.json，版本比較新就提示
  ‧ 更新：下載 https://github.com/<repo>/archive/refs/heads/<branch>.zip，
          先把目前的程式備份到 _backup\\，再換成新版；使用者自己的檔案不會動
          （設定、紀錄都在 %LOCALAPPDATA%\\MagicTool\\，本來就不在工具資料夾）
  ‧ 開發用資料夾（有 .git）不會被自動更新，請用 git pull

發佈新版（開發者）
  publish.bat（一鍵：自動加版本號、清掉 notebook 輸出、自我測試、commit + push）
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

from .core.settings import TOOL_ROOT as _ROOT

TOOL_ROOT = str(_ROOT)

RELEASE_FILE = os.path.join(TOOL_ROOT, "release.json")
INSTALLED_FILE = ".installed_commit"     # 目前安裝的是 GitHub 上哪一個 commit（沒改版本號的修改也能更新）
# 不會被更新覆蓋的使用者檔案 / 資料夾（工具資料夾第一層）
PRESERVE = {INSTALLED_FILE, "settings.toml", "_backup", "logs", ".git", "__pycache__", ".ipynb_checkpoints"}
KEEP_BACKUPS = 3


# ---------------------------------------------------------------------------
# 版本資訊
# ---------------------------------------------------------------------------
def read_release(path=RELEASE_FILE):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"version": "0", "repo": "", "branch": "main", "notes": []}


def write_release(data, path=RELEASE_FILE):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def parse_version(v):
    out = []
    for part in str(v).lstrip("vV").split("."):
        num = "".join(ch for ch in part if ch.isdigit())
        out.append(int(num) if num else 0)
    while len(out) < 3:
        out.append(0)
    return tuple(out)


def push_history(rel):
    """換版本號之前，把目前這一版的說明移到 history（最新的在前面）。"""
    cur = {k: rel.get(k) for k in ("version", "date", "notes") if rel.get(k) is not None}
    if not cur.get("version"):
        return rel
    hist = [h for h in rel.get("history", []) if h.get("version") != cur["version"]]
    rel["history"] = ([cur] + hist)[:60]
    return rel


def all_notes(rel):
    """[(版本, 日期, [說明…])]，最新的在前面。"""
    out = [(rel.get("version", "?"), rel.get("date", ""), rel.get("notes", []))]
    out += [(h.get("version", "?"), h.get("date", ""), h.get("notes", [])) for h in rel.get("history", [])
            if h.get("version") != rel.get("version")]
    return out


def notes_since(remote, current):
    """遠端 release.json 裡，比 current 新的每一版說明（同事跳過好幾版時一次列出）。"""
    return [(v, d, n) for v, d, n in all_notes(remote or {}) if parse_version(v) > parse_version(current)]


def disk_version(root=None):
    """資料夾裡 release.json 現在寫的版本（覆蓋新檔案後可能和執行中的程式不同）。"""
    return read_release(os.path.join(root or TOOL_ROOT, "release.json")).get("version", "0")


def manifest_url(repo, branch="main"):
    return f"https://raw.githubusercontent.com/{repo}/{branch}/release.json"


def zip_url(repo, branch="main"):
    return f"https://github.com/{repo}/archive/refs/heads/{branch}.zip"


def is_dev_folder(root=None):
    return os.path.isdir(os.path.join(root or TOOL_ROOT, ".git"))


def _get(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": "MagicTool-updater",
                                               "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


# ---------------------------------------------------------------------------
# 檢查
# ---------------------------------------------------------------------------
def remote_commit(repo, branch="main", timeout=8):
    """GitHub 上最新的 commit → (sha, 第一行說明)；讀不到回傳 (None, "")。"""
    try:
        req = urllib.request.Request(f"https://api.github.com/repos/{repo}/commits/{branch}",
                                     headers={"User-Agent": "MagicTool-updater",
                                              "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        return data.get("sha"), (data.get("commit", {}).get("message", "") or "").strip()
    except Exception:
        return None, ""


def installed_commit(root=None):
    root = root or TOOL_ROOT
    try:
        with open(os.path.join(root, INSTALLED_FILE), encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def _write_installed(sha, root=None):
    root = root or TOOL_ROOT
    if sha and not is_dev_folder(root):
        try:
            with open(os.path.join(root, INSTALLED_FILE), "w", encoding="utf-8") as f:
                f.write(sha)
        except OSError:
            pass


def check(timeout=8, url=None):
    """回傳 {current, latest, newer, notes, repo, branch, remote}；沒設定儲存庫時 newer=False。"""
    local = read_release(os.path.join(TOOL_ROOT, "release.json"))
    repo, branch = local.get("repo", ""), local.get("branch", "main")
    info = {"current": local.get("version", "0"), "latest": None, "newer": False, "notes": [],
            "repo": repo, "branch": branch, "remote": None}
    if not repo and not url:
        info["error"] = "尚未設定 GitHub 儲存庫（release.json 的 repo）"
        return info
    use_github = url is None
    url = url or manifest_url(repo, branch)
    remote = json.loads(_get(url + ("&" if "?" in url else "?") + f"t={int(time.time())}"
                             if url.startswith("http") else url, timeout).decode("utf-8"))
    info.update(latest=remote.get("version", "0"), notes=remote.get("notes", []), remote=remote,
                newer=parse_version(remote.get("version", "0")) > parse_version(info["current"]))
    info["since"] = notes_since(remote, info["current"])
    # 版本號沒變、但 GitHub 上有新的修改（例如直接用 GitHub Desktop 推上去）→ 也算有更新
    if not info["newer"] and use_github and not is_dev_folder():
        sha, msg = remote_commit(repo, branch, timeout)
        info["commit"], info["commit_msg"] = sha, msg
        mine = installed_commit()
        same_version = parse_version(info["latest"]) == parse_version(info["current"])
        if sha and mine is None and same_version:
            _write_installed(sha)                       # 第一次：當作目前就是 GitHub 上這一版
        elif sha and mine and sha != mine and same_version:
            info.update(newer=True, by_commit=True, latest=info["current"],
                        notes=[l for l in msg.splitlines() if l.strip()][:8] or ["GitHub 上有新的修改"])
    return info


# ---------------------------------------------------------------------------
# 更新
# ---------------------------------------------------------------------------
def _find_root(folder):
    """在解壓縮的資料夾裡找含有 magic/__main__.py 的那一層（GitHub 的 zip 會多包一層 repo-branch/）。"""
    for dirpath, dirs, files in os.walk(folder):
        if os.path.isfile(os.path.join(dirpath, "magic", "__main__.py")):
            return dirpath
        if dirpath.count(os.sep) - folder.count(os.sep) > 2:
            dirs[:] = []
    return None


def _copy_item(src, dst):
    if os.path.isdir(src):
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"), dirs_exist_ok=True)
    else:
        shutil.copy2(src, dst)


EXEC_PATTERNS = ("*.command", "*.sh")          # macOS / Linux 的啟動檔要有執行權限


def make_executable(root=TOOL_ROOT):
    """解壓縮後的檔案沒有執行權限 → macOS 雙擊 .command 會說「沒有權限」；這裡補上。Windows 不用。"""
    if os.name == "nt":
        return []
    done = []
    for pat in EXEC_PATTERNS:
        for fp in glob.glob(os.path.join(root, pat)):
            try:
                os.chmod(fp, os.stat(fp).st_mode | 0o111)
                done.append(os.path.basename(fp))
            except OSError:
                pass
    return done


def _remove(path):
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)
    elif os.path.exists(path):
        os.remove(path)


def apply_update(info=None, log=print, zip_source=None, root=TOOL_ROOT):
    """下載並安裝新版。回傳新版本號。zip_source 可以是網址或本機 zip 路徑（測試用）。"""
    if is_dev_folder(root):
        raise RuntimeError("這是開發用資料夾（有 .git），請用 git pull 更新，不會自動覆蓋")
    local = read_release(os.path.join(root, "release.json"))
    if zip_source is None:
        if not local.get("repo"):
            raise RuntimeError("尚未設定 GitHub 儲存庫")
        zip_source = zip_url(local["repo"], local.get("branch", "main"))
    tmp = tempfile.mkdtemp(prefix="magic_update_")
    try:
        log("下載新版本…")
        zpath = os.path.join(tmp, "update.zip")
        if os.path.isfile(zip_source):
            shutil.copy2(zip_source, zpath)
        else:
            with open(zpath, "wb") as f:
                f.write(_get(zip_source, timeout=60))
        log("解壓縮…")
        with zipfile.ZipFile(zpath) as z:
            z.extractall(os.path.join(tmp, "x"))
        new_root = _find_root(os.path.join(tmp, "x"))
        if not new_root:
            raise RuntimeError("下載的檔案裡找不到程式（magic\\__main__.py）")
        new_rel = read_release(os.path.join(new_root, "release.json"))
        new_ver = new_rel.get("version", "0")
        if not new_rel.get("repo") and local.get("repo"):
            new_rel["repo"] = local["repo"]                    # 保留更新來源

        # ---- 備份目前版本 ----
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup = os.path.join(root, "_backup", f"v{local.get('version', '0')}_{stamp}")
        os.makedirs(backup, exist_ok=True)
        entries = [e for e in os.listdir(new_root) if e not in PRESERVE]
        log(f"備份目前版本到 {backup}")
        for e in entries:
            cur = os.path.join(root, e)
            if os.path.exists(cur):
                if e == "magic":
                    try:
                        shutil.move(cur, os.path.join(backup, e))  # 整個搬走，避免留下已刪除的舊模組
                    except OSError:                                # 搬不動（被占用）就複製一份再盡量刪
                        _copy_item(cur, os.path.join(backup, e))
                        shutil.rmtree(cur, ignore_errors=True)
                else:
                    _copy_item(cur, os.path.join(backup, e))

        # ---- 安裝新版 ----
        log(f"安裝 v{new_ver}…")
        for e in entries:
            dst = os.path.join(root, e)
            _remove(dst)
            _copy_item(os.path.join(new_root, e), dst)
        write_release(new_rel, os.path.join(root, "release.json"))
        make_executable(root)
        sha = (info or {}).get("commit") or remote_commit(local.get("repo", ""), local.get("branch", "main"))[0] \
            if local.get("repo") else None
        _write_installed(sha, root)
        _prune_backups(os.path.join(root, "_backup"))
        log(f"完成：已更新到 v{new_ver}")
        return new_ver
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _prune_backups(folder, keep=KEEP_BACKUPS):
    try:
        items = sorted((os.path.join(folder, d) for d in os.listdir(folder)), key=os.path.getmtime)
    except OSError:
        return
    for old in items[:-keep]:
        shutil.rmtree(old, ignore_errors=True)


def list_backups(root=TOOL_ROOT):
    folder = os.path.join(root, "_backup")
    try:
        return sorted((os.path.join(folder, d) for d in os.listdir(folder)), key=os.path.getmtime,
                      reverse=True)
    except OSError:
        return []


def rollback(log=print, root=TOOL_ROOT):
    """還原到最近一次的備份。"""
    backups = list_backups(root)
    if not backups:
        raise RuntimeError("沒有可以還原的備份")
    b = backups[0]
    for e in os.listdir(b):
        dst = os.path.join(root, e)
        _remove(dst)
        _copy_item(os.path.join(b, e), dst)
    shutil.rmtree(b, ignore_errors=True)
    log(f"已還原：{os.path.basename(b)}")
    return os.path.basename(b)


# ---------------------------------------------------------------------------
# 發佈（開發者）
# ---------------------------------------------------------------------------
def release(version=None, notes=None, repo=None, branch=None, push=False, log=print):
    """更新 release.json（版本、更新內容、儲存庫），--push 時用 git commit + push。"""
    rel = read_release()
    if repo:
        rel["repo"] = repo.strip().removeprefix("https://github.com/").strip("/")
    if branch:
        rel["branch"] = branch
    rel.setdefault("branch", "main")
    if version:
        push_history(rel)
        if parse_version(version) <= parse_version(rel.get("version", "0")):
            log(f"注意：新版本 {version} 沒有比目前的 {rel.get('version')} 大，使用者不會收到更新")
        rel["version"] = version.lstrip("vV")
        rel["date"] = time.strftime("%Y-%m-%d")
    if notes is not None:
        rel["notes"] = notes
    write_release(rel)
    log(f"release.json：版本 {rel.get('version')}，儲存庫 {rel.get('repo') or '（未設定）'}，"
        f"分支 {rel.get('branch')}")
    for n in rel.get("notes", []):
        log(f"  ‧ {n}")
    if not push:
        log("\n要發佈給其他人，請把整個資料夾 commit 並 push 到 GitHub（或加上 --push 自動執行）。")
        return rel
    if not is_dev_folder():
        log("\n這個資料夾還不是 git 儲存庫，請先照「發佈與更新.md」第 1 步設定。")
        return rel

    def git(*args):
        log("$ git " + " ".join(args))
        out = subprocess.run([find_git() or "git", *args], cwd=TOOL_ROOT, capture_output=True, text=True)
        if out.stdout.strip():
            log(out.stdout.strip())
        if out.returncode != 0:
            raise RuntimeError(out.stderr.strip() or f"git {args[0]} 失敗")
    git("add", "-A")
    msg = f"v{rel.get('version')}" + (": " + "; ".join(rel.get("notes", [])) if rel.get("notes") else "")
    try:
        git("commit", "-m", msg)
    except RuntimeError as e:
        if "nothing to commit" not in str(e):
            raise
    git("push", "origin", rel.get("branch", "main"))
    log(f"\n已發佈 v{rel.get('version')}。其他人下次開啟軟體就會收到更新通知。")
    return rel


# ---------------------------------------------------------------------------
# 一鍵發佈（publish.bat / 設定 → 更新 → 發佈到 GitHub）
# ---------------------------------------------------------------------------
def find_git():
    """找 git：PATH → Git for Windows → GitHub Desktop 內建的 git。"""
    import glob
    import shutil
    path = shutil.which("git")
    if path:
        return path
    cands = []
    for env in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        base = os.environ.get(env)
        if base:
            cands.append(os.path.join(base, "Git", "cmd", "git.exe"))
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        cands.append(os.path.join(local, "Programs", "Git", "cmd", "git.exe"))
        cands += sorted(glob.glob(os.path.join(local, "GitHubDesktop", "app-*", "resources", "app", "git",
                                               "cmd", "git.exe")), reverse=True)
    return next((c for c in cands if os.path.isfile(c)), None)


def bump_patch(version):
    parts = list(parse_version(version)) + [0, 0, 0]
    major, minor, patch = parts[:3]
    return f"{major}.{minor}.{patch + 1}"


PERSONAL_FILES = ("settings.toml", "gui_state.json", "service_account.json")


def run_selftest(root, log=print, python=None):
    """在工具資料夾跑 python -m magic selftest --release（獨立的行程，用的是資料夾裡的新程式）。
    發佈前一定要實際開視窗跑過：每個功能畫一次、量切換機台 / 背景計算 / 動畫的流暢度，沒通過就不上傳。回傳 True/False。"""
    import sys as _sys
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", MPLBACKEND="Agg")
    env.pop("MAGIC_PERF_FACTOR", None)              # 你電腦上一律用原本的流暢度門檻（不放寬）
    proc = subprocess.Popen([python or _sys.executable, "-m", "magic", "selftest", "--release"], cwd=root, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                            errors="replace")
    for line in proc.stdout:
        log(line.rstrip())
    return proc.wait() == 0


def publish(log=print, ask=input, root=None, test=True):
    """把工具資料夾發佈到 GitHub：不用開 GitHub Desktop、不用打版本號。

    · 版本號用 release.json 的（我給你的更新檔已經改好）
    · 你自己改了程式、版本號沒變 → 自動 +0.0.1，並問一句更新說明（直接 Enter 也可以）
    · notebooks 資料夾裡的 .ipynb 會先清掉輸出（圖、印出的數值可能是真實數據），程式碼保留
    · 不小心被追蹤的個人檔案（settings.toml、金鑰）會停止上傳，但留在你的電腦上
    推送失敗時（例如還沒登入）：變更已經存好，打開 GitHub Desktop 按「Push origin」即可。"""
    root = root or TOOL_ROOT
    if not os.path.isdir(os.path.join(root, ".git")):
        log("這個資料夾不是用 GitHub Desktop 複製（Clone）下來的，沒辦法直接發佈。")
        log("請照「發佈與更新.md」的步驟，用 GitHub Desktop Clone 一份，以後都在那個資料夾裡操作。")
        return False
    git = find_git()
    if not git:
        log("找不到 git。請安裝 GitHub Desktop（https://desktop.github.com）或 Git for Windows（https://git-scm.com）。")
        return False

    def run(*args, check=True, quiet=False, extra=()):
        out = subprocess.run([git, *extra, *args], cwd=root, capture_output=True, text=True,
                             encoding="utf-8", errors="replace")
        if not quiet and out.stdout.strip():
            log(out.stdout.strip())
        if check and out.returncode != 0:
            raise RuntimeError((out.stderr or out.stdout).strip() or f"git {args[0]} 失敗")
        return out

    rel = read_release(os.path.join(root, "release.json"))
    branch = rel.get("branch", "main")
    if run("rev-parse", "--verify", "HEAD", check=False, quiet=True).returncode != 0:
        # 剛 Clone 下來的空儲存庫：第一個 commit 直接放在 main（有些 git 預設叫 master）
        run("symbolic-ref", "HEAD", f"refs/heads/{branch}", check=False, quiet=True)
    log(f"工具資料夾：{root}")
    log(f"使用的 git：{git}")
    run("fetch", "origin", branch, check=False, quiet=True)
    changes = [l for l in run("status", "--porcelain", quiet=True).stdout.splitlines() if l.strip()]
    remote = None
    try:
        remote = check(timeout=8).get("latest")
    except Exception as e:
        log(f"（讀不到 GitHub 上的版本：{e}，照本機 release.json 發佈）")
    local = rel.get("version", "0")
    log(f"本機版本 v{local}　GitHub 上 v{remote or '?'}　有變更的檔案：{len(changes)} 個")

    from .tools_nb import suspicious
    pending = [l[3:].split(" -> ")[-1] for l in run("status", "--porcelain", "-uall", quiet=True).stdout.splitlines()
               if l.strip() and not l.startswith(" D")]
    bad = suspicious(pending)
    if bad:
        log("\n這些檔案看起來像量測資料，公開的 GitHub 不能放，所以沒有上傳：")
        for b in bad[:20]:
            log(f"  ✗ {b}")
        log("請把它們移出工具資料夾（或加進 .gitignore）後再執行 publish.bat。")
        return False


    if remote and parse_version(local) <= parse_version(remote):
        if not changes:
            ahead = run("rev-list", "--count", f"origin/{branch}..HEAD", check=False, quiet=True).stdout.strip()
            if ahead and ahead != "0":
                log("有已經存好但還沒上傳的版本，直接上傳。")
            else:
                log(f"\nGitHub 上已經是 v{remote}，而且沒有新的變更，不需要發佈。")
                return True
        else:
            new = bump_patch(remote)
            note = (ask(f"\n版本號會改成 v{new}。這一版改了什麼？（直接 Enter = 小幅修正）：") or "").strip()
            push_history(rel)
            rel["version"] = new
            rel["date"] = time.strftime("%Y-%m-%d")
            rel["notes"] = [note or "小幅修正"]
            write_release(rel, os.path.join(root, "release.json"))
            log(f"release.json → v{new}")

    try:
        from .tools_nb import strip_folder
        cleaned = strip_folder(os.path.join(root, "notebooks"))
        if cleaned:
            log(f"已清掉 notebook 輸出：{', '.join(cleaned)}")
    except Exception as e:
        log(f"（清除 notebook 輸出失敗：{e}）")
        return False

    if test:
        log("\n--- 上傳前自我測試：會實際開視窗操作每個功能、量切換與動畫的流暢度（約 40–70 秒，期間請不要點視窗）---")
        if not run_selftest(root, log):
            ans = (ask("\n自我測試沒有通過，所以還沒上傳（避免把壞掉的版本推給同事）。\n"
                       "確定要強制上傳請輸入 yes，直接 Enter = 取消：") or "").strip().lower()
            if ans != "yes":
                log("已取消，沒有上傳。把上面 ✗ 的錯誤訊息貼給 Claude 就可以修正。")
                return False
            log("強制上傳。")
        log("")

    for f in PERSONAL_FILES:
        if run("ls-files", "--error-unmatch", f, check=False, quiet=True).returncode == 0:
            run("rm", "--cached", "--quiet", f, check=False)
            log(f"停止上傳 {f}（檔案仍留在你的電腦）")

    ident = ()
    if run("config", "user.email", check=False, quiet=True).returncode != 0:
        owner = (rel.get("repo") or "user/x").split("/")[0]
        ident = ("-c", f"user.name={owner}", "-c", f"user.email={owner}@users.noreply.github.com")
    run("add", "-A")
    # Windows 的 git 不會記錄「可執行」：.command / .sh 要明確標記，Mac 下載後才能雙擊執行
    execs = [os.path.basename(f) for pat in EXEC_PATTERNS for f in glob.glob(os.path.join(root, pat))]
    if execs:
        run("update-index", "--chmod=+x", *execs, check=False, quiet=True)
    msg = f"v{rel['version']}"
    body = "\n".join("- " + n for n in rel.get("notes", []))
    out = run("commit", "-m", msg, *(("-m", body) if body else ()), check=False, extra=ident)
    if out.returncode != 0 and "nothing to commit" not in (out.stdout + out.stderr):
        raise RuntimeError(out.stderr.strip() or "commit 失敗")
    log(f"\n已存好：{msg}")
    try:
        run("push", "origin", branch)
    except RuntimeError as e:
        log(f"\n上傳到 GitHub 失敗：{e}")
        log("→ 變更已經存好了。打開 GitHub Desktop，按上方的「Push origin」就完成（不用再填 Summary）。")
        log("  以後想完全一鍵：安裝 Git for Windows（https://git-scm.com），第一次上傳會跳出瀏覽器登入 GitHub。")
        return False
    log(f"\n✓ 已發佈 v{rel['version']} 到 GitHub（{rel.get('repo')}）。")
    log("  同事開啟軟體時、或執行中每 30 分鐘會檢查到；GitHub 快取約 5 分鐘，最慢幾分鐘內就會跳出更新提示。")
    return True


# ---------------------------------------------------------------------------
# 收更新（開發者）：Claude 把測試過的更新推到 pending 分支 → 你按「收更新.bat」→ 自動發佈
# ---------------------------------------------------------------------------
PENDING_BRANCH = "pending"


def actions_url(repo):
    return f"https://github.com/{repo}/actions"


def ci_status(repo, sha, timeout=10):
    """GitHub Actions 雲端測試（真的 Windows / Mac）對這個 commit 的結果。
    回傳 (狀態, 說明)；狀態：success / running / failure / none（沒有測試紀錄）/ error（讀不到）。"""
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/commits/{sha}/check-runs?per_page=100",
            headers={"User-Agent": "MagicTool-updater", "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            runs = json.loads(r.read().decode("utf-8")).get("check_runs", [])
    except Exception as e:
        return "error", f"讀不到雲端測試結果（{e}）"
    if not runs:
        return "none", "這個版本沒有雲端測試紀錄"
    names = lambda rs: "、".join(sorted({x.get("name", "?") for x in rs}))
    waiting = [x for x in runs if x.get("status") != "completed"]
    if waiting:
        return "running", f"還在跑：{names(waiting)}"
    bad = [x for x in runs if x.get("conclusion") not in ("success", "skipped", "neutral")]
    if bad:
        return "failure", f"沒有通過：{names(bad)}"
    return "success", f"全部通過：{names(runs)}"


def _publish_subprocess(root, log=print, ask=None, test=True):
    """用資料夾裡的「新」程式執行 publish（收更新後程式已經換新，不能用記憶體裡的舊版）。"""
    import sys as _sys
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    env.pop("MAGIC_PERF_FACTOR", None)
    return subprocess.call([_sys.executable, "-m", "magic", "publish"], cwd=root, env=env) == 0


RECEIVE_RESULT = "receive_result.json"


def receive_result_path():
    from .core.settings import data_dir
    return os.path.join(str(data_dir()), RECEIVE_RESULT)


def read_receive_result():
    try:
        with open(receive_result_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def receive(log=print, ask=input, root=None, test=True, ci=ci_status, do_publish=_publish_subprocess):
    """收更新（見 _receive）。結束時把結果寫到設定資料夾的 receive_result.json，
    讓開著的 Magic Tool 知道收完了（成功 → 提示重新開啟）。"""
    root = root or TOOL_ROOT
    t0 = time.time()
    ok = False
    try:
        ok = _receive(log=log, ask=ask, root=root, test=test, ci=ci, do_publish=do_publish)
        return ok
    finally:
        try:
            with open(receive_result_path(), "w", encoding="utf-8") as f:
                json.dump({"ok": bool(ok), "version": disk_version(root), "started": t0, "finished": time.time()}, f)
        except OSError:
            pass


def _receive(log=print, ask=input, root=None, test=True, ci=ci_status, do_publish=_publish_subprocess):
    """收更新：抓 GitHub 上的 pending 分支 → 確認雲端測試（Windows + Mac）通過 → 套用到 main →
    在你的電腦上實際開視窗測流暢度（publish 的發佈前檢查）→ 發佈。任何一步沒過就停下來，資料夾恢復原狀。"""
    root = root or TOOL_ROOT
    if not os.path.isdir(os.path.join(root, ".git")):
        log("這個資料夾不是用 GitHub Desktop 複製（Clone）下來的開發資料夾，沒辦法收更新。")
        log("請在 D:\\Yeep\\MagicTool（GitHub Desktop Clone 的那一份）裡執行 收更新.bat。")
        return False
    git = find_git()
    if not git:
        log("找不到 git。請安裝 GitHub Desktop（https://desktop.github.com）或 Git for Windows（https://git-scm.com）。")
        return False

    def run(*args, check=True):
        out = subprocess.run([git, *args], cwd=root, capture_output=True, text=True, encoding="utf-8",
                             errors="replace")
        if check and out.returncode != 0:
            raise RuntimeError((out.stderr or out.stdout).strip() or f"git {args[0]} 失敗")
        return out

    def ok(*args):
        return run(*args, check=False).returncode == 0

    rel = read_release(os.path.join(root, "release.json"))
    repo, branch = rel.get("repo", ""), rel.get("branch", "main")
    pend_ref = f"origin/{PENDING_BRANCH}"
    log(f"工具資料夾：{root}")
    log("向 GitHub 查詢待發佈的更新…")
    out = run("fetch", "origin", branch, PENDING_BRANCH, check=False)
    if out.returncode != 0:
        if not ok("fetch", "origin", branch):
            log(f"連不上 GitHub：{(out.stderr or out.stdout).strip()}")
            return False
        run("update-ref", "-d", f"refs/remotes/{pend_ref}", check=False)     # GitHub 上已經沒有 pending
    if not ok("rev-parse", "--verify", "--quiet", pend_ref):
        log("\n目前沒有待發佈的更新。")
        return True
    pend = run("rev-parse", pend_ref).stdout.strip()
    if ok("merge-base", "--is-ancestor", pend_ref, f"origin/{branch}"):
        log(f"\n待發佈的更新已經發佈過了（GitHub 上是 v{rel.get('version')}），不需要再收。")
        return True

    # ---- 你這台的資料夾要是乾淨的（沒有還沒發佈的修改），才不會把兩邊的東西混在一起 ----
    dirty = [l for l in run("status", "--porcelain").stdout.splitlines() if l.strip()]
    if dirty:
        log("\n你的資料夾有還沒發佈的修改，為了不混在一起，這次先不收更新：")
        for l in dirty[:15]:
            log(f"  {l}")
        log("→ 要保留：先執行 publish.bat 發佈；不要了：在 GitHub Desktop 對檔案按右鍵 → Discard changes。然後再按一次 收更新。")
        return False
    if run("rev-parse", "--abbrev-ref", "HEAD").stdout.strip() != branch:
        run("checkout", branch)
        log(f"已切換到 {branch} 分支")
    if not ok("merge-base", "--is-ancestor", "HEAD", pend_ref) and ok("merge-base", "--is-ancestor", "HEAD",
                                                                     f"origin/{branch}"):
        run("merge", "--ff-only", f"origin/{branch}")          # 本機落後 GitHub：先跟上
    if not ok("merge-base", "--is-ancestor", "HEAD", pend_ref):
        log("\n待發佈的更新是接在比較舊的版本上（之後你自己又發佈或修改過），不能直接套用。")
        log("→ 跟 Claude 說：「pending 要重新接在最新的 main 上」。你的資料夾沒有改變。")
        return False

    # ---- 雲端測試（真的 Windows + Mac）要先通過 ----
    state, msg = ci(repo, pend)
    log(f"雲端測試（Windows + Mac）：{msg}")
    if state == "running":
        log(f"→ 測試還沒跑完（通常 5–10 分鐘），等一下再按一次 收更新。進度：{actions_url(repo)}")
        return False
    if state == "failure":
        log(f"→ 沒有通過，所以不會發佈。詳細：{actions_url(repo)}（把這段訊息貼給 Claude 就可以修正）")
        return False
    if state in ("none", "error"):
        if (ask("找不到雲端測試結果，仍要繼續（你的電腦上還是會跑完整測試）？輸入 y 繼續，直接 Enter = 取消：")
                or "").strip().lower() not in ("y", "yes"):
            log("已取消，資料夾沒有改變。")
            return False

    try:
        new = json.loads(run("show", f"{pend}:release.json").stdout)
    except Exception:
        new = {}
    log(f"\n待發佈：v{new.get('version', '?')}（目前 v{rel.get('version', '?')}）")
    for n in new.get("notes", [])[:12]:
        log(f"  · {n}")

    old = run("rev-parse", "HEAD").stdout.strip()
    run("merge", "--ff-only", pend_ref)
    log("\n已套用到你的資料夾。接下來在你的電腦上實際開視窗測試，通過才會發佈給同事：\n")
    done = do_publish(root, log=log, ask=ask, test=test)
    if done:
        return True
    run("fetch", "origin", branch, check=False)
    if ok("merge-base", "--is-ancestor", pend, f"origin/{branch}"):
        return True                                               # 其實已經上傳了
    if run("rev-parse", "HEAD").stdout.strip() == pend:
        run("reset", "--hard", old)                              # 沒有發佈：恢復成收更新之前的樣子
        log("\n這次沒有發佈，資料夾已經恢復成收更新之前的版本（同事那邊完全沒有影響）。")
        log("把上面 ✗ 的訊息貼給 Claude 修正後，再按一次 收更新。")
    return False


def _api_json(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": "MagicTool-updater",
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def pending_info(repo=None, branch=None, timeout=10, get_json=None, ci=None):
    """GitHub 上的 pending 是否比 main 新（有 Claude 準備好、還沒發佈的更新）。只用 GitHub 網頁 API，不需要 git。
    回傳 None（沒有待發佈）或 {ahead, sha, version, notes, ci: (狀態, 說明)}。"""
    rel = read_release()
    repo = repo or rel.get("repo", "")
    branch = branch or rel.get("branch", "main")
    if not repo:
        return None
    get_json = get_json or (lambda url: _api_json(url, timeout))
    try:
        cmp = get_json(f"https://api.github.com/repos/{repo}/compare/{branch}...{PENDING_BRANCH}")
    except urllib.error.HTTPError as e:
        if e.code == 404:                               # 沒有 pending 分支
            return None
        raise
    ahead = int(cmp.get("ahead_by", 0) or 0)
    if ahead <= 0 or cmp.get("status") not in ("ahead", "diverged"):
        return None
    commits = cmp.get("commits") or []
    sha = commits[-1]["sha"] if commits else None
    info = {"ahead": ahead, "sha": sha, "version": None, "notes": [], "diverged": cmp.get("status") == "diverged"}
    try:
        newrel = get_json(f"https://raw.githubusercontent.com/{repo}/{sha or PENDING_BRANCH}/release.json")
        info["version"], info["notes"] = newrel.get("version"), list(newrel.get("notes", []))
    except Exception:
        pass
    info["ci"] = (ci or ci_status)(repo, sha) if sha else ("none", "")
    return info


def receive_launcher(root=None):
    """收更新的啟動檔（Windows：收更新.bat；Mac / Linux：收更新.command）。"""
    root = root or TOOL_ROOT
    return os.path.join(root, "收更新.bat" if os.name == "nt" else "收更新.command")


def launch_receive(root=None):
    """在新的命令列視窗執行收更新（它會問問題、開視窗測試，所以要看得到）。回傳 True / 錯誤訊息。"""
    import sys as _sys
    path = receive_launcher(root)
    if not os.path.exists(path):
        return f"找不到 {os.path.basename(path)}"
    try:
        if os.name == "nt":
            os.startfile(path)                                    # 開新的命令列視窗
        elif _sys.platform == "darwin":
            subprocess.Popen(["open", "-a", "Terminal", path])
        else:
            for term in (["x-terminal-emulator", "-e"], ["gnome-terminal", "--"], ["xterm", "-e"]):
                if shutil.which(term[0]):
                    subprocess.Popen([*term, "bash", path])
                    break
            else:
                return "找不到終端機程式，請在終端機執行：bash 收更新.command"
        return True
    except Exception as e:
        return str(e)
