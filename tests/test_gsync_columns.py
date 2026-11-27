"""測試連線的欄位對照（v0.9.3）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from magic.etching import gsync, store

LAB_HEAD = ["DateTime", "Method", "Power", "Bias", "Pressure", "Type", "Name", "H_hBN_before (nm)", "H_hBN_after (nm)",
            "H_marker_before (nm)", "H_marker_after (nm)", "H_SiO2_before (nm)", "H_SiO2_after (nm)", "T (sec)",
            "Δ_marker (nm)", "Δ_hBN (nm)", "Δ_SiO2 (nm)", "R_SiO2(nm/sec)", "R_hBN(nm/sec)", "Gas", "note"]


def test_col_letter():
    assert [gsync.col_letter(j) for j in (0, 25, 26, 51, 52, 701, 702)] == ["A", "Z", "AA", "AZ", "BA", "ZZ", "AAA"]


def test_report_lab_sheet():
    rep = gsync.columns_report(LAB_HEAD)
    assert rep["width"] == 21
    assert rep["current"][20] == ("U", "note", "Notes")            # 自己加的 note 對到 Notes，不會再加一欄
    assert rep["added"][0] == ("V", "Schema") and len(rep["added"]) == len(store.HEADERS) - 21
    assert "Notes" not in [c for _, c in rep["added"]]
    txt = gsync.columns_text(rep)
    assert "U  note = Notes" in txt and "V  Schema" in txt and "Regenerate structure" in txt
    assert "［AppSheet：Decimal］" in txt


def test_report_unknown_and_empty():
    head = LAB_HEAD[:20] + ["我的欄位"]
    rep = gsync.columns_report(head)
    assert rep["current"][20] == ("U", "我的欄位", None)
    assert "Magic Tool 不使用" in gsync.columns_text(rep)
    empty = gsync.columns_report([])
    assert empty["width"] == 0 and len(empty["added"]) == len(store.HEADERS)
    with pytest.raises(gsync.SheetError):
        gsync.columns_report(["a", "b", "c"])


def test_every_column_has_help():
    assert set(store.HEADERS) <= set(gsync.COLUMN_HELP)
