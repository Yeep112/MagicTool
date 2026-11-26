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
FONT_SIZES = {"小": dict(xlabel=10, ylabel=10, ticks=9, legend=7, title=10),
              "中": dict(xlabel=12, ylabel=12, ticks=10, legend=8, title=11),
              "大": dict(xlabel=14, ylabel=14, ticks=12, legend=10, title=13)}
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
        bar = tk.Frame(self, bg=T.SUBTLE, highlightthickness=1, highlightbackground=T.BORDER)
        bar.pack(fill="x", pady=(8, 0))
        tk.Label(bar, text="圖", bg=T.SUBTLE, fg=T.MUTED, font=T.font(9, "bold")).pack(side="left", padx=(8, 6))
        self.size_var = tk.StringVar(value=self.view.get("size_mode", SIZE_MODES[0]))
        cb = ttk.Combobox(bar, textvariable=self.size_var, values=SIZE_MODES, state="readonly", width=9)
        cb.pack(side="left", pady=4)
        self.w_var = tk.StringVar(value=str(self.view.get("fig_w", 1100)))
        self.h_var = tk.StringVar(value=str(self.view.get("fig_h", 650)))
        tk.Label(bar, text="寬", bg=T.SUBTLE, fg=T.MUTED, font=T.font(9)).pack(side="left", padx=(8, 2))
        ew = ttk.Entry(bar, textvariable=self.w_var, width=6)
        ew.pack(side="left")
        tk.Label(bar, text="高", bg=T.SUBTLE, fg=T.MUTED, font=T.font(9)).pack(side="left", padx=(6, 2))
        eh = ttk.Entry(bar, textvariable=self.h_var, width=6)
        eh.pack(side="left")
        tk.Label(bar, text="px", bg=T.SUBTLE, fg=T.FAINT, font=T.font(9)).pack(side="left", padx=(2, 10))
        self.grid_var = tk.BooleanVar(value=bool(self.view.get("grid", True)))
        ttk.Checkbutton(bar, text="格線", variable=self.grid_var, style=f"{self.key}.TCheckbutton").pack(side="left")
        tk.Label(bar, text="字體", bg=T.SUBTLE, fg=T.MUTED, font=T.font(9)).pack(side="left", padx=(10, 2))
        self.font_var = tk.StringVar(value=self.view.get("font", "中"))
        fc = ttk.Combobox(bar, textvariable=self.font_var, values=list(FONT_SIZES), state="readonly", width=3)
        fc.pack(side="left", padx=(0, 8))
        for v in (self.size_var, self.grid_var, self.font_var):
            v.trace_add("write", lambda *a: self._style_changed())
        for e in (ew, eh):
            e.bind("<Return>", lambda ev: self._style_changed())
            e.bind("<FocusOut>", lambda ev: self._style_changed())

    def _style_changed(self):
        if getattr(self, "_syncing", False):
            return
        try:
            w = max(300, min(6000, int(float(self.w_var.get()))))
            h = max(200, min(6000, int(float(self.h_var.get()))))
        except ValueError:
            w, h = self.view.get("fig_w", 1100), self.view.get("fig_h", 650)
        self.view.update(size_mode=self.size_var.get(), fig_w=w, fig_h=h, grid=bool(self.grid_var.get()),
                         font=self.font_var.get())
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
        finally:
            self._syncing = False

    def style_dict(self):
        return {**FONT_SIZES.get(self.view.get("font", "中"), FONT_SIZES["中"]), "grid": self.view.get("grid", True)}

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

    def layout(self):
        self._layout_job = None
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
