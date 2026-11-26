"""pytest 用：和 python -m magic selftest 相同的檢查（不含視窗）。只用合成資料。

    cd MagicTool
    python -m pytest -q
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


@pytest.fixture(scope="session")
def paths(tmp_path_factory):
    os.environ["MAGIC_DATA"] = str(tmp_path_factory.mktemp("appdata"))
    os.environ.setdefault("MPLBACKEND", "Agg")
    from magic.testdata import write_all
    return write_all(str(tmp_path_factory.mktemp("data")))


def test_imports():
    from magic import selftest
    selftest.check_imports()


def test_readers(paths):
    from magic import selftest
    selftest.check_readers(paths)


def test_analyses(paths):
    from magic import selftest
    selftest.check_analyses(paths)


def test_etching(paths):
    from magic import selftest
    selftest.check_etching(paths)


def test_raman_tools(paths):
    from magic import selftest
    selftest.check_raman_tools(paths)


def test_settings_and_tools(paths, tmp_path):
    from magic import selftest
    selftest.check_settings_and_tools(str(tmp_path))


def test_update(tmp_path):
    from magic import selftest
    selftest.check_update(str(tmp_path))


def test_segments_ignore_setpoint_jitter():
    import numpy as np
    from magic.core.segments import split_sweeps
    T = np.concatenate([np.linspace(300, 2, 200), 2 + 0.001 * np.random.default_rng(0).normal(size=50),
                        np.linspace(2, 300, 200)])
    segs = split_sweeps(T)
    assert [s.direction for s in segs] == [-1, 1]


def test_range_param_defaults_survive_gui_text():
    """預設值是文字的範圍參數（例如「1550, 1620」）轉成介面文字時不能變成空白。"""
    from magic.core.registry import P
    q = P("w", "範圍", "1550, 1620", kind="range")
    assert q.to_text(q.default) == "1550, 1620"
    assert q.parse(q.to_text(q.default)) == (1550.0, 1620.0)
