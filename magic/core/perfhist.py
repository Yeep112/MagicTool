"""流暢度紀錄：每次在你電腦上發佈前的檢查（selftest --release）量到的數字，存在設定資料夾的 perf_history.csv。

雲端測試機是共用虛擬機，數字抖動很大、不能拿來比；真正有意義的是同一台電腦、版本和版本之間的比較。
發佈時會印出「和上一版比」，明顯變慢會提醒（但不擋發佈，擋發佈的是固定門檻）。
"""
from __future__ import annotations

import csv
import os
import platform
import sys
import time

FILE = "perf_history.csv"
FIELDS = ["time", "version", "machine", "python", "switch_med", "switch_max", "bg_gap", "draw_max", "anim_max"]
LABELS = {"switch_max": "切換機台最慢", "bg_gap": "背景計算時畫面停頓", "anim_max": "蝕刻動畫最長一格",
          "draw_max": "單張圖最久繪製"}
SLOWER = 1.3          # 比上一版慢 30% 以上，而且多 15 ms 以上 → 提醒
SLOWER_MS = 15.0


def path(base=None):
    if base is None:
        from .settings import data_dir
        base = data_dir()
    return os.path.join(str(base), FILE)


def machine():
    return f"{platform.node() or '?'} / {platform.system()} {platform.release()}"


def read_all(base=None):
    try:
        with open(path(base), encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))
    except OSError:
        return []


def last(base=None, same_machine=True):
    rows = read_all(base)
    if same_machine:
        rows = [r for r in rows if r.get("machine") == machine()]
    return rows[-1] if rows else None


def append(values, version, base=None):
    rec = {"time": time.strftime("%Y-%m-%d %H:%M"), "version": version, "machine": machine(),
           "python": sys.version.split()[0]}
    rec.update({k: f"{float(values[k]):.1f}" for k in FIELDS[4:] if k in values})
    fp = path(base)
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    new = not os.path.exists(fp)
    with open(fp, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(rec)
    return rec


def compare(prev, cur):
    """回傳 (說明行, 明顯變慢的項目)。"""
    if not prev:
        return ["（這台電腦第一次記錄流暢度，下次發佈開始會和這次比較）"], []
    lines, slower = [f"和上一次比（v{prev.get('version')}，{prev.get('time')}）："], []
    for k, label in LABELS.items():
        try:
            a, b = float(prev[k]), float(cur[k])
        except (KeyError, TypeError, ValueError):
            continue
        mark = ""
        if b > a * SLOWER and b - a > SLOWER_MS:
            mark = "　⚠ 明顯變慢"
            slower.append(label)
        elif a > 0 and b < a * 0.77:
            mark = "　↓ 變快"
        lines.append(f"    {label}：{a:.0f} → {b:.0f} ms{mark}")
    return lines, slower
