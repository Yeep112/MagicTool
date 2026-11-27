"""v0.9.1：DXF / GDS 用 KLayout（預設）或 AutoCAD 開。"""
import os
import sys

from magic.fab import cad


def test_default_app():
    assert cad.default_app("a.dxf") == "klayout"
    assert cad.default_app("a.DXF", "autocad") == "autocad"
    assert cad.default_app("a.dwg", "klayout") == "autocad"          # DWG 只能 AutoCAD
    assert cad.default_app("a.gds", "nonsense") == "klayout"
    assert ".dxf" in cad.CAD_EXT and ".gds" in cad.CAD_EXT


def test_find_custom_and_missing(tmp_path, monkeypatch):
    exe = tmp_path / "klayout_app.exe"
    exe.write_text("")
    assert cad.find_app("klayout", str(exe)) == str(exe)
    monkeypatch.setattr(cad, "candidates", lambda app: [str(tmp_path / "nope.exe")])
    monkeypatch.setattr(cad.shutil, "which", lambda n: None)
    assert cad.find_app("autocad", str(tmp_path / "missing.exe")) == ""


def test_windows_candidates(monkeypatch, tmp_path):
    monkeypatch.setattr(cad.os, "name", "nt")
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "roam"))
    acad = tmp_path / "Autodesk" / "AutoCAD 2024" / "acad.exe"
    acad.parent.mkdir(parents=True)
    acad.write_text("")
    old = tmp_path / "Autodesk" / "AutoCAD 2021" / "acad.exe"
    old.parent.mkdir(parents=True)
    old.write_text("")
    c = cad.candidates("autocad")
    assert c[0] == str(acad)                                           # 新版優先
    assert os.path.join(str(tmp_path / "roam"), "KLayout", "klayout_app.exe") in cad.candidates("klayout")


def test_command(monkeypatch):
    assert cad.command("/x/klayout", "a.dxf") == ["/x/klayout", "a.dxf"]
    monkeypatch.setattr(sys, "platform", "darwin")
    assert cad.command("/Applications/klayout.app", "a.dxf") == ["open", "-a", "/Applications/klayout.app", "a.dxf"]
