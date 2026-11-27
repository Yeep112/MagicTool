"""Google Sheet 同步（gsync）：欄位用名稱對應、不蓋掉自己加的欄位、Apps Script 寫入程式（用 Node 模擬）。
全部用合成資料，不連網路。"""
import json
import math
import shutil
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from magic.etching import gsync, store  # noqa: E402
from magic.etching.model import EtchInput, compute  # noqa: E402
from magic.testdata import FakeWorksheet, team_sheet_values  # noqa: E402

HERE = Path(__file__).resolve().parent


def _rec(name="Cat", mat_out="40", notes=""):
    inp = EtchInput(material="hBN", steps="20+20", sio2_method="marker", marker_before="50", marker_out="55",
                    mat_method="outside", mat_before="100", mat_out=mat_out, name=name, notes=notes)
    r = store.make_record(inp, compute(inp))
    r["Record ID"] = store.new_id()
    r["Revision"] = 1
    return r


def _clean(d):
    return {k: ("" if isinstance(v, float) and math.isnan(v) else v) for k, v in d.items() if k in store.HEADERS}


def test_read_team_sheet():
    df = gsync.rows_to_df(team_sheet_values())
    assert len(df) == 5                                    # 空白列、只有空格的列不算
    assert df["Notes"].tolist()[0] == "#01" and df["Notes"].tolist()[2] == "baked 60 min"
    assert df["ICP power (W)"].tolist()[:3] == [60, 60, 100]
    assert df["RF power (W)"].iloc[2] == 8 and df["DC bias (V)"].iloc[0] == 10   # 8W = RF bias、10V = DC bias
    assert df["Material"].eq("hBN").all() and df["Schema"].eq("1").all()
    assert df["DateTime_parsed"].notna().all()
    assert math.isclose(df["R_hBN(nm/sec)"].iloc[0], 14.8 / 45, rel_tol=1e-9)


def test_append_keeps_existing_columns():
    vals = team_sheet_values()
    ws = FakeWorksheet(vals)
    rec = _rec(notes="=1+1 不是公式")
    rec["Record ID"] = "12e45"                              # 看起來像數字的 ID 要保持文字
    rows = gsync.append_records(gsync.GspreadSheet(ws), [rec])
    v = ws.get_all_values()
    assert rows == [7]                                     # 最後一筆資料的下一列
    assert v[0][:21] == vals[0]                            # 原本 21 欄（含 note）不動
    assert v[0][21:] == [c for c in store.EXTRA if c != "Notes"]
    assert [r[20] for r in v[1:6]] == [r[20] for r in vals[1:6]]   # 舊的 note 還在
    assert v[6][20] == "=1+1 不是公式" and v[6][v[0].index("Record ID")] == "12e45"
    assert ws.col_count >= len(v[0])
    back = gsync.rows_to_df(v)
    assert len(back) == 6 and back["Record ID"].iloc[-1] == "12e45"
    assert math.isclose(back["R_hBN(nm/sec)"].iloc[-1], 65 / 40)


def test_unknown_columns_and_formulas_untouched():
    vals = team_sheet_values()
    vals[0] = vals[0][:5] + ["我的欄位"] + vals[0][5:]
    for r in vals[1:]:
        r.insert(5, "x" if any(c.strip() for c in r) else "")
    ws = FakeWorksheet(vals)
    rec = _rec()
    gsync.append_records(gsync.GspreadSheet(ws), [rec])
    i = gsync.update_record(gsync.GspreadSheet(ws), rec["Record ID"], dict(rec, Name="Dan"), rec)
    v = ws.get_all_values()
    assert v[i - 1][5] == "" and v[1][5] == "x"            # 認不得的欄位不寫
    assert v[i - 1][v[0].index("Name")] == "Dan"
    for call in ws.calls:                                  # 沒有任何一次寫到「我的欄位」那一欄
        if call[0] == "update" and call[1][1:] != "1":
            col0 = FakeWorksheet._parse(call[1])[1]
            assert not (col0 <= 5 < col0 + len(call[2][0])), call


def test_update_delete_and_legacy_match():
    ws = FakeWorksheet(team_sheet_values())
    sheet = gsync.GspreadSheet(ws)
    a, b = _rec("A"), _rec("B", "41")
    gsync.append_records(sheet, [a, b])
    gsync.update_record(sheet, b["Record ID"], dict(b, Notes="改過"), b)
    df = gsync.rows_to_df(ws.get_all_values())
    assert df.set_index("Record ID").loc[b["Record ID"], "Notes"] == "改過"
    gsync.delete_record(sheet, a["Record ID"], a)
    df = gsync.rows_to_df(ws.get_all_values())
    assert a["Record ID"] not in set(df["Record ID"]) and len(df) == 6
    old = _clean(df.iloc[2].to_dict())                     # 沒有 Record ID 的舊紀錄：用日期 + 厚度找
    old["Record ID"] = "local-id"
    i = gsync.update_record(sheet, "local-id", dict(old, Notes="legacy"), old)
    v = ws.get_all_values()
    assert i == 4 and v[3][20] == "legacy" and v[3][v[0].index("Record ID")] == "local-id"
    with pytest.raises(store.SheetError):
        gsync.update_record(sheet, "沒有這個", dict(b), None)


def test_refuse_unknown_header():
    with pytest.raises(store.SheetError):
        gsync.append_records(gsync.GspreadSheet(FakeWorksheet([["A", "B"], ["1", "2"]])), [_rec()])


def test_store_wrappers_compatible():
    ws = FakeWorksheet([])
    assert store.ensure_sheet_header(ws) == "new" and ws.get_all_values()[0] == store.HEADERS
    ws = FakeWorksheet([store.V1])
    assert store.ensure_sheet_header(ws) == "upgraded" and ws.get_all_values()[0] == store.HEADERS
    assert store.ensure_sheet_header(ws) == "ok"


def test_diff_import_upload(tmp_path):
    p = tmp_path / "log.csv"
    store.append_record(_rec("Cat"), p)
    sheet_df = gsync.rows_to_df(team_sheet_values())
    only_sheet, only_local = gsync.diff(store.read_log(p), sheet_df)
    assert len(only_sheet) == 5 and len(only_local) == 1
    n, backup = gsync.import_to_local(only_sheet, p)
    assert n == 5 and backup and backup.exists()
    loc = store.read_log(p)
    assert len(loc) == 6 and loc["Name"].iloc[0] == "Ann" and loc["Name"].iloc[-1] == "Cat"   # 依日期排序
    assert loc["Record ID"].astype(bool).all()
    assert gsync.diff(loc, sheet_df)[0] == []                                                  # 不會重複匯入
    ws = FakeWorksheet(team_sheet_values())
    gsync.append_records(gsync.GspreadSheet(ws), gsync.diff(loc, sheet_df)[1])
    assert gsync.diff(loc, gsync.rows_to_df(ws.get_all_values())) == ([], [])


def test_team_code_roundtrip():
    cfg = {"etching": {"gsheet_key": "https://docs.google.com/spreadsheets/d/abc/edit#gid=0",
                       "gsheet_script_url": "https://script.google.com/macros/s/X/exec", "gsheet_token": "t0k"}}
    code = gsync.make_code(cfg)
    assert code.startswith("MAGIC-SHEET:")
    d = gsync.parse_code("  " + code[:20] + "\n" + code[20:])
    assert d["gsheet_token"] == "t0k" and d["gsheet_script_url"].endswith("/exec")
    with pytest.raises(store.SheetError):
        gsync.parse_code("亂打的")


def test_norm_dt():
    assert gsync._norm_dt("2026/5/7 下午 2:03:04") == "2026-05-07 14:03"
    assert gsync._norm_dt("2026-05-07 0:02:48") == "2026-05-07 00:02"
    assert gsync._norm_dt("2026-05-07T12:30") == "2026-05-07 12:30"


# ---------------------------------------------------------------------------
# Apps Script（Node 模擬）
# ---------------------------------------------------------------------------
def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def script_server(tmp_path, monkeypatch):
    node = shutil.which("node")
    if not node:
        pytest.skip("沒有 Node.js")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"title": "蝕刻紀錄（測試）", "sheets": [
        {"name": "工作表1", "id": 0, "rows": team_sheet_values()}, {"name": "其他", "id": 77, "rows": [["x"]]}]}),
        encoding="utf-8")
    port = _free_port()
    proc = subprocess.Popen([node, str(HERE / "apps_script_harness.js"), "serve", str(port), str(seed)],
                            stdout=subprocess.PIPE, text=True)
    line = proc.stdout.readline().split()
    assert line and line[0] == "ready", line
    url = f"http://127.0.0.1:{port}"

    def state():
        with urllib.request.urlopen(url + "/__state") as r:
            return json.loads(r.read().decode("utf-8"))

    def sheet(token=line[1], **kw):
        s = gsync.ScriptSheet("https://script.google.com/macros/s/test/exec", token, **kw)
        s.url = url
        return s
    yield sheet, state
    proc.terminate()
    proc.wait(5)


def test_apps_script_end_to_end(script_server):
    sheet, state = script_server
    with pytest.raises(store.SheetError, match="通行碼"):
        sheet(token="錯的").values()
    s = sheet()
    assert s.call("ping")["sheet"] == "工作表1"
    a, b = _rec("A"), _rec("B", "41")
    rows = gsync.append_records(s, [a, b])
    assert rows == [7, 8]
    v = state()["sheets"][0]["rows"]
    assert v[0][:21] == team_sheet_values()[0] and v[0][21] == "Schema"
    assert v[6][v[0].index("Record ID")] == a["Record ID"] and v[1][20] == "#01"
    gsync.update_record(s, b["Record ID"], dict(b, Notes="改過"), b)
    gsync.delete_record(s, a["Record ID"], a)
    st = state()
    v = st["sheets"][0]["rows"]
    df = gsync.rows_to_df(v)
    assert len(df) == 6 and df["Notes"].iloc[-1] == "改過" and a["Record ID"] not in set(df["Record ID"])
    hist = next(x for x in st["sheets"] if x["name"] == "MagicTool 修改紀錄")["rows"]
    assert [r[1] for r in hist[1:]] == ["修改", "刪除"]                # 修改 / 刪除前先備份舊的那一列
    assert st["locks"] == 0
    # 有人在中間改了那一列 → 停下來，不改錯列
    i = gsync.find_row(v, gsync.plan(v[0])[0], b["Record ID"])
    with pytest.raises(store.SheetError, match="被別人改過"):
        s.update(i, [(20, "x")], [(0, "不是這個日期")])
    # Google 的網址會 302 轉址：POST 的結果要跟著轉址用 GET 拿
    r = sheet()
    r.url += "/redirect"
    assert r.call("ping")["sheet"] == "工作表1" and len(r.values()) == len(v)
    # 用 gid 選工作表
    assert sheet(gid="77").call("ping")["sheet"] == "其他"
    # 標題列被改過的欄位不會被覆蓋
    with pytest.raises(store.SheetError, match="標題列"):
        s.call("append", rows=[], key_cols=[0], header=[0, ["不一樣"]])
