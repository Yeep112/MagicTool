"""右欄：圖（固定大小或填滿視窗；放不下就捲動，不會被壓扁）＋ 工具列 ＋ 滑鼠讀值 ＋ 文字結果。"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

from . import theme as T
from .hover import Hover
from .widgets import Chip, Paned

SIZE_MODES = ["填滿視窗", "固定大小"]
FONT_SIZES = {"小": dict(xlabel=10, ylabel=10, cbar=10, ticks=9, legend=7, title=10, suptitle=13),
              "中": dict(xlabel=12, ylabel=12, cbar=12, ticks=10, legend=8, title=11, suptitle=15),
              "大": dict(xlabel=14, ylabel=14, cbar=14, ticks=12, legend=10, title=13, suptitle=18),
              "特大": dict(xlabel=18, ylabel=18, cbar=16, ticks=15, legend=13, title=16, suptitle=22)}
STYLE_FIELDS = [("xlabel", "X 標籤"), ("ylabel", "Y 標籤"), ("cbar", "色條"), ("ticks", "刻度"),
                ("legend", "圖例"), ("title", "標題")]
PANEL_MIN = (380, 300)            # 每個子圖的最小大小（100% 介面），不夠放就出現捲軸


class SmoothCanvas(FigureCanvasTkAgg):
    """拉動視窗、分隔線時，等停下來 0.15 秒才重畫圖（不會每移動一點就整張重畫而卡頓）。
    切換機台時頁面重新出現，大小沒變就不重畫。"""
    _resize_job = None
    _last_size = None
    _pending = None

    # ---- 排版只在需要時算：畫完一次後把子圖位置固定，之後縮放、平移重畫會快一倍
    _freeze_cid = None

    def relayout(self):
        """下一次重畫時重新計算排版（新圖、改大小、改字體時）。"""
        fig = self.figure
        try:
            fig.set_layout_engine("constrained")
        except Exception:
            return
        if self._freeze_cid is None:
            self._freeze_cid = self.mpl_connect("draw_event", self._freeze)

    def _freeze(self, event=None):
        if self._freeze_cid is not None:
            self.mpl_disconnect(self._freeze_cid)
            self._freeze_cid = None
        try:
            self.figure.set_layout_engine("none")
        except Exception:
            pass

    def resize_to(self, width, height):
        """我們自己排版時直接設定大小（只畫一次）；之後同樣大小的 Configure 事件會被略過。"""
        w = self.get_tk_widget()
        if self._resize_job is not None:
            try:
                w.after_cancel(self._resize_job)
            except Exception:
                pass
            self._resize_job = None
        self._pending = None
        if (width, height) == self._last_size:
            return False

        class _Event:
            pass
        ev = _Event()
        ev.width, ev.height = int(width), int(height)
        self._last_size = (ev.width, ev.height)
        self.relayout()
        try:
            FigureCanvasTkAgg.resize(self, ev)
        except Exception:
            return False
        return True

    def _on_map(self):
        ev = self._pending
        if ev is not None:
            self._pending = None
            self.resize(ev)

    def resize(self, event):
        w = self.get_tk_widget()
        if self._resize_job is not None:            # 新的大小取代還沒執行的那一次
            try:
                w.after_cancel(self._resize_job)
            except Exception:
                pass
            self._resize_job = None
        if (event.width, event.height) == self._last_size:
            return                                   # 暫時變了又變回來（換頁時常見）→ 不重畫
        self._resize_job = w.after(150, lambda e=event: self._do_resize(e))

    def _do_resize(self, event):
        self._resize_job = None
        w = self.get_tk_widget()
        try:
            if not w.winfo_viewable():               # 這頁已經被換掉了：等它再出現時才重畫
                if not getattr(self, "_map_bound", False):
                    w.bind("<Map>", lambda e: self._on_map(), add="+")
                    self._map_bound = True
                self._pending = event
                return
        except Exception:
            pass
        self._pending = None
        self._last_size = (event.width, event.height)
        self.relayout()
        try:
            FigureCanvasTkAgg.resize(self, event)
        except Exception:
            pass


class FitToolbar(NavigationToolbar2Tk):
    def __init__(self, canvas, window, on_home, **kw):
        self._on_home = on_home
        super().__init__(canvas, window, **kw)

    def home(self, *args):
        self._on_home()


class FigurePanel(tk.Frame):
    def __init__(self, parent, key, view, on_view_change):
        super().__init__(parent, bg=T.CARD)
        self.key = key
        self.view = view                      # 共用的圖設定 dict：size_mode、fig_w、fig_h、grid、font
        self.on_view_change = on_view_change
        a = T.accent(key)
        head = tk.Frame(self, bg=T.CARD)
        head.pack(fill="x")
        tt = tk.Frame(head, bg=T.CARD)
        tt.pack(side="left", fill="x", expand=True)
        self.title = tk.Label(tt, text="尚未繪圖", bg=T.CARD, fg=T.TEXT, font=T.font(13, "bold"), anchor="w")
        self.title.pack(fill="x")
        self.sub = tk.Label(tt, text="", bg=T.CARD, fg=T.MUTED, font=T.font(9), anchor="w")
        self.sub.pack(fill="x")
        self.hint = tk.Label(tt, text="", bg=T.CARD, fg=a["text"], font=T.font(9), anchor="w")
        self.hint.pack(fill="x")
        self.n_chip = Chip(head, "")
        self.n_chip.pack(side="right")

        self._build_style_bar()
        vp = Paned(self, orient="vertical", bg=T.CARD)
        vp.pack(fill="both", expand=True, pady=(4, 0))
        figf = tk.Frame(vp, bg=T.CARD)
        txtf = tk.Frame(vp, bg=T.CARD)
        vp.add_pane(figf, stretch=True, minsize=T.px(220))
        vp.add_pane(txtf, stretch=False, size=T.px(150), minsize=T.px(60))
        self.vpaned = vp

        self.fig = Figure(figsize=(6, 4), layout="constrained")
        host = tk.Frame(figf, bg=T.CARD)
        self.host = tk.Canvas(host, bg="white", highlightthickness=0, bd=0)
        self.vsb = ttk.Scrollbar(host, orient="vertical", command=self.host.yview)
        self.hsb = ttk.Scrollbar(host, orient="horizontal", command=self.host.xview)
        self.host.configure(xscrollcommand=self.hsb.set, yscrollcommand=self.vsb.set)
        self.host.grid(row=0, column=0, sticky="nsew")
        host.rowconfigure(0, weight=1)
        host.columnconfigure(0, weight=1)
        self.canvas = SmoothCanvas(self.fig, master=self.host)
        self.canvas.get_tk_widget().configure(width=320, height=240)
        self._win = self.host.create_window(0, 0, window=self.canvas.get_tk_widget(), anchor="nw")
        self.need = (0, 0)
        self._layout_job = None
        self.host.bind("<Configure>", lambda e: self.schedule_layout())
        w = self.canvas.get_tk_widget()
        w.bind("<MouseWheel>", self._wheel, add="+")
        w.bind("<Shift-MouseWheel>", lambda e: self._wheel(e, horizontal=True), add="+")
        w.bind("<Button-4>", lambda e: self._wheel(e, delta=120), add="+")
        w.bind("<Button-5>", lambda e: self._wheel(e, delta=-120), add="+")
        self.toolbar = FitToolbar(self.canvas, figf, self.fit_view, pack_toolbar=False)
        try:
            self.toolbar.configure(background=T.CARD)
            for c in self.toolbar.winfo_children():
                c.configure(background=T.CARD)
        except Exception:
            pass
        self.toolbar.update()
        self.toolbar.pack(side="top", fill="x")
        host.pack(side="top", fill="both", expand=True)
        self.hover = Hover(self.canvas)
        from .fig_tools import FigTools
        self.picking = False                  # 其他工具正在等使用者點圖（例如新增峰標註）時，不拖曳圖例
        self.tools = FigTools(self)
        self.redraw_request = self.restyle    # 頁面會換成「用上次的結果重畫」
        self._home = {}

        th = tk.Frame(txtf, bg=T.CARD)
        th.pack(fill="x", pady=(6, 2))
        tk.Label(th, text="≡ 文字結果", bg=T.CARD, fg=T.MUTED, font=T.font(9, "bold")).pack(side="left")
        ttk.Button(th, text="複製", style=f"{key}.Small.TButton", command=self.copy_text).pack(side="right")
        tf = tk.Frame(txtf, bg=T.CARD)
        tf.pack(fill="both", expand=True)
        self.text = tk.Text(tf, height=6, font=(T.MONO_FAMILY, 10), wrap="none", bg=T.TEXT_BG, fg=T.TEXT, bd=0,
                            highlightthickness=1, highlightbackground=T.BORDER, padx=8, pady=6)
        tsb = ttk.Scrollbar(tf, orient="vertical", command=self.text.yview)
        thsb = ttk.Scrollbar(tf, orient="horizontal", command=self.text.xview)
        self.text.configure(yscrollcommand=tsb.set, xscrollcommand=thsb.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        tsb.grid(row=0, column=1, sticky="ns")
        thsb.grid(row=1, column=0, sticky="ew")
        tf.rowconfigure(0, weight=1)
        tf.columnconfigure(0, weight=1)
        self.text.tag_configure("warn", foreground=T.WARNING)
        self.text.tag_configure("error", foreground=T.ERROR)
        self.message("還沒有選資料", "在中間選一個或多個檔案（可以按住 Ctrl / Shift 多選）")

    # ------------------------------------------------------------------ 樣式列
    def _build_style_bar(self):
        from .widgets import Flow
        bar = tk.Frame(self, bg=T.SUBTLE, highlightthickness=1, highlightbackground=T.BORDER)
        bar.pack(fill="x", pady=(8, 0))
        rows = []
        for _ in range(3):                    # 三列：圖標題 / 圖的大小 / 圖表樣式；窄視窗時每列自動換行
            r = Flow(bar, bg=T.SUBTLE)
            r.pack(fill="x")
            rows.append(r)
        r0, r1, r2 = rows

        def lab(parent, text, bold=False, padx=(0, 2)):
            tk.Label(parent, text=text, bg=T.SUBTLE, fg=T.MUTED, font=T.font(9, "bold" if bold else "normal")).pack(
                side="left", padx=padx)
        self._build_title_row(r0, lab)
        # 圖的大小
        g = r1.group()
        lab(g, "圖的大小", True, (2, 6))
        self.size_var = tk.StringVar(value=self.view.get("size_mode", SIZE_MODES[0]))
        ttk.Combobox(g, textvariable=self.size_var, values=SIZE_MODES, state="readonly", width=9).pack(side="left",
                                                                                                    pady=3)
        self.w_var = tk.StringVar(value=str(self.view.get("fig_w", 1100)))
        self.h_var = tk.StringVar(value=str(self.view.get("fig_h", 650)))
        g = r1.group()
        lab(g, "寬")
        ew = ttk.Entry(g, textvariable=self.w_var, width=6)
        ew.pack(side="left", pady=3)
        lab(g, "高", padx=(6, 2))
        eh = ttk.Entry(g, textvariable=self.h_var, width=6)
        eh.pack(side="left")
        tk.Label(g, text="px", bg=T.SUBTLE, fg=T.FAINT, font=T.font(9)).pack(side="left", padx=(2, 0))
        g = r1.group()
        lab(g, "字體一鍵設定")
        self.font_var = tk.StringVar(value=self.view.get("font", "中"))
        fc = ttk.Combobox(g, textvariable=self.font_var, values=list(FONT_SIZES), state="readonly", width=4)
        fc.pack(side="left", pady=3)
        fc.bind("<<ComboboxSelected>>", lambda e: self._preset())
        g = r1.group()
        ttk.Button(g, text="✎ 標題與軸標籤", style=f"{self.key}.Small.TButton", command=self.edit_labels).pack(
            side="left", pady=2)
        ttk.Button(g, text="↺ 圖例", style=f"{self.key}.Small.TButton", command=self.reset_legends).pack(
            side="left", padx=(4, 0), pady=2)
        # 圖表樣式（格線、各種字體大小）
        g = r2.group()
        lab(g, "圖表樣式", True, (2, 6))
        self.grid_var = tk.BooleanVar(value=bool(self.view.get("grid", True)))
        ttk.Checkbutton(g, text="格線", variable=self.grid_var, style=f"{self.key}.TCheckbutton").pack(side="left",
                                                                                                     pady=3)
        self.size_vars = {}
        base = FONT_SIZES["中"]
        for k, text in STYLE_FIELDS:
            g = r2.group()
            lab(g, text)
            var = tk.StringVar(value=str(self.view.get(k, base[k])))
            sp = ttk.Spinbox(g, from_=5, to=48, increment=1, textvariable=var, width=3, command=self._style_changed)
            sp.pack(side="left", pady=3)
            sp.bind("<Return>", lambda e: self._style_changed())
            sp.bind("<FocusOut>", lambda e: self._style_changed())
            self.size_vars[k] = var
        for v in (self.size_var, self.grid_var):
            v.trace_add("write", lambda *a: self._style_changed())
        for e in (ew, eh):
            e.bind("<Return>", lambda ev: self._style_changed())
            e.bind("<FocusOut>", lambda ev: self._style_changed())

    def _build_title_row(self, row, lab):
        """圖標題：新增 / 修改 / 移除；可以用 {日期}{機台}{功能}{檔名}；套用範圍：這個功能 / 這台機台 / 所有圖。"""
        from .fig_tools import PLACEHOLDERS, TITLE_SCOPES
        from .params_panel import Tooltip
        g = row.group()
        lab(g, "圖標題", True, (2, 6))
        self.title_var = tk.StringVar()
        self.title_entry = ttk.Entry(g, textvariable=self.title_var, width=22)
        self.title_entry.pack(side="left", pady=3)
        Tooltip(self.title_entry, "例如「{日期}的{機台}分析圖」→「20261126的Raman分析圖」。空白 = 沒有標題")
        menu = tk.Menu(g, tearoff=False)
        for ph, desc in PLACEHOLDERS:
            menu.add_command(label=f"{ph}　{desc}", command=lambda ph=ph: self._insert_placeholder(ph))
        menu.add_separator()
        for ex in ("{日期}的{機台}分析圖", "{日期} {功能}", "{檔名} — {功能}"):
            menu.add_command(label=f"範例：{ex}", command=lambda ex=ex: self.title_var.set(ex))
        b = ttk.Button(g, text="插入 ▾", width=6, style=f"{self.key}.Small.TButton")
        b.configure(command=lambda: menu.tk_popup(b.winfo_rootx(), b.winfo_rooty() + b.winfo_height()))
        b.pack(side="left", padx=(4, 0))
        g = row.group()
        lab(g, "範圍")
        self.title_scope = tk.StringVar(value=TITLE_SCOPES[0])
        sc = ttk.Combobox(g, textvariable=self.title_scope, values=TITLE_SCOPES, state="readonly", width=10)
        Tooltip(sc, "只有這張圖 = 這個分析功能；這台機台全部 = 這台機台的所有功能；所有圖 = 所有機台、所有功能")
        sc.pack(side="left", pady=3)
        sc.bind("<<ComboboxSelected>>", lambda e: self._title_changed(now=True))
        g = row.group()
        lab(g, "大小")
        var = tk.StringVar(value=str(self.view.get("suptitle", FONT_SIZES["中"]["suptitle"])))
        sp = ttk.Spinbox(g, from_=6, to=60, increment=1, textvariable=var, width=3, command=self._style_changed)
        sp.pack(side="left", pady=3)
        sp.bind("<Return>", lambda e: self._style_changed())
        sp.bind("<FocusOut>", lambda e: self._style_changed())
        self._title_size_var = var
        self.bold_var = tk.BooleanVar(value=bool(self.view.get("suptitle_bold", True)))
        ttk.Checkbutton(g, text="粗體", variable=self.bold_var, style=f"{self.key}.TCheckbutton",
                        command=self._style_changed).pack(side="left", padx=(6, 0))
        g = row.group()
        rm = ttk.Button(g, text="✕ 移除", width=6, style=f"{self.key}.Small.TButton", command=self.remove_title)
        rm.pack(side="left", pady=2)
        Tooltip(rm, "依「範圍」移除：只有這張圖、這台機台、或所有圖都不顯示標題")
        self._title_job = None
        self._title_loading = False
        self.title_api = None                 # 頁面設定（存在哪裡、目前是哪一層）
        self.title_var.trace_add("write", lambda *a: self._title_changed())

    def _insert_placeholder(self, ph):
        e = self.title_entry
        try:
            i = e.index("insert")
        except tk.TclError:
            i = "end"
        e.insert(i, ph)
        e.focus_set()

    def _title_changed(self, now=False):
        if self._title_loading or self.title_api is None:
            return
        if self._title_job is not None:
            try:
                self.after_cancel(self._title_job)
            except Exception:
                pass
            self._title_job = None
        if now:
            self._commit_title()
        else:
            self._title_job = self.after(450, self._commit_title)

    def _commit_title(self):
        self._title_job = None
        if self.title_api is None:
            return
        self.title_api.title_set(self.title_scope.get(), self.title_var.get().strip())
        self.restyle()

    def remove_title(self):
        if self.title_api is None:
            return
        scope = self.title_api.title_remove(self.title_scope.get())
        self.sync_title()
        self.restyle()
        self.tools.status(f"已移除標題（{scope}）；要加回來，直接在「圖標題」輸入", "ok")

    def sync_title(self):
        """換功能、畫完圖時：輸入框顯示這張圖目前的標題，以及它是哪個範圍設定的。"""
        if self.title_api is None or (self.focus_get() is self.title_entry and self._title_job is not None):
            return
        text, scope = self.title_api.title_effective()
        self._title_loading = True
        try:
            if self.title_var.get() != text:
                self.title_var.set(text)
            if scope:
                self.title_scope.set(scope)
        finally:
            self._title_loading = False

    def _preset(self):
        """「一鍵」小 / 中 / 大 / 特大：一次設定所有字體大小。"""
        pre = FONT_SIZES.get(self.font_var.get(), FONT_SIZES["中"])
        self._syncing = True
        try:
            for k, var in self.size_vars.items():
                var.set(str(pre[k]))
            self._title_size_var.set(str(pre["suptitle"]))
        finally:
            self._syncing = False
        self._style_changed()

    def _style_changed(self):
        if getattr(self, "_syncing", False):
            return
        try:
            w = max(300, min(6000, int(float(self.w_var.get()))))
            h = max(200, min(6000, int(float(self.h_var.get()))))
        except ValueError:
            w, h = self.view.get("fig_w", 1100), self.view.get("fig_h", 650)
        sizes = {}
        for k, var in list(self.size_vars.items()) + [("suptitle", self._title_size_var)]:
            try:
                sizes[k] = max(4.0, min(60.0, float(var.get())))
            except ValueError:
                sizes[k] = self.view.get(k, FONT_SIZES["中"][k])
        sizes["suptitle_bold"] = bool(self.bold_var.get())
        new = dict(size_mode=self.size_var.get(), fig_w=w, fig_h=h, grid=bool(self.grid_var.get()),
                   font=self.font_var.get(), **sizes)
        if all(self.view.get(k) == v for k, v in new.items()):
            return
        self.view.update(new)
        self.on_view_change()

    def sync_view(self):
        """另一台機台改了圖的設定 → 這頁跟著更新（不觸發重畫）。"""
        self._syncing = True
        try:
            self.w_var.set(str(self.view.get("fig_w", 1100)))
            self.h_var.set(str(self.view.get("fig_h", 650)))
            for var, key in ((self.size_var, "size_mode"), (self.font_var, "font")):
                if var.get() != self.view.get(key):
                    var.set(self.view.get(key))
            if bool(self.grid_var.get()) != bool(self.view.get("grid", True)):
                self.grid_var.set(bool(self.view.get("grid", True)))
            for k, var in list(self.size_vars.items()) + [("suptitle", self._title_size_var)]:
                v = self.view.get(k, FONT_SIZES["中"][k])
                txt = f"{v:g}" if isinstance(v, (int, float)) else str(v)
                if var.get() != txt:
                    var.set(txt)
            if bool(self.bold_var.get()) != bool(self.view.get("suptitle_bold", True)):
                self.bold_var.set(bool(self.view.get("suptitle_bold", True)))
            self.sync_title()
        finally:
            self._syncing = False

    def style_dict(self):
        base = FONT_SIZES.get(self.view.get("font", "中"), FONT_SIZES["中"])
        return {**base, **{k: self.view[k] for k in base if k in self.view}, "grid": self.view.get("grid", True),
                "suptitle_bold": self.view.get("suptitle_bold", True)}

    def edit_labels(self):
        self.tools.edit_labels(self.winfo_toplevel(), self.key, self.restyle)

    def reset_legends(self):
        n = self.tools.hidden_count()
        self.tools.reset()
        self.tools.status("圖例回到原位" + (f"、{n} 條隱藏的資料重新顯示" if n else "") + "（文字標註也回到原位）", "ok")
        self.redraw_request()

    # ------------------------------------------------------------------ 版面
    def fixed(self):
        return self.view.get("size_mode") == SIZE_MODES[1]

    def compute_need(self):
        if self.fixed():
            self.need = (T.px(self.view.get("fig_w", 1100)), T.px(self.view.get("fig_h", 650)))
            return
        rows = cols = 1
        for ax in self.fig.axes:
            ss = ax.get_subplotspec()
            if ss is None:
                continue
            gs = ss.get_topmost_subplotspec().get_gridspec()
            rows, cols = max(rows, gs.nrows), max(cols, gs.ncols)
        self.need = (cols * T.px(PANEL_MIN[0]), rows * T.px(PANEL_MIN[1]))

    def schedule_layout(self):
        if self._layout_job is not None:
            try:
                self.after_cancel(self._layout_job)
            except Exception:
                pass
        self._layout_job = self.after(80, self.layout)

    is_active = staticmethod(lambda: True)       # 頁面設定：這頁是不是目前顯示的那一頁
    _layout_dirty = False

    def on_show(self):
        if self._layout_dirty:
            self._layout_dirty = False
            self.schedule_layout()

    def layout(self):
        self._layout_job = None
        if not self.is_active():
            self._layout_dirty = True                # 被蓋住：等切換回來再排版、重畫（不浪費時間畫看不到的圖）
            return
        try:
            aw, ah = int(self.host.winfo_width()), int(self.host.winfo_height())
        except (tk.TclError, ValueError):
            return
        if aw < 20 or ah < 20:
            return
        nw, nh = self.need
        if self.fixed():
            W, H = nw, nh                 # 固定大小：不拉伸、不壓縮，放不下就捲動
        else:
            W, H = max(aw, nw), max(ah, nh)
        self.host.itemconfigure(self._win, width=W, height=H)
        self.host.configure(scrollregion=(0, 0, W, H))
        self.canvas.resize_to(W, H)
        for sb, need, kw in ((self.hsb, W > aw, dict(row=1, column=0, sticky="ew")),
                             (self.vsb, H > ah, dict(row=0, column=1, sticky="ns"))):
            if need:
                sb.grid(**kw)
            else:
                sb.grid_remove()
        if W <= aw:
            self.host.xview_moveto(0)
        if H <= ah:
            self.host.yview_moveto(0)

    def _wheel(self, event, horizontal=False, delta=None):
        d = delta if delta is not None else getattr(event, "delta", 0)
        step = -1 if d > 0 else 1
        nw, nh = self.need
        aw, ah = int(self.host.winfo_width() or 0), int(self.host.winfo_height() or 0)
        if horizontal or (nh <= ah and nw > aw):
            if nw > aw:
                self.host.xview_scroll(step * 3, "units")
        elif nh > ah:
            self.host.yview_scroll(step * 3, "units")

    def fit_view(self):
        """工具列的 Home：回到剛畫好時的範圍。"""
        for ax, (xl, yl) in getattr(self, "_home", {}).items():
            if ax in self.fig.axes:
                ax.set_xlim(xl)
                ax.set_ylim(yl)
        self.canvas.draw_idle()

    # ------------------------------------------------------------------ 畫圖
    def begin(self):
        """重畫前：清空圖。"""
        self.fig.clear()
        self.hover.reset()
        self.canvas.relayout()

    def finish(self):
        """畫完後：套樣式、排版、重畫（draw_idle：合併成一次，不會卡住）。"""
        from ..core.plotstyle import apply_style
        apply_style(self.fig, self.style_dict())
        try:
            self.tools.apply()
        except Exception:
            pass
        self.sync_title()
        self.canvas.relayout()
        self._home = {ax: (ax.get_xlim(), ax.get_ylim()) for ax in self.fig.axes}
        self.compute_need()
        self.layout()
        self.canvas.draw_idle()
        try:
            self.toolbar.update()
        except Exception:
            pass

    def restyle(self):
        """只改了樣式（字體、格線、大小）：不重新計算。"""
        if self.fig.axes:
            self.finish()
        else:
            self.compute_need()
            self.layout()

    def message(self, title, detail="", kind="info"):
        self.begin()
        color = {"info": T.MUTED, "warn": T.WARNING, "error": T.ERROR}.get(kind, T.MUTED)
        self.fig.text(0.5, 0.56, title, ha="center", va="center", fontsize=15, color=T.TEXT, weight="bold")
        if detail:
            self.fig.text(0.5, 0.44, detail, ha="center", va="center", fontsize=10.5, color=color, wrap=True)
        self.need = (0, 0)
        self.layout()
        self.canvas.draw_idle()

    def set_header(self, title, sub="", hint="", n=""):
        self.title.configure(text=title)
        self.sub.configure(text=sub)
        self.hint.configure(text=hint)
        if hint:
            self.hint.pack(fill="x")
        else:
            self.hint.pack_forget()
        self.n_chip.set(n)

    def set_text(self, text, warnings=(), error=None):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        if error:
            self.text.insert("end", error + "\n", "error")
        for w in warnings or []:
            self.text.insert("end", "⚠ " + w + "\n", "warn")
        if warnings:
            self.text.insert("end", "\n")
        self.text.insert("end", text or "")

    def copy_text(self):
        self.clipboard_clear()
        self.clipboard_append(self.text.get("1.0", "end"))
