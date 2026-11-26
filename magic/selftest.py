"""發佈前自我測試：python -m magic selftest（publish.bat 上傳前會自動執行）。

只用程式產生的合成資料（magic.testdata），不需要、也不會碰到真實資料；設定與紀錄寫在暫存資料夾。
  1. 所有程式檔沒有語法錯誤、每個分析功能都能載入
  2. 讀檔：QD .dat（文字欄位、檔頭、編碼）、Raman（標題列、逗號 / Tab、由大到小）
  3. 每個分析功能都能算、能畫，關鍵數值和合成資料的正確答案一致（Tc、峰位、FWHM、Hc…）
  4. 蝕刻速率：正負號、缺值、負值提醒、重複紀錄
  5. 設定檔讀寫、notebook 清除輸出、自動更新（用本機 zip 模擬）
  6. 軟體視窗：開啟、切換機台、每個功能實際畫一次；量測切換與畫面卡住的時間
任何一項失敗 → 回傳失敗，publish 不會上傳。
"""
from __future__ import annotations

import compileall
import os
import shutil
import sys
import tempfile
import time
import traceback

TOL = {"Tc": 0.03, "peak": 1.0, "fwhm": 1.5, "Hc": 6.0}


class Report:
    def __init__(self, log):
        self.log = log
        self.failed = []
        self.n = 0

    def check(self, name, fn):
        self.n += 1
        t0 = time.perf_counter()
        try:
            extra = fn()
            self.log(f"  ✓ {name}" + (f"　{extra}" if extra else "") + f"（{time.perf_counter() - t0:.2f} 秒）")
            return True
        except Exception as e:
            self.failed.append(name)
            self.log(f"  ✗ {name}：{type(e).__name__}: {e}")
            self.log("    " + traceback.format_exc().strip().replace("\n", "\n    "))
            return False


def _near(v, target, tol, what):
    if not (abs(v - target) <= tol):
        raise AssertionError(f"{what} = {v:.4g}，預期 {target:.4g} ± {tol}")


def check_imports():
    from .core.settings import TOOL_ROOT
    ok = compileall.compile_dir(str(TOOL_ROOT / "magic"), quiet=1, force=False)
    if not ok:
        raise AssertionError("有程式檔語法錯誤")
    from .core.registry import LOAD_ERRORS, load_analyses
    a = load_analyses(reload=True)
    if LOAD_ERRORS:
        raise AssertionError("載入失敗：" + "；".join(LOAD_ERRORS))
    return "、".join(f"{k} {len(v)} 個" for k, v in a.items())


def check_readers(paths):
    from .readers import detect, load
    ds = load(paths["ppms"])
    assert ds.kind == "PPMS", ds.kind
    assert "Comment" in ds.df.columns and ds.df["Comment"].astype(str).str.contains("Start cooling").any(), \
        "Comment 欄的文字不見了"
    assert ds.header.get("BYAPP", "").startswith("Resistivity"), ds.header.get("BYAPP")
    assert detect(paths["squid_mt"]) == "SQUID"
    from .core.columns import find_col
    warns = []
    assert find_col(ds.df, "Resistance", warn=warns.append) == "Bridge 1 Resistance (Ohms)"
    assert warns, "好幾個欄位符合時應該要提醒"
    for k in ("raman_mono", "raman_multi", "raman_hybrid"):
        r = load(paths[k])
        assert r.kind == "Raman" and len(r.df) > 1000, (k, r.kind, len(r.df))
        x = r.df.iloc[:, 0].to_numpy()
        assert x[0] < x[-1], "Raman 應該自動排成由小到大"
    # 非 UTF-8 的 .dat
    tmp = os.path.join(os.path.dirname(paths["ppms"]), "_latin1.dat")
    with open(tmp, "wb") as f:
        f.write("[Header]\nTITLE,Probe \xb0C\n[Data]\nTemperature (K),Bridge 1 Resistance (Ohms)\n1,2\n3,4\n".encode("latin-1"))
    d2 = load(tmp, use_cache=False)
    assert any("編碼" in n for n in d2.notes), d2.notes
    os.remove(tmp)
    return "QD / Raman / 編碼"


def check_analyses(paths):
    from .runner import run
    from .testdata import TRUTH
    out = []
    _, res = run("PPMS", "R–T 與 Tc", [paths["ppms"]])                    # 溫度範圍空白 = 自動
    t = res.tables["Tc"]
    _near(t.iloc[0, 2], TRUTH["ppms_Tc_cool"], TOL["Tc"], "PPMS 降溫 Tc（自動範圍）")
    _, res = run("PPMS", "R–T 與 Tc", [paths["ppms"]], T_range="2, 12")
    t = res.tables["Tc"]
    _near(t.iloc[0, 2], TRUTH["ppms_Tc_cool"], TOL["Tc"], "PPMS 降溫 Tc")
    _near(t.iloc[1, 2], TRUTH["ppms_Tc_warm"], TOL["Tc"], "PPMS 升溫 Tc")
    out.append(f"PPMS Tc {t.iloc[0, 2]:.3f}/{t.iloc[1, 2]:.3f} K")
    _, res = run("SQUID", "M–T 與 Tc", [paths["squid_mt"]])
    t = res.tables["Tc"]
    assert len(t) == 2, f"應該分成 ZFC / FC 兩段，得到 {len(t)} 段"
    for i in range(2):
        _near(t.iloc[i, 2], TRUTH["squid_Tc"], TOL["Tc"], f"SQUID 第 {i + 1} 段 Tc")
        _near(t.iloc[i, 7], TRUTH["squid_Tc"], 0.05, f"SQUID 第 {i + 1} 段最大斜率處")
    assert "ZFC" in t.iloc[0, 1] and "FC" in t.iloc[1, 1], list(t.iloc[:, 1])
    out.append(f"SQUID Tc {t.iloc[0, 2]:.3f} K")
    _, res = run("SQUID", "M–H 迴線", [paths["squid_mh"]])
    t = res.tables["MH_fields"]
    hc = t["H_c,10% (Oe)"].dropna().abs()
    for v in hc:
        _near(v, TRUTH["squid_Hc"], TOL["Hc"], "M–H Hc")
    out.append(f"Hc {hc.mean():.0f} Oe")
    _, res = run("Raman", "石墨烯 G / 2D 峰", [paths["raman_mono"], paths["raman_hybrid"]], hbn=True)
    t = res.tables["peaks"]
    _near(t["G 位置 (cm⁻¹)"].iloc[0], TRUTH["raman_G"], TOL["peak"], "G 位置")
    _near(t["2D 位置 (cm⁻¹)"].iloc[0], TRUTH["raman_2D"], TOL["peak"], "2D 位置")
    _near(t["2D FWHM (cm⁻¹)"].iloc[0], TRUTH["raman_2D_fwhm"], TOL["fwhm"], "2D FWHM")
    _near(t["G FWHM (cm⁻¹)"].iloc[0], TRUTH["raman_G_fwhm"], TOL["fwhm"], "G FWHM")
    _near(t["I(2D)/I(G) 高度比"].iloc[0], TRUTH["raman_ratio"], 0.15, "I(2D)/I(G)")
    _near(t["hBN 位置 (cm⁻¹)"].iloc[1], TRUTH["raman_hBN"], TOL["peak"], "hBN 位置")
    import numpy as np
    assert not np.isfinite(t["hBN 位置 (cm⁻¹)"].iloc[0]) or "最大值" not in str(t["hBN 方法"].iloc[0]), \
        "沒有 hBN 的光譜不應該找到 hBN"
    out.append(f"2D/G {t['I(2D)/I(G) 高度比'].iloc[0]:.2f}")
    # 蝕刻：多個時間線性擬合 → 斜率 = 蝕刻率、截距 → 起始延遲；蝕穿的那筆要排除
    from .testdata import etch_rate_A
    _, res = run("Etching", "多時間線性擬合", [paths["etching"]])
    t = res.tables["time_fit"]
    assert len(t) == 4, f"應該有 4 個線寬各一條擬合，得到 {len(t)}"
    for _, row in t.iterrows():
        truth = etch_rate_A(row["線寬 (nm)"])
        assert abs(row["蝕刻率 (nm/s)"] - truth) < max(0.03, 3 * row["σ 蝕刻率"]), \
            f"線寬 {row['線寬 (nm)']:g} nm：擬合 {row['蝕刻率 (nm/s)']:.3f}，正確 {truth:.3f}"
        _near(row["起始延遲 (s)"], TRUTH["etch_delay"], 1.0, "起始延遲")
    assert t["排除（蝕穿）"].sum() == 1, "蝕穿的紀錄要被排除"
    rates = list(t.sort_values("線寬 (nm)")["蝕刻率 (nm/s)"])
    assert rates == sorted(rates), "線寬越小蝕刻率應該越低"
    out.append(f"蝕刻率 {rates[-1]:.3f} nm/s（2 µm）")
    _, res = run("Etching", "線寬比較", [paths["etching"]])
    t = res.tables["linewidth"]
    assert t["配方"].nunique() == 2 and not t["含蝕穿（下限）"].any(), t
    # 其他功能：能算、能畫
    others = [("PPMS", "曲線檢視", [paths["ppms"], paths["ppms2"]], {}),
              ("PPMS", "多樣品 R–T 比較", [paths["ppms"], paths["ppms2"]], {}),
              ("SQUID", "曲線檢視", [paths["squid_mt"], paths["squid_mh"]], {}),
              ("SQUID", "多樣品 M–T 比較", [paths["squid_mt"]], {}),
              ("Raman", "光譜檢視", [paths["raman_mono"], paths["raman_multi"]], {"baseline": "ALS（自動）"}),
              ("Raman", "背景扣除", [paths["raman_multi"]], {}),
              ("Raman", "多檔峰值總表", [paths["raman_mono"], paths["raman_multi"], paths["raman_hybrid"]], {}),
              ("Etching", "蝕刻速率趨勢", [paths["etching"]], {"x": "日期", "y": "兩個都畫"}),
              ("Etching", "條件比較（平均 ± 標準差）", [paths["etching"]], {}),
              ("Etching", "蝕刻速率趨勢", [paths["etching_v1"]], {"x": "日期", "y": "材料蝕刻率"}),
              ("Etching", "線寬比較", [paths["etching"]], {"log_x": True, "normalize": True})]
    for inst, name, src, kw in others:
        fig, res = run(inst, name, src, **kw)
        assert fig.axes, f"{inst}「{name}」沒有畫出任何圖"
    from .core.registry import load_analyses
    n_all = sum(len(v) for v in load_analyses().values())
    tested = {"R–T 與 Tc", "M–T 與 Tc", "M–H 迴線", "石墨烯 G / 2D 峰", "多時間線性擬合"} | {o[1] for o in others}
    missing = [f"{k}:{a.name}" for k, v in load_analyses().items() for a in v if a.name not in tested]
    if missing:
        raise AssertionError(f"這些功能還沒有測試：{missing}")
    return "；".join(out) + f"；共 {n_all} 個功能"


def check_etching(paths):
    import math
    import pandas as pd
    from .etching import store
    from .etching.model import (EtchInput, EtchInputError, compute, parse_length_nm, parse_pressure_pa,
                                parse_steps, parse_values)
    out = []
    # --- 讀輸入的小工具 ---
    assert parse_steps("20+20+20") == [20, 20, 20] and parse_steps("3x20") == [20, 20, 20]
    assert parse_steps("1.5min") == [90] and parse_steps("10, 20") == [10, 20], parse_steps("10, 20")
    _near(parse_pressure_pa("10", "mTorr"), 1.3332, 1e-3, "10 mTorr → Pa")
    _near(parse_length_nm("0.5um"), 500, 1e-9, "0.5 um → nm")
    m = parse_values("100, 101, 99")
    assert m.n == 3 and abs(m.mean - 100) < 1e-12 and abs(m.std - 1) < 1e-12, (m.mean, m.std)
    for bad in ("abc", "1, x"):
        try:
            parse_values(bad, "測試")
            raise AssertionError(f"「{bad}」應該要看不懂")
        except EtchInputError:
            pass
    # --- marker 量 SiO2 + 從基板量材料：d_SiO2 = H_m,out − T'_m，d = T + d_SiO2 − H_out ---
    base = dict(material="hBN", steps="20+20", sio2_method="marker", marker_before="50",
                marker_out="55", mat_method="outside", mat_before="100", mat_out="40")
    r = compute(EtchInput(**base))
    _near(r.d_sio2, 5, 1e-9, "d_SiO2（marker）")
    _near(r.d_mat, 65, 1e-9, "d_材料（從基板量）")
    _near(r.r_mat, 65 / 40, 1e-9, "r_材料（分段時間加總）")
    _near(r.r_sio2, 5 / 40, 1e-9, "r_SiO2")
    _near(r.selectivity, 13, 1e-9, "選擇比")
    assert not r.through and r.t_steps == [20, 20]
    # 有量 T'_m：用量到的值
    r = compute(EtchInput(**{**base, "marker_after_own": "49"}))
    _near(r.d_sio2, 6, 1e-9, "d_SiO2（有 T'_m）")
    _near(r.marker_etched, 1, 1e-9, "marker 被蝕刻量")
    # --- 多點平均與誤差傳遞 σ_d = √(Σσ²)、σ_r = σ_d / t ---
    r = compute(EtchInput(**{**base, "mat_before": "99, 100, 101", "mat_out": "39, 40, 41", "marker_out": "54, 55, 56"}))
    _near(r.d_mat, 65, 1e-9, "多點平均 d")
    _near(r.s_mat, math.sqrt(3), 1e-9, "σ_d 誤差傳遞")
    _near(r.sr_mat, math.sqrt(3) / 40, 1e-9, "σ_r")
    # --- AFM 台階 / 橢偏儀 + 圖案內台階 ---
    r = compute(EtchInput(material="WSe2", steps="30", sio2_method="afm_step", sio2_step="3",
                          mat_method="inside", mat_before="50", mat_step="30"))
    _near(r.r_mat, 1.0, 1e-9, "r（圖案內台階）")
    _near(r.remaining, 20, 1e-9, "剩下厚度")
    r = compute(EtchInput(steps="30", sio2_method="ellipsometer", sio2_before="300", sio2_after="297",
                          mat_method="inside", mat_step="30"))
    _near(r.r_sio2, 0.1, 1e-9, "r_SiO2（橢偏儀）")
    assert any("無法判斷" in w for w in r.warnings), "沒有 T 時要提醒無法判斷蝕穿"
    # --- 從基板量但沒有量 SiO2 → 要說明 ---
    try:
        compute(EtchInput(**{**base, "sio2_method": "none"}))
        raise AssertionError("從基板量卻沒有 SiO2 深度，應該要說明")
    except EtchInputError as e:
        assert "SiO2" in str(e)
    # --- 蝕穿：剩下 ≤ 0.5 nm → 下限 r ≥ T / t ---
    r = compute(EtchInput(**{**base, "mat_out": "5.2"}))
    assert r.through and r.lower_bound, "應該判斷為蝕穿"
    _near(r.r_mat, 100 / 40, 1e-9, "蝕穿時的下限 T / t")
    out.append("算式、分段時間、誤差傳遞、蝕穿")
    # --- 新格式 CSV：寫入、讀回、重複 ---
    folder = os.path.dirname(paths["etching"])
    inp = EtchInput(**{**base, "icp_power": "100", "rf_power": "30",
                       "gases": [("SF6", "40"), ("O2", "5")], "line_width": "0.5um"})
    rec = store.make_record(inp, compute(inp), version="selftest")
    assert set(rec) <= set(store.HEADERS), f"紀錄有表頭沒有的欄位：{set(rec) - set(store.HEADERS)}"
    _near(float(rec["R_hBN(nm/sec)"]), 65 / 40, 1e-9, "舊欄位 R_hBN")
    _near(float(rec["Δ_hBN (nm)"]) + float(rec["Δ_marker (nm)"]), 65, 1e-9, "舊公式 R = (Δ_hBN + Δ_marker)/t 仍成立")
    assert rec["Gas"] == "SF6+O2" and rec["Power"].startswith("ICP 100"), (rec["Gas"], rec["Power"])
    tmp = os.path.join(folder, "_new.csv")
    store.append_record(rec, tmp)
    df = store.read_log(tmp)
    assert store.file_schema(tmp) == "v2" and len(df) == 1
    _near(df["Line width (nm)"].iloc[0], 500, 1e-9, "線寬存檔")
    assert store.find_duplicates(df, rec) == [1], store.find_duplicates(df, rec)
    inp2 = EtchInput(**{**inp.__dict__, "notes": "另一個備註", "name": "別人"})
    assert store.find_duplicates(df, store.make_record(inp2, compute(inp2))) == [1], "只改備註、名字仍算重複"
    inp3 = EtchInput(**{**inp.__dict__, "mat_out": "41"})
    assert store.find_duplicates(df, store.make_record(inp3, compute(inp3))) == [], "量測值不同不算重複"
    os.remove(tmp)
    # --- 舊格式（v1）：不能直接寫，要先備份再升級；舊值不變 ---
    v1 = paths["etching_v1"]
    old = pd.read_csv(v1, dtype=str, keep_default_na=False)
    assert store.file_schema(v1) == "v1"
    try:
        store.append_record(rec, v1)
        raise AssertionError("舊格式不應該直接寫入")
    except store.NeedsUpgrade:
        pass
    legacy = store.read_log(v1)
    assert len(legacy) == len(old) and (legacy["Schema"].astype(str) == "1").all()
    i = 0
    d_old = float(old["Δ_hBN (nm)"].iloc[i]) + float(old["Δ_marker (nm)"].iloc[i])
    _near(legacy["d_material (nm)"].iloc[i], d_old, 1e-9, "舊紀錄換算的 d_材料")
    backup = store.upgrade_file(v1)
    assert os.path.exists(backup) and store.file_schema(v1) == "v2"
    new = pd.read_csv(v1, dtype=str, keep_default_na=False)
    for c in old.columns:
        assert (new[c] == old[c]).all(), f"升級後舊欄位「{c}」被改到"
    store.append_record(rec, v1)
    assert len(store.read_log(v1)) == len(old) + 1
    out.append(f"舊格式備份並升級（{len(old)} 筆不變）")
    # --- Google Sheet 表頭（用假的工作表測，不連網路） ---

    class FakeWS:
        def __init__(self, rows):
            self.rows = [list(r) for r in rows]

        def row_values(self, i):
            return self.rows[i - 1] if len(self.rows) >= i else []

        def get_all_values(self):
            return self.rows

        def update(self, range_name="A1", values=None, **kw):
            assert range_name == "A1"
            if self.rows:
                self.rows[0] = list(values[0])
            else:
                self.rows.append(list(values[0]))

        def append_row(self, row, **kw):
            self.rows.append(list(row))

    ws = FakeWS([])
    assert store.ensure_sheet_header(ws) == "new" and ws.rows[0] == store.HEADERS
    ws = FakeWS([store.V1, ["x"] * len(store.V1)])
    assert store.ensure_sheet_header(ws) == "upgraded" and ws.rows[0] == store.HEADERS
    assert store.ensure_sheet_header(ws) == "ok"
    store.gsheet_append(rec, "k", "sa.json", ws=ws)
    assert len(ws.rows) == 3 and ws.rows[2][store.HEADERS.index("Material")] == "hBN"
    back = store.gsheet_read("k", "sa.json", ws=ws)
    assert len(back) == 2 and back["Material"].iloc[1] == "hBN" and back["Schema"].iloc[0] == "1", back
    _near(back["R_hBN(nm/sec)"].iloc[1], 65 / 40, 1e-9, "從 Google Sheet 讀回的 R")
    try:
        store.ensure_sheet_header(FakeWS([["A", "B"]]))
        raise AssertionError("看不懂的表頭應該要停下來")
    except store.SheetError:
        pass
    out.append("Google Sheet 表頭（模擬）")
    return "；".join(out)


def check_settings_and_tools(tmp):
    from .core import settings as S
    cfg = S.load_settings()
    cfg["folders"]["PPMS"] = r"D:\Yeep\01 Magic Tool\PPMS\Data"
    cfg["etching"]["gsheet_key"] = "https://docs.google.com/spreadsheets/d/ABC_def-123/edit#gid=0"
    S.save_settings(cfg)
    back = S.load_settings()
    assert back["folders"]["PPMS"] == cfg["folders"]["PPMS"], back["folders"]
    from .etching.store import parse_sheet_key
    assert parse_sheet_key(back["etching"]["gsheet_key"]) == "ABC_def-123"
    from .tools_nb import strip_notebook, suspicious
    import json
    nb = os.path.join(tmp, "t.ipynb")
    with open(nb, "w", encoding="utf-8") as f:
        json.dump({"cells": [{"cell_type": "code", "source": "1", "metadata": {}, "execution_count": 3,
                              "outputs": [{"output_type": "stream", "text": "secret"}]}],
                   "metadata": {}, "nbformat": 4, "nbformat_minor": 5}, f)
    assert strip_notebook(nb) and "secret" not in open(nb, encoding="utf-8").read()
    assert suspicious(["magic/a.py", "Data/x.dat", "notebooks/y.ipynb", "assets/icon_40.png"]) == ["Data/x.dat"]
    return "settings.toml、notebook、資料檔檢查"


def check_update(tmp):
    """把目前的程式打包成 zip，裝到一個假的舊版資料夾，確認更新流程正常、使用者檔案不會被動到。"""
    import json
    import zipfile
    from . import updater
    from .core.settings import TOOL_ROOT
    src = str(TOOL_ROOT)
    zpath = os.path.join(tmp, "repo.zip")
    with zipfile.ZipFile(zpath, "w") as z:
        for root, dirs, files in os.walk(src):
            dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "_backup", ".ipynb_checkpoints")]
            for fn in files:
                fp = os.path.join(root, fn)
                z.write(fp, os.path.join("MagicTool-main", os.path.relpath(fp, src)))
    old = os.path.join(tmp, "installed")
    os.makedirs(os.path.join(old, "magic"))
    with open(os.path.join(old, "magic", "__main__.py"), "w") as f:
        f.write("# old\n")
    with open(os.path.join(old, "magic", "obsolete.py"), "w") as f:
        f.write("# should disappear\n")
    with open(os.path.join(old, "release.json"), "w", encoding="utf-8") as f:
        json.dump({"version": "0.0.1", "repo": "Yeep112/MagicTool", "branch": "main"}, f)
    with open(os.path.join(old, "settings.toml"), "w") as f:
        f.write("keep = true\n")
    ver = updater.apply_update({"commit": None}, log=lambda m: None, zip_source=zpath, root=old)
    assert ver == updater.read_release(os.path.join(src, "release.json"))["version"], ver
    assert os.path.exists(os.path.join(old, "magic", "registry.py")) is False
    assert os.path.exists(os.path.join(old, "magic", "core", "registry.py")), "新程式沒有裝進去"
    assert not os.path.exists(os.path.join(old, "magic", "obsolete.py")), "舊模組應該被移除"
    assert open(os.path.join(old, "settings.toml")).read() == "keep = true\n", "使用者檔案被覆蓋了"
    assert updater.list_backups(old), "沒有備份"
    return f"0.0.1 → {ver}，備份與使用者檔案正常"


# ---------------------------------------------------------------------------
# 介面
# ---------------------------------------------------------------------------
def run_gui(rep, timeout=90):
    try:
        import tkinter as tk
        root = tk.Tk()
    except Exception as e:
        rep.log(f"  － 略過介面測試（這台電腦沒有可用的 Tk 顯示：{e}）")
        return
    root.withdraw()
    import matplotlib
    matplotlib.use("TkAgg")
    from .gui.app import App, prepare
    from .core.registry import INSTRUMENTS
    stats = {}

    def go():
        prepare(root)
        app = App(root, check_updates=False)
        root.deiconify()
        root.geometry("1500x900+0+0")
        gaps = []
        last = [time.perf_counter()]

        def beat():
            now = time.perf_counter()
            gaps.append(now - last[0])
            last[0] = now
            if not app.dead:
                root.after(10, beat)
        root.after(10, beat)

        def pump(cond, limit=30.0):
            t0 = time.perf_counter()
            while time.perf_counter() - t0 < limit:
                root.update()
                if cond():
                    return True
                time.sleep(0.005)
            return False

        pump(lambda: len(app.pages) == len(INSTRUMENTS), 15)
        app.open_demo()
        pump(lambda: all(p.data.files for k, p in app.pages.items() if p.inst.source == "files"), 15)
        pump(lambda: app.pages["Etching"].data.df is not None, 10)
        switch_ms, results = [], []
        for key in INSTRUMENTS:
            app.segment.select(key)
            for _ in range(3):
                root.update()
            page = app.pages[key]
            for a in page.analyses:
                page.features.select(a.name)
                if page.inst.source == "files":
                    kids = page.data.tree.get_children()
                    names = {page.data.tree.set(i, "name"): i for i in kids}
                    pick = [i for n, i in names.items() if _wanted(key, a, n)] or list(kids)[:2]
                    page.data.tree.selection_set(pick)
                else:
                    page.data.tree.selection_set(())
                gen0 = page.gen
                page.plot()
                ok = pump(lambda: page.gen > gen0 and page.busy is None and page.last is not None
                          and page.last["analysis"] is a, 30)
                if not ok:
                    raise AssertionError(f"{key}「{a.name}」沒有畫完（{page.right.text.get('1.0', 'end').strip()[:200]}）")
                _gui_values(key, a.name, page.last["result"])        # 介面用預設參數算出來的數值也要對
                results.append(f"{key}:{a.name}")
        # 再切換一輪（頁面都建好了），量切換時間
        gaps.clear()
        t0 = time.perf_counter()
        for _ in range(3):
            for key in INSTRUMENTS:
                t1 = time.perf_counter()
                app.segment.select(key)
                root.update()                       # 包含重新排版與畫面更新的時間
                switch_ms.append((time.perf_counter() - t1) * 1000)
        switch_total = time.perf_counter() - t0
        # 背景計算時畫面不能卡住：選很多 Raman 檔一次算
        page = app.pages["Raman"]
        app.segment.select("Raman")
        page.features.select("多檔峰值總表")
        page.data.select_all()
        gaps.clear()
        last[0] = time.perf_counter()
        gen0 = page.gen
        page.plot()
        pump(lambda: page.gen > gen0 and page.busy is None, 30)
        bg_gaps = sorted(gaps)
        # 圖的大小：固定大小時要出現捲軸、圖不被壓縮
        app.view.update(size_mode="固定大小", fig_w=2400, fig_h=1400)
        app.on_view_change()
        pump(lambda: False, 0.5)
        w = page.right.canvas.get_tk_widget()
        fixed_ok = w.winfo_width() >= 2300 and page.right.hsb.winfo_ismapped()
        app.view.update(size_mode="填滿視窗")
        app.on_view_change()
        pump(lambda: False, 0.3)
        # 改參數 → 自動重畫；打錯字 → 紅框、不會當掉
        page = app.pages["PPMS"]
        app.segment.select("PPMS")
        page.features.select("R–T 與 Tc")
        page.data.tree.selection_set([i for i in page.data.tree.get_children() if "300K" in i])
        pump(lambda: page.busy is None and page.last is not None and page.last["analysis"].name == "R–T 與 Tc", 20)
        gen0 = page.gen
        page.panel().vars["T_range"].set("2, 12")
        assert pump(lambda: page.gen > gen0 and page.busy is None and page.last["params"]["T_range"] == (2.0, 12.0), 20), \
            "改參數後沒有自動重畫"
        gen1 = page.gen
        page.panel().vars["smooth"].set("abc")
        pump(lambda: False, 0.6)
        assert page.gen == gen1 and str(page.panel().widgets["smooth"].cget("style")) == "Bad.TEntry", "打錯字應該顯示紅框"
        page.panel().vars["smooth"].set("0")
        # 匯出結果：圖、CSV、result.json
        app.settings["output_root"] = os.path.join(os.environ["MAGIC_DATA"], "out")
        pump(lambda: page.busy is None, 10)
        page.export()
        import glob
        outs = glob.glob(os.path.join(app.settings["output_root"], "PPMS", "*", "result.json"))
        assert outs, "匯出結果沒有產生 result.json"
        import json as _json
        rec = _json.load(open(outs[0], encoding="utf-8"))
        assert rec["sources"][0].get("sha256") and rec["params"]["T_range"] == "2, 12", rec["params"]
        # 設定視窗：開啟、儲存
        from .gui.settings_dialog import SettingsDialog
        dlg = SettingsDialog(app)
        pump(lambda: False, 0.3)
        dlg.save()
        # 新增蝕刻紀錄（精靈）：填值 → 預覽 → 動畫不卡 → 寫入暫存的 CSV
        ep = app.pages["Etching"]
        app.segment.select("Etching")
        from .etching import store as _store
        local = ep.data.csv_path()
        n0 = len(_store.read_log(local)) if os.path.exists(local) else 0      # 寫入後表格會切到本機 CSV
        wz = ep.data.new_record()
        for k, v in dict(material="hBN", line_width="200", icp_power="100", rf_power="30", pressure="10",
                         steps="3x20", mat_before="80.1, 79.9, 80.3", mat_out="45.2, 45.8, 45.0",
                         marker_before="50.2 50.0", marker_out="53.1, 52.9", name="selftest").items():
            wz.vars[k].set(v)
        wz.vars["pressure_unit"].set("mTorr")
        wz.gas_vars[0][1].set("40")
        assert pump(lambda: wz.result is not None, 5), f"精靈沒有算出結果：{wz.small.cget('text')}"
        # d_SiO2 = 53.0 − 50.1 = 2.9；d = 80.1 + 2.9 − 45.333 = 37.667；t = 60
        _near(wz.result.r_mat, (80.1 + 2.9 - 136.0 / 3) / 60, 1e-6, "精靈算出的 r_hBN")
        assert "nm/s" in wz.big.cget("text"), wz.big.cget("text")
        for i in range(7):
            wz.select_stage(i)
            root.update()
        wz.focus_field("mat_out")
        pump(lambda: False, 0.5)              # 讓切換頁面時排隊的重畫先做完，只量動畫本身
        frame = []
        wz.play_etch()
        t0 = last_t = time.perf_counter()
        while wz._anim is not None and time.perf_counter() - t0 < 15:
            root.update()
            now = time.perf_counter()
            frame.append(now - last_t)
            last_t = now
            time.sleep(0.002)
        assert wz._anim is None, "蝕刻動畫沒有結束"
        wz.save()
        assert pump(lambda: ep.data.df is not None and len(ep.data.df) == n0 + 1
                    and ep.data.source_var.get() == "本機 CSV", 10), "新增的紀錄沒有出現在表格"
        last_row = ep.data.df.iloc[-1]
        assert last_row["Material"] == "hBN" and abs(last_row["Line width (nm)"] - 200) < 1e-9, last_row
        stats["anim_gap"] = max(frame)
        stats.update(results=results, switch_ms=switch_ms, switch_total=switch_total, bg_gaps=bg_gaps,
                     timings=list(app.timings), fixed_ok=fixed_ok)
        app.close()

    ok = rep.check("軟體視窗：每台機台、每個功能實際畫一次", lambda: (go(), f"{len(stats['results'])} 個功能")[1])
    if not ok:
        try:
            root.destroy()
        except Exception:
            pass
        return
    sw = sorted(stats["switch_ms"])
    worst_draw = max(t[3] for t in stats["timings"]) if stats["timings"] else 0
    max_gap = stats["bg_gaps"][-1] if stats["bg_gaps"] else 0

    def perf():
        rep.log(f"    切換時間（ms）：{', '.join(f'{v:.0f}' for v in stats['switch_ms'])}")
        if sw[-1] > 150:
            raise AssertionError(f"切換機台最慢 {sw[-1]:.0f} ms（> 150 ms）")
        if max_gap > 0.6:
            raise AssertionError(f"背景計算時畫面最多卡住 {max_gap * 1000:.0f} ms（> 600 ms）")
        if stats.get("anim_gap", 0) > 0.1:
            raise AssertionError(f"蝕刻動畫最多卡住 {stats['anim_gap'] * 1000:.0f} ms（> 100 ms）")
        if not stats["fixed_ok"]:
            raise AssertionError("固定大小時圖被壓縮或沒有出現捲軸")
        return (f"切換機台 中位數 {sw[len(sw) // 2]:.1f} ms、最慢 {sw[-1]:.1f} ms；"
                f"背景計算時畫面最長停頓 {max_gap * 1000:.0f} ms；單張圖最久繪製 {worst_draw * 1000:.0f} ms；"
                f"蝕刻動畫最長一格 {stats.get('anim_gap', 0) * 1000:.0f} ms")
    rep.check("介面流暢度", perf)


def _gui_values(key, name, res):
    """介面上用「預設參數」算出的結果要和正確答案一致（避免預設值沒有正確帶進參數面板）。"""
    from .testdata import TRUTH
    import numpy as np
    if (key, name) == ("PPMS", "R–T 與 Tc"):
        vals = [v for k, v in res.summary.items() if "300K" in k and np.isfinite(v)]
        assert vals, "沒有算出 Tc"
        for v in vals:
            assert abs(v - TRUTH["ppms_Tc_cool"]) < 0.1, f"介面算出的 PPMS Tc = {v:.3f}"
        other = [v for k, v in res.summary.items() if "sampleB" in k]
        for v in other:
            _near(v, 6.6, 0.05, "介面算出的 sampleB Tc")
    elif (key, name) == ("SQUID", "M–T 與 Tc"):
        for v in res.summary.values():
            _near(v, TRUTH["squid_Tc"], TOL["Tc"], "介面算出的 SQUID Tc")
    elif (key, name) == ("SQUID", "M–H 迴線"):
        hc = [abs(r["H_c,10% (Oe)"]) for r in res.summary["rows"] if np.isfinite(r["H_c,10% (Oe)"])]
        assert hc, "沒有算出 Hc"
        for v in hc:
            _near(v, TRUTH["squid_Hc"], TOL["Hc"], "介面算出的 Hc")
    elif (key, name) == ("Raman", "石墨烯 G / 2D 峰"):
        for label, d in res.summary.items():
            _near(d["G_pos"], TRUTH["raman_G"], TOL["peak"], f"介面算出的 G 位置（{label}）")
            _near(d["2D_pos"], TRUTH["raman_2D"], TOL["peak"], f"介面算出的 2D 位置（{label}）")


def _wanted(key, a, name):
    n = name.lower()
    if key == "SQUID":
        return "mh" in n if "M–H" in a.name else "mt" in n
    if key == "PPMS":
        return True
    if key == "Raman":
        return "hbn" in n or "mono" in n if a.group == "參數萃取" else True
    return True


def main(gui=True, log=print):
    from .core.settings import TOOL_ROOT
    from .testdata import write_all
    tmp = tempfile.mkdtemp(prefix="magic_selftest_")
    old_env = os.environ.get("MAGIC_DATA")
    os.environ["MAGIC_DATA"] = os.path.join(tmp, "appdata")        # 設定與紀錄寫到暫存資料夾
    os.environ.setdefault("MPLBACKEND", "Agg")
    rep = Report(log)
    log(f"Magic Tool 自我測試（{TOOL_ROOT}）")
    try:
        from . import __version__
        log(f"版本 v{__version__}，Python {sys.version.split()[0]}")
        paths = {}
        rep.check("程式載入", check_imports)
        rep.check("產生合成資料", lambda: paths.update(write_all(os.path.join(tmp, "data"))) or f"{len(paths)} 個檔案")
        if paths:
            rep.check("讀檔", lambda: check_readers(paths))
            rep.check("分析功能（數值和正確答案比對）", lambda: check_analyses(paths))
            rep.check("蝕刻速率", lambda: check_etching(paths))
        rep.check("設定與工具", lambda: check_settings_and_tools(tmp))
        rep.check("自動更新（本機模擬）", lambda: check_update(tmp))
        if gui:
            run_gui(rep)
    finally:
        if old_env is None:
            os.environ.pop("MAGIC_DATA", None)
        else:
            os.environ["MAGIC_DATA"] = old_env
        shutil.rmtree(tmp, ignore_errors=True)
    if rep.failed:
        log(f"\n✗ {len(rep.failed)} / {rep.n} 項沒有通過：{'、'.join(rep.failed)}")
        return False
    log(f"\n✓ 全部 {rep.n} 項通過")
    return True


if __name__ == "__main__":
    sys.exit(0 if main(gui="--no-gui" not in sys.argv) else 1)
