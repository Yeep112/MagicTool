"""v0.8：剖面堆疊、俯視輪廓、逐步狀態、存成 PNG（合成資料）。"""
import os

from magic import testdata
from magic.fab import visual as V

REC = {"label": "x", "type": "Tri-TaS2", "steps": [
    {"id": "s1", "kind": "transfer", "n": 1, "params": {"layers": [["hBN", 20], ["TaS2", 4], ["hBN", None]]}},
    {"id": "s2", "kind": "marker", "n": 1, "substeps": [{"kind": "deposit", "params": {"layers": [["Cr", 10], ["Au", 50]]}}]},
    {"id": "s3", "kind": "afm", "params": {"hbn_nm": 32}},
    {"id": "s4", "kind": "contact", "n": 1, "substeps": [
        {"kind": "rie", "params": {"time_s": 15, "oe_nm": 1}},
        {"kind": "deposit", "params": {"layers": [["Cr", 10], ["Au", 70]], "method": "E"}}]},
    {"id": "s5", "kind": "contact", "n": 2, "substeps": [
        {"kind": "rie", "params": {"time_s": 15}}, {"kind": "ion_mill", "params": {}},
        {"kind": "deposit", "params": {"layers": [["NbTi", 70]], "method": "S"}}]},
]}


def _col(sec, x):
    return [(m, round(t, 3)) for m, t, _ in sec.cols[int(x / V.W * V.N)]]


def test_stack_after_each_step():
    s0 = V.build_section(REC, 0)
    assert _col(s0, 5.0) == [("hBN", 20), ("TaS2", 4), ("hBN", 32)]      # 頂層 hBN 用後面 AFM 的厚度
    assert _col(s0, 0.5) == []
    s1 = V.build_section(REC, 1)
    assert _col(s1, 0.5) == [("Cr", 10), ("Au", 50)]                      # marker 在兩側
    s3 = V.build_section(REC, 3)
    win = _col(s3, 3.3)
    assert [m for m, _ in win] == ["hBN", "TaS2", "Cr", "Au"] and win[1][1] == 3   # 窗口：上層 hBN 蝕刻掉、OE 1 nm
    assert _col(s3, 5.0) == [("hBN", 20), ("TaS2", 4), ("hBN", 32)]      # 中間沒動
    s4 = V.build_section(REC)
    assert [m for m, _ in _col(s4, 4.0)][-1] == "NbTi" and s4.notes[-1] == "Contact #2"


def test_rects_cover_columns():
    sec = V.build_section(REC)
    area = sum((x1 - x0) * (y1 - y0) for x0, x1, y0, y1, m, s in sec.rects())
    want = sum(sum(t for _, t, _ in c) for c in sec.cols) * V.W / V.N
    assert abs(area - want) / want < 1e-6


def test_outlines_and_png(tmp_path):
    p = testdata.write_samples(str(tmp_path))
    outs = V.find_outlines(p["901"])
    names = sorted(o["name"] for o in outs)
    assert names == ["TaS2", "contact", "graphene", "hBN", "top hBN"]
    assert [o["electrode"] for o in outs if o["name"] == "contact"] == [True]
    rec = dict(REC)
    assert V.outlines_at(rec, outs, -1) == []
    assert "contact" not in [o["name"] for o in V.outlines_at(rec, outs, 2)]
    assert "contact" in [o["name"] for o in V.outlines_at(rec, outs, 3)]
    assert V.find_outlines(p["902"]) == []
    for what in ("both", "section", "top"):
        out = V.render_png(str(tmp_path / f"{what}.png"), rec, outs, 3, what=what, size=(5, 3), dpi=80)
        assert os.path.getsize(out) > 3000
    V.render_png(str(tmp_path / "empty.png"), {"label": "e", "steps": []}, [], size=(4, 3), dpi=60)
