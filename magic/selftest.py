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


def perf_factor():
    """流暢度門檻的倍數。只有 GitHub 的雲端測試機（共用的虛擬機，時間抖動大）會設 MAGIC_PERF_FACTOR；
    你電腦上的 publish / 收更新 一律用原本的門檻（1 倍）。"""
    try:
        return max(1.0, float(os.environ.get("MAGIC_PERF_FACTOR", "1")))
    except ValueError:
        return 1.0


def _record_perf(values, base, log=print):
    """發佈前檢查（你電腦上）量到的流暢度存起來，並和這台電腦上一次比較。"""
    try:
        from . import __version__
        from .core import perfhist
        prev = perfhist.last(base)
        cur = perfhist.append(values, __version__, base)
        lines, slower = perfhist.compare(prev, cur)
        log("")
        for line in lines:
            log("  " + line)
        if slower:
            log(f"  ⚠ {'、'.join(slower)} 比上一版明顯變慢（還在門檻內，所以可以發佈；把這段貼給 Claude 可以查原因）")
    except Exception as e:
        log(f"  （流暢度紀錄沒有存成功：{e}）")


def _has_tk(python):
    import subprocess
    try:
        return subprocess.run([python, "-c", "import tkinter"], capture_output=True, timeout=60).returncode == 0
    except Exception:
        return False


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

    from .testdata import FakeWorksheet

    class FakeWS(FakeWorksheet):
        @property
        def rows(self):
            return self.grid

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
    out.append(_check_etching_03(paths, FakeWS))
    out.append(_check_gsync(paths))
    return "；".join(out)


def _check_gsync(paths):
    """v0.7：團隊共用的 Google Sheet（合成的舊試算表：20 欄 + 自己加的 note）。"""
    import math
    from .etching import gsync, store
    from .etching.model import EtchInput, compute
    from .testdata import FakeWorksheet, team_sheet_values
    vals = team_sheet_values()
    df = gsync.rows_to_df(vals)
    assert len(df) == 5 and df["Notes"].iloc[2] == "baked 60 min", "讀舊試算表：空白列略過、note → Notes"
    assert df["RF power (W)"].iloc[2] == 8 and df["DC bias (V)"].iloc[0] == 10, "Bias 的 8W / 10V 要分開"
    inp = EtchInput(material="hBN", steps="20+20", sio2_method="marker", marker_before="50", marker_out="55",
                    mat_method="outside", mat_before="100", mat_out="40", name="Cat")
    rec = store.make_record(inp, compute(inp))
    rec.update({"Record ID": "12e45", "Revision": 1})
    ws = FakeWorksheet(vals)
    assert gsync.append_records(gsync.GspreadSheet(ws), [rec]) == [7], "新紀錄寫在最後一筆資料下面"
    v = ws.get_all_values()
    assert v[0][:21] == vals[0] and [r[20] for r in v[1:6]] == [r[20] for r in vals[1:6]], "原本的欄位（含 note）不能動"
    assert v[6][v[0].index("Record ID")] == "12e45", "Record ID 要保持文字"
    gsync.update_record(gsync.GspreadSheet(ws), "12e45", dict(rec, Notes="改過"), rec)
    assert gsync.rows_to_df(ws.get_all_values())["Notes"].iloc[-1] == "改過"
    folder = os.path.join(os.path.dirname(paths["etching"]), "gsync_test")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "log.csv")
    if os.path.exists(path):
        os.remove(path)
    store.append_record(rec, path)
    only_sheet, only_local = gsync.diff(store.read_log(path), df)
    assert (len(only_sheet), len(only_local)) == (5, 1), (len(only_sheet), len(only_local))
    gsync.import_to_local(only_sheet, path)
    loc = store.read_log(path)
    assert len(loc) == 6 and loc["Name"].iloc[0] == "Ann" and gsync.diff(loc, df)[0] == [], "匯入後不能重複"
    assert math.isclose(loc["R_hBN(nm/sec)"].iloc[0], 14.8 / 45, rel_tol=1e-9)
    assert gsync.parse_code(gsync.make_code({"etching": {"gsheet_key": "k", "gsheet_token": "t"}}))["gsheet_token"] == "t"
    assert "function doPost" in gsync.script_code(), "Apps Script 程式碼要跟著軟體"
    return "團隊 Google Sheet（名稱對應、保留 note、匯入 / 上傳比對）"


def _check_etching_03(paths, FakeWS):
    """v0.3：交叉檢查、光阻蝕刻率、修改 / 刪除 / 歷史、0.2 格式自動升級、Google Sheet 同步、AFM profile、
    每段延遲模型、線寬模型擬合。"""
    import csv as _csv
    import numpy as np
    import pandas as pd
    from .etching import store
    from .etching.afm import read_profiles, step_height
    from .etching.model import EtchInput, compute
    from .testdata import TRUTH, afm_profile
    from .runner import run
    out = []
    base = dict(material="hBN", steps="20+20", sio2_method="marker", marker_before="50", marker_out="55",
                mat_method="outside", mat_before="100", mat_out="40")
    # --- 交叉檢查 ---
    r = compute(EtchInput(**base, cross_check=True, sio2_step="5.3, 5.1", mat_step="64.5, 65.5"))
    assert len(r.sio2_cross) == 1 and r.sio2_cross[0][5] and len(r.mat_cross) == 1 and r.mat_cross[0][5], \
        (r.sio2_cross, r.mat_cross)
    _near(r.sio2_cross[0][1], 5.2, 1e-9, "交叉檢查 d_SiO2（AFM）")
    assert not r.warnings, r.warnings
    r = compute(EtchInput(**base, cross_check=True, sio2_step="8"))
    assert r.sio2_cross and not r.sio2_cross[0][5] and any("兩種量法" in w for w in r.warnings), "差太多要提醒"
    r = compute(EtchInput(**base, sio2_step="8"))
    assert not r.sio2_cross, "沒勾交叉檢查就不比對"
    # --- 光阻蝕刻率 ---
    r = compute(EtchInput(**base, resist_thickness="300", resist_after="280, 282"))
    _near(r.r_resist, 19 / 40, 1e-9, "r_光阻")
    _near(r.sel_resist, (65 / 40) / (19 / 40), 1e-9, "材料 / 光阻選擇比")
    _near(r.resist_life, 300 / (19 / 40), 1e-6, "光阻可以撐的時間")
    r = compute(EtchInput(**base, resist_thickness="300", resist_after="20"))
    assert any("光阻只剩" in w for w in r.warnings) and any("光阻不夠厚" in w for w in r.warnings), r.warnings
    r = compute(EtchInput(**base, resist_thickness="300", resist_after="0.2"))
    assert r.resist_through and any("光阻已經被蝕刻完" in w for w in r.warnings)
    out.append("交叉檢查、光阻蝕刻率")
    # --- 修改 / 刪除 / 歷史 / 還原 ---
    folder = os.path.join(os.path.dirname(paths["etching"]), "edit_test")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "log.csv")
    recs = []
    for k, mo in enumerate(("40", "41", "42")):
        inp = EtchInput(**{**base, "mat_out": mo, "name": f"P{k}"})
        recs.append(store.append_record(store.make_record(inp, compute(inp)), path))
    df = store.read_log(path)
    ids = list(df["Record ID"])
    assert len(set(ids)) == 3 and all(ids), "每筆都要有 Record ID"
    row = df.iloc[1].to_dict()
    back = store.record_to_inputs(row)
    assert back["mat_out"] == "41" and back["sio2_method"] == "marker", back
    inp = EtchInput(**{**back, "mat_out": "45"})
    old, new = store.replace_record(path, ids[1], store.make_record(inp, compute(inp)))
    df2 = store.read_log(path)
    assert len(df2) == 3 and list(df2["Record ID"]) == ids, "修改不能改變順序和 ID"
    assert df2["Revision"].iloc[1] == "2" and df2["DateTime"].iloc[1] == df["DateTime"].iloc[1]
    _near(df2["H_hBN_after (nm)"].iloc[1], 45, 1e-9, "修改後的值")
    hist = store.read_history(path)
    assert len(hist) == 1 and hist["Action"].iloc[0] == "修改" and "H_hBN_after" in hist["Changed fields"].iloc[0]
    store.delete_record(path, ids[0])
    assert list(store.read_log(path)["Record ID"]) == ids[1:]
    hist = store.read_history(path).to_dict("records")
    store.restore_history(path, hist[-1])                       # 還原刪除 → 回到第 1 筆
    assert list(store.read_log(path)["Record ID"]) == ids, "還原刪除要放回原來的位置"
    store.restore_history(path, hist[0])                        # 還原修改 → 41
    df3 = store.read_log(path)
    _near(df3["H_hBN_after (nm)"].iloc[1], 41, 1e-9, "還原修改")
    assert df3["Revision"].iloc[1] == "3"
    try:
        store.replace_record(path, "不存在", recs[0])
        raise AssertionError("找不到的 ID 要停下來")
    except store.RecordNotFound:
        pass
    out.append("修改 / 刪除 / 歷史還原")
    # --- OM 照片：複製到 _images、相對路徑、換照片時舊的留著 ---
    import numpy as _np
    from PIL import Image
    src_dir = os.path.join(folder, "photos")
    os.makedirs(src_dir, exist_ok=True)
    pics = []
    for k in range(2):
        fp = os.path.join(src_dir, f"om{k}.png")
        Image.fromarray((_np.random.default_rng(k).random((40, 60, 3)) * 255).astype("uint8")).save(fp)
        pics.append(fp)
    rel = store.attach_image(path, ids[1], "before", pics[0])
    assert rel == f"log_images/{ids[1]}_before.png", rel
    assert store.resolve_image(path, rel) is not None and os.path.exists(pics[0]), "原始照片要留著"
    assert store.attach_image(path, ids[1], "before", str(store.resolve_image(path, rel))) == rel, "同一張不要重複複製"
    store.attach_image(path, ids[1], "before", pics[1])
    olds = [n for n in os.listdir(store.images_dir(path)) if "_old_" in n]
    assert len(olds) == 1, "換照片時舊的要改名留著"
    assert store.resolve_image(path, "log_images/不存在.png") is None
    inp = EtchInput(**{**back, "mat_out": "41"})
    rec = store.make_record(inp, compute(inp))
    rec["OM before"] = rel
    store.replace_record(path, ids[1], rec)
    assert store.read_log(path)["OM before"].iloc[1] == rel
    out.append("OM 照片")
    # --- 0.2 寫的檔案（少了後面的欄位）→ 自動備份、補欄位 ---
    old_head = store.HEADERS[:len(store.HEADERS) - len(store.EXTRA_03) - len(store.EXTRA_04)]
    p02 = os.path.join(folder, "v02.csv")
    with open(p02, "w", encoding="utf-8-sig", newline="") as f:
        w = _csv.writer(f)
        w.writerow(old_head)
        w.writerow([store._cell(recs[0].get(c, "")) for c in old_head])
    assert store.file_schema(p02) == "v2old"
    store.append_record(recs[1], p02)
    assert store.file_schema(p02) == "v2" and len(store.read_log(p02)) == 2
    assert any("升級前備份" in n for n in os.listdir(folder)), "0.2 的檔案升級前要備份"
    assert all(store.read_log(p02)["Record ID"]), "升級時要補上 Record ID"
    # --- Google Sheet：修改、刪除對到正確的列 ---
    ws = FakeWS([store.HEADERS] + [[str(store._cell(r.get(c, ""))) for c in store.HEADERS] for r in recs])
    new_rec = dict(recs[2], **{"Notes": "改過"})
    i = store.gsheet_update(recs[2]["Record ID"], new_rec, recs[2], "k", "sa", ws=ws)
    assert i == 4 and ws.rows[3][store.HEADERS.index("Notes")] == "改過", "Google Sheet 要改對的那一列"
    store.gsheet_delete(recs[0]["Record ID"], recs[0], "k", "sa", ws=ws)
    assert len(ws.rows) == 3 and ws.rows[1][store.HEADERS.index("Record ID")] == recs[1]["Record ID"]
    try:
        store.gsheet_update("沒有這個", new_rec, None, "k", "sa", ws=ws)
        raise AssertionError("Google Sheet 找不到時要停下來，不能改錯列")
    except store.SheetError:
        pass
    out.append("0.2 格式自動升級、Google Sheet 修改 / 刪除（模擬）")
    # --- AFM profile ---
    for kind, trench in (("gwyddion", False), ("gwyddion", True), ("nanoscope", False)):
        fp = afm_profile(os.path.join(folder, f"afm_{kind}_{trench}.txt"), h=37.5, kind=kind, trench=trench)
        profs = read_profiles(fp)
        assert len(profs) == (2 if kind == "gwyddion" else 1), len(profs)
        for k, pr in enumerate(profs):
            _near(pr.x.max(), 6000, 1.0, f"AFM x 單位換算（{kind}）")
            r = step_height(pr.x, pr.z)
            assert r["ok"] and not r["reason"], r["reason"]
            _near(r["h"], 37.5, 0.3, f"AFM 台階（{kind}{'，溝槽' if trench else ''}）")
            assert len(r["edges"]) == (2 if trench else 1), r["edges"]
    pr = read_profiles(os.path.join(folder, "afm_nanoscope_False.txt"))[0]
    r = step_height(pr.x, pr.z, low_range=(300, 2600), high_range=(3400, 5800))
    _near(r["h"], 37.5, 0.3, "AFM 手動範圍")
    flat = step_height(pr.x, 20 + np.random.default_rng(1).normal(0, 0.3, pr.x.size))
    assert not flat["ok"] or flat["reason"], "平的 profile 不應該找到可靠的台階"
    out.append("AFM profile 找台階")
    # --- 每段延遲模型：d = r·(t − N·t0) ---
    rr, t0 = 1.0, 3.0
    rows = []
    for steps, t, n in (("20", 20, 1), ("40", 40, 1), ("2x20", 40, 2), ("3x20", 60, 3), ("60", 60, 1)):
        inp = EtchInput(material="hBN", line_width="1000", steps=steps, sio2_method="none", mat_method="inside",
                        mat_before="200", mat_step=f"{rr * (t - n * t0):.4f}")
        rows.append(store.make_record(inp, compute(inp)))
    df = store.normalize(pd.DataFrame(rows))
    _, res = run("Etching", "多時間線性擬合", [df], model="每段都有延遲（d = r·(t − N·t₀)）")
    t = res.tables["time_fit"]
    _near(t["蝕刻率 (nm/s)"].iloc[0], rr, 1e-6, "每段延遲模型的蝕刻率")
    _near(t["每段延遲 t₀ (s)"].iloc[0], t0, 1e-6, "每段延遲 t₀")
    _, res = run("Etching", "多時間線性擬合", [df])
    assert abs(res.tables["time_fit"]["蝕刻率 (nm/s)"].iloc[0] - rr) > 0.01, "整段延遲模型應該擬合不好（對照）"
    # --- 線寬模型 r(w) = r∞(1 − e^(−w/w0)) ---
    _, res = run("Etching", "線寬比較", [paths["etching"]], source="多時間擬合的斜率（扣掉起始延遲）")
    f = res.tables["linewidth_fit"]
    _near(f["r∞"].iloc[0], TRUTH["etch_r_inf"], 0.04, "線寬模型 r∞")
    _near(f["w₀ (nm)"].iloc[0], TRUTH["etch_w0"], 15, "線寬模型 w₀")
    out.append(f"每段延遲 t₀ = {t0:g} s、線寬模型 r∞ = {f['r∞'].iloc[0]:.3f}、w₀ = {f['w₀ (nm)'].iloc[0]:.0f} nm")
    return "；".join(out)


def check_mac_support(tmp):
    """macOS：.command / .sh 啟動檔（LF 換行、可執行）、找 Python、Magic Tool.app 的內容。
    （這台不是 Mac 時只檢查檔案與 app 結構；找 Python 的腳本在 macOS / Linux 上實際跑一次）"""
    import plistlib
    import subprocess
    from .core.settings import TOOL_ROOT
    from .install import make_mac_app, mac_launcher_script
    from .updater import make_executable
    out = []
    names = ("run_magic.command", "install.command", "publish.command", "收更新.command", "magic_env.sh")
    for name in names:
        fp = os.path.join(TOOL_ROOT, name)
        data = open(fp, "rb").read()
        assert data.startswith(b"#!/bin/bash"), f"{name} 第一行要是 #!/bin/bash"
        assert b"\r" not in data, f"{name} 不能有 Windows 換行（Mac 會無法執行）"
    out.append(f"啟動檔 {len(names)} 個")
    app = make_mac_app(os.path.join(tmp, "Applications", "Magic Tool.app"), python=sys.executable)
    with open(os.path.join(app, "Contents", "Info.plist"), "rb") as f:
        info = plistlib.load(f)
    assert info["CFBundleExecutable"] == "MagicTool" and info["CFBundleIdentifier"]
    exe = os.path.join(app, "Contents", "MacOS", "MagicTool")
    assert os.path.exists(os.path.join(app, "Contents", "Resources", "icon.icns")), "app 沒有圖示"
    script = mac_launcher_script("/路徑 有 空白/Magic'Tool", "/opt/anaconda3/bin/python")
    bash = shutil.which("bash")
    if os.name != "nt" and bash:
        assert os.stat(exe).st_mode & 0o111, "app 的啟動腳本要可以執行"
        for code in (open(exe, encoding="utf-8").read(), script):
            r = subprocess.run([bash, "-n"], input=code, text=True, encoding="utf-8", capture_output=True)
            assert r.returncode == 0, r.stderr
        # 啟動檔沒有執行權限時（例如從 zip 解壓縮）→ 更新後補上
        d = os.path.join(tmp, "exec_test")
        os.makedirs(d, exist_ok=True)
        fp = os.path.join(d, "a.command")
        open(fp, "w", encoding="utf-8").write("#!/bin/bash\n")
        os.chmod(fp, 0o644)
        assert make_executable(d) == ["a.command"] and os.stat(fp).st_mode & 0o100
        # 找 Python 的腳本：用目前這個 Python 的資料夾當 PATH，要找得到
        # （magic_env.sh 只接受有 tkinter 的 Python；這台的 Python 沒有 tkinter 時，這一小項略過）
        if _has_tk(sys.executable):
            env = dict(os.environ, MAGIC_DATA=os.path.join(tmp, "envtest"),
                       PATH=os.path.dirname(sys.executable) + os.pathsep + "/usr/bin:/bin")
            env.pop("CONDA_PREFIX", None)
            r = subprocess.run([bash, "-c", 'source "$1" && echo "PY=$PYEXE"', "_",
                                os.path.join(TOOL_ROOT, "magic_env.sh")],
                               env=env, capture_output=True, text=True, encoding="utf-8", timeout=120, input="n\n")
            assert r.returncode == 0 and "PY=" in r.stdout and r.stdout.strip() != "PY=", r.stdout + r.stderr
            out.append("找 Python 的腳本、app 腳本語法")
        else:
            out.append("app 腳本語法（這台的 Python 沒有 tkinter，略過找 Python 的腳本）")
        # App 殼：pythonw 一開就失敗 → 改用 python 再試；還是失敗 → 跳出說明（這台沒有 osascript 時印出 ALERT）
        fake = os.path.join(tmp, "fakepy")
        os.makedirs(fake, exist_ok=True)
        for name in ("pythonw", "python"):
            fp = os.path.join(fake, name)
            with open(fp, "w", newline="\n", encoding="utf-8") as f:
                f.write(f"#!/bin/bash\necho 'Traceback: {name} 測試失敗' >&2\nexit 1\n")
            os.chmod(fp, 0o755)
        home = os.path.join(tmp, "machome")
        app2 = make_mac_app(os.path.join(home, "Applications", "T.app"), python=os.path.join(fake, "python"))
        r = subprocess.run([os.path.join(app2, "Contents", "MacOS", "MagicTool")], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=60, env={"HOME": home, "PATH": "/usr/bin:/bin", "MAGIC_NO_ALERT": "1"})
        log = open(os.path.join(home, "Library", "Application Support", "MagicTool", "logs", "app_launch.log"),
                   encoding="utf-8").read()
        assert r.returncode == 1 and "改用 python 再試一次" in log, log
        assert "ALERT:" in r.stderr and "python 測試失敗" in r.stderr, r.stderr
        out.append("App 殼：失敗時改用 python 重試、顯示錯誤")
        # 程式放在「文件」裡：安裝時複製到不受 macOS 隱私權限制的位置
        from .install import copy_program, mac_protected
        fake_home = os.path.realpath(os.path.join(tmp, "machome"))
        old_home = os.environ.get("HOME")
        os.environ["HOME"] = fake_home
        try:
            assert mac_protected(os.path.join(fake_home, "Documents", "MagicTool-main"))
            assert mac_protected(os.path.join(fake_home, "Downloads", "x"))
            assert not mac_protected(os.path.join(fake_home, "MagicTool"))
            assert not mac_protected(os.path.join(fake_home, "Library", "Application Support", "MagicTool", "program"))
        finally:
            if old_home is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = old_home
        dst = copy_program(TOOL_ROOT, os.path.join(tmp, "program"))
        assert os.path.exists(os.path.join(dst, "magic", "__main__.py")) and not os.path.exists(os.path.join(dst, ".git"))
        assert os.stat(os.path.join(dst, "run_magic.command")).st_mode & 0o100, "複製後啟動檔要可以執行"
        dst = copy_program(TOOL_ROOT, os.path.join(tmp, "program"))          # 再裝一次：覆蓋舊的
        assert not os.path.exists(dst + ".old") and not os.path.exists(dst + ".new")
        r = subprocess.run([sys.executable, "-c", "import magic, sys; print(magic.__file__)"], cwd=tmp,
                           env=dict(os.environ, PYTHONPATH=dst), capture_output=True, text=True, encoding="utf-8", timeout=60)
        assert r.returncode == 0 and r.stdout.strip().startswith(dst), r.stdout + r.stderr
        out.append("文件資料夾 → 複製程式")
    out.append("Magic Tool.app")
    return "、".join(out)


def check_report(tmp):
    """📦 錯誤回報：log 與環境資訊打包成 zip，金鑰路徑與 Google Sheet 網址要遮掉。"""
    import zipfile
    from .core import settings as S
    from .core.report import make_report
    logs = S.log_dir()
    (logs / "error.log").write_text("Traceback 測試\n", encoding="utf-8")
    (logs / "crash.log").write_text("crash 測試\n", encoding="utf-8")
    cfg = S.load_settings()
    cfg["etching"]["gsheet_key"] = "https://docs.google.com/spreadsheets/d/SECRET123/edit"
    cfg["etching"]["service_account"] = r"D:\secret\sa.json"
    S.save_settings(cfg)
    fp = make_report(os.path.join(tmp, "report"), note="測試")
    with zipfile.ZipFile(fp) as z:
        names = z.namelist()
        assert {"環境.txt", "logs/error.log", "logs/crash.log"} <= set(names), names
        st = next(n for n in names if n.startswith("settings"))
        text = z.read(st).decode("utf-8")
        assert "SECRET123" not in text and "sa.json" not in text, "金鑰、試算表網址要遮掉"
        assert "Magic Tool v" in z.read("環境.txt").decode("utf-8")
    return f"{fp.name}（{len(names)} 個檔案，金鑰已遮掉）"


def check_raman_tools(paths):
    """Raman 編修（橡皮擦、手動背景）與峰標註。"""
    import numpy as np
    from matplotlib.figure import Figure
    from .raman import edits as E
    from .raman import labels as L
    from .readers import load
    from .readers.raman_txt import xy
    from .runner import run
    from .testdata import TRUTH
    p = paths["raman_mono"]
    ds = load(p)
    x, y = xy(ds)
    # 橡皮擦：指定的點被拿掉、原始資料不變
    i = int(np.argmin(np.abs(x - 2000)))
    ed = {"erase": [float(x[i]), float(x[i + 1])], "anchors": [], "sig": E.signature(x)}
    d2 = E.apply(ds, ed)
    assert len(d2.df) == len(ds.df) - 2 and len(load(p).df) == len(ds.df), "橡皮擦不能改到原始資料"
    assert any("橡皮擦" in n for n in d2.notes)
    bad = E.apply(ds, {**ed, "sig": [1, 2, 3]})
    assert len(bad.df) == len(ds.df) and any("不同" in n for n in bad.notes), "檔案換了就不套用"
    # 手動背景：通過每個錨點
    anchors = [[1100.0, 10.0], [1800.0, 30.0], [2400.0, 25.0], [3000.0, 5.0]]
    for interp in E.INTERPS:
        bg = E.manual_baseline(np.array([a for a, _ in anchors]), anchors, interp)
        assert np.allclose(bg, [b for _, b in anchors]), f"背景要通過錨點（{interp}）"
    # 用 ALS 背景上的點當錨點 → G、2D 位置仍正確；加一個假的宇宙射線尖峰 → 擦掉後結果不變
    from .core.peaks import baseline_als
    bgals = baseline_als(y)
    idx = np.linspace(0, x.size - 1, 10).round().astype(int)
    anchors = [[float(x[k]), float(bgals[k])] for k in idx]
    _, res = run("Raman", "石墨烯 G / 2D 峰", [p], baseline="手動（錨點）",
                 edits={p: {"erase": [], "anchors": anchors, "interp": "平滑"}})
    t = res.tables["peaks"]
    _near(t["G 位置 (cm⁻¹)"].iloc[0], TRUTH["raman_G"], TOL["peak"], "手動背景的 G 位置")
    _near(t["2D 位置 (cm⁻¹)"].iloc[0], TRUTH["raman_2D"], TOL["peak"], "手動背景的 2D 位置")
    _, res = run("Raman", "石墨烯 G / 2D 峰", [p], edits=False)
    _, res2 = run("Raman", "石墨烯 G / 2D 峰", [p], edits={p: {"erase": [float(x[i])], "anchors": []}})
    _near(res2.tables["peaks"]["G 位置 (cm⁻¹)"].iloc[0], res.tables["peaks"]["G 位置 (cm⁻¹)"].iloc[0], 0.05,
          "擦掉一個無關的點不影響 G")
    # 背景扣除分析：選手動但沒有錨點 → 說明，不會當掉
    _, res = run("Raman", "背景扣除", [p], method="手動（錨點）", edits=False)
    assert any("錨點" in w for w in res.warnings), res.warnings
    # 峰標註
    fig = Figure()
    run("Raman", "石墨烯 G / 2D 峰", [p], fig=fig, edits=False)
    defs = L.defaults() + [L.make(L.defaults(), "Si", 520.7), L.make(L.defaults(), "D'", 1620.0)]
    defs[0].update(text="G peak", size=15, color="#111111", bold=True)
    n = L.draw(fig, defs)
    texts = [(t.get_text(), t.get_fontsize()) for ax in fig.axes for t in ax.texts if getattr(t, "magic_key", None)]
    names = [t.split("\n")[0] for t, _ in texts]
    assert "G peak" in names and "2D" in names and "D'" in names, names
    assert "Si" not in names, "顯示範圍外的標註不畫"
    assert "hBN" not in names and "D" not in names, "沒有擬合到的峰（預設）不畫"
    assert dict(texts)[next(t for t, _ in texts if t.startswith("G peak"))] == 15
    g = next(t for t, _ in texts if t.startswith("G peak"))
    _near(float(g.split("\n")[1]), TRUTH["raman_G"], TOL["peak"], "標註上的 G 位置")
    # 疊圖方式
    fig, res = run("Raman", "光譜檢視", [paths["raman_mono"], paths["raman_multi"]], stack="自動往上平移（不重疊）")
    l0, l1 = [ln.get_ydata() for ln in fig.axes[0].lines[:2]]
    assert np.nanmin(l1) >= np.nanmax(l0), "自動平移後不能重疊"
    return f"橡皮擦、手動背景、峰標註 {n} 個、疊圖"


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
    with open(os.path.join(old, "magic", "__main__.py"), "w", encoding="utf-8") as f:
        f.write("# old\n")
    with open(os.path.join(old, "magic", "obsolete.py"), "w", encoding="utf-8") as f:
        f.write("# should disappear\n")
    with open(os.path.join(old, "release.json"), "w", encoding="utf-8") as f:
        json.dump({"version": "0.0.1", "repo": "Yeep112/MagicTool", "branch": "main"}, f)
    with open(os.path.join(old, "settings.toml"), "w", encoding="utf-8") as f:
        f.write("keep = true\n")
    ver = updater.apply_update({"commit": None}, log=lambda m: None, zip_source=zpath, root=old)
    assert ver == updater.read_release(os.path.join(src, "release.json"))["version"], ver
    assert os.path.exists(os.path.join(old, "magic", "registry.py")) is False
    assert os.path.exists(os.path.join(old, "magic", "core", "registry.py")), "新程式沒有裝進去"
    assert not os.path.exists(os.path.join(old, "magic", "obsolete.py")), "舊模組應該被移除"
    assert open(os.path.join(old, "settings.toml"), encoding="utf-8").read() == "keep = true\n", "使用者檔案被覆蓋了"
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
        if getattr(rep, "require_gui", False):
            rep.n += 1
            rep.failed.append("軟體視窗（發佈前一定要實際開視窗測流暢度）")
            rep.log(f"  ✗ 沒辦法開視窗測試（{e}）：發佈前一定要實際跑過介面與流暢度，請在有螢幕的電腦上執行")
            return
        rep.log(f"  － 略過介面測試（這台電腦沒有可用的 Tk 顯示：{e}）")
        return
    root.withdraw()
    import matplotlib
    matplotlib.use("TkAgg")
    from .gui.app import App, prepare
    from .gui import theme as _T0
    from .core.registry import INSTRUMENTS
    ALL_KEYS = [*INSTRUMENTS, "Samples"]
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

        pump(lambda: all(k in app.pages for k in ALL_KEYS), 15)
        app.open_demo()
        pump(lambda: all(p.data.files for k, p in app.pages.items() if getattr(p, "inst", None) and p.inst.source == "files"), 15)
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
        # 樣品頁上面沒有畫圖，還沒顯示過：先顯示一次（和機台頁一樣，量的是第二次以後的切換）
        app.segment.select("Samples")
        root.update()
        app._settle_gc()                    # 和實際使用一樣：頁面建好後回收一次、凍結常駐物件
        # 再切換一輪（頁面都建好了），量切換時間。先等最後一張圖畫完（剛畫完馬上切走的頁面，回來時才補畫一次）
        pump(lambda: False, 0.8)
        gaps.clear()
        t0 = time.perf_counter()
        moves = []
        prev = app.state.get("instrument")                 # 現在這一頁（切換前）
        for _ in range(3):
            for key in ALL_KEYS:
                t1 = time.perf_counter()
                app.segment.select(key)
                root.update()                       # 包含重新排版與畫面更新的時間
                switch_ms.append((time.perf_counter() - t1) * 1000)
                moves.append((prev, key))
                prev = key
        switch_total = time.perf_counter() - t0
        # 偶發變慢（Windows 背景程式、防毒、記憶體回收剛好遇到）：比門檻的 8 成慢的那幾次，同樣的切換再量兩次取最快的。
        # 真的變慢（每次都慢）重量也一樣慢，照樣不會通過；原始數字會印在報告裡
        lim_sw = 150 * perf_factor()
        stats["switch_raw"] = list(switch_ms)
        for i, (a, b) in enumerate(moves):
            if switch_ms[i] <= lim_sw * 0.8 or a is None:
                continue
            again = []
            for _ in range(2):
                app.segment.select(a)
                root.update()
                pump(lambda: False, 0.15)
                t1 = time.perf_counter()
                app.segment.select(b)
                root.update()
                again.append((time.perf_counter() - t1) * 1000)
            switch_ms[i] = min([switch_ms[i]] + again)
        # 拆開量：每一欄（左 / 中 / 右）拿掉再放回去要多久，和元件數（找出切換最花時間的地方）
        def count(w):
            return 1 + sum(count(c) for c in w.winfo_children() if c.winfo_manager())
        panes = {}
        for key in ALL_KEYS:
            app.segment.select(key)
            root.update()
            cells = []
            for f in app.pages[key].frames():
                ts = []
                for _ in range(3):
                    f.grid_remove()
                    root.update()
                    t = time.perf_counter()
                    f.grid()
                    root.update()
                    ts.append((time.perf_counter() - t) * 1000)
                cells.append((sorted(ts)[1], count(f)))
            panes[key] = cells
        stats["panes"] = panes
        stats["screen"] = f"{root.winfo_width()}×{root.winfo_height()}，介面縮放 {getattr(_T0, 'UI_FACTOR', 1):g}"
        # 四頁疊在一起：切換後滑鼠指到的地方，一定要是這一頁的元件（不能被別頁蓋住）
        _raise_for_check(root)
        try:
            for key in ALL_KEYS:
                app.segment.select(key)
                root.update()
                for f in app.pages[key].frames():
                    w = _shown_at(root, f)
                    assert w is not None and str(w).startswith(str(f)), \
                        f"切換到 {key} 後，畫面上看到的是 {w}（應該在 {f} 裡）：頁面被蓋住了"
        finally:
            _raise_for_check(root, False)
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
        from .gui import theme as _T
        fixed_ok = w.winfo_width() >= _T.px(2400) * 0.95 and page.right.hsb.winfo_ismapped()   # 小螢幕介面會縮放
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
            _audit_window(wz, f"Etching 精靈（第 {i + 1} 段）", root)
        aw = wz.import_afm("mat_out")
        aw._no_ask = True                      # 不要跳出選檔視窗（雲端沒有人按）
        _audit_window(aw, "AFM 匯入", root)
        aw.destroy()
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
        _gui_03(app, root, pump, ep)
        _gui_samples(app, root, pump)
        _gui_sheet(app, root, pump)
        stats["layout"] = _gui_layout(app, root, pump)
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
    def layout():
        bad = list(stats.get("layout") or [])
        for b in _LAYOUT_EXTRA:
            if b not in bad:
                bad.append(b)
        if bad:
            raise AssertionError(f"{len(bad)} 個地方被切掉或超出視窗：\n      " + "\n      ".join(bad[:40]))
        return "小視窗與大視窗：每一頁、每個對話框都沒有被切掉"
    rep.check("排版：文字、按鈕沒有被切掉，超出的內容可以捲動", layout)
    sw = sorted(stats["switch_ms"])
    worst_draw = max(t[3] for t in stats["timings"]) if stats["timings"] else 0
    max_gap = stats["bg_gaps"][-1] if stats["bg_gaps"] else 0

    k = perf_factor()
    lim_sw, lim_bg, lim_anim = 150 * k, 600 * k, 100 * k

    def perf():
        rep.perf = {"switch_med": sw[len(sw) // 2], "switch_max": sw[-1], "bg_gap": max_gap * 1000,
                    "draw_max": worst_draw * 1000, "anim_max": stats.get("anim_gap", 0) * 1000}
        rep.log(f"    切換時間（ms）：{', '.join(f'{v:.0f}' for v in stats['switch_ms'])}")
        raw = stats.get("switch_raw") or []
        redo = [(r, v) for r, v in zip(raw, stats["switch_ms"]) if abs(r - v) > 0.5]
        if redo:
            rep.log("    （偶發變慢的那幾次已重量：" + "、".join(f"{r:.0f} → {v:.0f}" for r, v in redo) + " ms）")
        if stats.get("panes"):
            rep.log(f"    每一欄重新顯示（ms / 顯示中的元件數；視窗 {stats.get('screen', '')}）：")
            for key, cells in stats["panes"].items():
                rep.log(f"      {key:8s} " + "　".join(f"{n} {t:.0f} ms / {c} 個"
                                                     for n, (t, c) in zip(("左", "中", "右"), cells)))
        if k != 1:
            rep.log(f"    （雲端測試機：門檻放寬 {k:g} 倍；真正的流暢度門檻在你電腦上的 publish / 收更新 檢查）")
        if sw[-1] > lim_sw:
            raise AssertionError(f"切換機台最慢 {sw[-1]:.0f} ms（> {lim_sw:.0f} ms）")
        if max_gap * 1000 > lim_bg:
            raise AssertionError(f"背景計算時畫面最多卡住 {max_gap * 1000:.0f} ms（> {lim_bg:.0f} ms）")
        if stats.get("anim_gap", 0) * 1000 > lim_anim:
            raise AssertionError(f"蝕刻動畫最多卡住 {stats['anim_gap'] * 1000:.0f} ms（> {lim_anim:.0f} ms）")
        if not stats["fixed_ok"]:
            raise AssertionError("固定大小時圖被壓縮或沒有出現捲軸")
        return (f"切換機台 中位數 {sw[len(sw) // 2]:.1f} ms、最慢 {sw[-1]:.1f} ms；"
                f"背景計算時畫面最長停頓 {max_gap * 1000:.0f} ms；單張圖最久繪製 {worst_draw * 1000:.0f} ms；"
                f"蝕刻動畫最長一格 {stats.get('anim_gap', 0) * 1000:.0f} ms")
    rep.check("介面流暢度", perf)


class _Ev:
    def __init__(self, x, y, button=1):
        self.x, self.y, self.button = x, y, button
        self.inaxes = self.xdata = self.ydata = None


def _texts(w):
    out = []
    try:
        t = w.cget("text")
        if t:
            out.append(str(t))
    except Exception:
        pass
    for c in w.winfo_children():
        out += _texts(c)
    return out


def _raise_for_check(root, on=True):
    """檢查「畫面上看到什麼」時把軟體視窗放到最上層（執行測試的命令列視窗常常蓋在上面）。"""
    try:
        root.attributes("-topmost", bool(on))
        if on:
            root.lift()
        root.update()
    except Exception:
        pass


def _shown_at(root, f):
    """f 中間（只算螢幕上看得到的部分）那一點，畫面上看到的是哪個元件。

    那一點被別的程式（例如執行測試的命令列）蓋住、或在螢幕外面時，winfo_containing 會是 None：
    改用 Tk 自己的疊放順序判斷，只看這個軟體自己的元件有沒有蓋住 f。"""
    x0, y0 = f.winfo_rootx(), f.winfo_rooty()
    x1, y1 = x0 + f.winfo_width(), y0 + f.winfo_height()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    vx0, vy0, vx1, vy1 = max(x0, 0), max(y0, 0), min(x1, sw), min(y1, sh)
    if vx1 - vx0 > 4 and vy1 - vy0 > 4:
        x, y = (vx0 + vx1) // 2, (vy0 + vy1) // 2
    else:
        x, y = (x0 + x1) // 2, (y0 + y1) // 2
    w = root.winfo_containing(x, y)
    if w is not None:
        return w
    cover = _covering(f, x, y)
    return f if cover is None else cover


def _covering(f, x, y):
    """這個軟體裡蓋在 f 上面（疊放順序比較高、而且包含 (x, y)）的元件；沒有就是 None。"""
    import tkinter as tk
    def inside(w):
        try:
            if not w.winfo_ismapped():
                return False
            wx, wy = w.winfo_rootx(), w.winfo_rooty()
            return wx <= x < wx + w.winfo_width() and wy <= y < wy + w.winfo_height()
        except Exception:
            return False
    cur = f
    while getattr(cur, "master", None) is not None:
        parent = cur.master
        kids = parent.winfo_children()                     # Tk：由下往上的疊放順序
        if cur in kids:
            for s in kids[kids.index(cur) + 1:]:
                if s.winfo_class() in ("Toplevel", "Menu") or isinstance(s, tk.Toplevel):
                    continue
                if inside(s):
                    return s
        cur = parent
    return None


_LAYOUT_EXTRA = []          # 其他小視窗（Etching 精靈、Raman 編修、AFM 匯入、峰標註）的排版問題


def _audit_window(win, name, root):
    """小視窗的排版：原本大小、縮到最小的大小，各看一次。"""
    try:
        root.update()
        _LAYOUT_EXTRA.extend(_layout_audit(win, name))
        mw, mh = win.minsize()
        if mw > 1 and mh > 1:
            geo = win.geometry()
            win.geometry(f"{mw}x{mh}")
            root.update()
            _LAYOUT_EXTRA.extend(_layout_audit(win, f"{name}（縮到最小 {mw}×{mh}）"))
            win.geometry(geo)
            root.update()
    except Exception as e:
        _LAYOUT_EXTRA.append(f"{name}：排版檢查失敗 {e}")


_TEXTY = {"Label", "TLabel", "Button", "TButton", "Checkbutton", "TCheckbutton", "Radiobutton", "TRadiobutton"}


def _in_scroll(w):
    """在 ScrollFrame 裡面（直的超出可以捲動）。"""
    while w is not None:
        m = getattr(w, "master", None)
        if m is not None and m.winfo_class() == "Canvas":
            return True
        w = m
    return False


def _layout_audit(widget, where=""):
    """找出被切掉的文字 / 按鈕、超出視窗的元件。回傳 ["位置：說明", …]。"""
    out = []
    try:
        top = widget.winfo_toplevel()
        tx, ty, tw, th = top.winfo_rootx(), top.winfo_rooty(), top.winfo_width(), top.winfo_height()
    except Exception:
        return out

    def walk(w):
        try:
            if not w.winfo_ismapped() or not w.winfo_viewable():
                return
            cls = w.winfo_class()
            if cls in _TEXTY:
                try:
                    text = str(w.cget("text") or "")
                except Exception:
                    text = ""
                if text.strip() and not str(w.cget("image") or ""):
                    ww, wh, rw, rh = w.winfo_width(), w.winfo_height(), w.winfo_reqwidth(), w.winfo_reqheight()
                    t = text.replace("\n", " ")[:24]
                    scroll = _in_scroll(w)
                    if ww > 1 and ww + 3 < rw:
                        out.append(f"{where}：「{t}」被切掉（寬 {ww} < 需要 {rw}）")
                    elif wh > 1 and wh + 3 < rh and not scroll:
                        out.append(f"{where}：「{t}」被切掉（高 {wh} < 需要 {rh}）")
                    elif not scroll and (w.winfo_rootx() + ww > tx + tw + 3 or w.winfo_rooty() + wh > ty + th + 3):
                        out.append(f"{where}：「{t}」超出視窗")
            for c in w.winfo_children():
                walk(c)
        except Exception:
            pass
    walk(widget)
    return out


def _figure_fits(canvas, where):
    """matplotlib 的圖和畫布一樣大（不然下面會被切掉）。"""
    try:
        w = canvas.get_tk_widget()
        if not w.winfo_ismapped():
            return []
        try:
            fw, fh = canvas.get_width_height(physical=True)
        except TypeError:
            fw, fh = (int(v) for v in canvas.figure.bbox.size)
        ww, wh = w.winfo_width(), w.winfo_height()
        if ww > 20 and (abs(fw - ww) > 2 or abs(fh - wh) > 2):
            return [f"{where}：圖 {fw}×{fh} 和畫布 {ww}×{wh} 不一樣大（會被切掉）"]
    except Exception:
        pass
    return []


def _gui_layout(app, root, pump):
    """排版檢查（每次更新都跑）：最小視窗與大視窗，每一頁、樣品頁的細節 / 示意圖、每個對話框。"""
    from tkinter import messagebox
    from .gui import samples_edit as SE
    from .gui import samples_page as SPM
    from .gui.settings_dialog import SettingsDialog
    from .gui import sheet_setup as SS
    from .testdata import write_samples
    bad = []
    # 按鈕列：很窄時先改成只顯示圖示（同一行），變寬再顯示完整文字
    import tkinter as tk
    from tkinter import ttk as _ttk
    from .gui.widgets import WrapRow
    tw = tk.Toplevel(root)
    row = WrapRow(tw)
    row.pack(fill="x")
    full = ["＋ 新增步驟", "✎ 編輯", "🗑 刪除"]
    btns = [row.add(_ttk.Button(row, text=t), compact=t.split(" ")[0], side="right") for t in full]
    tw.geometry("170x60")
    pump(lambda: False, 0.3)
    if [b.cget("text") for b in btns] != ["＋", "✎", "🗑"] or len(row._plan[0]) != 1:
        bad.append(f"按鈕列很窄時沒有改成只顯示圖示（{[b.cget('text') for b in btns]}，{len(row._plan[0])} 行）")
    tw.geometry("700x60")
    pump(lambda: False, 0.3)
    if [b.cget("text") for b in btns] != full:
        bad.append("按鈕列變寬後沒有恢復完整文字")
    tw.destroy()
    old_geo = root.geometry()
    pg = app.page("Samples")
    p = write_samples(tempfile.mkdtemp(prefix="magic_layout_"))
    pg.save_cfg(root=p["root"], sheet=p["sheet"], user="layout")
    assert pump(lambda: not pg.scanning and pg.lib is not None and pg.lib.root == p["root"], 20)
    rows = SPM.SH.parse_table(SPM.SH.read_file(p["sheet"]))
    pg.use_lib(pg.apply_sheet(rows, p["sheet"]))
    saved = messagebox.askyesno
    messagebox.askyesno = lambda *a, **k: True
    try:
        from .gui.app import default_window, min_window
        sw_, sh_ = root.winfo_screenwidth(), root.winfo_screenheight()
        sizes = ["%dx%d" % min_window(sw_, sh_), "%dx%d" % default_window(sw_, sh_)]   # 最小視窗、開啟時的大小（跟著介面縮放）
        for size in dict.fromkeys(sizes):
            root.geometry(size)
            pump(lambda: False, 0.4)
            for key in list(app.pages):
                app.segment.select(key)
                root.update()
                pump(lambda: False, 0.15)
                page = app.pages[key]
                for f in page.frames():
                    bad += _layout_audit(f, f"{size} {key}")
                cv = getattr(getattr(page, "right", None), "canvas", None)
                if cv is not None:
                    bad += _figure_fits(cv, f"{size} {key}")
            app.segment.select("Samples")
            s = pg.find("901")
            pg.refresh_list(select=s["key"])
            root.update()
            sid = next(x["id"] for x in pg.record()["steps"] if x["kind"] == "contact")
            pg.set_view("detail")
            pg.select_step(sid)
            pump(lambda: False, 0.4)
            for f in pg.frames():
                bad += _layout_audit(f, f"{size} 樣品頁（步驟細節）")
            pg.set_view("visual")
            pump(lambda: len(pg._outlines.get(s["key"], [])) > 0, 5)
            pump(lambda: False, 0.6)
            bad += _layout_audit(pg.detail, f"{size} 樣品頁（示意圖）")
            bad += _figure_fits(pg.vis["canvas"], f"{size} 示意圖")
            sfc = pg.vis["sf"].canvas
            region = sfc.bbox("all")
            if region and region[3] > sfc.winfo_height() + 2:
                top, bottom = sfc.yview()
                if top <= 0 and bottom >= 1:
                    bad.append(f"{size} 示意圖：圖比畫面高但不能捲動")
            pg.set_view("detail")
            dialogs = [("步驟編輯", lambda: pg.edit_selected_step()), ("匯出 PPT", pg.open_export),
                       ("樣品設定", lambda: SPM.SampleSettings(pg)), ("從試算表匯入", lambda: SPM.ImportDialog(pg)),
                       ("待確認", lambda: SPM.ReviewDialog(pg)), ("新樣品", pg.open_new_sample),
                       ("樣品結果", pg.open_results), ("擱置", lambda: SE.StateDialog(pg, s, "hold")),
                       ("試算表", pg.open_sync), ("設定", lambda: SettingsDialog(app)),
                       ("貼上團隊設定碼", lambda: SS.TeamCodePrompt(app)), ("一步一步接 Apps Script", lambda: SS.ScriptGuide(app))]
            for name, make in dialogs:
                d = make()
                root.update()
                pump(lambda: False, 0.25)
                bad += _layout_audit(d, f"{size} {name}")
                if hasattr(d, "nb"):                        # 有分頁的：每一頁都看
                    for tab in d.nb.tabs()[1:]:
                        d.nb.select(tab)
                        root.update()
                        bad += _layout_audit(d, f"{size} {name}（{d.nb.tab(tab, 'text')}）")
                try:
                    if d.winfo_height() > d.winfo_screenheight() or d.winfo_width() > d.winfo_screenwidth():
                        bad.append(f"{size} {name}：視窗比螢幕大")
                except Exception:
                    pass
                d.destroy()
    finally:
        messagebox.askyesno = saved
        root.geometry(old_geo)
        pg.save_cfg(root="", sheet="", user="")
        root.update()
    seen, out = set(), []
    for b in bad:
        if b not in seen:
            seen.add(b)
            out.append(b)
    return out


def _gui_sheet(app, root, pump):
    """v0.7 蝕刻紀錄 ↔ 團隊 Google Sheet（不連網路：用合成的舊試算表代替公開連結）。"""
    from tkinter import messagebox
    from .etching import gsync, store
    from .testdata import team_sheet_values
    saved = gsync._public_csv, messagebox.askyesno, messagebox.showinfo, messagebox.showerror
    et = app.settings.setdefault("etching", {})
    old_et = dict(et)
    import gc
    gc.collect()        # 先在主執行緒清掉關掉的視窗留下的 Tk 變數（不然會在背景執行緒回收、卡住背景工作；只有測試沒跑 mainloop 時會這樣）
    try:
        gsync._public_csv = lambda et_, timeout=20: team_sheet_values()
        messagebox.askyesno = messagebox.showinfo = messagebox.showerror = lambda *a, **k: True
        et.update(gsheet_key="https://docs.google.com/spreadsheets/d/TEST/edit#gid=0", gsheet_script_url="",
                  gsheet_token="", service_account=os.path.join(tempfile.gettempdir(), "沒有這個金鑰.json"))
        ep = app.pages["Etching"]
        app.segment.select("Etching")
        rp = ep.data
        rp.source_var.set("Google Sheet")
        rp.reload()
        _okr = pump(lambda: rp.df is not None and len(rp.df) == 5 and rp.source_var.get() == "Google Sheet", 10)
        assert _okr, \
            f"讀不到 Google Sheet（公開連結）的舊紀錄：{app.status_var.get()}（{None if rp.df is None else len(rp.df)} 筆）"
        pump(lambda: "公開連結" in rp.path_lab.cget("text"), 3)
        assert "公開連結，唯讀" in rp.path_lab.cget("text"), rp.path_lab.cget("text")
        assert len(rp.tree.get_children()) == 5
        # 用 Google Sheet 的舊紀錄畫圖（不選 = 全部）
        rp.tree.selection_set(())
        a = next(x for x in ep.analyses if "比較" in x.name or "趨勢" in x.name)
        ep.features.select(a.name)
        gen0 = ep.gen
        ep.plot()
        ok = pump(lambda: ep.gen > gen0 and ep.busy is None and ep.last is not None and ep.last["analysis"] is a, 20)
        assert ok, f"用 Google Sheet 的紀錄畫「{a.name}」沒有完成：{ep.right.text.get('1.0', 'end').strip()[:200]}"
        # ☁ 同步：比對 → 加到本機 CSV（不重複）
        n_local = len(store.read_log(rp.csv_path()))
        win = rp.sync_dialog()
        assert pump(lambda: win.result is not None, 10) and not win.result.get("error"), win.result
        assert len(win.result["only_sheet"]) == 5, len(win.result["only_sheet"])
        win.do_import()
        assert pump(lambda: win.result is not None and "已把 5 筆" in (win.result.get("done") or ""), 10), win.result
        assert len(store.read_log(rp.csv_path())) == n_local + 5 and win.result["only_sheet"] == []
        win.destroy()
        gc.collect()
        # ⚙ 設定：貼上團隊設定碼
        from .gui.settings_dialog import SettingsDialog
        code = gsync.make_code({"etching": {"gsheet_key": et["gsheet_key"], "gsheet_worksheet": "",
                                            "gsheet_script_url": "https://script.google.com/macros/s/TEST/exec",
                                            "gsheet_token": "selftest"}})
        dlg = SettingsDialog(app, "蝕刻紀錄")
        dlg.test_sheet = lambda: None                     # 不連網路
        assert dlg.paste_code(code)
        cfg = dlg.collect()["etching"]
        assert cfg["gsheet_token"] == "selftest" and cfg["gsheet_enabled"] and cfg["gsheet_script_url"].endswith("/exec")
        assert dlg.copy_code().startswith(gsync.CODE_PREFIX)
        _gui_sheet_setup(app, root, pump, dlg, code)
        dlg.destroy()
        gc.collect()
        rp.source_var.set("本機 CSV")
        rp.reload()
        pump(lambda: rp.df is not None and rp.source_var.get() == "本機 CSV", 5)
    finally:
        gsync._public_csv, messagebox.askyesno, messagebox.showinfo, messagebox.showerror = saved
        et.clear()
        et.update(old_et)


def _gui_sheet_setup(app, root, pump, dlg, code):
    """v0.9.3：測試連線列出欄位對照、第一次開 Etching 貼團隊設定碼、一步一步接 Apps Script（都不連網路）。"""
    from .etching import gsync
    from .gui import sheet_setup as SS
    from .testdata import team_sheet_values
    # 真的測試連線（公開連結那條路，資料是合成的舊試算表）：要列出欄位對照
    msg, ok, cols = SS.sheet_check({"etching": {"gsheet_key": "https://docs.google.com/spreadsheets/d/TEST/edit#gid=0",
                                                "service_account": os.path.join(tempfile.gettempdir(), "沒有.json")}})
    assert ok and "讀得到" in msg and cols, (msg, cols)
    head = team_sheet_values()[0]
    rep = gsync.columns_report(head)
    assert "第一次寫入時加在最後面" in cols and "Record ID" in cols and rep["added"][0][0] == gsync.col_letter(rep["width"]), cols
    # 設定視窗：測試連線後下面出現欄位對照
    dlg._check = lambda cfg: ("✓ 讀得到（測試）：5 列資料\n✓ 可以寫入（測試）", True, cols)
    del dlg.test_sheet                                     # 換回真的 test_sheet（剛剛為了不連網路蓋掉）
    dlg.test_sheet()
    assert pump(lambda: dlg.cols_view.winfo_manager() == "grid" and "Record ID" in dlg.cols_view.value, 5), \
        "測試連線後沒有列出欄位對照"
    assert dlg.cols_view.copy() == cols
    # 一步一步接 Apps Script：填好就自動測試、每一步打勾、套用寫回設定視窗
    applied = []
    real_apply = app.apply_settings
    app.apply_settings = lambda cfg: applied.append(cfg)
    try:
        g = dlg.open_script_guide()
        root.update()
        _LAYOUT_EXTRA.extend(_layout_audit(g, "一步一步接 Apps Script"))
        for k, v in (("gsheet_key", "https://docs.google.com/spreadsheets/d/TEST/edit#gid=0"),
                     ("gsheet_worksheet", "etching rate"), ("gsheet_token", "Magic Tool 通行碼：abc123def456ghi789"),
                     ("gsheet_script_url", "https://script.google.com/macros/s/TEST/exec")):
            g.v[k].set(v)
        g.copy_script()
        assert g.values()["gsheet_token"] == "abc123def456ghi789", "整行「Magic Tool 通行碼：…」貼進來要只取通行碼"
        assert pump(lambda: g.done_steps()[:5] == [True] * 5, 5), f"填好後沒有自動測試連線：{g.done_steps()}"
        assert g.cols.winfo_manager() and "Record ID" in g.cols.value
        assert [m.cget("text") for m in g.marks[:5]] == ["✓"] * 5
        g.v["gsheet_token"].set("changed000000000")      # 改了通行碼 → 要重新測試（自動）
        assert not g.done_steps()[4], "改了通行碼，「測試連線」的勾要先拿掉"
        assert pump(lambda: g.done_steps()[4], 5), "改了通行碼後沒有自動重新測試"
        g.apply()
        assert applied and applied[-1]["etching"]["gsheet_token"] == "changed000000000"
        assert dlg.vars["etching.gsheet_script_url"].get().endswith("/exec") and g.done_steps() == [True] * 6
        assert g.copy_code().startswith(gsync.CODE_PREFIX)
        g.destroy()
        # 第一次開 Etching：貼團隊設定碼 → 測試 → 儲存
        st = app.state.get("etch_sheet_prompt")
        p = SS.TeamCodePrompt(app, check=lambda cfg: ("✓ 可以寫入（測試）", True, None))
        root.update()
        _LAYOUT_EXTRA.extend(_layout_audit(p, "貼上團隊設定碼"))
        assert not p.use_text("亂打的") and p.save_btn.instate(["disabled"])
        assert p.use_text(code) and p.save_btn.instate(["!disabled"])
        assert pump(lambda: "可以寫入" in p.msg.cget("text"), 5), p.msg.cget("text")
        assert p.save()
        assert applied[-1]["etching"]["gsheet_token"] == "selftest" and applied[-1]["etching"]["gsheet_enabled"]
        assert app.state["etch_sheet_prompt"] == "done" and not SS.should_prompt(app)
        app.state["etch_sheet_prompt"] = "later"
        old_set = app.settings
        app.settings = {"etching": {}}
        assert SS.should_prompt(app), "還沒接上表單、選「以後再說」→ 下次要再問"
        app.state["etch_sheet_prompt"] = "never"
        assert not SS.should_prompt(app), "選「不要再問」就不要再跳出來"
        app.settings = old_set
        if st is None:
            app.state.pop("etch_sheet_prompt", None)
        else:
            app.state["etch_sheet_prompt"] = st
        assert app.prompts is False and app._maybe_sheet_prompt() is None, "自我測試時不應該跳出提示"
        # 團隊設定檔（team_sheet_secret.txt）：工具資料夾裡有這個檔 → 還沒設定寫入的電腦打開就自動接上
        troot = tempfile.mkdtemp(prefix="magic_team_")
        assert gsync.read_team_file(troot) is None
        tp = gsync.write_team_file({"etching": {"gsheet_key": "https://docs.google.com/spreadsheets/d/TEST/edit#gid=0",
                                                "gsheet_worksheet": "etching rate", "gsheet_token": "teamfile",
                                                "gsheet_script_url": "https://script.google.com/macros/s/TEST/exec"}},
                                   troot)
        assert os.path.basename(tp) == gsync.TEAM_FILE and "secret" in gsync.TEAM_FILE
        new = gsync.team_defaults({"etching": {}}, {}, troot)
        assert new and new["etching"]["gsheet_token"] == "teamfile" and new["etching"]["gsheet_enabled"]
        assert gsync.team_defaults({"etching": {}}, {"etch_team_file": "applied"}, troot) is None, "套用過就不再套用"
        assert gsync.team_defaults(new, {}, troot) is None, "已經可以寫入就不覆蓋"
        assert gsync.team_defaults({"etching": {"gsheet_script_url": "https://x/exec"}}, {}, troot) is None, \
            "自己填過 Apps Script 網址就不覆蓋"
        old_set, old_state = app.settings, dict(app.state)
        app.settings = {"etching": {}}
        app.state.pop("etch_team_file", None)
        try:
            assert app._apply_team_file(troot) and app.settings["etching"]["gsheet_token"] == "teamfile"
            assert app.state["etch_team_file"] == "applied" and not SS.should_prompt(app)
            assert not app._apply_team_file(troot), "同一台只套用一次"
        finally:
            app.settings = old_set
            app.state.clear()
            app.state.update(old_state)
            from .core import settings as _S
            _S.save_settings(old_set)
        shutil.rmtree(troot, ignore_errors=True)
    finally:
        app.apply_settings = real_apply


def _gui_samples(app, root, pump):
    """v0.6 製程 → 樣品頁：找樣品資料夾、從試算表匯入、時間軸、步驟細節、照片縮圖、待確認、篩選。"""
    from .fab import records as FR
    from .gui import samples_page as SP
    from .testdata import write_samples
    p = write_samples(tempfile.mkdtemp(prefix="magic_fab_"))
    pg = app.page("Samples")
    app.segment.select("Samples")
    root.update()
    assert app.current is pg and app.segment.buttons[app.segment.active][0] == "Samples", "切不到樣品頁"
    pg.save_cfg(root=p["root"], sheet="", user="tester")
    assert pump(lambda: not pg.scanning and pg.lib is not None and pg.lib.root == p["root"], 20), "掃描樣品資料夾沒有完成"
    assert {s["label"] for s in pg.lib.samples} == {"901", "902", "904", "al 906", "907", "909"}, \
        [s["label"] for s in pg.lib.samples]
    # 讀試算表（和匯入對話框同一條路）
    dlg = SP.ImportDialog(pg)
    dlg.src.set(p["sheet"])
    dlg.read()
    assert pump(lambda: dlg.go.instate(["!disabled"]), 20), f"讀試算表失敗：{dlg.info.cget('text')}"
    assert "試算表 8 個樣品" in dlg.info.cget("text") and "會建立：資料夾裡 6 個紀錄檔、這台電腦 3 個" in dlg.info.cget("text"), \
        dlg.info.cget("text")
    assert len(pg.tree.get_children()) == 9
    assert "abandoned" in pg.tree.item(pg.find("903")["key"], "tags"), "放棄的樣品要變灰"
    # 選 901 → 時間軸（還沒建立紀錄檔：初版預覽）
    pg.tree.selection_set(pg.find("901")["key"])
    root.update()
    assert pg.sample["label"] == "901" and len(pg.tl.get_children()) == 15, len(pg.tl.get_children())
    assert "還沒有紀錄檔" in pg.prev_lab.cget("text")
    assert "低溫電阻 1500 Ω" in pg.s_res.cget("text") and "超導 contact" in pg.s_res.cget("text")
    rec = pg.record()
    sid = next(s["id"] for s in rec["steps"] if s["folders"] == ["05 Lithography", "06 Lift Off"])
    pg.select_step(sid)
    root.update()
    txt = "\n".join(_texts(pg.body))
    for want in ("Contact #1", "子步驟", "微影（顯影後）", "RIE", "OE（多蝕刻）", "Cr 10 nm / Au 70 nm", "05 Lithography",
                 "照片（3）"):
        assert want in txt, f"步驟細節少了「{want}」"
    assert pump(lambda: len(pg._imgs) >= 3, 10), "照片縮圖沒有出現"
    # 建立紀錄檔
    dlg.create()
    assert pump(lambda: os.path.isfile(FR.record_path(p["901"])), 15), "沒有建立紀錄檔"
    assert pump(lambda: pg.find("901").get("rec") is not None, 5)
    pg._show_sample(pg.find("901"))
    assert pg.prev_lab.cget("text") == ""
    dlg.destroy()
    # 待確認：已確認寫回紀錄檔
    rd = SP.ReviewDialog(pg)
    n0 = len(rd.items)
    assert n0 >= 5, n0
    first = next(iter(rd.items))
    s0, r0 = rd.items[first]
    rd.tree.selection_set(first)
    rd.jump()
    root.update()
    assert pg.sample["key"] == s0["key"]
    rd.resolve()
    assert len(rd.items) == n0 - 1
    saved = FR.load(s0["path"])
    assert any(r["id"] == r0["id"] and r["resolved"] for r in saved["review"]), "已確認沒有寫進紀錄檔"
    rd.destroy()
    # 篩選：狀態、文字
    pg.state_var.set("放棄")
    pg.refresh_list()
    assert {pg.tree.set(i, "label").rstrip(" ·") for i in pg.tree.get_children()} == {"903", "905"}
    pg.state_var.set("全部")
    pg.filter_var.set("al")
    pg.refresh_list()
    assert [pg.tree.set(i, "label") for i in pg.tree.get_children()] == ["al 906"]
    pg.filter_var.set("")
    # 只有資料夾的樣品、設定視窗
    pg.tree.selection_set(pg.find("909")["key"])
    root.update()
    assert any("推測" in m for m in pg.rv_list.get(0, "end")), "只有資料夾的微影組要列成待確認"
    sd = SP.SampleSettings(pg)
    root.update()
    sd.destroy()
    _gui_samples_edit(app, root, pump, pg, p)
    _gui_samples_visual(app, root, pump, pg, p)
    _gui_samples_ppt(app, root, pump, pg, p)
    _gui_samples_091(app, root, pump, pg, p)
    pg.save_cfg(root="", sheet="", user="", sheet_sync=False)


def _gui_samples_091(app, root, pump, pg, p):
    """v0.9.1：待確認「種類是推測的」→ 直接修改那一步（改完自動算已確認）；DXF 用 KLayout / AutoCAD 開。"""
    from .fab import cad as FC
    from .fab import edit as FE
    from .fab import records as FR
    from .fab import steps as K
    from .gui import samples_page as SPM
    s = pg.find("909")                                   # 只有資料夾：微影組的種類是推測的
    pg.refresh_list(select=s["key"])
    root.update()
    guess = [r for r in pg._rv_items if r.get("step") and "推測" in r["msg"]]
    assert guess, [r["msg"] for r in pg._rv_items]
    pg.rv_list.selection_clear(0, "end")
    pg.rv_list.selection_set(pg._rv_items.index(guess[0]))
    pg._show_review_text()
    assert pg.rv_edit.instate(["!disabled"])
    ed = pg.edit_review_step()
    root.update()
    assert ed is not None and pg.step_id == guess[0]["step"], "待確認要能直接打開那一步"
    old_kind = ed.step["kind"]
    new_kind = "contact" if old_kind == "marker" else "marker"
    names = [f"{K.icon(k)} {K.label(k)}" for k in ed.kinds]
    ed.kind_var.set(names[ed.kinds.index(new_kind)])
    ed._build_body()
    assert ed.folder_names and ed.folder_list.curselection(), "換種類時資料夾（照片）要留著"
    assert any(r["orig"] for r in ed.subrows), "換種類時子步驟（顯影後 / 鍍完的照片）要留著"
    ed.save()
    root.update()
    st = FE.find(FR.load(s["path"]), guess[0]["step"])
    assert st["kind"] == new_kind and st["folders"], st
    saved = FR.load(s["path"])
    assert all(r["resolved"] for r in saved["review"] if r.get("step") == guess[0]["step"]), "改過的步驟要自動算已確認"
    # 待確認視窗也有「✎ 修改這一步」
    rd = SPM.ReviewDialog(pg)
    root.update()
    rd.destroy()
    # DXF：預設 KLayout，另一顆是 AutoCAD；找不到程式 → 問要不要指定
    from tkinter import messagebox
    d = os.path.join(s["dir"], "00 Design")
    os.makedirs(d, exist_ok=True)
    dxf = os.path.join(d, "mask.dxf")
    with open(dxf, "w") as f:
        f.write("0\nEOF\n")
    calls = []
    real = (FC.find_app, FC.open_with, messagebox.askyesno)
    FC.find_app = lambda app, custom="": f"/fake/{app}"
    FC.open_with = lambda exe, path: calls.append((exe, path)) or True
    try:
        pg._clear()
        pg._file_rows([dxf])
        texts = _texts(pg.body)
        assert "KLayout 開啟" in texts and "AutoCAD" in texts, texts
        assert pg.open_cad(dxf, "klayout") == "/fake/klayout" and calls[-1] == ("/fake/klayout", dxf)
        assert pg.open_cad(dxf, "autocad") == "/fake/autocad"
        FC.find_app = lambda app, custom="": ""
        messagebox.askyesno = lambda *a, **k: False
        assert pg.open_cad(dxf, "autocad") is None and len(calls) == 2
        pg.save_cfg(rescan=False, cad_default="autocad")
        pg._clear()
        pg._file_rows([dxf])
        assert "AutoCAD 開啟" in _texts(pg.body)
    finally:
        FC.find_app, FC.open_with, messagebox.askyesno = real
        pg.save_cfg(rescan=False, cad_default="klayout")
        os.remove(dxf)
    assert SPM.CAD is FC


def _gui_samples_ppt(app, root, pump, pg, p):
    """v0.9：匯出 PPT（單一樣品、多樣品比較）、模板（標題、關掉一步、給教授的說明）存進紀錄檔。"""
    import re
    import zipfile
    from .fab import records as FR
    s = pg.find("901")
    pg.refresh_list(select=s["key"])
    root.update()
    dlg = pg.open_export()
    root.update()
    assert dlg.selected() == [s] and len(dlg.steps.get_children()) == len(pg.record()["steps"])
    first = dlg.steps.get_children()[0]
    if dlg.steps.set(first, "on") == "—":
        dlg.toggle(first)
    dlg.toggle(first)
    assert dlg.steps.set(first, "on") == "—"
    sid = dlg.steps.get_children()[5]
    dlg.steps.selection_set(sid)
    root.update()
    dlg.note.insert("1.0", "給教授：這一步重做過一次")
    dlg._note_changed()
    dlg.t_title.set("901 製程報告（selftest）")
    dlg.t_rep.set("Yeep")
    dlg.nb.select(1)
    root.update()
    dlg.lists["problems"].insert("1.0", "08 Lift-off 有殘膠\n")
    dlg.lists["next"].insert("1.0", "改 RIE 時間 18 s")
    out = os.path.join(tempfile.mkdtemp(), "901.pptx")
    dlg.export(out)
    assert pump(lambda: "已匯出" in dlg.info.cget("text") or "失敗" in dlg.info.cget("text"), 60), dlg.info.cget("text")
    assert "已匯出" in dlg.info.cget("text"), dlg.info.cget("text")
    with zipfile.ZipFile(out) as z:
        xml = " ".join(z.read(n).decode("utf-8") for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n))
    assert "901 製程報告（selftest）" in xml and "給教授：這一步重做過一次" in xml
    for want in ("報告人　Yeep", "08 Lift-off 有殘膠", "改 RIE 時間 18 s", "旋塗光阻", "開窗（微影）", "製程流程"):
        assert want in xml, want
    tpl = FR.load(s["path"])["ppt"]
    assert tpl["reporter"] == "Yeep" and tpl["problems"] == ["08 Lift-off 有殘膠"] and tpl["next"] == ["改 RIE 時間 18 s"]
    assert first in tpl["skip_steps"] and tpl["step_notes"][sid].startswith("給教授") and tpl["title"].endswith("（selftest）")
    # 多樣品比較、中英並列
    dlg.slist.selection_clear(0, "end")
    for lab in ("901", "904"):
        dlg.slist.selection_set(dlg.samples.index(pg.find(lab)))
    dlg._load_tpl()
    dlg.lang.set("both")
    out2 = os.path.join(tempfile.mkdtemp(), "cmp.pptx")
    dlg.info.configure(text="")
    dlg.export(out2)
    assert pump(lambda: "已匯出" in dlg.info.cget("text") or "失敗" in dlg.info.cget("text"), 60), dlg.info.cget("text")
    assert "已匯出" in dlg.info.cget("text") and os.path.getsize(out2) > 20000, dlg.info.cget("text")
    with zipfile.ZipFile(out2) as z:
        xml = z.read("ppt/slides/slide2.xml").decode("utf-8")
    assert "樣品比較" in xml and "Sample comparison" in xml
    dlg.destroy()
    pg.st["ppt_lang"] = "zh"


def _gui_samples_visual(app, root, pump, pg, p):
    """v0.8：示意圖（剖面 + 俯視）、逐步切換、播放動畫、存圖。"""
    s = pg.find("901")
    pg.refresh_list(select=s["key"])
    root.update()
    pg.set_view("visual")
    root.update()
    n = len(pg.record()["steps"])
    assert pg.vis and pg.vis_step == n - 1, (pg.vis_step, n)
    assert pump(lambda: len(pg._outlines.get(s["key"], [])) == 5, 10), "digitalize 的輪廓沒有讀到"
    fig = pg.vis["fig"]
    assert len(fig.axes) == 2 and len(fig.axes[1].patches) == 5, (len(fig.axes), len(fig.axes[1].patches))
    pg.vis_goto(0)
    assert pg.vis_step == 0 and "第 1 /" in pg.vis["cap"].cget("text")
    pg.select_step(pg.record()["steps"][3]["id"])          # 時間軸點一步 → 示意圖跟著跳
    root.update()
    assert pg.vis_step == 3, pg.vis_step
    t0 = time.perf_counter()
    for _ in range(4):
        pg.vis_step_by(1)
        root.update()
    per = (time.perf_counter() - t0) / 4
    assert per < 1.5, f"示意圖一步要畫 {per:.2f} 秒"
    # 放大剖面 / 放大俯視 / 兩張
    pg.set_vis_zoom("section")
    root.update()
    assert len(fig.axes) == 1 and pg.vis["top_ax"] is None, "放大剖面：只畫剖面"
    pg.set_vis_zoom("top")
    root.update()
    assert len(fig.axes) == 1 and pg.vis["top_ax"] is fig.axes[0], "放大俯視：只畫俯視"
    pg.set_vis_zoom("section")
    pg.start_cut()
    assert pg.vis_zoom() == "both", "放大剖面時按切線 → 自動切回兩張（才點得到俯視圖）"
    pg._cut_pts = None
    root.update()
    assert len(fig.axes) == 2
    pg.vis_goto(0)
    pg.toggle_play()
    assert pump(lambda: pg.vis_step >= 2, 6), "播放動畫沒有前進"
    pg.stop_play()
    out = pg.save_visual(os.path.join(tempfile.mkdtemp(), "vis.png"))
    assert os.path.getsize(out) > 5000
    # v0.9.1：剖面照切線畫（digitalize 輪廓）；在俯視圖上點兩下設定切線、↺ 恢復自動
    from .fab import records as FR
    from .fab import visual as FV
    sec = FV.build_section(pg.record(), None, outlines=pg._outlines[s["key"]])
    assert sec.cut is not None, "有輪廓檔時剖面要照切線畫"
    pg.vis_goto(None)
    root.update()
    assert "A–A'" in fig.axes[0].get_title(loc="left"), fig.axes[0].get_title(loc="left")
    pg.start_cut()
    assert "點兩下" in pg.vis["cap"].cget("text")
    top = pg.vis["top_ax"]

    class _Click:
        def __init__(self, x, y):
            self.inaxes, self.xdata, self.ydata = top, x, y
    pg._on_vis_click(_Click(4040.0, 4944.0))
    pg._on_vis_click(_Click(4052.0, 4952.0))
    root.update()
    assert FR.load(s["path"])["visual"]["cut"] == [[4040.0, 4944.0], [4052.0, 4952.0]], "切線沒有存進紀錄檔"
    assert FV.cut_line(pg.record(), pg._outlines[s["key"]]) == ((4040.0, 4944.0), (4052.0, 4952.0))
    pg.set_cut(None)
    assert "cut" not in FR.load(s["path"]).get("visual", {})
    # v0.9.1：只在雲端的照片 → 打開資料夾；下載完自動顯示縮圖
    from .fab import folders as FF
    from .gui import samples_page as SPM
    pg.set_view("detail")
    sid = next(x["id"] for x in pg.record()["steps"] if x["folders"] == ["05 Lithography", "06 Lift Off"])
    cloud = {}
    real_cloud, real_reveal = FF.is_cloud_only, SPM.reveal
    opened = []
    FF.is_cloud_only = lambda path: path in cloud
    SPM.reveal = lambda path: opened.append(path) or True
    try:
        imgs = FF.scan_folder(os.path.join(s["dir"], "05 Lithography"))["images"]
        cloud[imgs[0]] = True
        pg._thumb_cache.clear()
        pg.select_step(sid)
        assert pump(lambda: pg._thumb_cache.get(imgs[0]) == "cloud", 10), "雲端照片要顯示「只在雲端」"
        assert "打開資料夾" in pg._thumb_labels[imgs[0]].cget("text")
        pg.show_photo(imgs[0])
        assert opened == [imgs[0]] and imgs[0] in pg._cloud_watch, "點雲端照片要打開資料夾"
        cloud.clear()                                          # 使用者在檔案總管點兩下 → 下載好了
        assert pump(lambda: pg._thumb_cache.get(imgs[0]) not in (None, "cloud"), 10), "下載完縮圖要自動更新"
        assert not pg._cloud_watch
    finally:
        FF.is_cloud_only, SPM.reveal = real_cloud, real_reveal
    pg.set_view("visual")
    pg.set_view("detail")
    root.update()
    assert pg.sf.winfo_ismapped() and not pg.vis["frame"].winfo_ismapped()


def _gui_samples_edit(app, root, pump, pg, p):
    """v0.7：新增 / 編輯 / 搬移 / 刪除步驟、RIE 時間建議、擱置 / 放棄、結果（含從量測頁帶入）、新樣品、寫回試算表。"""
    from tkinter import messagebox
    from .etching.gsync import GspreadSheet
    from .fab import records as FR
    from .fab import sheet as FSH
    from .fab import steps as K
    from .gui import samples_edit as SE
    from .testdata import SAMPLE_SHEET, FakeWorksheet
    ws = FakeWorksheet([list(r) for r in SAMPLE_SHEET])
    pg.sheet_writer = lambda: GspreadSheet(ws)                     # 假的試算表（不連網路）
    pg.can_sync = lambda: True
    pg.save_cfg(rescan=False, sheet_sync=True)
    saved = messagebox.askyesno
    messagebox.askyesno = lambda *a, **k: True
    try:
        s = pg.find("901")
        pg.refresh_list(select=s["key"])
        root.update()
        rec0 = pg.record()
        n0 = len(rec0["steps"])
        # ---- 新增 contact：勾 RIE（hBN 自動帶入前面 AFM 的厚度）→ 建議時間 → 套用 → 鍍膜
        last = rec0["steps"][-1]["id"]
        pg.tl.selection_set(last)
        root.update()
        ed = pg.new_step()
        root.update()
        assert ed.kind == "contact" and ed.subrows, "新增步驟預設要是 contact、有子步驟"
        rie = next(r for r in ed.subrows if r["kind"] == "rie")
        rie["on"].set(True)
        assert rie["fs"].vars["hbn_nm"].get() == "48.5", f"RIE 的 hBN 厚度要帶入前面 AFM：{rie['fs'].vars['hbn_nm'].get()}"
        rie["fs"].vars["oe_nm"].set("3")
        ed.suggest(rie["fs"])
        root.update()
        assert rie["fs"].sug and "建議" in rie["fs"].sug_lab.cget("text"), rie["fs"].sug_lab.cget("text")
        rie["fs"].sug_btn.invoke()
        assert rie["fs"].vars["time_s"].get() == str(rie["fs"].sug["time_s"])
        dep = next(r for r in ed.subrows if r["kind"] == "deposit")
        dep["on"].set(True)
        dep["fs"].vars["layers"].set("Cr/Au 5/60")
        dep["fs"].vars["method"].set("E 蒸鍍")
        ed.d1.set("2026/11/20")
        ed.notes.insert("1.0", "selftest")
        ed.save()
        root.update()
        rec = pg.record()
        assert len(rec["steps"]) == n0 + 1 and s.get("rec") is not None, "新增的步驟沒有存進紀錄檔"
        new = rec["steps"][-1]
        assert new["kind"] == "contact" and new["date"] == "2026-11-20" and new["notes"] == "selftest"
        assert [x["kind"] for x in new["substeps"]] == ["rie", "deposit"], new["substeps"]
        assert new["substeps"][1]["params"] == {"layers": [["Cr", 5], ["Au", 60]], "method": "E"}
        assert pg.tl.selection() == (new["id"],), "新增後要選到新的那一步"
        # 寫回試算表（背景）→ 901 那一列的 Process 最後是新的 contact
        assert pump(lambda: (pg.record().get("sync") or {}).get("state") == "ok", 15), pg.record().get("sync")
        row = next(r for r in ws.get_all_values() if len(r) > 1 and r[1] == "901")
        assert [c for c in row if c][-2:] == ["Cr/Au_5/60 (E)", "範例"], row
        # ---- 編輯：看不懂的格式要擋下來；改好再存
        ed = pg.edit_selected_step()
        root.update()
        dep = next(r for r in ed.subrows if r["kind"] == "deposit")
        dep["fs"].vars["layers"].set("Cr/Au ten/70")
        ed.save()
        assert ed.winfo_exists() and "看不懂" in ed.err.cget("text"), "格式錯誤要顯示在對話框裡"
        dep["fs"].vars["layers"].set("Cr/Au 10/70")
        ed.save()
        root.update()
        assert pg.record()["steps"][-1]["substeps"][1]["params"]["layers"] == [["Cr", 10], ["Au", 70]]
        # ---- 搬移、刪除
        pg.move_selected(-1)
        assert pg.record()["steps"][-2]["id"] == new["id"]
        pg.move_selected(1)
        pg.tl.selection_set(new["id"])
        pg.delete_selected_step(confirm=False)
        assert len(pg.record()["steps"]) == n0
        # ---- 單獨一步 RIE：建議時間；transfer 預設堆疊
        ed = SE.StepEditor(pg, s, pg.record(), None, None)
        names = [f"{K.icon(k)} {K.label(k)}" for k in ed.kinds]
        ed.kind_var.set(names[ed.kinds.index("transfer")])
        ed._build_body()
        assert "TaS2" in ed.main.vars["layers"].get(), ed.main.vars["layers"].get()
        ed.destroy()
        # ---- 擱置 → 繼續、放棄 → 取消放棄
        sd = pg.toggle_state("hold")
        sd.reason.set("等 Raith")
        sd.date.set("2026-12-03")
        sd.ok()
        root.update()
        assert pg.record()["status"]["state"] == "hold" and pg.hold_btn.cget("text") == "▶ 繼續製作"
        assert "擱置" in pg.tree.set(s["key"], "state")
        pg.toggle_state("hold")
        assert pg.record()["status"]["state"] == "active"
        ad = pg.toggle_state("abandoned")
        ad.reason.set("破掉")
        ad.ok()
        root.update()
        assert pg.record()["status"]["state"] == "abandoned" and "abandoned" in pg.tree.item(s["key"], "tags")
        assert pg.record()["status"]["stopped_at"] == pg.record()["steps"][-1]["id"]
        pg.toggle_state("abandoned")
        assert pg.record()["status"]["state"] == "active" and pg.record()["status"]["stopped_at"] is None
        # ---- 結果：手動填、從量測頁帶入
        rd = pg.open_results()
        rd.v["r_ohm"].set("1700")
        rd.sc.set(True)
        rd.v["sc_on"].set("TaS2")
        rd.v["tc_k"].set("4.2")
        rd.ok()
        root.update()
        res = pg.record()["results"]
        assert (res["r_ohm"], res["sc_contact"], res["sc_on"], res["tc_k"]) == (1700, True, "TaS2", 4.2), res
        assert "Tc 4.2 K" in pg.s_res.cget("text") and pg.record()["status"]["state"] == "measured"
        assert pump(lambda: (pg.record().get("sync") or {}).get("state") == "ok", 15)
        row = next(r for r in ws.get_all_values() if len(r) > 1 and r[1] == "901")
        assert row[0] == "measured R_1700 (SC) sc on TaS2 Tc_4.2K", row[0]
        assert FSH.parse_table(ws.get_all_values())[0]["results"]["tc_k"] == 4.2

        class _It:
            label, path = "demo.dat", os.path.join(p["901"], "19 Measurement", "demo.dat")

        class _Fake:
            key = "PPMS"
            current = type("A", (), {"name": "R–T 與 Tc"})()
            last = {"data": [{"item": _It(), "name": "降溫", "tc": 3.91, "res": {"y_s": 12.5}}]}

        pg.sample = None
        rd = SE.ResultDialog(pg, None, _Fake())
        assert rd.current() is s, "量測檔案在樣品資料夾裡 → 要預設選那個樣品"
        assert rd.v["tc_k"].get() == "3.91" and rd.v["r_ohm"].get() == "12.5", (rd.v["tc_k"].get(), rd.v["r_ohm"].get())
        rd.ok()
        assert pg.record(s)["results"]["source"] == "PPMS｜R–T 與 Tc"
        pg.sample = s
        wd = app.pages["PPMS"].write_to_sample()
        root.update()
        assert wd is not None and wd.winfo_exists(), "量測頁的「寫到樣品」要打開樣品結果"
        wd.destroy()
        # ---- 新樣品（建立資料夾 + 紀錄檔）→ 試算表多一列
        nd = pg.open_new_sample()
        nd.v["label"].set("950")
        nd.v["type"].set("Quad-NbSe2")
        nd.v["place"].set(nd.places[1])
        nd.ok()
        root.update()
        s950 = pg.find("950")
        assert s950 and s950["has_folder"] and os.path.isfile(s950["path"]), "新樣品沒有建立資料夾和紀錄檔"
        assert FR.load(s950["path"])["type"] == "Quad-NbSe2" and pg.sample["label"] == "950"
        assert pump(lambda: any(len(r) > 1 and r[1] == "950" for r in ws.get_all_values()), 15), "新樣品沒有寫進試算表"
        nd = pg.open_new_sample()
        nd.v["label"].set("950")
        nd.ok()
        assert nd.winfo_exists() and "已經有" in nd.err.cget("text")
        nd.destroy()
        # ---- ☁ 試算表對話框
        assert pump(lambda: not pg.pending_sync(), 15), [x["label"] for x in pg.pending_sync()]
        sy = pg.open_sync()
        root.update()
        assert "待更新：0 個樣品" in sy.info.cget("text"), sy.info.cget("text")
        sy.test()
        assert pump(lambda: "連得上" in sy.info.cget("text"), 10), sy.info.cget("text")
        sy.destroy()
    finally:
        messagebox.askyesno = saved
        for k in ("sheet_writer", "can_sync"):
            pg.__dict__.pop(k, None)


def _gui_03(app, root, pump, ep):
    """v0.3 的介面功能：圖表樣式、圖例點選 / 拖曳、Raman 編修與峰標註、蝕刻紀錄修改 / 刪除 / 歷史、AFM 匯入。"""
    import tempfile
    from tkinter import messagebox
    from .testdata import afm_profile
    saved = (messagebox.askyesno, messagebox.showinfo, messagebox.showwarning)
    messagebox.askyesno = lambda *a, **k: True                    # 測試時自動按「是」
    messagebox.showinfo = messagebox.showwarning = lambda *a, **k: None
    try:
        # ---- 圖表樣式與圖例（Raman 光譜檢視，三條光譜）
        pg = app.pages["Raman"]
        app.segment.select("Raman")
        pg.features.select("光譜檢視")
        pg.data.tree.selection_set(pg.data.tree.get_children()[:3])
        g0 = pg.gen
        pg.plot()
        assert pump(lambda: pg.gen > g0 and pg.busy is None and pg.last and pg.last["analysis"].name == "光譜檢視", 20)
        rp = pg.right
        rp.size_vars["xlabel"].set("19")
        rp._style_changed()
        pump(lambda: False, 0.3)
        assert rp.fig.axes[0].xaxis.label.get_size() == 19, "X 標籤字體大小沒有套用"
        rp.size_vars["xlabel"].set("12")
        rp._style_changed()
        ax = rp.fig.axes[0]
        leg = ax.get_legend()
        t = leg.get_texts()[1]
        bb = t.get_window_extent()
        cx, cy = (bb.x0 + bb.x1) / 2, (bb.y0 + bb.y1) / 2
        rp.tools.on_press(_Ev(cx, cy))
        rp.tools.on_release(_Ev(cx, cy))
        label = t.get_text()
        assert [ln.get_visible() for ln in ax.lines if ln.get_label() == label] == [False], "點圖例沒有隱藏"
        pg.redraw()
        ax = rp.fig.axes[0]
        assert not [ln for ln in ax.lines if ln.get_label() == label][0].get_visible(), "重畫後隱藏的要記住"
        bb = ax.get_legend().get_window_extent()
        rp.tools.on_press(_Ev(bb.x0 + 4, bb.y0 + 4))
        for k in range(1, 4):
            rp.tools.on_motion(_Ev(bb.x0 + 4 - 40 * k, bb.y0 + 4 - 30 * k))
        rp.tools.on_release(_Ev(bb.x0 - 116, bb.y0 - 86))
        assert pg.st["fig"]["光譜檢視"].get("legend"), "圖例拖曳後要記住位置"
        # ---- ↺ 回到初始：圖例 / 標註位置、隱藏的資料、縮放 → 原狀；10 秒內可以復原
        ovr = pg.st["fig"]["光譜檢視"]
        ovr.setdefault("annot", {})["peak:G"] = [30.0, 40.0]              # 假裝拖曳過一個峰標註
        ax = rp.fig.axes[0]
        x0, x1 = ax.get_xlim()
        ax.set_xlim(x0 + (x1 - x0) * 0.3, x1 - (x1 - x0) * 0.3)          # 假裝放大過
        assert rp.reset_all() >= 2
        pump(lambda: False, 0.3)
        assert not ovr.get("legend") and not ovr.get("annot") and not ovr.get("hidden"), "回到初始沒有清掉位置"
        assert str(rp.reset_btn.cget("text")).startswith("↶"), "回到初始後要能復原"
        rp.reset_all()                                                    # 再按一次 = 復原
        pump(lambda: False, 0.3)
        assert ovr.get("legend") and ovr.get("annot", {}).get("peak:G") == [30.0, 40.0], "↶ 復原沒有還原位置"
        assert str(rp.reset_btn.cget("text")) == "↺ 回到初始"
        rp.reset_all()
        rp._end_reset_undo()
        pump(lambda: False, 0.3)
        assert not ovr.get("legend") and not ovr.get("annot")
        ax = rp.fig.axes[0]
        hx = rp._home.get(ax, (None,))[0]
        assert hx is None or tuple(ax.get_xlim()) == tuple(hx), "回到初始要把縮放回到全部範圍"
        # ---- 圖標題：新增（含 {日期}{機台}）、字體大小、範圍、移除
        rp.title_scope.set("只有這張圖")
        rp.title_var.set("{日期}的{機台}分析圖")
        rp._commit_title()
        want = time.strftime("%Y%m%d") + "的Raman分析圖"
        sup = rp.fig._suptitle
        assert sup is not None and sup.get_text() == want, "圖標題沒有出現"
        rp._title_size_var.set("23")
        rp._style_changed()
        assert rp.fig._suptitle.get_fontsize() == 23, "圖標題的字體大小沒有套用"
        assert pg.figure_title() == want, "存圖的預設檔名要用標題"
        rp.title_scope.set("所有圖")
        rp.title_var.set("全部 {功能}")
        rp._commit_title()
        pp = app.pages["PPMS"]
        assert pp.title_effective() == ("全部 {功能}", "所有圖"), pp.title_effective()
        rp.remove_title()
        assert rp.fig._suptitle is None and not app.view.get("fig_title"), "移除標題沒有作用"
        rp._title_size_var.set("15")
        rp._style_changed()
        assert all(ln.get_visible() for ln in rp.fig.axes[0].lines), "↺ 圖例要讓隱藏的資料重新顯示"
        # ---- Raman 編修
        ed = pg.open_raman_editor()
        pump(lambda: ed.x is not None, 5)
        _audit_window(ed, "Raman 編修", root)
        import numpy as np
        i = int(np.argmax(ed.y))
        n = ed.erase_box(ed.x[i] - 3, ed.x[i] + 3, ed.y[i] * 0.98, ed.y[i] * 1.02, ed.y)
        assert n >= 1 and app.raman_edits.count(ed.path)[0] == n
        ed.undo()
        assert app.raman_edits.count(ed.path)[0] == 0, "復原沒有作用"
        ed.redo()
        ed.auto_anchors()
        assert app.raman_edits.count(ed.path) == (n, 8)
        ed.clear("anchors")
        ed.clear("erase")
        assert app.raman_edits.count(ed.path) == (0, 0)
        # ---- 橡皮擦（點 / 塗抹）：左鍵點一下、按住拖曳一筆、右鍵恢復；框選模式只點一下
        from .raman import edits as _E
        ed.set_mode("brush")
        assert ed.mode_var.get() == "brush"
        root.update()
        ed.canvas.draw()

        def mev(j, button=1):
            e = _Ev(*ed.ax1.transData.transform((ed.x[j], ed.y[j])), button)
            e.inaxes, e.xdata, e.ydata = ed.ax1, ed.x[j], ed.y[j]
            return e

        def erased(j):
            return bool(_E.erased_mask(ed.x, ed.ed.get("erase"))[j])

        nx = len(ed.x)
        j = nx // 3
        u0 = len(ed.undo_stack)
        ed._press(mev(j))
        ed._release(mev(j))
        n1 = app.raman_edits.count(ed.path)[0]
        assert erased(j) and n1 >= 1 and len(ed.undo_stack) == u0 + 1, "筆刷：左鍵點一下沒有擦掉滑鼠附近的點"
        a0, a1 = j + nx // 10, j + nx // 10 + 40
        ed._press(mev(a0))
        for k in range(a0, a1, 5):
            ed._motion(mev(k))
        ed._release(mev(a1))
        n2 = app.raman_edits.count(ed.path)[0]
        assert n2 >= n1 + 20 and erased(a0) and erased(a1), f"筆刷：拖曳一筆應該沿路擦掉（{n1} → {n2}）"
        assert len(ed.undo_stack) == u0 + 2, "拖曳一整筆要記成一步"
        ed.undo()
        assert app.raman_edits.count(ed.path)[0] == n1 and not erased(a0), "復原應該一次復原整筆"
        ed._press(mev(j, 3))
        ed._release(mev(j, 3))
        assert not erased(j) and app.raman_edits.count(ed.path)[0] < n1, "筆刷：右鍵應該恢復滑鼠附近的點"
        ed.set_mode("erase")
        jj = 2 * nx // 3
        ed._press(mev(jj))
        ed._release(mev(jj))
        assert erased(jj), "框選模式：只點一下也要擦掉滑鼠附近的點"
        ed.clear("erase")
        # ---- 筆刷範圍圓圈：跟著滑鼠、大小 = 筆刷大小
        ed.set_mode("brush")
        ed.brush_var.set("14")
        ed._motion(mev(j))
        c = ed.brush_circle
        assert c.get_visible() and abs(c.get_radius() - ed.brush_r()) < 1e-9, "筆刷圓圈沒有出現或大小不對"
        cx, cy = c.center
        px, py = ed.ax1.transData.transform((ed.x[j], ed.y[j]))
        assert abs(cx - px) < 1 and abs(cy - py) < 1, "筆刷圓圈沒有跟著滑鼠"
        ed.set_mode("view")
        assert not c.get_visible(), "換成縮放 / 平移時圓圈要消失"
        ed.brush_var.set("10")
        # ---- 🔍 找尖峰：在記憶體裡的光譜加 3 個尖峰（1、2、3 點寬）→ 找到 → 擦掉（一步）→ 復原
        y0 = ed.y
        ed.y = ed.y.copy()                                   # 讀進來的資料是唯讀的：測試用一份可以改的
        sp = {nx // 5: [400], nx // 2: [300, 350], 4 * nx // 5: [250, 500, 260]}
        for i0, hs in sp.items():
            ed.y[i0:i0 + len(hs)] += hs
        n_found = ed.find_spikes()
        want = sorted(i0 + d for i0, hs in sp.items() for d in range(len(hs)))
        assert n_found == 3 and sorted(np.flatnonzero(ed.spikes).tolist()) == want, \
            f"找尖峰：應該找到 3 個（{want}），結果 {np.flatnonzero(ed.spikes) if ed.spikes is not None else None}"
        assert ed.spike_erase.winfo_manager(), "找到尖峰時要出現「擦掉」按鈕"
        u1 = len(ed.undo_stack)
        assert ed.erase_spikes() == len(want) and all(erased(i) for i in want), "擦掉尖峰沒有作用"
        assert len(ed.undo_stack) == u1 + 1 and ed.spikes is None and not ed.spike_erase.winfo_manager()
        ed.undo()
        assert not any(erased(i) for i in want), "擦掉尖峰要能一次復原"
        ed.find_spikes()
        ed.cancel_spikes()
        assert ed.spikes is None and app.raman_edits.count(ed.path)[0] == 0
        ed.y = y0
        assert ed.find_spikes() == 0 and ed.spikes is None, "原本的合成光譜（只有真的峰）不應該找到尖峰"
        # ---- 螢幕縮放（例如 150%）時圖不能比畫布大（以前會跑版、下面被切掉）
        cv = ed.canvas
        if hasattr(cv, "_set_device_pixel_ratio"):
            cv._set_device_pixel_ratio(1.5)
            ed._fit()
            root.update()
            ww, wh = cv.get_tk_widget().winfo_width(), cv.get_tk_widget().winfo_height()
            fw, fh = cv.get_width_height(physical=True)
            assert abs(fw - ww) <= 1 and abs(fh - wh) <= 1, f"縮放 150% 時圖 {fw}×{fh} 和畫布 {ww}×{wh} 不一樣大（跑版）"
            cv._set_device_pixel_ratio(1.0)
            ed._fit()
            root.update()
        assert app.raman_edits.count(ed.path) == (0, 0)
        ed.close()
        # ---- 峰標註
        pg.features.select("石墨烯 G / 2D 峰")
        mono = [i for i in pg.data.tree.get_children() if "monolayer" in pg.data.tree.set(i, "name")]
        pg.data.tree.selection_set(mono)
        assert pump(lambda: pg.busy is None and pg.last and pg.last["analysis"].name == "石墨烯 G / 2D 峰"
                    and len(pg.last["items"]) == 1, 20)
        dlg = pg.open_peak_labels()
        _audit_window(dlg, "峰標註", root)
        dlg.add("D'", 1620.0)
        dlg.tree.selection_set("G")
        root.update()
        dlg.v["size"].set("17")
        dlg.v["text"].set("G peak")
        dlg.apply()
        anns = {a.get_text().split("\n")[0]: a for ax in rp.fig.axes for a in ax.texts if getattr(a, "magic_key", None)}
        assert "G peak" in anns and anns["G peak"].get_fontsize() == 17 and "D'" in anns, list(anns)
        dlg.reset()
        dlg.close()
        # ---- 蝕刻紀錄：修改 → 歷史 → 刪除 → 還原
        app.segment.select("Etching")
        root.update()
        ep.data.source_var.set("本機 CSV")
        ep.data.reload()
        assert pump(lambda: ep.data.df is not None and len(ep.data.df) >= 1, 10)
        n0 = len(ep.data.df)
        ep.data.tree.selection_set([str(n0)])
        root.update()
        wz = ep.data.edit_selected()
        assert pump(lambda: wz.result is not None, 5), "修改視窗沒有算出結果"
        wz.vars["cross_check"].set(True)
        wz._method_changed()
        d = tempfile.mkdtemp()
        afm = wz.import_afm("sio2_step")
        afm._no_ask = True
        afm.add_files([afm_profile(os.path.join(d, "afm.txt"), h=2.9, n_profiles=3, noise=0.05)])
        afm.fill()
        assert len(wz.vars["sio2_step"].get().split(",")) == 3, wz.vars["sio2_step"].get()
        wz.vars["resist_thickness"].set("300")
        wz.vars["resist_after"].set("250")
        pump(lambda: False, 0.4)
        assert wz.result is not None and wz.result.sio2_cross and wz.result.r_resist, "交叉檢查 / 光阻沒有算"
        wz.save()
        assert pump(lambda: ep.data.df is not None and str(ep.data.df["Revision"].iloc[-1]) == "2", 10), "修改沒有存"
        assert len(ep.data.df) == n0
        ep.data.tree.selection_set([str(n0)])
        root.update()
        assert ep.data.delete_selected(confirm=False) == 1
        assert pump(lambda: ep.data.df is not None and len(ep.data.df) == n0 - 1, 10)
        win = ep.data.show_history()
        assert [e["Action"] for e in win.entries] == ["刪除", "修改"], [e["Action"] for e in win.entries]
        win.tree.selection_set("0")
        win.restore()
        assert pump(lambda: ep.data.df is not None and len(ep.data.df) == n0, 10), "還原刪除沒有作用"
        # ---- OM 照片：精靈選圖 → 存檔 → 表格 📷 → 並排看
        import numpy as np
        from PIL import Image
        pic = os.path.join(d, "om.png")
        Image.fromarray((np.random.default_rng(3).random((300, 400, 3)) * 255).astype("uint8")).save(pic)
        wz = ep.data.new_record()
        for k, v in dict(material="hBN", steps="30", sio2_method="afm_step", sio2_step="3", mat_method="inside",
                         mat_before="50", mat_step="20", name="om").items():
            wz.vars[k].set(v)
        wz.om_slots["before"].set(pic)
        wz.om_slots["after"].set(pic)
        assert wz.om_slots["before"]._img is not None, "OM 縮圖沒有出來"
        assert pump(lambda: wz.result is not None, 5)
        wz.save()
        assert pump(lambda: ep.data.df is not None and len(ep.data.df) == n0 + 1, 10)
        last = ep.data.df.iloc[-1]
        assert str(last["OM before"]).endswith("_before.png") and str(last["OM after"]).endswith("_after.png"), last
        ep.data.tree.selection_set([str(n0 + 1)])
        root.update()
        assert ep.data.tree.set(str(n0 + 1), "OM after") == "📷"
        v = ep.data.show_om()
        pump(lambda: False, 0.4)
        assert v is not None and len(v._imgs) == 2, "OM 照片沒有顯示"
        v.destroy()
        # ---- 示意圖：光阻是貼著樣品的膜（多邊形，材料上方鼓起來）
        wz = ep.data.new_record()
        wz.select_stage(1)
        root.update()
        polys = [i for i in wz.canvas.find_all() if wz.canvas.type(i) == "polygon"]
        assert polys, "光阻應該畫成貼著樣品的膜"
        g = __import__("magic.gui.etch_schematic", fromlist=["Geometry"]).Geometry(
            wz.canvas.winfo_width(), wz.canvas.winfo_height(), wz.canvas.vals)
        xs, bottom, top = wz.canvas.resist_profile(g, wz.canvas.vals.get("T", 60.0), wz.canvas.vals.get("T_m", 50.0))
        mid = (g.flake[0] + g.flake[1]) / 2
        assert np.interp(mid, xs, top) < np.interp(g.sub[0] + 3, xs, top) - 5, "材料上方的光阻應該鼓起來"
        assert np.all(bottom - top >= 0.79 * g.resist_px), "光阻任何地方都要有厚度"
        wz.close()
        # ---- ⚙ 設定 → 更新：📦 打包錯誤紀錄
        from .gui.settings_dialog import SettingsDialog
        messagebox.askyesno = lambda *a, **k: False
        dlg = SettingsDialog(app)
        fp = dlg.make_report()
        assert fp is not None and os.path.exists(fp), "沒有產生錯誤回報 zip"
        os.remove(fp)
        dlg.destroy()
        # ---- 「有新版本待發佈」提示列（開發者）：通過 / 還在跑 / 沒通過、稍後
        info = {"ahead": 2, "sha": "abc", "version": "9.9.9", "notes": ["加快切換機台", "待發佈提示", "第三項", "第四項"]}
        app._on_pending_info({**info, "ci": ("success", "全部通過")})
        pump(lambda: app.pend_bar is not None and app.pend_bar.winfo_ismapped(), 3)
        assert app.pend_bar.winfo_ismapped(), "待發佈提示列沒有出現"
        assert "v9.9.9" in app.pend_title.cget("text") and "全部通過" in app.pend_title.cget("text")
        assert "共 4 項" in app.pend_sub.cget("text") and str(app.pend_btn.cget("state")) == "normal"
        app._on_pending_info({**info, "ci": ("failure", "沒有通過：Mac")})
        root.update()
        assert str(app.pend_btn.cget("state")) == "disabled", "雲端測試沒過時不能按收更新"
        app._on_pending_info({**info, "ci": ("running", "還在跑")})
        root.update()
        assert "還在跑" in app.pend_title.cget("text") and str(app.pend_btn.cget("state")) == "normal"
        app._dismiss_pending()
        root.update()
        assert not app.pend_bar.winfo_ismapped(), "按「稍後」後應該隱藏"
        app._on_pending_info({**info, "ci": ("success", "")})              # 同一版：稍後就不再跳出
        root.update()
        assert not app.pend_bar.winfo_ismapped()
        app._on_pending_info({**info, "sha": "def", "ci": ("success", "")})  # 有更新的待發佈版本：再出現
        root.update()
        assert app.pend_bar.winfo_ismapped()
        app._on_pending_info(None)                                         # 已經發佈：隱藏
        root.update()
        assert not app.pend_bar.winfo_ismapped()
        app.state.pop("pending_dismissed", None)
        # ---- 圖標題與樣式列：預設收起；打開後切到別台也是打開的；再收起
        cur = app.current.right
        assert not cur.style_bar.winfo_ismapped(), "樣式列預設應該收起來"
        cur.toggle_style()
        root.update()
        assert cur.style_bar.winfo_ismapped() and app.view["style_open"]
        other = next(k for k in app.pages if k != "Samples" and app.pages[k] is not app.current)
        app.segment.select(other)
        root.update()
        assert app.pages[other].right.style_bar.winfo_ismapped(), "切到別台時樣式列沒有跟著打開"
        app.pages[other].right.toggle_style()
        root.update()
        assert not app.pages[other].right.style_bar.winfo_ismapped() and not app.view["style_open"]
    finally:
        messagebox.askyesno, messagebox.showinfo, messagebox.showwarning = saved


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


def main(gui=True, log=print, require_gui=False):
    """require_gui：發佈前用。一定要實際開視窗、量流暢度（切換、背景計算、動畫）才算通過。"""
    from .core.settings import TOOL_ROOT
    from .testdata import write_all
    tmp = tempfile.mkdtemp(prefix="magic_selftest_")
    from .core.settings import data_dir
    real_data = data_dir()                                          # 流暢度紀錄存在真正的設定資料夾
    old_env = os.environ.get("MAGIC_DATA")
    os.environ["MAGIC_DATA"] = os.path.join(tmp, "appdata")        # 設定與紀錄寫到暫存資料夾
    os.environ.setdefault("MPLBACKEND", "Agg")
    rep = Report(log)
    rep.require_gui = require_gui
    if os.environ.get("GITHUB_ACTIONS"):                           # 雲端：卡住 20 分鐘就印出卡在哪裡
        import faulthandler
        faulthandler.dump_traceback_later(1200, exit=True)
    rep.perf = None
    log(f"Magic Tool 自我測試（{TOOL_ROOT}）" + ("　［發佈前檢查：含實際開視窗與流暢度］" if require_gui else ""))
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
            rep.check("Raman 編修與峰標註", lambda: check_raman_tools(paths))
        rep.check("設定與工具", lambda: check_settings_and_tools(tmp))
        rep.check("錯誤回報打包", lambda: check_report(tmp))
        rep.check("macOS 支援（啟動檔、App）", lambda: check_mac_support(tmp))
        rep.check("自動更新（本機模擬）", lambda: check_update(tmp))
        if gui:
            run_gui(rep)
    finally:
        if old_env is None:
            os.environ.pop("MAGIC_DATA", None)
        else:
            os.environ["MAGIC_DATA"] = old_env
        shutil.rmtree(tmp, ignore_errors=True)
    if require_gui and rep.perf and perf_factor() == 1:
        _record_perf(rep.perf, real_data, log)                      # 沒通過也記下來（才知道差多少）
    if rep.failed:
        log(f"\n✗ {len(rep.failed)} / {rep.n} 項沒有通過：{'、'.join(rep.failed)}")
        return False
    log(f"\n✓ 全部 {rep.n} 項通過")
    return True


if __name__ == "__main__":
    sys.exit(0 if main(gui="--no-gui" not in sys.argv, require_gui="--release" in sys.argv) else 1)
