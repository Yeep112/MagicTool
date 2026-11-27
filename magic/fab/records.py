"""樣品紀錄：找樣品資料夾、資料夾 + 試算表 → 初版紀錄、讀寫紀錄檔。

紀錄檔（JSON）放在樣品資料夾裡，檔名預設「<資料夾名稱>.json」（設定裡可以改，例如「{folder}_製程.json」）。
沒有資料夾的樣品（試算表裡有、但找不到資料夾，例如很早就放棄的），紀錄存在這台電腦的設定資料夾
samples\\<使用者>\\<編號>.json，之後找到資料夾再搬過去。

紀錄格式（schema 1）
  label, user, project, type, start, folder（樣品資料夾的路徑）
  status   {state: active|hold|measuring|measured|abandoned, reason, next, next_date, stopped_at}
  results  {r_ohm（低溫電阻 Ω）, sc_contact（超導 contact）, sc_on（在哪個材料上）, tc_k}
  steps    [{id, kind, n, date, date_end, folders: [資料夾名稱], params, substeps: [{kind, params, raw, folders}],
             source: ["folder", "sheet"], raw: [試算表原文], notes}]
  review   [{id, msg, step, resolved}]   ← 匯入時對不起來、需要人確認的地方
  sheet    試算表那一列的原文（狀態、每一格、備註）
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import time
from pathlib import Path

from . import folders as F
from . import steps as K

SCHEMA = 1
DEFAULT_RECORD_NAME = "{folder}.json"


def safe_name(s):
    return re.sub(r'[\\/:*?"<>|]+', "_", str(s)).strip() or "sample"


def record_path(sample_dir, record_name=DEFAULT_RECORD_NAME):
    folder = os.path.basename(os.path.normpath(sample_dir))
    try:
        name = (record_name or DEFAULT_RECORD_NAME).format(folder=folder, label=folder)
    except (KeyError, IndexError, ValueError):
        name = DEFAULT_RECORD_NAME.format(folder=folder)
    if not name.lower().endswith(".json"):
        name += ".json"
    return os.path.join(sample_dir, safe_name(name))


def local_dir(base, user):
    return os.path.join(str(base), "samples", safe_name(user or "me"))


def local_path(base, user, label):
    return os.path.join(local_dir(base, user), safe_name(label) + ".json")


def sample_key(user, label, project=""):
    return "/".join(x for x in (user or "me", project, str(label)) if x)


# ---------------------------------------------------------------------------
# 讀寫
# ---------------------------------------------------------------------------
def load(path):
    with open(path, encoding="utf-8") as f:
        rec = json.load(f)
    if not isinstance(rec, dict) or "steps" not in rec:
        raise ValueError(f"{path} 不是 Magic Tool 的樣品紀錄")
    rec.setdefault("review", [])
    rec.setdefault("status", {"state": "active"})
    rec.setdefault("results", {})
    return rec


def save(rec, path):
    """先寫暫存檔再取代（同步軟體或當機時不會留下寫一半的檔案）。"""
    from .. import __version__
    rec = dict(rec)
    rec["schema"] = SCHEMA
    rec["app"] = f"MagicTool {__version__}"
    rec["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, path)
    return path


def review_id(msg, step=""):
    return hashlib.sha1(f"{step}|{msg}".encode("utf-8")).hexdigest()[:10]


def add_review(rec, msg, step=""):
    rid = review_id(msg, step)
    if not any(r.get("id") == rid for r in rec["review"]):
        rec["review"].append({"id": rid, "msg": msg, "step": step, "resolved": False})


def open_reviews(rec):
    return [r for r in rec.get("review", []) if not r.get("resolved")]


# ---------------------------------------------------------------------------
# 資料夾 + 試算表 → 初版紀錄
# ---------------------------------------------------------------------------
def _folder_step(fs):
    """資料夾步驟（一組或單一）→ 紀錄的步驟。"""
    flds = fs["folders"]
    dates = [d for f in flds for d in (f["date"], f["date_end"]) if d]
    step = {"kind": fs["kind"], "folders": [f["folder"] for f in flds], "params": {}, "substeps": [],
            "date": min(dates) if dates else "", "date_end": max(dates) if dates else "", "source": ["folder"],
            "raw": [], "notes": ""}
    if fs["kind"] == "litho_group":                       # 照片歸到子步驟：顯影後 / 鍍完
        for f in flds:
            step["substeps"].append({"kind": "lithography" if f["kind"] == "lithography" else "liftoff",
                                     "params": {}, "raw": "", "folders": [f["folder"]]})
    if fs["kind"] == "afm":                               # 檔名「hBN_48.5, Ta_14.8」→ 厚度
        for f in flds:
            for img in f["images"]:
                m = re.search(r"hbn_?\s*([\d.]+)", os.path.basename(img), re.I)
                if m and "hbn_nm" not in step["params"]:
                    try:
                        step["params"]["hbn_nm"] = float(m.group(1).rstrip("."))
                    except ValueError:
                        pass
    return step


_COMPAT = {"marker": {"litho_group"}, "contact": {"litho_group"}, "top_gate": {"litho_group"},
           "transfer": {"transfer"}, "cover": {"cover"}, "afm": {"afm"}, "raman": {"raman"}}


def _merge_into(fstep, sstep):
    """把試算表的步驟資料併進資料夾步驟（資料夾是主要紀錄：種類、照片以資料夾為準，參數用試算表）。"""
    out = copy.deepcopy(fstep)
    if out["kind"] == "litho_group":
        out["kind"] = sstep["kind"]
        photos = {s["kind"]: s.get("folders", []) for s in out["substeps"]}
        subs = []
        for sub in sstep["substeps"]:
            sub = dict(sub)
            if sub["kind"] == "deposit" and "liftoff" in photos:
                sub["folders"] = []
            subs.append(sub)
        if "lithography" in photos:
            subs.insert(0, {"kind": "lithography", "params": {}, "raw": "", "folders": photos["lithography"]})
        if "liftoff" in photos:
            subs.append({"kind": "liftoff", "params": {}, "raw": "", "folders": photos["liftoff"]})
        out["substeps"] = subs
    else:
        out["substeps"] = sstep["substeps"] or out["substeps"]
    out["params"] = {**out.get("params", {}), **sstep.get("params", {})}
    out["raw"] = sstep.get("raw", [])
    out["source"] = ["folder", "sheet"]
    if sstep.get("implied"):
        out["implied"] = True
    return out


def build(label, user="", project="", sample_dir="", sheet_row=None, rule=None):
    """產生初版紀錄（不寫檔）。sheet_row = sheet.parse_table 的一筆；sample_dir 空白 = 沒有資料夾。"""
    srow = sheet_row or {}
    start = srow.get("start", "")
    entries = F.step_folders(sample_dir, rule, start) if sample_dir else []
    fsteps = F.group_folders(entries)
    ssteps = srow.get("steps", [])
    rec = {"label": str(label), "user": user, "project": project, "type": srow.get("type", ""), "start": start,
           "folder": sample_dir, "status": copy.deepcopy(srow.get("status") or {"state": "active"}),
           "results": copy.deepcopy(srow.get("results") or {"r_ohm": None, "sc_contact": None, "sc_on": "",
                                                            "tc_k": None}),
           "steps": [], "review": [], "notes": srow.get("raw", {}).get("remark", ""),
           "sheet": srow.get("raw"), "imported": time.strftime("%Y-%m-%d %H:%M:%S")}
    rec["status"].setdefault("stopped_at", None)
    for msg in srow.get("issues", []):
        add_review(rec, msg)

    if not fsteps:                                        # 只有試算表
        merged = [dict(s, folders=[], date="", date_end="", notes="") for s in ssteps]
    elif not ssteps:                                      # 只有資料夾：微影組用位置推測
        merged = [_folder_step(f) for f in fsteps]
    else:                                                 # 兩邊都有：依序對齊
        fmerged = [_folder_step(f) for f in fsteps]
        used = [False] * len(fmerged)
        inserts = {}
        j = 0
        for s in ssteps:
            ok = _COMPAT.get(s["kind"], set())
            k = next((i for i in range(j, len(fmerged)) if not used[i] and fmerged[i]["kind"] in ok), None)
            if k is None:
                inserts.setdefault(j, []).append(dict(s, folders=[], date="", date_end="", notes=""))
                continue
            fmerged[k] = _merge_into(fmerged[k], s)
            used[k] = True
            j = k + 1
        merged = []
        for i in range(len(fmerged) + 1):
            merged += inserts.get(i, [])
            if i < len(fmerged):
                merged.append(fmerged[i])
    seen_marker = False                                   # 對不到的微影組：第一組推測是 marker，之後是 contact
    for s in merged:
        if s["kind"] == "marker":
            seen_marker = True
        elif s["kind"] == "litho_group":
            s["kind"] = "contact" if seen_marker else "marker"
            s["guess"] = True
            seen_marker = True

    counts = {}
    missing = []
    for i, s in enumerate(merged, start=1):
        s["id"] = f"s{i}"
        counts[s["kind"]] = counts.get(s["kind"], 0) + 1
        s["n"] = counts[s["kind"]]
        s.setdefault("notes", "")
        name = K.label(s["kind"]) + (f" #{s['n']}" if s["kind"] in K.GROUP_KINDS else "")
        if s.get("guess"):
            add_review(rec, f"{name}（資料夾 {'、'.join(s['folders'])}）在試算表沒有對應的步驟，種類是推測的", s["id"])
        if fsteps and ssteps and "folder" not in s.get("source", []) and s["kind"] in _COMPAT:
            missing.append(name)
    if missing:
        add_review(rec, f"試算表有、資料夾裡找不到對應資料夾的步驟：{'、'.join(missing)}（可能沒有拍照，或資料夾名稱看不出步驟）")
    if srow.get("stopped") and merged:                    # 試算表最後是「-」：停在最後一步
        rec["status"]["stopped_at"] = merged[-1]["id"]
    rec["steps"] = merged
    return rec


# ---------------------------------------------------------------------------
# 找樣品資料夾
# ---------------------------------------------------------------------------
def discover(root, rule=None, record_name=DEFAULT_RECORD_NAME, labels=(), max_depth=3):
    """在根目錄下找樣品資料夾。回傳 [{label, dir, project, record}]（record = 紀錄檔路徑，可能還不存在）。
    判斷：已經有紀錄檔、資料夾名稱是試算表裡的編號、或有 3 個以上看得出種類的「NN 名稱」子資料夾。"""
    root = os.path.normpath(str(root))
    if not root or not os.path.isdir(root):
        return []
    labels = {str(x).strip().lower() for x in labels}
    rx = F.compile_rule(rule)
    out = []

    def walk(path, depth):
        try:
            subs = sorted((e for e in os.scandir(path) if e.is_dir() and not e.name.startswith(".")
                           and e.name not in F.SKIP_DIRS), key=lambda e: e.name.lower())
        except OSError:
            return
        for e in subs:
            rp = record_path(e.path, record_name)
            is_sample = (os.path.isfile(rp) or e.name.strip().lower() in labels and F.looks_like_sample(e.path, rx, 1)
                         or F.looks_like_sample(e.path, rx))
            if is_sample:
                rel = os.path.relpath(path, root)
                out.append({"label": e.name.strip(), "dir": e.path, "project": "" if rel == "." else rel.replace(os.sep, " / "),
                            "record": rp})
            elif depth < max_depth:            # 不是樣品就往下找（「09 TaS2 project」「08 AFM study」這種專案資料夾）
                walk(e.path, depth + 1)

    if os.path.isfile(record_path(root, record_name)) or F.looks_like_sample(root, rx):
        return [{"label": os.path.basename(root), "dir": root, "project": "", "record": record_path(root, record_name)}]
    walk(root, 1)
    return out


# ---------------------------------------------------------------------------
# 樣品清單（資料夾 + 試算表 + 紀錄檔）
# ---------------------------------------------------------------------------
class Library:
    """一個使用者的所有樣品。scan() 在背景執行緒跑（雲端硬碟上可能要幾秒）。"""

    def __init__(self, base, user="", root="", rule=None, record_name=DEFAULT_RECORD_NAME):
        self.base = str(base)
        self.user = user or "me"
        self.root = root
        self.rule = rule
        self.record_name = record_name or DEFAULT_RECORD_NAME
        self.samples = []            # [{key, label, project, dir, path, rec, has_folder, sheet}]
        self.sheet_rows = []
        self.errors = []

    # ---- 試算表快取（離線也能看到上次匯入的內容）
    def cache_path(self):
        return os.path.join(local_dir(self.base, self.user), "_sheet_cache.json")

    def load_cache(self):
        try:
            with open(self.cache_path(), encoding="utf-8") as f:
                self.sheet_rows = json.load(f).get("rows", [])
        except (OSError, ValueError):
            self.sheet_rows = []
        return self.sheet_rows

    def save_cache(self, rows, source=""):
        p = self.cache_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"source": source, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "rows": rows}, f,
                      ensure_ascii=False)
        self.sheet_rows = rows

    def scan(self):
        """找資料夾、讀紀錄檔，和試算表快取合在一起。不會寫任何檔案。"""
        if not self.sheet_rows:
            self.load_cache()
        rows = {str(r["label"]).strip().lower(): r for r in self.sheet_rows}
        found = discover(self.root, self.rule, self.record_name, rows.keys()) if self.root else []
        dup = {}
        for f in found:
            dup[f["label"].lower()] = dup.get(f["label"].lower(), 0) + 1
        out, seen, self.errors = [], set(), []
        for f in found:
            lab = f["label"]
            proj = f["project"] if dup[lab.lower()] > 1 else ""
            rec = None
            if os.path.isfile(f["record"]):
                try:
                    rec = load(f["record"])
                except Exception as e:
                    self.errors.append(f"{f['record']}：{e}")
            out.append({"key": sample_key(self.user, lab, proj), "label": lab, "project": f["project"], "dir": f["dir"],
                        "path": f["record"], "rec": rec, "has_folder": True, "sheet": rows.get(lab.lower())})
            seen.add(lab.lower())
        for lab_low, r in rows.items():                    # 試算表有、找不到資料夾
            if lab_low in seen:
                continue
            p = local_path(self.base, self.user, r["label"])
            rec = None
            if os.path.isfile(p):
                try:
                    rec = load(p)
                except Exception as e:
                    self.errors.append(f"{p}：{e}")
            out.append({"key": sample_key(self.user, r["label"]), "label": r["label"], "project": "", "dir": "",
                        "path": p, "rec": rec, "has_folder": False, "sheet": r})
        out.sort(key=lambda s: _sort_key(s["label"]))
        self.samples = out
        return out

    def preview(self, s):
        """還沒有紀錄檔的樣品：即時產生初版紀錄（只在記憶體裡）。"""
        if s.get("rec") is None:
            s["rec_preview"] = s.get("rec_preview") or build(s["label"], self.user, s["project"], s["dir"],
                                                             s.get("sheet"), self.rule)
            return s["rec_preview"]
        return s["rec"]

    def import_all(self, overwrite=False, log=None):
        """沒有紀錄檔的樣品 → 建立初版紀錄檔（資料夾裡或這台電腦）。已經有的不動（除非 overwrite）。"""
        made, kept, failed = [], [], []
        for s in self.samples:
            if s.get("rec") is not None and not overwrite:
                kept.append(s["label"])
                continue
            try:
                rec = build(s["label"], self.user, s["project"], s["dir"], s.get("sheet"), self.rule)
                save(rec, s["path"])
                s["rec"] = rec
                s.pop("rec_preview", None)
                made.append(s["label"])
            except Exception as e:
                failed.append(f"{s['label']}：{e}")
        return made, kept, failed

    def reviews(self):
        out = []
        for s in self.samples:
            rec = s.get("rec") or s.get("rec_preview")
            if rec:
                out += [(s, r) for r in open_reviews(rec)]
        return out


def _sort_key(label):
    m = re.match(r"^\s*([A-Za-z ]*?)\s*(\d+)", str(label))
    if m:
        return (m.group(1).strip().lower() != "", m.group(1).strip().lower(), int(m.group(2)), str(label))
    return (True, str(label).lower(), 0, str(label))


def state_of(s):
    rec = s.get("rec") or s.get("rec_preview") or {}
    st = (rec.get("status") or {}).get("state")
    if st:
        return st
    sh = s.get("sheet") or {}
    return (sh.get("status") or {}).get("state", "active")
