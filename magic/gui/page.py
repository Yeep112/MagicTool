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
from .widgets import set_if_changed, FeatureList, Paned, ScrollFrame, WrapRow


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
        bf = WrapRow(bottom, bg=T.CARD, padx=6)                    # 欄位窄的時候按鈕自動換行（不會被擠扁）
        bf.pack(side="bottom", fill="x", pady=(6, 0))
        bf.add(ttk.Button(bf, text="▶ 繪圖", style=f"{key}.Accent.TButton", command=self.plot))
        bf.add(ttk.Button(bf, text="存圖", style=f"{key}.Ghost.TButton", command=self.save_figure))
        bf.add(ttk.Button(bf, text="匯出結果", style=f"{key}.Ghost.TButton", command=self.export))
        if key in ("PPMS", "SQUID"):
            bf.add(ttk.Button(bf, text="📌 寫到樣品", style=f"{key}.Ghost.TButton", command=self.write_to_sample),
                   compact="📌")
        self.auto_var = tk.BooleanVar(value=self.st.get("auto", True))
        bf.add(ttk.Checkbutton(bf, text="自動重畫", variable=self.auto_var, style=f"{key}.TCheckbutton",
                               command=lambda: self.remember(auto=bool(self.auto_var.get()))), side="right")
        if key == "Raman":
            tf = WrapRow(bottom, bg=T.CARD, padx=6)
            tf.pack(side="bottom", fill="x", pady=(6, 0))
            tf.add(ttk.Button(tf, text="✎ 編修光譜（橡皮擦 / 手動背景）", style=f"{key}.Ghost.TButton",
                              command=self.open_raman_editor))
            tf.add(ttk.Button(tf, text="🏷 峰標註", style=f"{key}.Ghost.TButton", command=self.open_peak_labels))
        self.p_scroll = ScrollFrame(bottom)
        self.p_scroll.pack(fill="both", expand=True)
        self.p_host = self.p_scroll.body
        self.p_host.columnconfigure(0, weight=1)

        # ---- 右：圖
        self.right = FigurePanel(app.right_host, key, app.view, app.on_view_change)
        self.right.is_active = lambda: self.app.current is self    # 被蓋住的頁面：視窗大小改變時先不重新排版
        self.right.on_view_change_light = self.app.save_state_soon
        tools = self.right.tools
        tools.get_ov = lambda: self.st.setdefault("fig", {}).setdefault(self.current.name if self.current else "", {})
        tools.save = self.app.save_state_soon
        tools.status = self.app.status
        self.right.redraw_request = self.redraw
        tools.title_raw = lambda: self.title_effective(raw=True)[0]
        tools.title_ctx = self.title_context
        self.right.title_api = self
        self.post_draw = []                   # 畫完、套樣式之前的額外步驟（例如 Raman 的峰標註）
        if key == "Raman":
            self.post_draw.append(self._draw_peak_labels)
        self._wrap_job = None
        bottom.bind("<Configure>", lambda e: set_if_changed(self.p_help, wraplength=max(e.width - 10, 150)))
        if self.current:
            self._show_params(self.current)

    def write_to_sample(self):
        """把分析結果（Tc、低溫電阻）寫進樣品的結果欄位（製程 → 樣品）。"""
        sp = self.app.page("Samples")
        if sp.lib is None or sp.scanning:
            sp._scan_listeners.append(lambda: sp.open_results(self))
            self.app.status("讀取樣品清單中…完成後會打開「樣品結果」")
            return None
        return sp.open_results(self)

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
        self.right.sync_title()
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

    # ================================================================== 圖標題
    def _ov(self):
        return self.st.setdefault("fig", {}).setdefault(self.current.name if self.current else "", {})

    def title_effective(self, raw=False):
        """這張圖的標題 → (文字, 來自哪個範圍)。順序：這個功能 > 這台機台 > 所有圖；「-」= 這層設定成不顯示。"""
        from .fig_tools import TITLE_SCOPES
        for scope, v in zip(TITLE_SCOPES, (self._ov().get("suptitle", ""), self.st.get("fig_title", ""),
                                           self.app.view.get("fig_title", ""))):
            if v:
                return ((v if raw else ("" if v == "-" else v)), scope)
        return "", None

    def title_set(self, scope, text):
        """在 scope 設定標題；比它小的範圍（這個功能、這台機台）的設定會清掉，才看得到新的標題。"""
        from .fig_tools import TITLE_SCOPES
        ov = self._ov()
        i = TITLE_SCOPES.index(scope) if scope in TITLE_SCOPES else 0
        if i == 0:
            if text:
                ov["suptitle"] = text
            else:
                ov.pop("suptitle", None)
        else:
            ov.pop("suptitle", None)
            if i == 1:
                self.st["fig_title"] = text
            else:
                self.st.pop("fig_title", None)
                if self.app.view.get("fig_title", "") != text:
                    self.app.view["fig_title"] = text
                    self.app.on_view_change()
        self.app.save_state_soon()

    def title_remove(self, scope):
        """移除標題。回傳實際的範圍說明。"""
        from .fig_tools import TITLE_SCOPES
        ov = self._ov()
        i = TITLE_SCOPES.index(scope) if scope in TITLE_SCOPES else 0
        if i == 0:
            ov["suptitle"] = "-"                 # 這張圖不顯示（就算其他範圍有標題）
            msg = "只有這張圖"
        elif i == 1:
            ov.pop("suptitle", None)
            self.st["fig_title"] = "-"
            msg = f"{self.key} 的全部功能"
        else:
            ov.pop("suptitle", None)
            self.st.pop("fig_title", None)
            for p in self.app.pages.values():    # 所有機台、所有功能的標題都清掉
                p.st.pop("fig_title", None)
                for o in p.st.get("fig", {}).values():
                    o.pop("suptitle", None)
            self.app.view["fig_title"] = ""
            self.app.on_view_change()
            msg = "所有圖"
        self.app.save_state_soon()
        return msg

    def title_context(self):
        last = self.last
        ctx = {"機台": self.key, "功能": self.current.name if self.current else ""}
        if last and last.get("items"):
            items = last["items"]
            ctx["檔名"] = items[0].label if self.inst.source == "files" else \
                f"{len(items[0].data.df)} 筆紀錄"
        return ctx

    def figure_title(self):
        """存圖時的預設檔名用：展開後的標題（沒有就空白）。"""
        from .fig_tools import expand_title
        text, _ = self.title_effective()
        return expand_title(text, self.title_context()) if text else ""

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

    def on_show(self):
        """切換到這頁時：被蓋住期間累積的排版（例如視窗改過大小）現在補做。"""
        self.right.on_show()

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
                                          initialfile=f"{safe_name(self.figure_title() or self.current.name)}.{fmt}",
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
