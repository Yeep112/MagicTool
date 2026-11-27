"""v0.7：步驟編輯、狀態 / 結果、RIE 時間建議、寫回試算表（全部用合成資料）。"""
import copy

import pytest

from magic import testdata
from magic.etching.gsync import GspreadSheet
from magic.fab import edit as E
from magic.fab import etchrate as ER
from magic.fab import records as R
from magic.fab import sheet as SH
from magic.fab import sheet_sync as SS
from magic.fab import steps as K


@pytest.fixture()
def demo(tmp_path):
    p = testdata.write_samples(str(tmp_path))
    rows = SH.parse_table(SH.read_file(p["sheet"]))
    lib = R.Library(str(tmp_path / "data"), "demo", p["root"])
    lib.save_cache(rows, p["sheet"])
    lib.scan()
    return p, rows, lib


def _rec(lib, label):
    s = next(x for x in lib.samples if x["label"] == label)
    return s, copy.deepcopy(lib.preview(s))


def test_insert_update_delete_move(demo):
    _, _, lib = demo
    _, rec = _rec(lib, "901")
    n0 = len(rec["steps"])
    c = E.new_step("contact", rec)
    c["substeps"] = [{"kind": "rie", "params": {"hbn_nm": 40, "oe_nm": 3, "time_s": 18}},
                     {"kind": "deposit", "params": {"layers": [["Cr", 10], ["Au", 70]], "method": "E"}}]
    sid = E.insert_step(rec, c, after=rec["steps"][2]["id"])
    assert len(rec["steps"]) == n0 + 1 and rec["steps"][3]["id"] == sid
    contacts = [s for s in rec["steps"] if s["kind"] == "contact"]
    assert [s["n"] for s in contacts] == list(range(1, len(contacts) + 1))
    new = copy.deepcopy(E.find(rec, sid))
    new["notes"] = "改過"
    E.update_step(rec, sid, new)
    assert E.find(rec, sid)["notes"] == "改過" and E.find(rec, sid)["edited"]
    assert E.move_step(rec, sid, -1) and rec["steps"][2]["id"] == sid
    assert not E.move_step(rec, rec["steps"][0]["id"], -1)
    E.delete_step(rec, sid)
    assert len(rec["steps"]) == n0 and E.find(rec, sid) is None
    assert len(rec["log"]) == 4


def test_state_and_results(demo):
    _, _, lib = demo
    _, rec = _rec(lib, "902")
    E.set_state(rec, "hold", "等 Raith", "2026-12-03")
    assert SS.status_text(rec) == "擱置 等 Raith (12/3)"
    E.set_state(rec, "abandoned", "破了")
    assert rec["status"]["stopped_at"] == rec["steps"][-1]["id"] and SS.status_text(rec) == "-"
    E.set_state(rec, "active")
    assert rec["status"]["stopped_at"] is None
    E.set_results(rec, r_ohm=1700, sc_contact=True, sc_on="TaS2", tc_k=4.2)
    assert rec["status"]["state"] == "measured"
    txt = SS.status_text(rec)
    assert txt == "measured R_1700 (SC) sc on TaS2 Tc_4.2K"
    back = SH.parse_status(txt)
    assert back["state"] == "measured" and back["results"] == {"r_ohm": 1700, "sc_contact": True, "sc_on": "TaS2",
                                                                "tc_k": 4.2}


def test_process_round_trip(demo):
    """軟體產生的文字，用匯入程式讀回來要得到同樣的步驟與參數。"""
    _, rows, lib = demo
    for label in ("901", "904", "al 906", "907"):
        _, rec = _rec(lib, label)
        for s in rec["steps"]:
            s["edited"] = True                                # 強迫全部重新產生（不抄原文）
        cells = SS.process_cells(rec)
        steps, issues, _ = SH.parse_process(cells)
        mine = [s for s in rec["steps"] if SS.in_sheet(s)]
        assert [s["kind"] for s in steps] == [s["kind"] for s in mine], (label, cells)
        for a, b in zip(mine, steps):
            sa = [(x["kind"], x.get("params")) for x in a.get("substeps", []) if x["kind"] not in ("lithography", "liftoff")]
            sb = [(x["kind"], x.get("params")) for x in b.get("substeps", [])]
            assert sa == sb, (label, a, b)
        assert not [i for i in issues if "看不懂" in i], (label, issues)


def test_unedited_steps_keep_original_text(demo):
    _, rows, lib = demo
    _, rec = _rec(lib, "al 906")
    cells = SS.process_cells(rec)
    assert "hBN_40.17 RIE_17s OE_4.03nm" in cells and "Ion miling 18mA 30height_120s" in cells


def test_push_update_and_append(demo):
    p, rows, lib = demo
    ws = testdata.FakeWorksheet([list(r) for r in testdata.SAMPLE_SHEET])
    sh = GspreadSheet(ws)
    _, rec = _rec(lib, "902")
    E.set_state(rec, "hold", "等 Raith", "2026-12-03")
    rie = E.new_step("contact", rec)
    rie["substeps"] = [{"kind": "rie", "params": {"hbn_nm": 41.2, "oe_nm": 3, "time_s": 19}},
                       {"kind": "deposit", "params": {"layers": [["Cr", 10], ["Au", 70]], "method": "E"}}]
    E.insert_step(rec, rie)
    act, row = SS.push(rec, sh)
    assert act == "update" and row == 3
    vals = ws.get_all_values()
    head = vals[0]
    r = vals[2]
    assert r[head.index("Status")] == "擱置 等 Raith (12/3)" and r[head.index("Label")] == "902"
    proc = [c for c in r[head.index("Process"):head.index("備註")] if c]
    assert proc[-3:] == ["contact", "hBN_41.2 RIE_19s OE_3nm", "Cr/Au_10/70 (E)"]
    assert SS.push(rec, sh) == ("same", 3)
    # 新樣品 → 加在最後一筆資料下面
    new = {"label": "950", "type": "Tri-TaS2", "start": "2026-11-27", "status": {"state": "active", "next": "transfer"},
           "results": {}, "steps": [], "notes": ""}
    act, row = SS.push(new, sh)
    assert act == "append" and row == len(testdata.SAMPLE_SHEET) + 1
    assert ws.get_all_values()[row - 1][head.index("Label")] == "950"
    # 讀回來：整張表解析得出來，902 有新的 contact
    back = {x["label"]: x for x in SH.parse_table(ws.get_all_values())}
    assert back["902"]["status"]["state"] == "hold" and back["902"]["steps"][-1]["kind"] == "contact"


def test_push_shrinks_and_overflows(demo):
    _, rows, lib = demo
    ws = testdata.FakeWorksheet([list(r) for r in testdata.SAMPLE_SHEET])
    sh = GspreadSheet(ws)
    _, rec = _rec(lib, "901")
    rec["steps"] = rec["steps"][:2]
    for s in rec["steps"]:
        s["edited"] = True
    SS.push(rec, sh)
    r = ws.get_all_values()[1]
    head = ws.get_all_values()[0]
    proc = r[head.index("Process"):head.index("備註")]
    assert [c for c in proc if c] == SS.process_cells(rec) and r[head.index("備註")] == "範例"
    ci = SS.columns(head)
    many = {"label": "x", "steps": [dict(E.new_step("afm"), params={"hbn_nm": i}) for i in range(30)]}
    cells = dict(SS.row_cells(many, ci))
    span = ci["process_end"] - ci["process"]
    assert " | " in cells[ci["process"] + span - 1] and ci["remark"] not in cells


def test_push_inserts_columns(demo):
    """Process 格子不夠 → 在「備註」前面整欄插入，其他列的備註跟著移、不會錯位。"""
    _, rows, lib = demo
    ws = testdata.FakeWorksheet([list(r) for r in testdata.SAMPLE_SHEET])
    sh = GspreadSheet(ws)
    _, rec = _rec(lib, "901")
    for i in range(12):
        E.insert_step(rec, dict(E.new_step("afm"), params={"hbn_nm": 30 + i}))
    need = len(SS.process_cells(rec))
    SS.push(rec, sh)
    vals = ws.get_all_values()
    head = vals[0]
    assert head.index("備註") - head.index("Process") == need
    assert vals[1][head.index("備註")] == "範例"
    assert [c for c in vals[1][head.index("Process"):head.index("備註")] if c] == SS.process_cells(rec)
    back = {x["label"]: x for x in SH.parse_table(vals)}
    assert back["901"]["raw"]["remark"] == "範例" and back["904"]["steps"]


def test_rie_suggestion(demo):
    _, rows, lib = demo
    recs = [lib.preview(s) for s in lib.samples]
    hist = ER.history(recs, "rie")
    assert hist and all(h["rate"] > 0 for h in hist)
    al = [h for h in hist if h["label"] == "al 906"]
    assert al and abs(al[0]["rate"] - (40.17 + 4.03) / 17) < 1e-6
    rates, src = ER.rates_for(recs, None, "rie")
    sug = ER.suggest(40, 3, rates, src)
    assert sug and sug["low"] <= sug["time_s"] <= sug["high"] and "建議" in sug["text"]
    assert ER.suggest(None, 3, rates) is None and ER.suggest(40, 3, []) is None


def test_rie_from_etch_log():
    import pandas as pd
    df = pd.DataFrame([{"Method": "RIE", "Material": "hBN", "R_hBN(nm/sec)": "2.0", "Name": "A", "DateTime": "2026-01-01"},
                       {"Method": "ICP", "Material": "hBN", "R_hBN(nm/sec)": "1.0"},
                       {"Method": "RIE", "Material": "SiO2", "R_hBN(nm/sec)": "9"}])
    rates, src = ER.rates_for([], df, "rie")
    assert [r["rate"] for r in rates] == [2.0] and "Etching" in src
    assert ER.suggest(40, 0, rates)["time_s"] == 20


def test_layers_and_stack():
    assert K.parse_layers("Cr/Au 10/70") == [["Cr", 10], ["Au", 70]]
    assert K.parse_layers("hBN 20 / TaS2 / hBN 40") == [["hBN", 20], ["TaS2", None], ["hBN", 40]]
    assert K.parse_layers("???") is None
    assert K.format_layers([["Cr", 10], ["Au", 70]]) == "Cr/Au 10/70"
    assert K.stack_from_type("Quad-NbSe2")[1][0] == "NbSe2"
    assert K.params_text("deposit", {"layers": [["Cr", 10]], "method": "E"}, "en")[1] == ("Method",
                                                                                          "E-beam evaporation (E)")


def test_sample_sheet_via_apps_script(tmp_path, monkeypatch, demo):
    """樣品試算表用同一份 Apps Script：更新、插欄、新增，讀回來一致。"""
    import json
    import shutil
    import socket
    import subprocess
    import urllib.request
    from pathlib import Path
    from magic.etching import gsync
    node = shutil.which("node")
    if not node:
        pytest.skip("沒有 Node.js")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"title": "Sample Tracking（測試）", "sheets": [
        {"name": "工作表1", "id": 0, "rows": testdata.SAMPLE_SHEET}]}), encoding="utf-8")
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        port = so.getsockname()[1]
    proc = subprocess.Popen([node, str(Path(__file__).with_name("apps_script_harness.js")), "serve", str(port), str(seed)],
                            stdout=subprocess.PIPE, text=True)
    try:
        line = proc.stdout.readline().split()
        url = f"http://127.0.0.1:{port}"
        sh = gsync.ScriptSheet("https://script.google.com/macros/s/test/exec", line[1])
        sh.url = url
        _, _, lib = demo
        _, rec = _rec(lib, "901")
        for i in range(10):
            E.insert_step(rec, dict(E.new_step("afm"), params={"hbn_nm": 30 + i}))
        E.set_results(rec, r_ohm=1500, sc_contact=True, tc_k=4.1)
        assert SS.push(rec, sh)[0] == "update"
        assert SS.push({"label": "960", "type": "x", "start": "", "status": {"state": "active"}, "results": {},
                        "steps": [], "notes": ""}, sh)[0] == "append"
        with urllib.request.urlopen(url + "/__state") as r:
            st = json.loads(r.read().decode("utf-8"))
        vals = st["sheets"][0]["rows"]
        back = {x["label"]: x for x in SH.parse_table(vals)}
        assert back["901"]["results"]["tc_k"] == 4.1 and back["901"]["steps"][-1]["params"] == {"hbn_nm": 39}
        assert back["901"]["raw"]["remark"] == "範例" and "960" in back
        hist = next(x for x in st["sheets"] if x["name"] == "MagicTool 修改紀錄")["rows"]
        assert hist[1][1] == "修改"
    finally:
        proc.terminate()
        proc.wait(5)
