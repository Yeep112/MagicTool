"""修改樣品紀錄：新增 / 編輯 / 刪除 / 搬移步驟、擱置 / 放棄、結果。

全部只改記憶體裡的 rec（dict），存檔交給 records.save。每次修改都記一行在 rec["log"]（最多留 200 行），
之後可以看出誰在什麼時候改了什麼。
"""
from __future__ import annotations

import copy
import re
import time

from . import steps as K

LOG_MAX = 200


def _now():
    return time.strftime("%Y-%m-%d %H:%M")


def log(rec, action, step="", user=""):
    rec.setdefault("log", []).append({"time": _now(), "action": action, "step": step, "user": user})
    del rec["log"][:-LOG_MAX]


def next_id(rec):
    nums = [int(m.group(1)) for s in rec.get("steps", []) for m in [re.fullmatch(r"s(\d+)", str(s.get("id", "")))] if m]
    return f"s{max(nums, default=0) + 1}"


def renumber(rec):
    """同一種步驟依序編號（Contact #1、#2…）。"""
    counts = {}
    for s in rec.get("steps", []):
        counts[s["kind"]] = counts.get(s["kind"], 0) + 1
        s["n"] = counts[s["kind"]]


def new_step(kind, rec=None):
    """空白的一步（預設參數：轉移 → 依樣品類型猜堆疊）。"""
    st = {"kind": kind, "params": {}, "substeps": [], "folders": [], "date": "", "date_end": "",
          "source": ["manual"], "raw": [], "notes": "", "edited": True}
    if kind == "transfer":
        st["params"]["layers"] = K.stack_from_type((rec or {}).get("type", ""))
    return st


def find(rec, sid):
    return next((s for s in rec.get("steps", []) if s.get("id") == sid), None)


def index(rec, sid):
    return next((i for i, s in enumerate(rec.get("steps", [])) if s.get("id") == sid), None)


def insert_step(rec, step, after=None, user=""):
    """after = 步驟 id（插在它後面）；None = 加在最後面。回傳新步驟的 id。"""
    step = copy.deepcopy(step)
    step["id"] = next_id(rec)
    step["edited"] = True
    steps = rec.setdefault("steps", [])
    i = index(rec, after)
    steps.insert(len(steps) if i is None else i + 1, step)
    renumber(rec)
    log(rec, f"新增 {K.step_name(step)}", step["id"], user)
    return step["id"]


def update_step(rec, sid, new, user=""):
    i = index(rec, sid)
    if i is None:
        raise KeyError(sid)
    old = rec["steps"][i]
    step = copy.deepcopy(new)
    step["id"] = sid
    step["edited"] = True
    for k in ("source", "raw", "implied"):                 # 來源與試算表原文留著（看得出這一步從哪裡來）
        if k in old and k not in step:
            step[k] = copy.deepcopy(old[k])
    step.pop("guess", None)                                  # 使用者看過、改過 → 不再是推測
    rec["steps"][i] = step
    renumber(rec)
    log(rec, f"修改 {K.step_name(step)}", sid, user)
    return step


def delete_step(rec, sid, user=""):
    i = index(rec, sid)
    if i is None:
        return None
    step = rec["steps"].pop(i)
    renumber(rec)
    st = rec.setdefault("status", {})
    if st.get("stopped_at") == sid:
        st["stopped_at"] = rec["steps"][i - 1]["id"] if i > 0 and rec["steps"] else None
    log(rec, f"刪除 {K.step_name(step)}", sid, user)
    return step


def move_step(rec, sid, delta, user=""):
    i = index(rec, sid)
    if i is None:
        return False
    j = i + delta
    if not 0 <= j < len(rec["steps"]):
        return False
    rec["steps"][i], rec["steps"][j] = rec["steps"][j], rec["steps"][i]
    for k in (i, j):
        rec["steps"][k]["edited"] = True
    renumber(rec)
    log(rec, f"{'上移' if delta < 0 else '下移'} {K.step_name(rec['steps'][j])}", sid, user)
    return True


def set_state(rec, state, reason="", next_date="", nxt=None, user=""):
    """製作中 / 擱置 / 量測中 / 已量測 / 放棄。放棄會記下停在哪一步（最後一步）。"""
    if state not in K.STATES:
        raise ValueError(state)
    st = rec.setdefault("status", {})
    prev = st.get("state", "active")
    st["state"] = state
    st["reason"] = reason if state in ("hold", "abandoned") else ""
    if next_date is not None:
        st["next_date"] = next_date
    if nxt is not None:
        st["next"] = nxt
    if state == "abandoned":
        st["stopped_at"] = rec["steps"][-1]["id"] if rec.get("steps") else None
    elif prev == "abandoned":
        st["stopped_at"] = None
    st["changed"] = _now()
    log(rec, f"狀態：{K.state_label(prev)} → {K.state_label(state)}" + (f"（{reason}）" if reason else ""), "", user)


def set_results(rec, r_ohm=None, sc_contact=None, sc_on="", tc_k=None, note=None, source="", user=""):
    res = rec.setdefault("results", {})
    res.update({"r_ohm": r_ohm, "sc_contact": sc_contact, "sc_on": sc_on or "", "tc_k": tc_k})
    if note is not None:
        res["note"] = note
    if source:
        res["source"] = source
    res["updated"] = _now()
    if (r_ohm is not None or tc_k is not None) and rec.get("status", {}).get("state") in ("active", "measuring", None):
        set_state(rec, "measured", user=user)
    log(rec, "更新結果" + (f"（來自 {source}）" if source else ""), "", user)


def num(text):
    """輸入框文字 → 數字（空白 → None；看不懂 → ValueError）。"""
    t = str(text if text is not None else "").strip().replace(",", "")
    if not t:
        return None
    x = float(t)
    return int(x) if x.is_integer() else x
