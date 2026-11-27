"""製程頁（樣品紀錄）：試算表解析、資料夾掃描、合併比對、紀錄檔讀寫。只用合成資料（magic.testdata.write_samples）。"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from magic.fab import folders as F          # noqa: E402
from magic.fab import records as R          # noqa: E402
from magic.fab import sheet as SH           # noqa: E402
from magic.fab import steps as K            # noqa: E402


@pytest.mark.parametrize("text,kind,params", [
    ("transfer ", "transfer", {}),
    ("Raith.marker", "marker", {"tool": "Raith"}),
    ("Cr/Au_10/70 (E)", "deposit", {"layers": [["Cr", 10], ["Au", 70]], "method": "E"}),
    ("NbTi_70nm (S)", "deposit", {"layers": [["NbTi", 70]], "method": "S"}),
    ("Al_70nm", "deposit", {"layers": [["Al", 70]]}),
    ("plasma 40W 30sccm 30s ", "plasma", {"power_w": 40, "flow_sccm": 30, "time_s": 30}),
    ("RIE_20s OE_3nm", "rie", {"time_s": 20, "oe_nm": 3}),
    ("hBN_43.78 RIE_18s OE_3.02nm", "rie", {"time_s": 18, "hbn_nm": 43.78, "oe_nm": 3.02}),
    ("hBN_38.89RIE_16s OE_2.71nm", "rie", {"time_s": 16, "hbn_nm": 38.89, "oe_nm": 2.71}),
    ("Ion miling 18mA 30height_10+10", "ion_mill", {"current_ma": 18, "height": 30, "time_s": "10+10"}),
    ("ICP_60s+60s", "icp", {"time_s": "60+60"}),
    ("AFM hBN_36.06", "afm", {"hbn_nm": 36.06}),
    ("Raman (monolayer)", "raman", {"note": "monolayer"}),
    ("top gate", "top_gate", {}),
    ("N/A", "skip", {}),
    ("-", "stop", {}),
])
def test_classify(text, kind, params):
    assert SH.classify(text) == (kind, params)


def test_parse_process_groups():
    steps, issues, stopped = SH.parse_process(
        ["transfer", "marker", "Cr/Au_10/50 (E)", "contact", "plasma 40W 30sccm 30s", "RIE_20s OE_3nm",
         "Cr/Au_10/70 (E)", "contact", "plasma 40W 30sccm 30s", "RIE_20s OE_3nm", "Ion miling 18mA 30height_30s",
         "NbTi_70nm (S)"])
    assert [s["kind"] for s in steps] == ["transfer", "marker", "contact", "contact"]
    assert [x["kind"] for x in steps[1]["substeps"]] == ["deposit"]          # marker 的金屬
    assert [x["kind"] for x in steps[3]["substeps"]] == ["plasma", "rie", "ion_mill", "deposit"]
    assert not issues and not stopped
    assert K.summary(steps[2]) == "plasma · RIE 20 s OE 3 nm · Cr 10 / Au 70 nm (E)"


def test_parse_irregular():
    steps, issues, _ = SH.parse_process(["transfer", "marker", "Cr/Au_10/40 (E)", "contact", "plasma 40W 30sccm 30s",
                                         "RIE_18s", "Cr/Au_10/60 (E)", "plasma 40W 30sccm 30s", "RIE_18s"])
    assert [s["kind"] for s in steps] == ["transfer", "marker", "contact", "contact"] and steps[3].get("implied")
    assert issues and "少寫" in issues[0]
    steps, issues, stopped = SH.parse_process(["transfer", "raman", "Cr/Au_10/50 (E)", "-"])
    assert steps[-1]["kind"] == "deposit" and "前面沒有" in issues[0] and stopped


def test_parse_status():
    st = SH.parse_status("R_1659 (SC on TaS2)", "2026-01-26")
    assert st["state"] == "measured" and st["results"]["r_ohm"] == 1659 and st["results"]["sc_contact"]
    assert st["results"]["sc_on"] == "TaS2"
    st = SH.parse_status("Raith(4/28）擱置", "2026-03-11")
    assert st["state"] == "hold" and st["next_date"] == "2026-04-28"
    st = SH.parse_status("RIE(1/5)", "2026-11-20")            # 月日比開始日期早 → 隔年
    assert st["state"] == "active" and st["next"] == "RIE" and st["next_date"] == "2027-01-05"
    assert SH.parse_status("-")["state"] == "abandoned"


def test_file_dates():
    assert F.file_date("20250410_140104.png").isoformat() == "2025-04-10"
    assert F.file_date("102_251001_ZHeight_001.png").isoformat() == "2025-10-01"
    assert F.file_date("0731-0001.png", "2025-03-30").isoformat() == "2025-07-31"
    assert F.file_date("0131-0001.png", "2025-03-30").isoformat() == "2026-01-31"
    assert F.file_date("11-0001.png") is None and F.file_date("hBN_48.5, Ta_14.8.png") is None


def test_folder_kinds():
    for name, kind in [("Transfer", "transfer"), ("After Cleaning", "cleaning"), ("Lift Off", "liftoff"),
                       ("Lithography", "lithography"), ("AFM", "afm"), ("Cover hBN", "cover"),
                       ("After measurement", "inspection"), ("Measurement", "measurement"), ("Bonding", "bonding"),
                       ("Data Analysis", "analysis"), ("Design", "design"), ("TaS2 project", "other")]:
        assert F.folder_kind(name) == kind, name
    assert F.match_folder("05 Lithography") == (5, "Lithography")
    assert F.match_folder("Lithography_05", F.RULE_PRESETS[1][1]) == (5, "Lithography")


@pytest.fixture
def demo(tmp_path):
    from magic.testdata import write_samples
    p = write_samples(str(tmp_path / "demo"))
    rows = SH.parse_table(SH.fetch(p["sheet"]))
    lib = R.Library(str(tmp_path / "appdata"), "Yeep", p["root"])
    lib.save_cache(rows, p["sheet"])
    lib.scan()
    return p, rows, lib


def test_sheet_table(demo):
    p, rows, lib = demo
    assert [r["label"] for r in rows] == ["901", "902", "903", "904", "905", "al 906", "907", "908"]
    r901 = rows[0]
    assert r901["start"] == "2025-03-30" and r901["raw"]["remark"] == "範例" and r901["results"]["r_ohm"] == 1500


def test_xlsx_same_as_csv(demo, tmp_path):
    from openpyxl import Workbook
    from magic.testdata import SAMPLE_SHEET
    wb = Workbook()
    ws = wb.active
    for row in SAMPLE_SHEET:
        ws.append([int(c) if c.isdigit() and len(c) == 8 else c for c in row])   # 開始日期在 Excel 裡常變數字
    fp = tmp_path / "sheet.xlsx"
    wb.save(fp)
    a = SH.parse_table(SH.fetch(str(fp)))
    b = demo[1]
    assert [(x["label"], x["start"], len(x["steps"])) for x in a] == [(x["label"], x["start"], len(x["steps"])) for x in b]


def test_discover(demo):
    p, rows, lib = demo
    got = {s["label"]: s for s in lib.samples}
    assert set(got) == {"901", "902", "903", "904", "905", "al 906", "907", "908", "909"}
    assert got["901"]["has_folder"] and got["901"]["project"] == "09 Demo project"
    assert not got["903"]["has_folder"] and got["903"]["path"].endswith(os.path.join("Yeep", "903.json"))
    assert got["909"]["sheet"] is None                       # 只有資料夾
    assert R.state_of(got["903"]) == "abandoned" and R.state_of(got["902"]) == "hold"


def test_merge_901(demo):
    p, rows, lib = demo
    s = next(x for x in lib.samples if x["label"] == "901")
    rec = lib.preview(s)
    kinds = [(x["kind"], x["folders"]) for x in rec["steps"]]
    assert ("marker", ["03 Lift Off"]) in kinds
    assert ("contact", ["05 Lithography", "06 Lift Off"]) in kinds
    assert ("contact", ["07 Lithography", "08 Lift Off"]) in kinds
    c1 = next(x for x in rec["steps"] if x["folders"] == ["05 Lithography", "06 Lift Off"])
    assert [x["kind"] for x in c1["substeps"]] == ["lithography", "plasma", "rie", "deposit", "liftoff"]
    assert c1["substeps"][0]["folders"] == ["05 Lithography"] and c1["substeps"][-1]["folders"] == ["06 Lift Off"]
    assert c1["date"] == "2025-04-12" and c1["date_end"] == "2025-04-15" and c1["source"] == ["folder", "sheet"]
    afm = next(x for x in rec["steps"] if x["folders"] == ["04 AFM"])
    assert afm["params"]["hbn_nm"] == 48.5                   # 檔名讀到的厚度
    tr2 = next(x for x in rec["steps"] if x["folders"] == ["13 Transfer"])
    assert tr2["date"] == "2025-07-31"                      # 0731-0001 → 年份從開始日期推
    c3 = next(x for x in rec["steps"] if x["folders"] == ["15 Lithography", "17 Lift Off"])
    assert c3["kind"] == "contact" and c3.get("guess")
    assert any("15 Lithography" in r["msg"] for r in R.open_reviews(rec))
    assert rec["results"]["sc_contact"] and rec["status"]["state"] == "measured"


def test_import_and_reload(demo):
    p, rows, lib = demo
    made, kept, failed = lib.import_all()
    assert not failed and len(made) == 9 and not kept
    rp = R.record_path(p["901"])
    assert os.path.basename(rp) == "901.json" and os.path.isfile(rp)
    rec = json.load(open(rp, encoding="utf-8"))
    assert rec["schema"] == 1 and rec["label"] == "901" and rec["steps"][0]["id"] == "s1"
    # 標記已確認 → 寫回 → 重新掃描後記得
    rid = R.open_reviews(rec)[0]["id"]
    for r in rec["review"]:
        if r["id"] == rid:
            r["resolved"] = True
    R.save(rec, rp)
    lib2 = R.Library(lib.base, "Yeep", p["root"])
    lib2.scan()
    s = next(x for x in lib2.samples if x["label"] == "901")
    assert s["rec"] is not None and rid not in [r["id"] for r in R.open_reviews(s["rec"])]
    made, kept, _ = lib2.import_all()                         # 再匯入一次：已經有的不動
    assert not made and len(kept) == 9
    assert not any(n.endswith(".tmp") for n in os.listdir(p["901"]))


def test_record_name_pattern(tmp_path):
    d = tmp_path / "102"
    d.mkdir()
    assert R.record_path(str(d), "{folder}_製程.json").endswith("102_製程.json")
    assert R.record_path(str(d), "sample").endswith("sample.json")
    assert R.record_path(str(d), "{bad}.json").endswith("102.json")


def test_discover_project_named_like_step(tmp_path):
    """專案資料夾名稱剛好有步驟關鍵字（08 AFM study）也要往下找；樣品資料夾裡的步驟資料夾不能被當成樣品。"""
    root = tmp_path / "00 Samples"
    for proj, lab in (("08 AFM study", "301"), ("09 TaS2 project", "102")):
        for d in ("01 Transfer", "02 Lithography", "03 Lift Off", "04 AFM"):
            (root / proj / lab / d).mkdir(parents=True)
    found = sorted((f["label"], f["project"]) for f in R.discover(str(root)))
    assert found == [("102", "09 TaS2 project"), ("301", "08 AFM study")], found
    assert F.is_cloud_only(str(root)) is False
