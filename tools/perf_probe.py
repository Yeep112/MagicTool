"""效能分析（開發用）：實際開視窗，用 cProfile 找出「切換機台」與「蝕刻動畫」最花時間的地方。

    python tools/perf_probe.py

GitHub Actions 的 perf.yml 會在真的 Windows / Mac 上跑這支，結果印在 log 裡。只用合成資料。
"""
import cProfile
import io
import os
import pstats
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["MAGIC_DATA"] = tempfile.mkdtemp(prefix="magic_perf_")


def top(prof, n=25, key="cumulative"):
    s = io.StringIO()
    st = pstats.Stats(prof, stream=s)
    st.strip_dirs().sort_stats(key).print_stats(n)
    return s.getvalue()


def main():
    import tkinter as tk
    import matplotlib
    matplotlib.use("TkAgg")
    from magic.gui.app import App, prepare
    from magic.core.registry import INSTRUMENTS

    root = tk.Tk()
    root.withdraw()
    prepare(root)
    app = App(root, check_updates=False)
    root.deiconify()
    root.geometry("1500x900+0+0")

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
    pump(lambda: all(p.data.files for p in app.pages.values() if p.inst.source == "files"), 15)
    pump(lambda: app.pages["Etching"].data.df is not None, 10)
    for key in INSTRUMENTS:                      # 每台畫一張圖（和自我測試一樣）
        app.segment.select(key)
        page = app.pages[key]
        if page.inst.source == "files":
            kids = page.data.tree.get_children()
            page.data.tree.selection_set(list(kids)[:2])
        gen0 = page.gen
        page.plot()
        pump(lambda: page.gen > gen0 and page.busy is None, 30)
    pump(lambda: False, 1.0)

    # ---------------- 切換機台 ----------------
    print("=" * 70)
    print("切換機台：每次 select + update 的時間（ms），以及拆開來量")
    keys = list(INSTRUMENTS)
    rows = []
    prof = cProfile.Profile()
    for _ in range(4):
        for key in keys:
            t0 = time.perf_counter()
            prof.enable()
            app.segment.select(key)
            t1 = time.perf_counter()
            root.update_idletasks()
            t2 = time.perf_counter()
            root.update()
            prof.disable()
            t3 = time.perf_counter()
            rows.append((key, (t1 - t0) * 1e3, (t2 - t1) * 1e3, (t3 - t2) * 1e3))
    print(f"{'機台':8s} {'select':>8s} {'idle':>8s} {'update':>8s} {'合計':>8s}")
    for k, a, b, c in rows:
        print(f"{k:8s} {a:8.1f} {b:8.1f} {c:8.1f} {a + b + c:8.1f}")
    print(top(prof, 15, "cumulative"))

    # ---------------- 拆開量：只換左 / 中 / 右其中一欄 ----------------
    def count(w):
        return 1 + sum(count(c) for c in w.winfo_children())

    print("=" * 70)
    print("每一欄的元件數，以及只把那一欄拿掉再放回去的時間（ms，update 合計）")
    names = ("左（功能清單）", "中（檔案 + 參數）", "右（圖 + 文字結果）")
    for key in keys:
        app.segment.select(key)
        root.update()
        page = app.pages[key]
        cells = []
        for i, f in enumerate(page.frames()):
            ts = []
            for _ in range(5):
                f.grid_remove()
                root.update()
                t = time.perf_counter()
                f.grid()
                root.update()
                ts.append((time.perf_counter() - t) * 1e3)
            cells.append(f"{names[i]} {count(f)} 個元件 {sorted(ts)[2]:.1f}")
        print(f"{key:8s} " + "　".join(cells))
    # 右欄再細分：圖（matplotlib 畫布）本身
    for key in keys:
        app.segment.select(key)
        root.update()
        rp = app.pages[key].right
        w = rp.canvas.get_tk_widget()
        ts = []
        for _ in range(5):
            rp.host.itemconfigure(rp._win, state="hidden")
            root.update()
            t = time.perf_counter()
            rp.host.itemconfigure(rp._win, state="normal")
            root.update()
            ts.append((time.perf_counter() - t) * 1e3)
        print(f"{key:8s} 只重新顯示圖（{w.winfo_width()}×{w.winfo_height()}）：{sorted(ts)[2]:.1f} ms")

    # ---------------- 蝕刻動畫 ----------------
    print("=" * 70)
    print("蝕刻動畫：每一格的時間（ms）")
    ep = app.pages["Etching"]
    app.segment.select("Etching")
    root.update()
    wz = ep.data.new_record()
    for k, v in dict(material="hBN", line_width="200", steps="3x20", mat_before="80.1, 79.9, 80.3",
                     mat_out="45.2, 45.8, 45.0", marker_before="50.2 50.0", marker_out="53.1, 52.9").items():
        try:
            wz.vars[k].set(v)
        except Exception:
            pass
    pump(lambda: False, 1.0)
    for i in range(7):
        wz.select_stage(i)
        root.update()
    pump(lambda: False, 0.5)
    frames = []
    prof = cProfile.Profile()
    prof.enable()
    wz.play_etch()
    t0 = last = time.perf_counter()
    while wz._anim is not None and time.perf_counter() - t0 < 15:
        root.update()
        now = time.perf_counter()
        frames.append((now - last) * 1e3)
        last = now
        time.sleep(0.002)
    prof.disable()
    big = sorted(range(len(frames)), key=lambda i: -frames[i])[:8]
    print(f"共 {len(frames)} 次 update；最長的幾次：" + "、".join(f"#{i} {frames[i]:.0f}" for i in big))
    c = wz.canvas
    print(f"畫布上的物件數：{len(c.find_all())}")
    t = time.perf_counter()
    for _ in range(20):
        c.redraw()
    root.update_idletasks()
    print(f"redraw() 平均 {(time.perf_counter() - t) / 20 * 1e3:.1f} ms（不含螢幕更新）")
    t = time.perf_counter()
    for _ in range(20):
        c.redraw()
        root.update()
    print(f"redraw() + update 平均 {(time.perf_counter() - t) / 20 * 1e3:.1f} ms")
    print(top(prof, 30, "cumulative"))
    print(top(prof, 20, "tottime"))
    app.close()


if __name__ == "__main__":
    main()
