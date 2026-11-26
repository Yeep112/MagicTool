"""一台機台的整頁（左：功能清單；中：資料 + 參數；右：圖）。

每台機台各有一頁，第一次開啟時建立，之後切換只是把頁面換上來（不重建、不重畫），所以不會卡頓。
讀檔與計算都在背景執行；畫圖在主執行緒（matplotlib 的限制），用 draw_idle 合併重畫。
"""
from __future__ import annotations

import os
import time
import tkinter as tk
import traceback
from tkinter import filedialog, ttk

from ..core.registry import Item
from ..core.plotstyle import PLOT_CYCLE
from . import theme as T
from .figure_panel import FigurePanel
from .params_panel import ParamPanel
from .widgets import FeatureList, Paned, ScrollFrame


class Cancelled(Exception):
    """背景計算已經過時（選取或參數又改了），停止。"""


class Page:
    def __init__(self, app, inst, analyses):
        self.app = app
        self.inst = inst
        self.key = inst.key
        self.analyses = analyses
        self.st = app.state.setdefault("pages", {}).setdefault(inst.key, {})
        self.st.setdefault("params", {})
        names = [a.name for a in analyses]
        self.current = analyses[names.index(self.st["analysis"])] if self.st.get("analysis") in names else \
            (analyses[0] if analyses else None)
        self.param_panels = {}
        self.gen = 0
        self._plot_job = None
        self._columns = ()
        self.last = None
        self.busy = None
        self._build()

    # ================================================================== 版面
    def _build(self):
        app, key = self.app, self.key
        a = T.accent(key)
        # ---- 左：功能清單
        self.left = tk.Frame(app.left_host, bg=T.CARD)
        tk.Label(self.left, text="分析功能", bg=T.CARD, fg=T.TEXT, font=T.font(11, "bold"), anchor="w").pack(fill="x")
        tk.Label(self.left, text=self.inst.sub, bg=T.CARD, fg=T.MUTED, font=T.font(9), anchor="w").pack(fill="x")
        sf = ScrollFrame(self.left)
        sf.pack(fill="both", expand=True, pady=(4, 0))
        self.features = FeatureList(sf.body, key, self.select_analysis)
        self.features.pack(fill="both", expand=True)
        self.features.set_items(self.analyses, self.current.name if self.current else None)
        if not self.analyses:
            tk.Label(sf.body, text="這台機台還沒有分析功能", bg=T.CARD, fg=T.MUTED).pack(pady=20)

        # ---- 中：資料 + 參數
        self.mid = tk.Frame(app.mid_host, bg=T.CARD)
        vp = Paned(self.mid, orient="vertical", bg=T.CARD)
        vp.pack(fill="both", expand=True)
        self.vpaned = vp
        top = tk.Frame(vp, bg=T.CARD)
        bottom = tk.Frame(vp, bg=T.CARD)
        vp.add_pane(top, stretch=True, minsize=T.px(160))
        vp.add_pane(bottom, stretch=False, size=T.px(330), minsize=T.px(170))
        if self.inst.source == "records":
            from .records_panel import RecordsPanel
            self.data = RecordsPanel(top, self)
        else:
            from .files_panel import FilePanel
            self.data = FilePanel(top, self)
        self.data.pack(fill="both", expand=True)

        ph = tk.Frame(bottom, bg=T.CARD)
        ph.pack(fill="x", pady=(8, 0))
        self.p_icon = tk.Label(ph, text="", bg=T.CARD, fg=a["main"], font=T.font(12, "bold"))
        self.p_icon.pack(side="left", padx=(0, 6))
        self.p_title = tk.Label(ph, text="參數", bg=T.CARD, fg=T.TEXT, font=T.font(11, "bold"))
        self.p_title.pack(side="left")
        ttk.Button(ph, text="恢復預設", style=f"{key}.Small.TButton", command=self.reset_params).pack(side="right")
        self.p_help = tk.Label(bottom, text="", bg=T.CARD, fg=T.MUTED, font=T.font(8), anchor="w", justify="left",
                               wraplength=T.px(420))
        self.p_help.pack(fill="x", pady=(2, 4))
        bf = tk.Frame(bottom, bg=T.CARD)
        bf.pack(side="bottom", fill="x", pady=(6, 0))
        ttk.Button(bf, text="▶ 繪圖", style=f"{key}.Accent.TButton", command=self.plot).pack(side="left")
        ttk.Button(bf, text="存圖", style=f"{key}.Ghost.TButton", command=self.save_figure).pack(side="left", padx=(6, 0))
        ttk.Button(bf, text="匯出結果", style=f"{key}.Ghost.TButton", command=self.export).pack(side="left", padx=(6, 0))
        self.auto_var = tk.BooleanVar(value=self.st.get("auto", True))
        ttk.Checkbutton(bf, text="自動重畫", variable=self.auto_var, style=f"{key}.TCheckbutton",
                        command=lambda: self.remember(auto=bool(self.auto_var.get()))).pack(side="right")
        if key == "Raman":
            tf = tk.Frame(bottom, bg=T.CARD)
            tf.pack(side="bottom", fill="x", pady=(6, 0))
            ttk.Button(tf, text="✎ 編修光譜（橡皮擦 / 手動背景）", style=f"{key}.Ghost.TButton",
                       command=self.open_raman_editor).pack(side="left")
            ttk.Button(tf, text="🏷 峰標註", style=f"{key}.Ghost.TButton",
                       command=self.open_peak_labels).pack(side="left", padx=(6, 0))
        self.p_scroll = ScrollFrame(bottom)
        self.p_scroll.pack(fill="both", expand=True)
        self.p_host = self.p_scroll.body
        self.p_host.columnconfigure(0, weight=1)

        # ---- 右：圖
        self.right = FigurePanel(app.right_host, key, app.view, app.on_view_change)
        tools = self.right.tools
        tools.get_ov = lambda: self.st.setdefault("fig", {}).setdefault(self.current.name if self.current else "", {})
        tools.save = self.app.save_state_soon
        tools.status = self.app.status
        self.right.redraw_request = self.redraw
        self.post_draw = []                   # 畫完、套樣式之前的額外步驟（例如 Raman 的峰標註）
        if key == "Raman":
            self.post_draw.append(self._draw_peak_labels)
        self._wrap_job = None
        bottom.bind("<Configure>", lambda e: self.p_help.configure(wraplength=max(e.width - 10, 150)))
        if self.current:
            self._show_params(self.current)

    # ================================================================== Raman 工具
    def open_raman_editor(self):
        from .raman_editor import RamanEditor
        sel = self.data.selected_paths()
        allp = [f["path"] for f in self.data.files if f.get("kind") in ("Raman", "?", None)] or \
            [f["path"] for f in self.data.files]
        paths = sel + [p for p in allp if p not in sel]
        if not paths:
            self.app.status("先選資料夾（或用範例資料），再編修光譜", "warn")
            return None
        win = getattr(self, "_editor", None)
        if win is not None and win.winfo_exists():
            win.destroy()
        self._editor = RamanEditor(self, paths, sel[0] if sel else None)
        return self._editor

    def peak_label_defs(self):
        from ..raman import labels as L
        defs = self.app.state.get("raman_labels")
        if not isinstance(defs, list):
            defs = L.defaults()
            self.app.state["raman_labels"] = defs
        return defs

    def _draw_peak_labels(self, page, a, items, p, data, res):
        from ..raman import labels as L
        L.draw(self.right.fig, self.peak_label_defs())

    def open_peak_labels(self):
        from .peak_labels import PeakLabelDialog
        win = getattr(self, "_labels_win", None)
        if win is not None and win.winfo_exists():
            win.lift()
            return win
        self._labels_win = PeakLabelDialog(self)
        return self._labels_win

    def frames(self):
        return self.left, self.mid, self.right

    def restore(self):
        """建立後還原上次的資料夾與選取（或設定裡的預設資料夾）。"""
        if self.inst.source == "records":
            self.data.reload()
            return
        folder = self.st.get("folder") or self.app.settings.get("folders", {}).get(self.key) or ""
        if folder and os.path.isdir(folder):
            sel = [os.path.normpath(os.path.join(folder, n)) for n in self.st.get("selected", [])]
            self.data.set_folder(folder, select=sel)

    def remember(self, **kw):
        self.st.update(kw)
        self.app.save_state_soon()

    # ================================================================== 功能與參數
    def _show_params(self, a):
        panel = self.param_panels.get(a.name)
        if panel is None:
            saved = self.st["params"].get(a.name, {})
            panel = ParamPanel(self.p_host, a, f"{self.key}.", lambda k, ok, a=a: self.on_param(a, k, ok), saved)
            panel.grid(row=0, column=0, sticky="nsew")
            if self._columns:
                panel.set_columns(self._columns)
            self.param_panels[a.name] = panel
        for name, p in self.param_panels.items():
            if name != a.name:
                p.grid_remove()
        panel.grid()
        self.p_scroll.to_top()
        self.p_icon.configure(text=a.icon)
        self.p_title.configure(text=f"{a.name}")
        self.p_help.configure(text=a.help)

    def select_analysis(self, name):
        a = next((x for x in self.analyses if x.name == name), None)
        if a is None or a is self.current:
            return
        self.current = a
        self._show_params(a)
        self.remember(analysis=a.name)
        self.schedule_plot(0)

    def panel(self):
        return self.param_panels[self.current.name]

    def on_param(self, a, key, ok):
        panel = self.param_panels[a.name]
        self.st["params"][a.name] = panel.changed_texts()
        self.app.save_state_soon()
        if not ok:
            self.app.status(f"「{a.name}」有參數格式不對（紅框），修正後才會重畫", "warn")
            return
        if a is self.current and self.auto_var.get():
            self.schedule_plot(350)

    def reset_params(self):
        if self.current:
            self.panel().reset()

    def on_selection(self):
        if self.inst.source == "files":
            folder = self.data.folder
            sel = [os.path.relpath(p, folder) if folder else os.path.basename(p) for p in self.data.selected_paths()]
            self.remember(selected=sel)
        if self.auto_var.get():
            self.schedule_plot(200)

    # ================================================================== 繪圖
    def schedule_plot(self, delay=250):
        if self._plot_job is not None:
            try:
                self.app.root.after_cancel(self._plot_job)
            except Exception:
                pass
        self._plot_job = self.app.root.after(delay, self.plot)

    def _sources(self):
        if self.inst.source == "records":
            df = self.data.selection_df()
            return None if df is None else df
        paths = self.data.selected_paths()
        if self.current and not self.current.multi:
            paths = paths[:1]
        return paths

    def plot(self):
        self._plot_job = None
        a = self.current
        if a is None:
            return
        self.gen += 1
        gen = self.gen
        try:
            p = self.panel().values()
        except ValueError as e:
            self.right.message("參數格式不對", str(e), "warn")
            self.app.status(str(e), "warn")
            return
        src = self._sources()
        if src is None or (hasattr(src, "__len__") and len(src) == 0):
            self.set_busy(None)
            if self.inst.source == "records":
                self.right.message("還沒有紀錄", "按中間的「＋ 新增紀錄」，或在 ⚙ 設定 → 蝕刻紀錄 指定 CSV")
            else:
                self.right.message("還沒有選資料", "在中間選一個或多個檔案（按住 Ctrl / Shift 多選，Ctrl+A 全選）")
            self.right.set_header(a.name, a.help.split("。")[0], n="")
            return
        n = len(src)
        self.set_busy((0, n, "讀取資料"))
        records = self.inst.source == "records"
        key = self.key
        rec_path = self.data.source_path() if records else None      # tk 變數只能在主執行緒讀
        edits = self.app.raman_edits.snapshot(src) if key == "Raman" else {}

        def progress(k, total, text=""):
            if gen != self.gen or self.app.dead:
                raise Cancelled()
            self.app.post(("progress", (self, gen, k, total, text)))

        def work():
            t0 = time.perf_counter()
            try:
                if records:
                    from ..readers import Dataset
                    items = [Item(rec_path, "紀錄", PLOT_CYCLE[0], Dataset(rec_path, "Etching", src))]
                else:
                    from ..readers import load
                    items = []
                    for k, path in enumerate(src):
                        if gen != self.gen or self.app.dead:
                            return
                        ds = load(path)
                        items.append(Item(path, os.path.splitext(os.path.basename(path))[0],
                                          PLOT_CYCLE[k % len(PLOT_CYCLE)], ds))
                        self.app.post(("progress", (self, gen, k + 1, len(src), "讀取資料")))
                    if edits:
                        from ..raman.edits import apply_all
                        apply_all(items, edits)               # 橡皮擦、手動背景（原始檔不變）
                data = None
                if a.compute is not None:
                    data = a.compute(items, dict(p), progress)
                self.app.post(("plotdata", (self, gen, a, items, p, data, None, time.perf_counter() - t0)))
            except Cancelled:
                pass
            except Exception as e:
                self.app.post(("plotdata", (self, gen, a, None, p, None, (e, traceback.format_exc()), 0)))
        self.app.submit(work)
        self.app.log(f"[{key}] {a.name}：{n} 筆")

    def on_progress(self, gen, k, n, text):
        if gen == self.gen:
            self.set_busy((k, n, text))

    def set_busy(self, state):
        self.busy = state
        if self.app.current is self:
            self.app.show_busy(state)

    def on_plotdata(self, gen, a, items, p, data, err, seconds):
        if gen != self.gen or self.app.dead:
            return
        self.set_busy(None)
        if err is not None:
            e, tb = err
            self.app.log(tb)
            self.right.message(f"{a.name}：無法完成", str(e), "error")
            self.right.set_header(a.name, "發生錯誤", n="")
            self.right.set_text("", error=f"{type(e).__name__}: {e}\n\n如果是欄位名稱不對，可以在參數面板改欄位（下拉選單）。")
            self.app.status(f"{a.name}：{e}", "error")
            self.last = None
            return
        self._update_columns(items)
        self._draw(a, items, p, data, seconds)

    def _draw(self, a, items, p, data, seconds=0.0):
        t0 = time.perf_counter()
        self.right.begin()
        try:
            res = a.func(self.right.fig, items, p, data)
            for hook in self.post_draw:
                hook(self, a, items, p, data, res)
        except Exception as e:
            self.app.log(traceback.format_exc())
            self.right.message(f"{a.name}：畫圖失敗", str(e), "error")
            self.right.set_text("", error=f"{type(e).__name__}: {e}")
            self.app.status(f"{a.name}：{e}", "error")
            self.last = None
            return
        self.right.finish()
        draw_t = time.perf_counter() - t0
        n = len(items) if self.inst.source == "files" else len(items[0].data.df)
        unit = "個檔案" if self.inst.source == "files" else "筆紀錄"
        sub = "、".join(it.label for it in items[:4]) + (f" 等 {len(items)} 個" if len(items) > 4 else "") \
            if self.inst.source == "files" else f"{n} 筆紀錄"
        hidden = self.right.tools.hidden_count()
        hint = res.hint + ("　" if res.hint and hidden else "") + (f"（{hidden} 條資料被隱藏：點圖例可以顯示）" if hidden else "")
        self.right.set_header(res.title or a.name, sub, hint, f"{n} {unit}")
        notes = []
        if self.inst.source == "files":
            for it in items:
                notes += [f"{it.label}：{x}" for x in it.data.notes if "略過" not in x and "保留為文字" not in x]
        self.right.set_text(res.text, list(res.warnings) + notes)
        self.last = dict(analysis=a, items=items, params=p, result=res, data=data)
        self.app.status(f"{a.name}：完成（計算 {seconds:.2f} 秒、繪圖 {draw_t:.2f} 秒）", "ok")
        self.app.timings.append((self.key, a.name, seconds, draw_t))

    def redraw(self):
        """用上一次算好的結果重畫（改了標註、圖例、標題時用，不重新計算）。"""
        last = self.last
        if last is None or last["analysis"] is not self.current:
            self.right.restyle()
            return
        self._draw(last["analysis"], last["items"], last["params"], last.get("data"))

    def _update_columns(self, items):
        if self.inst.source != "files" or not items:
            return
        cols = []
        for it in items:
            for c in it.data.numeric_columns:
                if c not in cols:
                    cols.append(c)
        cols = tuple(cols)
        if cols != self._columns:
            self._columns = cols
            for panel in self.param_panels.values():
                panel.set_columns(cols)

    def restyle(self):
        self.right.sync_view()
        self.right.restyle()

    # ================================================================== 存檔
    def _out_dir(self):
        from ..core.settings import output_root
        d = output_root(self.app.settings) / self.key
        return d

    def save_figure(self):
        if self.last is None:
            self.app.status("還沒有圖可以存", "warn")
            return
        from ..core.records import safe_name
        d = self._out_dir()
        d.mkdir(parents=True, exist_ok=True)
        fmt = self.app.settings.get("fig_format", "png")
        fp = filedialog.asksaveasfilename(parent=self.app.root, title="存圖", initialdir=str(d),
                                          initialfile=f"{safe_name(self.current.name)}.{fmt}",
                                          defaultextension=f".{fmt}",
                                          filetypes=[("PNG", "*.png"), ("JPG", "*.jpg"), ("PDF", "*.pdf"),
                                                     ("SVG", "*.svg")])
        if not fp:
            return
        self.right.fig.savefig(fp, dpi=int(self.app.settings.get("dpi", 200)), bbox_inches="tight")
        self.app.status(f"已存圖：{fp}", "ok", open_path=os.path.dirname(fp))

    def export(self):
        if self.last is None:
            self.app.status("還沒有結果可以匯出（先繪圖）", "warn")
            return
        from .. import __version__
        from ..core.records import export_result
        last = self.last
        texts = self.panel().texts() if self.current is last["analysis"] else {}
        texts = dict(texts or last["params"])
        if self.key == "Raman":
            eds = {it.path: getattr(it.data, "edits", None) for it in last["items"]}
            eds = {k: v for k, v in eds.items() if v}
            if eds:
                texts["_編修（橡皮擦 / 手動背景）"] = eds
        if self.inst.source == "files":
            sources = [it.path for it in last["items"]]
        else:
            df = last["items"][0].data.df
            sources = [{"records": last["items"][0].path, "rows": [int(x) for x in df["#"]]}]
        try:
            out = export_result(self._out_dir().parent, self.key, last["analysis"].name, self.right.fig,
                                last["result"], texts, sources, __version__,
                                fig_format=self.app.settings.get("fig_format", "png"),
                                dpi=int(self.app.settings.get("dpi", 200)))
        except Exception as e:
            self.app.log(traceback.format_exc())
            self.app.status(f"匯出失敗：{e}", "error")
            return
        self.app.status(f"已匯出：{out}", "ok", open_path=str(out))
