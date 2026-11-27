"""v0.9：一鍵匯出 PPT（自己寫的 .pptx 產生器；有裝 python-pptx 的話再用它打開檢查）。"""
import copy
import re
import zipfile

import pytest

from magic import testdata
from magic.fab import edit as E
from magic.fab import pptx_writer as PW
from magic.fab import records as R
from magic.fab import report_ppt as RP
from magic.fab import sheet as SH
from magic.fab import visual as V


@pytest.fixture()
def items(tmp_path):
    p = testdata.write_samples(str(tmp_path / "demo"))
    lib = R.Library(str(tmp_path / "data"), "t", p["root"])
    lib.save_cache(SH.parse_table(SH.read_file(p["sheet"])), p["sheet"])
    lib.scan()
    out = []
    for lab in ("901", "904", "al 906"):
        s = next(x for x in lib.samples if x["label"] == lab)
        out.append({"rec": copy.deepcopy(lib.preview(s)), "dir": s["dir"], "outlines": V.find_outlines(s["dir"])})
    return out


def _slides(path):
    with zipfile.ZipFile(path) as z:
        names = sorted((n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                       key=lambda n: int(re.findall(r"\d+", n)[0]))
        return [z.read(n).decode("utf-8") for n in names], z.namelist()


def _text(xml):
    return " ".join(re.findall(r"<a:t>([^<]*)</a:t>", xml))


def test_single_zh(items, tmp_path):
    it = items[0]
    E.set_results(it["rec"], r_ohm=1500, sc_contact=True, sc_on="TaS2", tc_k=4.2)
    c2 = [x for x in it["rec"]["steps"] if x["kind"] == "contact"][1]["id"]
    it["rec"]["ppt"] = {"title": "TaS2 contact 測試", "reporter": "Yeep", "skip_steps": [it["rec"]["steps"][0]["id"]],
                        "step_notes": {c2: "多蝕刻 3 nm 確保接觸乾淨"}, "problems": ["08 Lift-off 有殘膠"],
                        "next": ["改 RIE 時間 18 s"]}
    path, n = RP.export([it], str(tmp_path / "a.pptx"), "zh")
    xml, names = _slides(path)
    assert n == len(xml) and n >= 10
    allt = " ".join(_text(x) for x in xml)
    for want in ("TaS2 contact 測試", "報告人　Yeep", "樣品總覽", "製程流程", "第一輪", "第二輪", "旋塗光阻", "曝光、顯影",
                 "Lift-off", "開窗（微影）", "離子研磨", "重點", "多蝕刻 3 nm", "AFM 厚度：hBN 48.5 nm、TaS2 14.8 nm",
                 "電性量測：R_1500 (SC)", "結果、問題與下一步", "08 Lift-off 有殘膠", "改 RIE 時間 18 s",
                 "附錄：試算表製程紀錄", "RIE_20s OE_3nm", "1500 Ω", "4.2 K"):
        assert want in allt, want
    assert "步驟 00" not in allt                                  # 模板裡關掉的步驟不放
    assert any(nm.startswith("ppt/media/") and nm.endswith(".jpeg") for nm in names), "照片要縮成 JPEG 放進去"


def test_stage_sections_template_style(items):
    from magic.fab import visual as V
    rec = items[0]["rec"]
    i = next(k for k, x in enumerate(rec["steps"]) if x["kind"] == "contact")
    labels = [x["label"] for x in V.stage_sections(rec, i)]
    assert labels[:2] == ["旋塗光阻", "曝光、顯影"] and labels[-1] == "Lift-off" and "RIE" in " ".join(labels)
    t = next(k for k, x in enumerate(rec["steps"]) if x["kind"] == "transfer")
    assert [x["label"] for x in V.stage_sections(rec, t)] == ["疊上 hBN", "疊上 TaS2", "疊上 hBN"]
    a = next(k for k, x in enumerate(rec["steps"]) if x["kind"] == "afm")
    assert V.stage_sections(rec, a) == []
    lift = V.stage_sections(rec, i)[-1]["sec"]
    assert not any(m == V.RESIST for col in lift.cols for m, _, _ in col), "lift-off 後不能留下光阻"


def test_multi_both_and_en(items, tmp_path):
    path, n = RP.export(copy.deepcopy(items), str(tmp_path / "m.pptx"), "both")
    xml, _ = _slides(path)
    allt = " ".join(_text(x) for x in xml)
    assert "樣品比較 Sample comparison" in allt and "樣品 Sample al 906" in allt
    path, n = RP.export([copy.deepcopy(items[2])], str(tmp_path / "e.pptx"), "en", sections={"cover", "flow", "timeline"})
    xml, _ = _slides(path)
    allt = " ".join(_text(x) for x in xml)
    assert n == 3 and "Process flow" in allt and "Process overview" in allt and "製程" not in allt


def test_opens_in_python_pptx(items, tmp_path):
    pptx = pytest.importorskip("pptx")
    path, n = RP.export(copy.deepcopy(items[:2]), str(tmp_path / "x.pptx"), "zh")
    pr = pptx.Presentation(path)
    assert len(pr.slides) == n
    kinds = {sh.shape_type for sl in pr.slides for sh in sl.shapes}
    assert {13, 17, 19} <= {int(k) for k in kinds}                 # 圖片、文字框、表格


def test_writer_basics(tmp_path):
    png = tmp_path / "a.png"
    testdata._png(str(png), w=40, h=20)
    assert PW.image_size(str(png)) == (40, 20)
    d = PW.Deck(title="t & <x>")
    s = d.slide("一")
    s.text(1, 1, 3, 1, "a & b <c>", size=12)
    s.image(str(png), 1, 2, 4, 4)
    s.image(str(png), 1, 2, 2, 2)                                   # 同一張圖只放一份
    s.table(1, 1, 5, [["h1", "h2"], ["1", "2"]])
    d.save(str(tmp_path / "w.pptx"))
    with zipfile.ZipFile(tmp_path / "w.pptx") as z:
        assert [n for n in z.namelist() if n.startswith("ppt/media/")] == ["ppt/media/image1.png"]
        assert "a &amp; b &lt;c&gt;" in z.read("ppt/slides/slide1.xml").decode()
