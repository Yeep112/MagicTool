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


def _sq(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]


OUTS = [{"name": "hBN", "pts": _sq(0, 0, 100, 40), "electrode": False},
        {"name": "TaS2", "pts": _sq(20, 10, 80, 30), "electrode": False},
        {"name": "top hBN", "pts": _sq(10, 5, 90, 35), "electrode": False},
        {"name": "contact", "pts": _sq(25, 15, 35, 25), "electrode": True},
        {"name": "contact2", "pts": _sq(60, 15, 70, 25), "electrode": True}]


def test_cut_helpers():
    import numpy as np
    assert V.electrode_target("contact") == ("contact", 1) and V.electrode_target("Contact_2") == ("contact", 2)
    assert V.electrode_target("marker") == ("marker", 1) and V.electrode_target("top gate") == ("top_gate", 1)
    m = V.inside(_sq(0, 0, 10, 10), np.array([5, 15, 0.1]), np.array([5, 5, 9.9]))
    assert list(m) == [True, False, True]
    (x1, y1), (x2, y2) = V.auto_cut(OUTS)                       # 穿過兩個電極的中心（y = 20）
    assert abs(y1 - 20) < 1e-6 and abs(y2 - 20) < 1e-6 and x1 < 0 < 100 < x2


def test_cut_section_follows_outlines():
    rec = {"label": "c", "type": "Tri-TaS2", "steps": [
        {"id": "s1", "kind": "transfer", "n": 1, "params": {"layers": [["hBN", 20], ["TaS2", 4], ["hBN", 30]]}},
        {"id": "s2", "kind": "contact", "n": 1, "substeps": [
            {"kind": "rie", "params": {"oe_nm": 1}}, {"kind": "deposit", "params": {"layers": [["Cr", 5], ["Au", 60]]}}]},
        {"id": "s3", "kind": "contact", "n": 2, "substeps": [
            {"kind": "deposit", "params": {"layers": [["NbTi", 70]]}}]}]}
    sec = V.build_section(rec, None, outlines=OUTS)
    assert sec.cut is not None and not sec.missing
    (ax, _), (bx, _) = sec.cut

    def col(x):
        i = int((x - ax) / (bx - ax) * V.N)
        return [(m, round(t, 2)) for m, t, _ in sec.cols[i]]
    assert col(5) == [("hBN", 20)]                                # 只有下層 hBN
    assert col(50) == [("hBN", 20), ("TaS2", 4), ("hBN", 30)]     # 中間：完整堆疊
    assert col(30) == [("hBN", 20), ("TaS2", 3), ("Cr", 5), ("Au", 60)]   # contact #1：RIE 吃掉上層 hBN + OE
    assert col(65) == [("hBN", 20), ("TaS2", 4), ("hBN", 30), ("NbTi", 70)]  # contact #2 沒有 RIE
    s1 = V.build_section(rec, 1, outlines=OUTS[:4])               # 沒有 contact2.csv → 記下來
    s2 = V.build_section(rec, 2, outlines=OUTS[:4])
    assert not s1.missing and s2.missing == ["Contact #2"]
    rec["visual"] = {"cut": [[50, -10], [50, 50]]}                 # 自己設的切線（直的）
    sec = V.build_section(rec, 0, outlines=OUTS)
    assert sec.cut == ((50, -10), (50, 50))
    mid = sec.cols[V.N // 2]
    assert [m for m, _, _ in mid] == ["hBN", "TaS2", "hBN"]
