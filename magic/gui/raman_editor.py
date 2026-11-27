"""✎ 編修光譜：橡皮擦（框選擦掉雜訊點，例如宇宙射線的尖峰）與手動背景（點選錨點）。

‧ 只改「顯示與分析用的資料」，原始檔完全不動；編修存在 %LOCALAPPDATA%\\MagicTool\\raman_edits.json
‧ 每一步都可以復原（Ctrl+Z）／重做（Ctrl+Y），也可以一鍵清除這個檔案的所有編修
‧ 上圖：原始光譜（被擦掉的點畫成灰色 ×）、錨點（橘色方塊）、手動背景（橘色虛線）
  下圖：扣掉手動背景後的光譜（還沒有錨點時顯示原始光譜）

滑鼠：
  ⌫ 橡皮擦（點 / 塗抹）：左鍵點一下 = 擦掉滑鼠附近的點；按住左鍵拖曳 = 沿路擦掉；右鍵 = 恢復（筆刷大小可以調）
  ⬚ 橡皮擦（框選）：拖曳畫框 → 框裡的點被擦掉（上下兩張圖都可以框）；只點一下也會擦掉滑鼠附近的點
  ↺ 還原筆：拖曳畫框 → 框裡被擦掉的點恢復；只點一下 = 恢復滑鼠附近的點
  🔍 找尖峰：自動找出宇宙射線（1～3 個點寬、突然衝高的尖峰），用紅圈標出來，確認後一鍵擦掉
  ✚ 背景錨點：左鍵點一下新增、拖曳移動；右鍵刪除最近的錨點
  🔍 縮放 / 平移：用工具列（這時滑鼠不會改到資料）
"""
from __future__ import annotations

import copy
import os
import tkinter as tk
from tkinter import ttk

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
from matplotlib.patches import Circle
from matplotlib.transforms import IdentityTransform
from matplotlib.widgets import RectangleSelector

from ..raman import edits as E
from ..raman.spikes import find_spikes
from ..readers import load
from ..readers.raman_txt import xy
from . import theme as T
from .widgets import Paned, WrapRow, fit_label, keep_figure_fit

MODES = [("view", "🔍 縮放 / 平移"), ("brush", "⌫ 橡皮擦（點 / 塗抹）"), ("erase", "⬚ 橡皮擦（框選）"),
         ("restore", "↺ 還原筆（框選）"), ("anchor", "✚ 背景錨點")]
HINTS = {
    "view": "用下面的工具列放大（放大鏡）或平移（十字），看清楚要擦的雜訊；Home 回到全部範圍",
    "brush": "左鍵點一下：擦掉滑鼠附近的點；按住左鍵拖曳：沿路擦掉；右鍵（點或拖曳）：恢復。一筆 = 一步，Ctrl+Z 復原",
    "erase": "拖曳畫一個框：框裡的點會被擦掉；只點一下 = 擦掉滑鼠附近的點（只影響顯示與分析，原始檔不變）。Ctrl+Z 復原",
    "restore": "拖曳畫一個框：框裡被擦掉的點會恢復；只點一下 = 恢復滑鼠附近的點",
    "anchor": "左鍵點背景的位置新增錨點（勾「貼齊光譜」會自動對到那裡的光譜高度）；拖曳移動；右鍵刪除",
}


class RamanEditor(tk.Toplevel):
    def __init__(self, page, paths, start=None):
        super().__init__(page.app.root)
        self.page = page
        self.app = page.app
        self.key = page.key
        self.store = self.app.raman_edits
        self.paths = list(dict.fromkeys(paths))
        self.title("編修光譜（橡皮擦 / 手動背景）")
        self.configure(bg=T.CARD)
        self.transient(page.app.root)
        try:
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        except Exception:
            sw, sh = 1600, 1000
        self.geometry(f"{min(T.px(1320), sw - 60)}x{min(T.px(860), sh - 80)}")
        self.minsize(min(T.px_min(900), sw - 60), min(T.px_min(600), sh - 100))   # 介面縮放（125%、150%）時跟著放大
        self.undo_stack, self.redo_stack = [], []
        self.path = None
        self.x = self.y = None
        self.ed = E.empty()
        self.drag = None
        self.stroke = None                    # 筆刷正在畫的那一筆（放開滑鼠才算一步）
        self._click = None                    # 框選模式：按下的位置（沒有拖曳 = 點一下）
        self.spikes = None                    # 🔍 找到、還沒擦掉的尖峰（True = 尖峰的點）
        self._bg = None                       # 筆刷圓圈用：沒有圓圈時的畫面（blit 才不用整張重畫）
        self.changed = False
        a = T.accent(self.key)
        head = tk.Frame(self, bg=a["main"], padx=16, pady=8)
        head.pack(fill="x")
        tk.Label(head, text="✎ 編修光譜", bg=a["main"], fg="white", font=T.font(13, "bold")).pack(side="left")
        sub = tk.Label(head, text="　擦掉雜訊點、手動定義背景；只影響顯示與分析，原始檔不會被修改，隨時可以復原",
                       bg=a["main"], fg=T.mix_color("#ffffff", a["main"], 0.25), font=T.font(9), justify="left")
        sub.pack(side="left", fill="x", expand=True)
        fit_label(sub)

        bottom = tk.Frame(self, bg=T.SUBTLE, highlightthickness=1, highlightbackground=T.BORDER)
        bottom.pack(side="bottom", fill="x")
        self.hint = tk.Label(bottom, text="", bg=T.SUBTLE, fg=T.MUTED, font=T.font(9), anchor="w", justify="left")
        self.hint.pack(side="left", fill="x", expand=True, padx=10, pady=8)
        ttk.Button(bottom, text="完成", style=f"{self.key}.Accent.TButton", command=self.close).pack(
            side="right", padx=10, pady=6)

        body = Paned(self, orient="horizontal", bg=T.CARD)
        body.pack(fill="both", expand=True, padx=10, pady=8)
        left = tk.Frame(body, bg=T.CARD)
        right = tk.Frame(body, bg=T.CARD)
        body.add_pane(left, stretch=False, size=T.px(300), minsize=T.px(180))
        body.add_pane(right, stretch=True, minsize=T.px(500))
        self._build_list(left)
        self._build_tools(right)
        self._build_figure(right)
        self.set_mode("brush")
        self.protocol("WM_DELETE_WINDOW", self.close)
        for seq, fn in (("<Control-z>", self.undo), ("<Control-Z>", self.undo), ("<Control-y>", self.redo),
                        ("<Control-Y>", self.redo), ("<Command-z>", self.undo), ("<Command-Z>", self.redo),
                        ("<Command-y>", self.redo), ("<Escape>", lambda: self.set_mode("view")),
                        ("e", lambda: self.set_mode("brush")), ("b", lambda: self.set_mode("erase")),
                        ("a", lambda: self.set_mode("anchor")),
                        ("r", lambda: self.set_mode("restore"))):
            self.bind(seq, lambda ev, f=fn: f())
        start = start if start in self.paths else (self.paths[0] if self.paths else None)
        if start:
            self.open_file(start)

    # ================================================================== 版面
    def _build_list(self, parent):
        tk.Label(parent, text="檔案", bg=T.CARD, fg=T.TEXT, font=T.font(11, "bold"), anchor="w").pack(fill="x")
        tk.Label(parent, text="✎ = 有編修（擦掉的點 / 錨點）", bg=T.CARD, fg=T.MUTED, font=T.font(8),
                 anchor="w").pack(fill="x")
        f = tk.Frame(parent, bg=T.CARD)
        f.pack(fill="both", expand=True, pady=(4, 0))
        self.tree = ttk.Treeview(f, columns=("name", "ed"), show="headings", selectmode="browse")
        self.tree.heading("name", text="檔名")
        self.tree.heading("ed", text="編修")
        self.tree.column("name", width=T.px(150), stretch=True)
        self.tree.column("ed", width=T.px(100), stretch=False, anchor="center")
        sb = ttk.Scrollbar(f, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        for p in self.paths:
            self.tree.insert("", "end", iid=p, values=(os.path.basename(p), ""))
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._on_pick())
        self._refresh_list()

    def _refresh_list(self):
        for p in self.paths:
            ne, na = self.store.count(p)
            txt = "" if not (ne or na) else "✎ " + "、".join(x for x in (f"擦 {ne}" if ne else "",
                                                                        f"錨 {na}" if na else "") if x)
            try:
                self.tree.set(p, "ed", txt)
            except tk.TclError:
                pass

    def _build_tools(self, parent):
        bar = tk.Frame(parent, bg=T.SUBTLE, highlightthickness=1, highlightbackground=T.BORDER)
        bar.pack(fill="x")
        S = T.SUBTLE

        def group(row, *parts):
            """幾個元件綁成一組（換行時不會被拆開，例如「筆刷大小 [10] px」）。"""
            f = tk.Frame(row, bg=S)
            for build in parts:
                build(f).pack(side="left")
            return f

        def lab(text, size=9, fg=None, bold=False):
            return lambda f: tk.Label(f, text=text, bg=S, fg=fg or T.MUTED, font=T.font(size, "bold") if bold else T.font(size))

        # ---- 工具
        r1 = WrapRow(bar, bg=S, padx=6)
        r1.pack(fill="x", padx=8, pady=(4, 2))
        self.mode_var = tk.StringVar(value="brush")
        r1.add(lab("工具", bold=True)(r1), padx=0)
        for k, text in MODES:
            r1.add(ttk.Radiobutton(r1, text=text, value=k, variable=self.mode_var, style=f"{self.key}.TRadiobutton",
                                   command=lambda k=k: self.set_mode(k)))
        self.brush_var = tk.StringVar(value="10")
        r1.add(group(r1, lab("筆刷大小"),
                     lambda f: ttk.Spinbox(f, from_=2, to=60, increment=2, textvariable=self.brush_var, width=3),
                     lab(" px")), padx=10)
        self.undo_btn = ttk.Button(r1, text="↶ 復原", style=f"{self.key}.Small.TButton", command=self.undo)
        self.redo_btn = ttk.Button(r1, text="↷ 重做", style=f"{self.key}.Small.TButton", command=self.redo)
        r1.add(self.undo_btn, side="right", padx=4)
        r1.add(self.redo_btn, side="right", padx=4)

        # ---- 背景
        r2 = WrapRow(bar, bg=S, padx=6)
        r2.pack(fill="x", padx=8, pady=2)
        r2.add(lab("背景", bold=True)(r2), padx=0)
        self.interp_var = tk.StringVar(value=E.INTERPS[0])
        holder = {}

        def combo(f):
            cb = ttk.Combobox(f, textvariable=self.interp_var, values=E.INTERPS, state="readonly", width=5)
            cb.bind("<<ComboboxSelected>>", lambda e: self._set_interp())
            holder["cb"] = cb
            return cb
        r2.add(group(r2, lab("錨點之間 "), combo))
        self.snap_var = tk.BooleanVar(value=True)
        r2.add(ttk.Checkbutton(r2, text="貼齊光譜", variable=self.snap_var, style=f"{self.key}.TCheckbutton"))
        self.n_auto = tk.StringVar(value="8")
        r2.add(group(r2, lab("自動放 "),
                     lambda f: ttk.Spinbox(f, from_=2, to=40, textvariable=self.n_auto, width=3),
                     lambda f: ttk.Button(f, text="個錨點（沿 ALS 背景）", style=f"{self.key}.Small.TButton",
                                          command=self.auto_anchors)), padx=10)
        r2.add(ttk.Button(r2, text="還原所有擦掉的點", style=f"{self.key}.Small.TButton",
                          command=lambda: self.clear("erase")), side="right", padx=4)
        r2.add(ttk.Button(r2, text="清除錨點", style=f"{self.key}.Small.TButton",
                          command=lambda: self.clear("anchors")), side="right", padx=4)

        # ---- 尖峰
        r3 = WrapRow(bar, bg=S, padx=6)
        r3.pack(fill="x", padx=8, pady=(2, 4))
        self.spike_row = r3
        r3.add(lab("尖峰", bold=True)(r3), padx=0)
        r3.add(ttk.Button(r3, text="🔍 找尖峰（宇宙射線）", style=f"{self.key}.Small.TButton", command=self.find_spikes))
        self.spike_k = tk.StringVar(value="6")
        self.spike_w = tk.StringVar(value="3")
        r3.add(group(r3, lab("靈敏度 "),
                     lambda f: ttk.Spinbox(f, from_=3, to=15, increment=0.5, textvariable=self.spike_k, width=4),
                     lab("（越小越敏感）", 8, T.FAINT)), padx=10)
        r3.add(group(r3, lab("最多 ", 8, T.FAINT),
                     lambda f: ttk.Spinbox(f, from_=1, to=5, textvariable=self.spike_w, width=2),
                     lab(" 個點寬", 8, T.FAINT)))
        self.spike_lab = tk.Label(r3, text="", bg=S, fg=T.TEXT, font=T.font(9))
        self.spike_erase = ttk.Button(r3, text="", style=f"{self.key}.Accent.TButton", command=self.erase_spikes)
        self.spike_cancel = ttk.Button(r3, text="取消", style=f"{self.key}.Small.TButton", command=self.cancel_spikes)
        for w in (self.spike_lab, self.spike_erase, self.spike_cancel):
            r3.add(w, padx=8)
            r3.set_visible(w, False)

    def _build_figure(self, parent):
        holder = tk.Frame(parent, bg=T.CARD)
        holder.pack(fill="both", expand=True, pady=(6, 0))
        self.fig = Figure(figsize=(8, 6), layout="constrained")
        self.ax1 = self.fig.add_subplot(2, 1, 1)
        self.ax2 = self.fig.add_subplot(2, 1, 2, sharex=self.ax1)
        self.canvas = FigureCanvasTkAgg(self.fig, master=holder)
        self.toolbar = NavigationToolbar2Tk(self.canvas, holder, pack_toolbar=False)
        self.toolbar.update()
        self.toolbar.pack(side="bottom", fill="x")
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        props = dict(facecolor="#ef4444", edgecolor="#b91c1c", alpha=0.18, fill=True)
        self.selectors = [RectangleSelector(ax, lambda e1, e2, ax=ax: self._boxed(ax, e1, e2), useblit=True,
                                            button=[1], minspanx=2, minspany=2, spancoords="pixels",
                                            interactive=False, props=props) for ax in (self.ax1, self.ax2)]
        self.canvas.mpl_connect("button_press_event", self._press)
        self.canvas.mpl_connect("motion_notify_event", self._motion)
        self.canvas.mpl_connect("button_release_event", self._release)
        self._fit = keep_figure_fit(self.canvas)          # 螢幕縮放時圖不會比視窗大（跑版）
        # 筆刷範圍：跟著滑鼠走的半透明圓圈（animated + blit：移動滑鼠不用整張圖重畫）
        self.brush_circle = Circle((0, 0), 10, transform=IdentityTransform(), facecolor="#ef4444",
                                   edgecolor="#b91c1c", alpha=0.22, lw=1.2, animated=True, visible=False)
        self.fig.add_artist(self.brush_circle)
        self.canvas.mpl_connect("draw_event", self._on_draw)
        self.canvas.mpl_connect("figure_leave_event", lambda e: self._hide_circle())

    # ================================================================== 模式
    def set_mode(self, mode):
        self.mode_var.set(mode)
        boxing = mode in ("erase", "restore")
        if mode != "view" and str(getattr(self.toolbar, "mode", "")):
            # 關掉工具列的縮放 / 平移，滑鼠才會用來編修
            if "zoom" in str(self.toolbar.mode).lower():
                self.toolbar.zoom()
            else:
                self.toolbar.pan()
        for s in self.selectors:
            s.set_active(boxing)
        col = "#16a34a" if mode == "restore" else "#ef4444"
        for s in self.selectors:
            try:
                s._selection_artist.set_facecolor(col)
                s._selection_artist.set_edgecolor(col)
            except Exception:
                pass
        self.hint.configure(text=HINTS[mode])
        if mode != "brush":
            self._hide_circle()
        cursor = {"brush": "crosshair", "erase": "crosshair", "restore": "crosshair", "anchor": "tcross"}.get(mode, "")
        try:
            self.canvas.get_tk_widget().configure(cursor=cursor)
        except tk.TclError:
            pass

    # ================================================================== 檔案
    def _on_pick(self):
        sel = self.tree.selection()
        if sel and sel[0] != self.path:
            self.open_file(sel[0])

    def open_file(self, path):
        try:
            ds = load(path)
        except Exception as e:
            self.hint.configure(text=f"讀不到 {os.path.basename(path)}：{e}", fg=T.ERROR)
            return
        self.path = path
        self.spikes = None
        self._spike_ui(0)
        self.x, self.y = xy(ds)
        self.sig = E.signature(self.x)
        ed = self.store.get(path)
        if ed.get("sig") and ed["sig"] != self.sig:
            self.hint.configure(text="⚠ 檔案內容和上次編修時不同，舊的編修已清除", fg=T.WARNING)
            ed = E.empty()
        self.ed = ed
        self.interp_var.set(ed.get("interp", E.INTERPS[0]))
        if self.tree.selection() != (path,):
            self.tree.selection_set(path)
            self.tree.see(path)
        self._home = None
        self.redraw(reset_view=True)

    # ================================================================== 編修（每一步都可以復原）
    def _commit(self, new_ed, what=""):
        self.undo_stack.append((self.path, copy.deepcopy(self.ed)))
        self.redo_stack.clear()
        self.ed = new_ed
        self._save()
        if what:
            self.hint.configure(text=what, fg=T.MUTED)

    def _save(self):
        self.ed["interp"] = self.interp_var.get()
        self.store.set(self.path, self.ed, self.sig)
        self.changed = True
        self._refresh_list()
        self.redraw()
        self._update_buttons()
        self.page.schedule_plot(600)         # 主畫面跟著更新（不用關掉這個視窗）

    def _update_buttons(self):
        self.undo_btn.state(["!disabled"] if self.undo_stack else ["disabled"])
        self.redo_btn.state(["!disabled"] if self.redo_stack else ["disabled"])

    def undo(self):
        if not self.undo_stack:
            return
        path, ed = self.undo_stack.pop()
        if path != self.path:
            self.open_file(path)
        self.redo_stack.append((path, copy.deepcopy(self.ed)))
        self.ed = ed
        self.interp_var.set(ed.get("interp", E.INTERPS[0]))
        self._save()
        self.hint.configure(text="已復原上一步（Ctrl+Y 重做）", fg=T.MUTED)

    def redo(self):
        if not self.redo_stack:
            return
        path, ed = self.redo_stack.pop()
        if path != self.path:
            self.open_file(path)
        self.undo_stack.append((path, copy.deepcopy(self.ed)))
        self.ed = ed
        self._save()
        self.hint.configure(text="已重做", fg=T.MUTED)

    def clear(self, what):
        if self.path is None or not self.ed.get(what):
            return
        new = copy.deepcopy(self.ed)
        n = len(new[what])
        new[what] = []
        self._commit(new, f"已清除 {n} 個{'擦掉的點' if what == 'erase' else '錨點'}（Ctrl+Z 可以復原）")

    def _set_interp(self):
        if self.path is None:
            return
        new = copy.deepcopy(self.ed)
        new["interp"] = self.interp_var.get()
        self._commit(new)

    def erase_box(self, x0, x1, y0, y1, values, restore=False):
        """values = 這張圖上每個點的 y（上圖是原始、下圖是扣背景後）。"""
        lo, hi = sorted((x0, x1))
        blo, bhi = sorted((y0, y1))
        inside = (self.x >= lo) & (self.x <= hi) & (values >= blo) & (values <= bhi)
        return self.apply_hits(inside, restore)

    def apply_hits(self, inside, restore=False, commit=True):
        """inside = 要擦掉（或恢復）的點。commit=False：只改目前顯示（筆刷拖曳中），放開滑鼠才記成一步。"""
        erased = E.erased_mask(self.x, self.ed.get("erase"))
        new = copy.deepcopy(self.ed)
        if restore:
            hit = inside & erased
            if not hit.any():
                return 0
            keep = set(np.round(self.x[hit], E.ND).tolist())
            new["erase"] = [v for v in new["erase"] if round(v, E.ND) not in keep]
            if not commit:
                self.ed = new
                return int(hit.sum())
            self._commit(new, f"恢復 {int(hit.sum())} 個點（Ctrl+Z 可以復原）")
        else:
            hit = inside & ~erased
            if not hit.any():
                return 0
            if (~(erased | hit)).sum() < 5:
                self.hint.configure(text="至少要留 5 個點", fg=T.WARNING)
                return 0
            new["erase"] = sorted(set(new["erase"]) | set(np.round(self.x[hit], E.ND).tolist()))
            if not commit:
                self.ed = new
                return int(hit.sum())
            self._commit(new, f"擦掉 {int(hit.sum())} 個點（只影響顯示與分析；Ctrl+Z 可以復原）")
        return int(hit.sum())

    # ---- 筆刷：滑鼠附近（半徑 = 筆刷大小，螢幕像素）的點
    def brush_px(self):
        try:
            return max(2.0, min(60.0, float(self.brush_var.get())))
        except (ValueError, AttributeError):
            return 10.0

    def brush_r(self):
        """筆刷半徑（畫布上的實際像素）：螢幕縮放 150% 時，10 px 的筆刷在畫布上是 15 個實際像素。"""
        return self.brush_px() * float(getattr(self.canvas, "device_pixel_ratio", 1) or 1)

    def near_mask(self, ax, px, py, r=None):
        """這張圖上，離螢幕位置 (px, py) 在 r 像素以內的點（上圖用原始值、下圖用扣背景後的值）。"""
        r = self.brush_r() if r is None else r
        values = self.y if ax is self.ax1 else self.y - self._bg_full()
        pts = ax.transData.transform(np.column_stack([self.x, values]))
        return np.hypot(pts[:, 0] - px, pts[:, 1] - py) <= r

    def _brush_at(self, event):
        st = self.stroke
        mask = self.near_mask(st["ax"], event.x, event.y)
        if st.get("last") is not None:                      # 滑鼠移動很快時，兩點之間也要擦到
            x0, y0 = st["last"]
            steps = int(np.hypot(event.x - x0, event.y - y0) // max(self.brush_r() * 0.7, 1))
            for k in range(1, steps + 1):
                f = k / (steps + 1)
                mask |= self.near_mask(st["ax"], x0 + (event.x - x0) * f, y0 + (event.y - y0) * f)
        st["last"] = (event.x, event.y)
        n = self.apply_hits(mask, st["restore"], commit=False)
        if n:
            st["n"] += n
            self.redraw(light=True)

    def _snap(self, xv, yv):
        if not self.snap_var.get():
            return float(xv), float(yv)
        keep = ~E.erased_mask(self.x, self.ed.get("erase"))
        xs, ys = self.x[keep], self.y[keep]
        i = int(np.argmin(np.abs(xs - xv)))
        lo, hi = max(i - 3, 0), min(i + 4, xs.size)
        return float(xs[i]), float(np.median(ys[lo:hi]))

    def add_anchor(self, xv, yv):
        new = copy.deepcopy(self.ed)
        new["anchors"] = sorted(new.get("anchors", []) + [list(self._snap(xv, yv))])
        self._commit(new, f"新增錨點（共 {len(new['anchors'])} 個）")

    def delete_anchor(self, i):
        new = copy.deepcopy(self.ed)
        new["anchors"].pop(i)
        self._commit(new, f"刪除錨點（剩 {len(new['anchors'])} 個；Ctrl+Z 可以復原）")

    def auto_anchors(self):
        """沿著 ALS 背景平均放 N 個錨點，再自己微調。"""
        if self.path is None:
            return
        from ..core.peaks import baseline_als
        try:
            n = max(2, min(40, int(self.n_auto.get())))
        except ValueError:
            n = 8
        keep = ~E.erased_mask(self.x, self.ed.get("erase"))
        xs, ys = self.x[keep], self.y[keep]
        bg = baseline_als(ys)
        idx = np.unique(np.linspace(0, xs.size - 1, n).round().astype(int))
        new = copy.deepcopy(self.ed)
        new["anchors"] = [[float(xs[i]), float(bg[i])] for i in idx]
        self._commit(new, f"放了 {len(idx)} 個錨點（沿 ALS 背景）；可以拖曳微調、右鍵刪除")

    # ================================================================== 滑鼠
    def _boxed(self, ax, e1, e2):
        mode = self.mode_var.get()
        if mode not in ("erase", "restore") or self.path is None or None in (e1.xdata, e2.xdata, e1.ydata, e2.ydata):
            return
        values = self.y if ax is self.ax1 else self.y - self._bg_full()
        self.erase_box(e1.xdata, e2.xdata, e1.ydata, e2.ydata, values, restore=(mode == "restore"))

    def _near_anchor(self, event, px=10):
        if event.inaxes is not self.ax1 or not self.ed.get("anchors"):
            return None
        pts = self.ax1.transData.transform(np.asarray(self.ed["anchors"], float))
        d = np.hypot(pts[:, 0] - event.x, pts[:, 1] - event.y)
        i = int(np.argmin(d))
        return i if d[i] <= px else None

    def _press(self, event):
        mode = self.mode_var.get()
        if str(getattr(self.toolbar, "mode", "")) or self.path is None:
            return
        if mode == "brush":
            if event.inaxes in (self.ax1, self.ax2) and event.button in (1, 3):
                self.stroke = dict(ax=event.inaxes, restore=(event.button == 3), before=copy.deepcopy(self.ed),
                                   n=0, last=None)
                self._brush_at(event)
            return
        if mode in ("erase", "restore"):
            if event.inaxes in (self.ax1, self.ax2) and event.button == 1:
                self._click = (event.x, event.y, event.inaxes)
            return
        if mode != "anchor":
            return
        if event.inaxes is not self.ax1 or event.xdata is None:
            return
        i = self._near_anchor(event)
        if event.button == 3:
            if i is not None:
                self.delete_anchor(i)
            return
        if event.button != 1:
            return
        if i is not None:
            self.drag = dict(i=i, before=copy.deepcopy(self.ed), moved=False)
        else:
            self.add_anchor(event.xdata, event.ydata)

    def _motion(self, event):
        if self.mode_var.get() == "brush" and not str(getattr(self.toolbar, "mode", "")):
            if event.inaxes in (self.ax1, self.ax2) and event.x is not None:
                self._show_circle(event.x, event.y)
            else:
                self._hide_circle()
        if self.stroke is not None:
            if event.inaxes is self.stroke["ax"] and event.x is not None:
                self._brush_at(event)
            return
        d = self.drag
        if d is None or event.inaxes is not self.ax1 or event.xdata is None:
            return
        d["moved"] = True
        self.ed["anchors"][d["i"]] = [float(event.xdata), float(event.ydata)]
        self.redraw(light=True)

    def _release(self, event):
        if self.stroke is not None:
            st, self.stroke = self.stroke, None
            if st["n"]:
                done = self.ed
                self.ed = st["before"]                      # 整筆記成一步（Ctrl+Z 一次復原整筆）
                what = "恢復" if st["restore"] else "擦掉"
                self._commit(done, f"{what} {st['n']} 個點（一筆；Ctrl+Z 可以復原）")
            return
        if self._click is not None:
            x0, y0, ax = self._click
            self._click = None
            if event.x is not None and abs(event.x - x0) < 2 and abs(event.y - y0) < 2:   # 沒有拖曳 = 點一下（框選至少 2 px）
                restore = self.mode_var.get() == "restore"
                if not self.apply_hits(self.near_mask(ax, x0, y0), restore):
                    self.hint.configure(text="滑鼠附近沒有可以" + ("恢復" if restore else "擦掉") +
                                        "的點（可以調大「筆刷大小」）", fg=T.MUTED)
            return
        d, self.drag = self.drag, None
        if d is None or not d["moved"]:
            return
        pts = self.ed["anchors"]
        if event.xdata is not None and event.inaxes is self.ax1:
            pts[d["i"]] = list(self._snap(event.xdata, event.ydata)) if self.snap_var.get() else \
                [float(event.xdata), float(event.ydata)]
        moved = copy.deepcopy(self.ed)
        moved["anchors"] = sorted(pts)
        self.ed = d["before"]
        self._commit(moved, "錨點已移動（Ctrl+Z 可以復原）")

    # ================================================================== 畫圖
    def _bg_full(self):
        if not self.ed.get("anchors"):
            return np.zeros_like(self.y)
        try:
            return E.manual_baseline(self.x, self.ed["anchors"], self.interp_var.get())
        except Exception:
            return np.zeros_like(self.y)

    def redraw(self, reset_view=False, light=False):
        if self.x is None:
            return
        lims = None if reset_view else (self.ax1.get_xlim(), self.ax1.get_ylim(), self.ax2.get_ylim())
        x, y = self.x, self.y
        er = E.erased_mask(x, self.ed.get("erase"))
        bg = self._bg_full()
        has_bg = bool(self.ed.get("anchors"))
        for ax in (self.ax1, self.ax2):
            ax.cla()
        a1, a2 = self.ax1, self.ax2
        a1.plot(x[~er], y[~er], color="#374151", lw=1, label="光譜（已擦掉的點不畫）")
        if er.any():
            a1.plot(x[er], y[er], "x", color="#9ca3af", ms=5, mew=1.2, label=f"擦掉的點（{int(er.sum())}）")
        if has_bg:
            a1.plot(x, bg, "--", color="#f2a541", lw=1.6, label="手動背景")
            ap = np.asarray(self.ed["anchors"], float)
            a1.plot(ap[:, 0], ap[:, 1], "s", color="#f2a541", mec="#b45309", ms=7, label=f"錨點（{len(ap)}）")
        sp = self.spikes if self.spikes is not None and self.spikes.size == x.size else None
        if sp is not None and sp.any():
            a1.plot(x[sp], y[sp], "o", mfc="none", mec="#dc2626", ms=12, mew=2,
                    label=f"找到的尖峰（{int(sp.sum())} 點）")
        a1.set_ylabel("Intensity（原始）")
        a1.set_title(os.path.basename(self.path or ""), loc="left", fontsize=10)
        a1.legend(fontsize=8, loc="upper left")
        corr = y - bg
        a2.plot(x[~er], corr[~er], color=T.accent(self.key)["main"], lw=1.1)
        if er.any():
            a2.plot(x[er], corr[er], "x", color="#9ca3af", ms=5, mew=1.2)
        if sp is not None and sp.any():
            a2.plot(x[sp], corr[sp], "o", mfc="none", mec="#dc2626", ms=12, mew=2)
        a2.axhline(0, color="#9ca3af", lw=0.8)
        a2.set_ylabel("扣手動背景後" if has_bg else "（還沒有錨點：顯示原始）")
        a2.set_xlabel("Raman shift (cm$^{-1}$)")
        if lims is not None:
            a1.set_xlim(lims[0])
            a1.set_ylim(lims[1])
            if light:
                a2.set_ylim(lims[2])
            else:                                          # 下圖的 Y 範圍跟著扣背景後的資料（看得到的 X 範圍內）
                lo, hi = sorted(lims[0])
                m = (~er) & (x >= lo) & (x <= hi) & np.isfinite(corr)
                if m.sum() > 1:
                    c0, c1 = float(np.min(corr[m])), float(np.max(corr[m]))
                    pad = 0.06 * ((c1 - c0) or 1.0)
                    a2.set_ylim(min(c0, 0) - pad, c1 + pad)
        if reset_view:
            self.toolbar.update()                       # Home = 這個檔案的全部範圍
        self.canvas.draw_idle()

    # ================================================================== 筆刷圓圈
    def _on_draw(self, event=None):
        """每次整張圖畫完：存下沒有圓圈的畫面，再把圓圈畫上去。"""
        try:
            self._bg = self.canvas.copy_from_bbox(self.fig.bbox)
            if self.brush_circle.get_visible():
                self.fig.draw_artist(self.brush_circle)
        except Exception:
            self._bg = None

    def _show_circle(self, px, py):
        c = self.brush_circle
        restore = bool(self.stroke and self.stroke["restore"])
        col, edge = ("#16a34a", "#15803d") if restore else ("#ef4444", "#b91c1c")
        c.set_facecolor(col)
        c.set_edgecolor(edge)
        c.center = (px, py)
        c.set_radius(self.brush_r())
        c.set_visible(True)
        self._blit()

    def _hide_circle(self):
        if self.brush_circle.get_visible():
            self.brush_circle.set_visible(False)
            self._blit()

    def _blit(self):
        if self._bg is None:
            return
        try:
            self.canvas.restore_region(self._bg)
            if self.brush_circle.get_visible():
                self.fig.draw_artist(self.brush_circle)
            self.canvas.blit(self.fig.bbox)
        except Exception:
            pass

    # ================================================================== 🔍 找尖峰
    def find_spikes(self):
        """在還沒擦掉的點裡找宇宙射線尖峰，用紅圈標出來（還沒擦掉，按「擦掉」才擦）。"""
        if self.path is None:
            return 0
        try:
            k = max(2.0, min(20.0, float(self.spike_k.get())))
        except ValueError:
            k = 6.0
        try:
            mw = max(1, min(5, int(float(self.spike_w.get()))))
        except ValueError:
            mw = 3
        keep = np.flatnonzero(~E.erased_mask(self.x, self.ed.get("erase")))
        mask = np.zeros(self.x.size, bool)
        runs = find_spikes(self.y[keep], k=k, max_width=mw)
        for a, b in runs:
            mask[keep[a:b + 1]] = True
        self.spikes = mask if runs else None
        self._spike_ui(len(runs), int(mask.sum()))
        if not runs:
            self.hint.configure(text=f"沒有找到尖峰（靈敏度 {k:g}）。看得到卻沒找到：把靈敏度調小（例如 5）再找一次", fg=T.MUTED)
        else:
            where = "、".join(f"{self.x[keep[a]]:.0f}" for a, b in runs[:8]) + ("…" if len(runs) > 8 else "")
            self.hint.configure(text=f"找到 {len(runs)} 個尖峰（紅圈；位置 {where} cm⁻¹）。確認後按「擦掉」；"
                                     "有不是尖峰的，可以先用還原筆或取消", fg=T.MUTED)
        self.redraw(light=True)
        return len(runs)

    def _spike_ui(self, n_spikes, n_points=0):
        if not hasattr(self, "spike_lab"):
            return
        if n_spikes:
            self.spike_lab.configure(text=f"找到 {n_spikes} 個（{n_points} 點，紅圈）")
            self.spike_erase.configure(text=f"⌫ 擦掉這 {n_spikes} 個")
            for w in (self.spike_lab, self.spike_erase, self.spike_cancel):
                self.spike_row.set_visible(w, True)
            self.spike_row._plan = None
            self.spike_row._relayout()
        else:
            self.spike_lab.configure(text="")
            for w in (self.spike_lab, self.spike_erase, self.spike_cancel):
                self.spike_row.set_visible(w, False)

    def erase_spikes(self):
        if self.spikes is None or not self.spikes.any():
            return 0
        n = self.apply_hits(self.spikes, restore=False)
        self.spikes = None
        self._spike_ui(0)
        self.redraw(light=True)
        return n

    def cancel_spikes(self):
        self.spikes = None
        self._spike_ui(0)
        self.hint.configure(text="已取消，沒有擦掉任何點", fg=T.MUTED)
        self.redraw(light=True)

    def close(self):
        try:
            self.destroy()
        finally:
            if self.changed:
                self.page.schedule_plot(50)
                self.app.status("編修已套用（原始檔沒有修改；✎ 編修光譜 可以隨時復原）", "ok")
