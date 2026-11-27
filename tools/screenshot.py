"""截圖（開發用）：實際開視窗，用範例樣品（合成資料）截下樣品頁，檢查排版。

    python tools/screenshot.py [輸出資料夾]

GitHub Actions 的 perf.yml 會在 Windows / Linux 跑這支並把圖上傳成 artifact。
"""
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["MAGIC_DATA"] = tempfile.mkdtemp(prefix="magic_shot_")
OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "screenshots")


def main():
    import tkinter as tk
    import matplotlib
    matplotlib.use("TkAgg")
    from PIL import ImageGrab
    from magic.gui.app import App, prepare
    from magic.gui import samples_page as SP

    os.makedirs(OUT, exist_ok=True)
    root = tk.Tk()
    root.withdraw()
    prepare(root)
    app = App(root, check_updates=False)
    root.deiconify()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"{min(1600, sw)}x{min(960, sh - 40)}+0+0")

    def pump(cond=lambda: False, limit=2.0):
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < limit:
            root.update()
            if cond():
                return True
            time.sleep(0.01)
        return False

    def shot(name, win=None):
        w = win or root
        w.lift()
        pump(limit=0.6)
        x, y = w.winfo_rootx(), w.winfo_rooty()
        img = ImageGrab.grab(bbox=(x, y, x + w.winfo_width(), y + w.winfo_height()))
        fp = os.path.join(OUT, name)
        img.save(fp)
        print("saved", fp, img.size)
        if os.environ.get("SHOT_BASE64"):              # 印進 log（artifact 下載不了的環境用）
            import base64
            import io
            buf = io.BytesIO()
            small = img.convert("RGB")
            if small.width > 1400:
                small = small.resize((1400, int(small.height * 1400 / small.width)))
            small.save(buf, "JPEG", quality=82)
            b = base64.b64encode(buf.getvalue()).decode()
            print(f"==SHOT {name}==")
            for k in range(0, len(b), 2000):
                print(b[k:k + 2000])
            print("==END==", flush=True)

    pump(lambda: "Samples" in app.pages, 10)
    pg = app.page("Samples")
    app.segment.select("Samples")
    shot("01_empty.png")
    p = pg.open_demo()
    pump(lambda: not pg.scanning and pg.lib is not None and pg.lib.root == p["root"], 20)
    dlg = SP.ImportDialog(pg)
    dlg.src.set(p["sheet"])
    dlg.read()
    pump(lambda: dlg.go.instate(["!disabled"]), 20)
    shot("02_import_preview.png", dlg)
    dlg.create()
    pump(lambda: pg.find("901") and pg.find("901").get("rec") is not None, 15)
    dlg.destroy()
    pg.tree.selection_set(pg.find("901")["key"])
    pump(limit=1.0)
    shot("03_sample_overview.png")
    rec = pg.record()
    sid = next(s["id"] for s in rec["steps"] if s["folders"] == ["05 Lithography", "06 Lift Off"])
    pg.select_step(sid)
    pump(lambda: len(pg._imgs) >= 3, 5)
    shot("04_step_contact.png")
    pg.tree.selection_set(pg.find("904")["key"])
    pump(limit=0.8)
    shot("05_sample_review.png")
    rd = SP.ReviewDialog(pg)
    pump(limit=0.8)
    shot("06_review_dialog.png", rd)
    rd.destroy()
    # v0.7–v0.9
    pg.tree.selection_set(pg.find("901")["key"])
    pump(limit=0.6)
    sid = next(s["id"] for s in pg.record()["steps"] if s["kind"] == "contact")
    pg.tl.selection_set(sid)
    pump(limit=0.4)
    ed = pg.edit_selected_step()
    pump(limit=0.6)
    rie = next(r for r in ed.subrows if r["kind"] == "rie")
    rie["on"].set(True)
    rie["fs"].vars["hbn_nm"].set("43.8")
    ed.suggest(rie["fs"])
    pump(limit=0.5)
    shot("08_step_editor.png", ed)
    ed.destroy()
    sd = pg.toggle_state("hold")
    pump(limit=0.4)
    shot("09_hold_dialog.png", sd)
    sd.destroy()
    rd = pg.open_results()
    pump(limit=0.4)
    shot("10_results_dialog.png", rd)
    rd.destroy()
    pg.set_view("visual")
    pump(lambda: len(pg._outlines.get(pg.sample["key"], [])) > 0, 5)
    pg.vis_goto(5)
    pump(limit=0.8)
    shot("11_visual.png")
    xd = pg.open_export()
    pump(limit=0.6)
    shot("12_export_dialog.png", xd)
    xd.destroy()
    pg.set_view("detail")
    sy = pg.open_sync()
    pump(limit=0.4)
    shot("13_sync_dialog.png", sy)
    sy.destroy()
    app.segment.select("PPMS")
    shot("07_ppms_header.png")
    app.close()


if __name__ == "__main__":
    main()
