"""Magic Tool 主視窗（Tkinter）。

    python -m magic app [檔案或資料夾]

版面：
  頂部     Logo、機台切換（PPMS / SQUID / Raman / Etching）、輸出資料夾、⚙ 設定
  左欄     分析功能（快速檢視 / 參數萃取 / 批次比較）
  中欄     資料（檔案清單或蝕刻紀錄）→ 參數 → 繪圖 / 存圖 / 匯出結果
  右欄     圖（固定大小或填滿視窗，放不下就捲動）→ 文字結果
  底部     狀態列（進度、訊息）

不卡頓的做法：
  ‧ 每台機台一頁，啟動後在空檔先建好；切換只是換頁，不重建也不重畫
  ‧ 每台機台的按鈕顏色在啟動時就設定好樣式，切換時不重新套樣式
  ‧ 讀檔、掃描資料夾、計算都在背景執行緒；結果透過佇列交回主執行緒畫圖
  ‧ 拉動視窗 / 分隔線時，放開或停下來才重新排版、重畫
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from tkinter import messagebox, ttk

from .. import __version__
from ..core import settings as S
from ..core.registry import INSTRUMENTS, LOAD_ERRORS, load_analyses
from . import theme as T
from .page import Page
from .widgets import Paned, Segmented, card

VIEW_DEFAULTS = dict(size_mode="填滿視窗", fig_w=1100, fig_h=650, grid=True, font="中",
                     xlabel=12, ylabel=12, cbar=12, ticks=10, legend=8, title=11, suptitle=15,
                     suptitle_bold=True, fig_title="")


class App:
    UPDATE_INTERVAL_MS = 30 * 60 * 1000

    def __init__(self, root, open_path=None, check_updates=True):
        self.root = root
        self.dead = False
        self.settings = S.load_settings()
        self.state = S.load_gui_state()
        saved_view = dict(self.state.get("view", {}))
        if "xlabel" not in saved_view:              # 0.2 以前只有「字體 小 / 中 / 大」
            from .figure_panel import FONT_SIZES
            saved_view.update(FONT_SIZES.get(saved_view.get("font", "中"), FONT_SIZES["中"]))
        self.view = {**VIEW_DEFAULTS, **saved_view}
        self.state["view"] = self.view
        self.analyses = load_analyses()
        from ..raman.edits import EditStore
        self.raman_edits = EditStore()               # Raman 橡皮擦、手動背景（只影響顯示，原始檔不變）
        self.queue = queue.Queue()
        self.executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="magic")
        self.pages = {}
        self.current = None
        self.timings = []
        self._save_job = None
        self._open_path = None
        self._log_lock = threading.Lock()

        T.set_accents(INSTRUMENTS)
        self.style = ttk.Style(root)
        T.setup_all(self.style, list(INSTRUMENTS))
        root.title(f"Magic Tool 實驗分析　v{__version__}")
        try:
            sw, sh = int(root.winfo_screenwidth()), int(root.winfo_screenheight())
        except Exception:
            sw, sh = 1920, 1080
        root.geometry(f"{min(T.px(1600), sw - 40)}x{min(T.px(940), sh - 80)}")
        root.minsize(1100, 680)
        root.configure(bg=T.BG)
        self._build()
        key = self.state.get("instrument") if self.state.get("instrument") in INSTRUMENTS else next(iter(INSTRUMENTS))
        self.switch(key)
        root.after(40, self._poll)
        root.after(400, self._prebuild)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<F5>", lambda e: self.current and self.current.plot())
        mods = ("Control", "Command") if sys.platform == "darwin" else ("Control",)   # macOS 用 ⌘
        for mod in mods:
            root.bind(f"<{mod}-s>", lambda e: self.current and self.current.save_figure())
            root.bind(f"<{mod}-e>", lambda e: self.current and self.current.export())
        for i, k in enumerate(INSTRUMENTS, 1):
            for mod in mods:
                root.bind(f"<{mod}-Key-{i}>", lambda e, k=k: self.segment.select(k))
        if LOAD_ERRORS:
            root.after(800, self._show_load_errors)
        if open_path:
            root.after(300, lambda: self.open_path(open_path))
        if check_updates:
            if self.state.get("auto_update_check", True):
                root.after(3000, self.check_update)
            root.after(self.UPDATE_INTERVAL_MS, self._periodic_update)
        root.after(1500, self._maybe_whats_new)

    # ================================================================== 版面
    def _build(self):
        h = tk.Frame(self.root, bg=T.HEADER)
        h.pack(fill="x")
        logo = tk.Frame(h, bg=T.HEADER)
        logo.pack(side="left", padx=(16, 18), pady=8)
        self._logo_img = None
        try:
            self._logo_img = tk.PhotoImage(file=os.path.join(str(S.TOOL_ROOT), "assets", "icon_40.png"))
            tk.Label(logo, image=self._logo_img, bg=T.HEADER).pack(side="left", padx=(0, 10))
        except Exception:
            tk.Label(logo, text="✦", bg=T.HEADER, fg="#5eead4", font=T.font(20, "bold")).pack(side="left", padx=(0, 8))
        tt = tk.Frame(logo, bg=T.HEADER)
        tt.pack(side="left")
        tk.Label(tt, text="Magic Tool", bg=T.HEADER, fg=T.HEADER_TEXT, font=T.font(15, "bold")).pack(anchor="w")
        tk.Label(tt, text=f"實驗分析　v{__version__}", bg=T.HEADER, fg=T.HEADER_MUTED, font=T.font(9)).pack(anchor="w")
        opts = [(k, i.title, i.sub) for k, i in INSTRUMENTS.items()]
        self.segment = Segmented(h, opts, self.switch, bg=T.HEADER_2)
        self.segment.pack(side="left", padx=10, pady=8)
        ttk.Button(h, text="⚙ 設定", style="Header.TButton", command=self.open_settings).pack(side="right", padx=(6, 14))
        ttk.Button(h, text="📂 輸出資料夾", style="Header.TButton",
                   command=lambda: self.open_folder(S.output_root(self.settings))).pack(side="right")
        self.update_btn = ttk.Button(h, text="", style="Header.TButton", command=self.check_update_manual)

        body = tk.Frame(self.root, bg=T.BG)
        body.pack(fill="both", expand=True, padx=10, pady=(10, 4))
        pw = Paned(body, orient="horizontal")
        pw.pack(fill="both", expand=True)
        self.paned = pw
        hosts = []
        for size, minsize, stretch in ((T.px(290), T.px(230), False), (T.px(470), T.px(380), False),
                                       (None, T.px(420), True)):
            outer, inner = card(pw, pad=10)
            inner.rowconfigure(0, weight=1)
            inner.columnconfigure(0, weight=1)
            pw.add_pane(outer, stretch=stretch, size=size, minsize=minsize)
            hosts.append(inner)
        self.left_host, self.mid_host, self.right_host = hosts
        self.root.after(300, self._restore_sash)

        sb = tk.Frame(self.root, bg=T.BG)
        sb.pack(fill="x", padx=12, pady=(0, 6))
        self.status_dot = tk.Label(sb, text="●", bg=T.BG, fg=T.SUCCESS, font=T.font(9))
        self.status_dot.pack(side="left")
        self.status_var = tk.StringVar(value="準備好了")
        tk.Label(sb, textvariable=self.status_var, bg=T.BG, fg=T.MUTED, font=T.font(9), anchor="w").pack(
            side="left", fill="x", expand=True, padx=(4, 0))
        self.open_btn = ttk.Button(sb, text="開啟資料夾", style="Neutral.Small.TButton")
        self.busy_lab = tk.Label(sb, text="", bg=T.BG, fg=T.MUTED, font=T.font(9))
        self.busy_bar = ttk.Progressbar(sb, length=T.px(160), mode="determinate", maximum=1.0)

    def _restore_sash(self):
        for i, pos in enumerate(self.state.get("sash", [])[:2]):
            if pos:
                self.paned.set_sash(i, pos)

    # ================================================================== 頁面
    def page(self, key):
        p = self.pages.get(key)
        if p is None:
            p = Page(self, INSTRUMENTS[key], self.analyses.get(key, []))
            self.pages[key] = p
            for f in p.frames():
                f.grid(row=0, column=0, sticky="nsew")
                f.grid_remove()
            p.restore()
        return p

    def switch(self, key):
        """切換機台：只把該頁換上來（第一次才建立）。"""
        t0 = time.perf_counter()
        new = self.page(key)
        if new is self.current:
            return
        old = self.current
        for f in new.frames():
            f.grid()
        if old is not None:
            for f in old.frames():
                f.grid_remove()
        self.current = new
        if self.segment.buttons[self.segment.active][0] != key:
            self.segment.select(key, notify=False)
        self.show_busy(new.busy)
        if getattr(new, "_restyle_pending", False):
            new._restyle_pending = False
            new.root_after = self.root.after_idle(new.restyle)
        self.state["instrument"] = key
        self.save_state_soon()
        self.last_switch_ms = (time.perf_counter() - t0) * 1000

    def _prebuild(self):
        """啟動後在空檔把其他機台的頁面先建好，之後切換不用等。"""
        if self.dead:
            return
        for key in INSTRUMENTS:
            if key not in self.pages:
                self.page(key)
                self.root.after(120, self._prebuild)
                return

    # ================================================================== 背景工作
    def submit(self, fn):
        def wrapped():
            try:
                fn()
            except Exception:
                import traceback
                self.log(traceback.format_exc())
        return self.executor.submit(wrapped)

    def post(self, msg):
        self.queue.put(msg)

    def _poll(self):
        if self.dead:
            return
        t0 = time.perf_counter()
        try:
            while time.perf_counter() - t0 < 0.03:          # 一次最多處理 30 ms，畫面不會被佔住
                kind, data = self.queue.get_nowait()
                self._handle(kind, data)
        except queue.Empty:
            pass
        busy = any(p.busy for p in self.pages.values()) or not self.queue.empty()
        self.root.after(30 if busy else 100, self._poll)

    def _handle(self, kind, data):
        if kind == "files":
            panel, gen, found, select = data
            panel.on_files(gen, found, select)
        elif kind == "kinds":
            panel, gen, batch = data
            panel.on_kinds(gen, batch)
        elif kind == "records":
            panel, gen, df, err, select_last = data
            panel.on_records(gen, df, err, select_last)
        elif kind == "progress":
            page, gen, k, n, text = data
            page.on_progress(gen, k, n, text)
        elif kind == "plotdata":
            page = data[0]
            page.on_plotdata(*data[1:])
        elif kind == "status":
            self.status(*data)
        elif kind == "update":
            self._on_update_info(*data)
        elif kind == "updated":
            messagebox.showinfo("更新完成", f"已更新到 v{data}，接下來會重新開啟軟體。", parent=self.root)
            self.restart()
        elif kind == "update_error":
            self.status(f"更新失敗：{data}", "error")
            messagebox.showerror("更新失敗", f"{data}\n\n可以在 ⚙ 設定 → 更新 裡還原上一版。", parent=self.root)
        elif kind == "call":
            data()

    # ================================================================== 狀態列
    def status(self, text, kind="info", open_path=None):
        self.status_var.set(text)
        self.status_dot.configure(fg={"ok": T.SUCCESS, "warn": T.WARNING, "error": T.ERROR}.get(kind, T.MUTED))
        if open_path:
            self.open_btn.configure(command=lambda: self.open_folder(open_path))
            self.open_btn.pack(side="right", padx=(6, 0))
        else:
            self.open_btn.pack_forget()

    def show_busy(self, state):
        if state is None:
            self.busy_bar.pack_forget()
            self.busy_lab.pack_forget()
            return
        k, n, text = state
        self.busy_lab.configure(text=f"{text} {k}/{n}" if n else text)
        self.busy_bar.configure(value=(k / n) if n else 0)
        if not self.busy_bar.winfo_ismapped():
            self.busy_bar.pack(side="right", padx=(6, 0))
            self.busy_lab.pack(side="right")

    def log(self, text):
        with self._log_lock:
            try:
                with open(S.log_dir() / "app.log", "a", encoding="utf-8") as f:
                    f.write(f"[{time.strftime('%H:%M:%S')}] {text}\n")
            except OSError:
                pass

    # ================================================================== 設定與狀態
    def on_view_change(self):
        """圖的大小、字體、格線：所有機台共用；改了只重新套樣式，不重新計算。"""
        self.save_state_soon()
        for p in self.pages.values():
            if p is self.current:
                p.restyle()
            else:
                p.right.sync_view()
                p._restyle_pending = True

    def save_state_soon(self):
        if self._save_job is not None:
            try:
                self.root.after_cancel(self._save_job)
            except Exception:
                pass
        self._save_job = self.root.after(800, self.save_state)

    def save_state(self):
        self._save_job = None
        try:
            self.state["sash"] = [self.paned.get_sash(0), self.paned.get_sash(1)]
        except Exception:
            pass
        S.save_gui_state(self.state)

    def open_settings(self, tab=None):
        from .settings_dialog import SettingsDialog
        SettingsDialog(self, tab)

    def apply_settings(self, new):
        """設定視窗按「儲存」後。"""
        old = self.settings
        self.settings = new
        S.save_settings(new)
        for key, p in self.pages.items():
            if p.inst.source == "records":
                p.data.reload()
            elif not p.data.folder and new.get("folders", {}).get(key) and os.path.isdir(new["folders"][key]):
                p.data.set_folder(new["folders"][key])
        if old.get("output_root") != new.get("output_root"):
            self.status(f"輸出資料夾：{S.output_root(new)}", "ok")

    # ================================================================== 開啟
    def open_folder(self, path):
        path = str(path)
        try:
            os.makedirs(path, exist_ok=True)
            if os.name == "nt":
                os.startfile(path)                     # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            self.status(f"無法開啟：{e}（{path}）", "error")

    def open_path(self, path):
        """命令列或拖曳：依檔案種類切到對應的機台並選取。"""
        from ..readers import detect
        path = os.path.normpath(str(path).strip('"'))
        if os.path.isdir(path):
            kinds = []
            for n in sorted(os.listdir(path))[:30]:
                fp = os.path.join(path, n)
                if os.path.isfile(fp):
                    kinds.append(detect(fp))
            key = max(("PPMS", "SQUID", "Raman"), key=kinds.count) if kinds else (self.current.key if self.current else "PPMS")
            self.segment.select(key)
            self.pages[key].data.set_folder(path)
            return
        if os.path.isfile(path):
            if path.lower().endswith(".csv") and "etch" in os.path.basename(path).lower():
                self.segment.select("Etching")
                return
            kind = detect(path)
            key = kind if kind in INSTRUMENTS else ("PPMS" if kind == "QD" else self.current.key)
            self.segment.select(key)
            self.pages[key].data.set_folder(os.path.dirname(path), select=[path])

    def open_demo(self):
        """產生範例資料（合成資料，不是真實量測）並開啟，給第一次使用的人試用。"""
        from ..testdata import write_all
        d = S.data_dir() / "demo"
        paths = write_all(str(d))
        for key in ("PPMS", "SQUID", "Raman"):
            self.page(key).data.set_folder(str(d / key), select=None)
        ep = self.page("Etching")
        ep.data.source_var.set("範例資料（唯讀）")
        ep.data.reload()
        self.status(f"已產生範例資料（合成資料）：{d}", "ok", open_path=str(d))
        return paths

    def _show_load_errors(self):
        text = "\n\n".join(f"{k}\n{v.strip().splitlines()[-1]}" for k, v in LOAD_ERRORS.items())
        self.log("載入失敗：\n" + "\n".join(f"{k}\n{v}" for k, v in LOAD_ERRORS.items()))
        messagebox.showwarning("有分析功能載入失敗", f"以下檔案有錯誤，這些功能暫時不會出現：\n\n{text}", parent=self.root)

    # ================================================================== 更新
    def check_update(self, manual=False):
        def work():
            from .. import updater
            try:
                info = updater.check()
            except Exception as e:
                info = {"error": str(e), "newer": False}
            self.post(("update", (info, manual)))
        threading.Thread(target=work, daemon=True).start()

    def check_update_manual(self):
        self.status("檢查更新中…")
        self.check_update(manual=True)

    def _periodic_update(self):
        if self.dead:
            return
        if self.state.get("auto_update_check", True):
            self.check_update()
        self.root.after(self.UPDATE_INTERVAL_MS, self._periodic_update)

    def _on_update_info(self, info, manual):
        from .. import updater
        if info.get("error"):
            if manual:
                messagebox.showwarning("檢查更新", f"沒辦法檢查更新：{info['error']}", parent=self.root)
            return
        if not info.get("newer"):
            if manual:
                messagebox.showinfo("檢查更新", f"已經是最新版 v{info.get('current')}", parent=self.root)
            self.update_btn.pack_forget()
            return
        latest = info.get("latest")
        self.update_btn.configure(text=f"⬆ 有新版 v{latest}")
        self.update_btn.pack(side="right", padx=(0, 6))
        if self.state.get("skip_version") == latest and not manual:
            return
        if updater.is_dev_folder():
            if manual:
                messagebox.showinfo("檢查更新", f"GitHub 上有 v{latest}。這是開發用資料夾（有 .git），請用 GitHub Desktop 的 Pull 更新。",
                                    parent=self.root)
            return
        notes = info.get("since") or [(latest, "", info.get("notes", []))]
        lines = []
        for v, d, ns in notes[:6]:
            lines.append(f"v{v}" + (f"（{d}）" if d else ""))
            lines += [f"  ‧ {n}" for n in ns[:8]]
        ok = messagebox.askyesno("有新版本", f"目前 v{info.get('current')}，GitHub 上有 v{latest}：\n\n" +
                                 "\n".join(lines) + "\n\n現在更新嗎？（設定與紀錄都不會被覆蓋）", parent=self.root)
        if not ok:
            self.state["skip_version"] = latest
            self.save_state_soon()
            return
        self.status("下載新版本…")

        def work():
            try:
                ver = updater.apply_update(info, log=lambda m: self.post(("status", (m,))))
                self.state["updated_from"] = __version__
                S.save_gui_state(self.state)
                self.post(("updated", ver))
            except Exception as e:
                self.post(("update_error", str(e)))
        threading.Thread(target=work, daemon=True).start()

    def _maybe_whats_new(self):
        if self.dead:
            return
        from .. import updater
        since = self.state.pop("updated_from", None) or self.state.get("last_seen_version")
        self.state["last_seen_version"] = __version__
        self.save_state_soon()
        if not since or updater.parse_version(__version__) <= updater.parse_version(since):
            return
        rel = updater.read_release()
        entries = [(v, d, n) for v, d, n in updater.all_notes(rel)
                   if updater.parse_version(since) < updater.parse_version(v) <= updater.parse_version(__version__)]
        if entries:
            text = "\n\n".join(f"v{v}" + (f"（{d}）" if d else "") + "\n" + "\n".join(f"‧ {x}" for x in n)
                               for v, d, n in entries[:6])
            messagebox.showinfo("這版新增了什麼", f"已更新到 v{__version__}（上次是 v{since}）\n\n{text}", parent=self.root)

    def restart(self):
        self.close(restart=True)

    def close(self, restart=False):
        if self.dead:
            return
        self.save_state()
        self.dead = True
        self.executor.shutdown(wait=False, cancel_futures=True)
        if restart:
            try:
                from ..install import pythonw_path
                subprocess.Popen([pythonw_path(), "-m", "magic", "app"], cwd=str(S.TOOL_ROOT))
            except Exception:
                pass
        self.root.destroy()


def prepare(root):
    """建立視窗前：字型、介面大小、matplotlib 樣式。"""
    from tkinter import font as tkfont
    from ..core import plotstyle
    T.pick_fonts(tkfont)
    T.apply_scaling(root, S.load_gui_state().get("ui_scale", "auto"))
    plotstyle.apply()


def run_gui(path=None):
    root = tk.Tk()
    prepare(root)
    App(root, path)
    root.mainloop()
