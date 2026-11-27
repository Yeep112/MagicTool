"""掃描樣品資料夾：子資料夾 → 步驟、照片、資料檔、日期。

預設命名規則「NN 步驟名稱」（例如 05 Lithography、14 Cover hBN）；每個人可以在設定裡改成自己的規則
（一個正規表示式，第一組 = 編號、第二組 = 名稱）。步驟種類從名稱的關鍵字判斷（Lithography、Lift Off、AFM…）。
日期從照片檔名讀：20250410_140104、102_250411_…、0731-0001（月日，年份用樣品開始日期推）。
"""
from __future__ import annotations

import os
import re
from datetime import date

DEFAULT_RULE = r"^\s*(\d{1,3})\s*[ _.\-]?\s*(.+?)\s*$"
RULE_PRESETS = [("NN 名稱（例如 05 Lithography）", DEFAULT_RULE),
                ("名稱_NN（例如 Lithography_05）", r"^\s*(?P<name>.+?)\s*[ _.\-]\s*(?P<no>\d{1,3})\s*$")]

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".gif"}
DATA_EXT = {".db", ".dat", ".txt", ".csv", ".ipynb", ".xlsx", ".xls", ".dwg", ".dxf", ".gds", ".spe", ".wdf",
            ".h5", ".hdf5", ".pptx", ".pdf", ".json", ".npz", ".mat"}
SKIP_DIRS = {"__pycache__", ".ipynb_checkpoints", ".vscode", ".git", "@eaDir", "#recycle"}

# 名稱關鍵字 → 種類（由上往下，先對到的算）
KEYWORDS = [
    (r"design|設計|cad|layout", "design"),
    (r"cover\s*h?bn|top\s*h?bn|cover", "cover"),
    (r"transfer|stack|轉移|堆疊", "transfer"),
    (r"clean|清潔|anneal", "cleaning"),
    (r"after\s*meas|量測後", "inspection"),
    (r"litho|曝光|顯影|ebl|raith|expos", "lithography"),
    (r"lift\s*-?\s*off|剝離", "liftoff"),
    (r"\bafm\b|afm", "afm"),
    (r"raman", "raman"),
    (r"bond|打線", "bonding"),
    (r"data\s*anal|analysis|分析", "analysis"),
    (r"meas|量測|ppms|squid|transport|低溫", "measurement"),
    (r"marker", "lithography"),
    (r"contact|electrode|電極", "lithography"),
    (r"\brie\b|etch|蝕刻|plasma|icp|mill", "rie"),
    (r"evap|sputter|depos|鍍", "deposit"),
    (r"\bom\b|optical|inspect|照片|photo", "inspection"),
]


# Windows：只在雲端、還沒下載的檔案（Synology Drive / OneDrive 的「隨選同步」）。讀內容會觸發下載。
_CLOUD_ATTRS = 0x400000 | 0x40000 | 0x1000      # RECALL_ON_DATA_ACCESS、RECALL_ON_OPEN、OFFLINE


def is_cloud_only(path):
    try:
        return bool(getattr(os.stat(path), "st_file_attributes", 0) & _CLOUD_ATTRS)
    except OSError:
        return False


def compile_rule(rule):
    try:
        return re.compile(rule or DEFAULT_RULE)
    except re.error:
        return re.compile(DEFAULT_RULE)


def match_folder(name, rule=None):
    """「05 Lithography」→ (5, 'Lithography')；不符合規則 → None。"""
    rx = rule if hasattr(rule, "match") else compile_rule(rule)
    m = rx.match(name)
    if not m:
        return None
    gd = m.groupdict()
    no, nm = (gd.get("no"), gd.get("name")) if gd else (m.group(1), m.group(2))
    try:
        return int(no), nm.strip()
    except (TypeError, ValueError):
        return None


def folder_kind(name):
    low = name.lower()
    for rx, kind in KEYWORDS:
        if re.search(rx, low):
            return kind
    return "other"


# ---------------------------------------------------------------------------
# 檔名 → 日期
# ---------------------------------------------------------------------------
def _valid(y, m, d):
    try:
        dt = date(y, m, d)
    except ValueError:
        return None
    return dt if 2010 <= y <= 2040 else None


def file_date(name, start=""):
    """回傳 date 或 None。start = 樣品開始日期（ISO），用來推「0731-0001」這種只有月日的年份。"""
    m = re.search(r"(?<!\d)(20\d{2})[-_.]?(\d{2})[-_.]?(\d{2})(?!\d)", name)
    if m:
        dt = _valid(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if dt:
            return dt
    m = re.search(r"(?<![\d.])(\d{2})(\d{2})(\d{2})(?![\d.])", name)
    if m and 15 <= int(m.group(1)) <= 40:
        dt = _valid(2000 + int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if dt:
            return dt
    m = re.match(r"^(\d{2})(\d{2})-\d{3,4}", name)
    if m:
        y = int(start[:4]) if start else date.today().year
        dt = _valid(y, int(m.group(1)), int(m.group(2)))
        if dt and start and dt.isoformat() < start:
            dt = _valid(y + 1, int(m.group(1)), int(m.group(2)))
        return dt
    return None


# ---------------------------------------------------------------------------
# 掃描
# ---------------------------------------------------------------------------
def _files(path, depth=2):
    out = []
    try:
        entries = sorted(os.scandir(path), key=lambda e: e.name.lower())
    except OSError:
        return out
    for e in entries:
        if e.name.startswith((".", "~$")) or e.name in SKIP_DIRS:
            continue
        try:
            if e.is_dir():
                if depth > 1:
                    out += _files(e.path, depth - 1)
            else:
                out.append(e.path)
        except OSError:
            pass
    return out


def scan_folder(path, start=""):
    """一個步驟資料夾 → {images, data, dates}（含一層子資料夾，例如 00 Design\\digitalize）"""
    imgs, data, dates = [], [], []
    for f in _files(path):
        ext = os.path.splitext(f)[1].lower()
        if ext in IMAGE_EXT:
            imgs.append(f)
        elif ext in DATA_EXT:
            data.append(f)
        else:
            continue
        dt = file_date(os.path.basename(f), start)
        if dt:
            dates.append(dt)
    dates.sort()
    return {"images": imgs, "data": data,
            "date": dates[0].isoformat() if dates else "", "date_end": dates[-1].isoformat() if dates else ""}


def step_folders(sample_dir, rule=None, start=""):
    """樣品資料夾 → [{no, name, folder, kind, path, images, data, date, date_end}]（依編號排序）"""
    rx = compile_rule(rule) if not hasattr(rule, "match") else rule
    out = []
    try:
        entries = list(os.scandir(sample_dir))
    except OSError:
        return out
    for e in entries:
        try:
            if not e.is_dir() or e.name.startswith(".") or e.name in SKIP_DIRS:
                continue
        except OSError:
            continue
        m = match_folder(e.name, rx)
        if not m:
            continue
        no, name = m
        info = scan_folder(e.path, start)
        out.append({"no": no, "name": name, "folder": e.name, "kind": folder_kind(name), "path": e.path, **info})
    out.sort(key=lambda d: (d["no"], d["folder"]))
    return out


def loose_files(sample_dir):
    """樣品資料夾最外層的檔案（例如 summary_102.pptx）。"""
    out = []
    try:
        for e in os.scandir(sample_dir):
            if e.is_file() and not e.name.startswith((".", "~$")):
                out.append(e.path)
    except OSError:
        pass
    return sorted(out)


def looks_like_sample(path, rule=None, min_steps=3):
    """不知道是不是樣品資料夾時：至少有 min_steps 個符合命名規則、而且看得出種類的子資料夾。"""
    rx = compile_rule(rule) if not hasattr(rule, "match") else rule
    n = 0
    try:
        for e in os.scandir(path):
            if e.is_dir() and not e.name.startswith("."):
                m = match_folder(e.name, rx)
                if m and folder_kind(m[1]) != "other":
                    n += 1
                    if n >= min_steps:
                        return True
    except OSError:
        return False
    return False


# ---------------------------------------------------------------------------
# 資料夾 → 步驟（微影 + lift-off 合成一組）
# ---------------------------------------------------------------------------
_BREAK = {"lithography", "transfer", "cover", "bonding", "measurement", "design", "analysis"}


def group_folders(entries):
    """「05 Lithography + 06 Lift Off」→ 一組（還不知道是 marker 還是 contact，種類先寫 litho_group）。
    中間夾著的 AFM、Raman、OM 檢查（例如 15 Lithography、16 AFM、17 Lift Off）各自是一步。"""
    out, i = [], 0
    while i < len(entries):
        e = entries[i]
        if e["kind"] == "lithography":
            j = i + 1
            while j < len(entries) and entries[j]["kind"] not in ("liftoff",) and entries[j]["kind"] not in _BREAK:
                j += 1
            if j < len(entries) and entries[j]["kind"] == "liftoff":
                out.append({"kind": "litho_group", "folders": [e, entries[j]]})
                out.extend({"kind": m["kind"], "folders": [m]} for m in entries[i + 1:j])
                i = j + 1
                continue
            out.append({"kind": "litho_group", "folders": [e]})
            i += 1
            continue
        if e["kind"] == "liftoff":
            out.append({"kind": "litho_group", "folders": [e]})
        else:
            out.append({"kind": e["kind"], "folders": [e]})
        i += 1
    out.sort(key=lambda s: s["folders"][0]["no"])
    return out
