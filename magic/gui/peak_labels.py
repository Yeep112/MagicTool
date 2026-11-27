"""🏷 峰標註：每個峰代表什麼（G、2D、hBN、Si…）；新增、刪除、改文字、顏色、大小、字型。

‧ 改了馬上套用到 Raman 的圖（不重新計算）；設定會記住，下次開啟一樣
‧ 「跟隨擬合」= 放在擬合到的峰位（G / 2D 峰的圖）；其他圖放在「位置」附近光譜最高的地方
‧ 「在圖上點選新增」：點一下圖上的峰，自動對到最高點，再填它代表什麼
‧ 圖上的標註可以直接用滑鼠拖曳到想要的位置（會記住）；「標註回原位」可以重設
"""
from __future__ import annotations

import copy
import tkinter as tk
from tkinter import colorchooser, ttk

from ..raman import labels as L
from . import theme as T
from .widgets import fit_window

COLS = [("show", "顯示", 44), ("text", "文字", 110), ("x", "位置 (cm⁻¹)", 84), ("follow", "跟隨擬合", 84),
        ("color", "顏色", 70), ("size", "大小", 44), ("font", "字型", 120)]
QUICK_COLORS = ["#e4572e", "#2563eb", "#17a398", "#7c3aed", "#f2a541", "#ef476f", "#111827", "#6b7280"]


def font_choices():
    names = ["（預設）"]
    try:
        from matplotlib import font_manager
        have = sorted({f.name for f in font_manager.fontManager.ttflist})
    except Exception:
        have = []
    pref = ["Microsoft JhengHei", "Arial", "Times New Roman", "Calibri", "Cambria", "Segoe UI", "DejaVu Sans",
            "DejaVu Serif", "Noto Sans CJK TC"]
    names += [f for f in pref if f in have]
    names += [f for f in have if f not in names and not f.startswith(".")]
    return names


class PeakLabelDialog(tk.Toplevel):
    def __init__(self, page):
        super().__init__(page.app.root)
        self.page = page
        self.app = page.app
        self.key = page.key
        self.title("峰標註")
        self.configure(bg=T.CARD)
        self.transient(page.app.root)
        fit_window(self, T.px(720), T.px(600), 560, 420)
        self._job = None
        self._loading = False
        a = T.accent(self.key)
        head = tk.Frame(self, bg=a["main"], padx=14, pady=7)
        head.pack(fill="x")
        tk.Label(head, text="🏷 峰標註", bg=a["main"], fg="white", font=T.font(12, "bold")).pack(side="left")
        tk.Label(head, text="　每個峰代表什麼；改了馬上套用到圖上。圖上的標註可以直接拖曳", bg=a["main"],
                 fg=T.mix_color("#ffffff", a["main"], 0.25), font=T.font(9)).pack(side="left")

        bar = tk.Frame(self, bg=T.CARD)
        bar.pack(fill="x", padx=12, pady=(8, 4))
        mb = ttk.Button(bar, text="＋ 新增常見的峰 ▾", style=f"{self.key}.Ghost.TButton")
        menu = tk.Menu(mb, tearoff=False)
        self.menu = menu
        mb.configure(command=lambda: menu.tk_popup(mb.winfo_rootx(), mb.winfo_rooty() + mb.winfo_height()))
        for group, items in L.PRESETS:
            sub = tk.Menu(menu, tearoff=False)
            for text, x, fol in items:
                sub.add_command(label=f"{text}　{x:g} cm⁻¹", command=lambda t=text, x=x, f=fol: self.add(t, x, f))
            menu.add_cascade(label=group, menu=sub)
        menu.add_separator()
        menu.add_command(label="自訂（空白）", command=lambda: self.add("峰", 1000.0, None))
        mb.pack(side="left")
        self.pick_btn = ttk.Button(bar, text="⌖ 在圖上點選新增", style=f"{self.key}.Ghost.TButton", command=self.pick)
        self.pick_btn.pack(side="left", padx=6)
        ttk.Button(bar, text="刪除", style=f"{self.key}.Ghost.TButton", command=self.delete).pack(side="left")
        ttk.Button(bar, text="恢復預設", style=f"{self.key}.Small.TButton", command=self.reset).pack(side="right")
        ttk.Button(bar, text="標註回原位", style=f"{self.key}.Small.TButton", command=self.reset_positions).pack(
            side="right", padx=6)

        tf = tk.Frame(self, bg=T.CARD)
        tf.pack(fill="both", expand=True, padx=12)
        self.tree = ttk.Treeview(tf, columns=[c for c, _, _ in COLS], show="headings", selectmode="browse", height=8)
        for c, text, w in COLS:
            self.tree.heading(c, text=text)
            self.tree.column(c, width=T.px(w), stretch=c in ("text", "font"), anchor="w" if c in ("text", "font") else "center")
        sb = ttk.Scrollbar(tf, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._load_selected())
        self.tree.bind("<Double-1>", lambda e: self.w_text.focus_set())

        self._build_editor()
        self.hint = tk.Label(self, text="", bg=T.CARD, fg=T.MUTED, font=T.font(9), anchor="w")
        self.hint.pack(fill="x", padx=12, pady=(0, 8))
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.refresh_tree()
        kids = self.tree.get_children()
        if kids:
            self.tree.selection_set(kids[0])

    # ================================================================== 編輯區
    def _build_editor(self):
        box = tk.LabelFrame(self, text=" 選到的標註 ", bg=T.CARD, fg=T.MUTED, font=T.font(9, "bold"), bd=1,
                            relief="solid", highlightthickness=0)
        box.pack(fill="x", padx=12, pady=8)
        g = tk.Frame(box, bg=T.CARD)
        g.pack(fill="x", padx=8, pady=6)
        self.v = {k: tk.StringVar() for k in ("text", "x", "follow", "size", "font", "color")}
        self.b = {k: tk.BooleanVar() for k in ("show", "pos", "bold", "italic", "always")}

        def lab(r, c, text):
            tk.Label(g, text=text, bg=T.CARD, fg=T.MUTED, font=T.font(9)).grid(row=r, column=c, sticky="w", padx=(0, 4),
                                                                                pady=3)
        lab(0, 0, "文字")
        self.w_text = ttk.Entry(g, textvariable=self.v["text"], width=18)
        self.w_text.grid(row=0, column=1, sticky="ew")
        lab(0, 2, "位置 (cm⁻¹)")
        ttk.Entry(g, textvariable=self.v["x"], width=8).grid(row=0, column=3, sticky="w")
        lab(0, 4, "跟隨擬合")
        ttk.Combobox(g, textvariable=self.v["follow"], values=L.FOLLOW, state="readonly", width=12).grid(
            row=0, column=5, sticky="w")
        lab(1, 0, "顏色")
        cf = tk.Frame(g, bg=T.CARD)
        cf.grid(row=1, column=1, columnspan=3, sticky="w")
        self.swatch = tk.Label(cf, text="　　", bg="#374151", relief="solid", bd=1, cursor="hand2")
        self.swatch.pack(side="left")
        self.swatch.bind("<Button-1>", lambda e: self.choose_color())
        for c in QUICK_COLORS:
            sw = tk.Label(cf, text="  ", bg=c, cursor="hand2")
            sw.pack(side="left", padx=1)
            sw.bind("<Button-1>", lambda e, c=c: self.v["color"].set(c))
        ttk.Button(cf, text="其他…", style=f"{self.key}.Small.TButton", command=self.choose_color).pack(side="left", padx=4)
        lab(1, 4, "大小")
        ttk.Spinbox(g, from_=5, to=40, increment=1, textvariable=self.v["size"], width=5).grid(row=1, column=5, sticky="w")
        lab(2, 0, "字型")
        ttk.Combobox(g, textvariable=self.v["font"], values=font_choices(), width=22).grid(row=2, column=1, columnspan=3,
                                                                                         sticky="w")
        cb = tk.Frame(g, bg=T.CARD)
        cb.grid(row=2, column=4, columnspan=2, sticky="w")
        for k, text in (("bold", "粗體"), ("italic", "斜體")):
            ttk.Checkbutton(cb, text=text, variable=self.b[k], style=f"{self.key}.TCheckbutton").pack(side="left", padx=2)
        cb2 = tk.Frame(g, bg=T.CARD)
        cb2.grid(row=3, column=0, columnspan=6, sticky="w", pady=(4, 0))
        ttk.Checkbutton(cb2, text="顯示", variable=self.b["show"], style=f"{self.key}.TCheckbutton").pack(side="left")
        ttk.Checkbutton(cb2, text="文字下面加峰位數值", variable=self.b["pos"], style=f"{self.key}.TCheckbutton").pack(
            side="left", padx=10)
        ttk.Checkbutton(cb2, text="沒有擬合時也標在「位置」", variable=self.b["always"],
                        style=f"{self.key}.TCheckbutton").pack(side="left")
        ttk.Button(cb2, text="這個樣式套用到全部標註（大小、字型、粗斜體）", style=f"{self.key}.Small.TButton",
                   command=self.style_to_all).pack(side="right")
        g.columnconfigure(1, weight=1)
        for var in list(self.v.values()) + list(self.b.values()):
            var.trace_add("write", lambda *a: self._edited())

    # ================================================================== 資料
    @property
    def defs(self):
        return self.page.peak_label_defs()

    def _find(self, iid):
        return next((d for d in self.defs if d["id"] == iid), None)

    def refresh_tree(self):
        sel = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for d in self.defs:
            d2 = L.full(d)
            self.tree.insert("", "end", iid=d["id"], values=(
                "✓" if d2["show"] else "", d2["text"], f"{d2['x']:g}", d2["follow"] if d2["follow"] != L.FIXED else "—",
                d2["color"], f"{d2['size']:g}", d2["font"] or "（預設）"))
        if sel and self.tree.exists(sel[0]):
            self.tree.selection_set(sel[0])

    def _load_selected(self):
        sel = self.tree.selection()
        d = self._find(sel[0]) if sel else None
        if d is None:
            return
        d = L.full(d)
        self._loading = True
        try:
            self.v["text"].set(d["text"])
            self.v["x"].set(f"{d['x']:g}")
            self.v["follow"].set(d["follow"] or L.FIXED)
            self.v["size"].set(f"{d['size']:g}")
            self.v["font"].set(d["font"] or "（預設）")
            self.v["color"].set(d["color"])
            for k in self.b:
                self.b[k].set(bool(d[k]))
            self.swatch.configure(bg=d["color"])
        finally:
            self._loading = False

    def _edited(self):
        if self._loading:
            return
        sel = self.tree.selection()
        d = self._find(sel[0]) if sel else None
        if d is None:
            return
        d["text"] = self.v["text"].get()
        try:
            d["x"] = float(self.v["x"].get())
        except ValueError:
            pass
        d["follow"] = self.v["follow"].get() or L.FIXED
        try:
            d["size"] = max(4.0, min(60.0, float(self.v["size"].get())))
        except ValueError:
            pass
        f = self.v["font"].get()
        d["font"] = "" if f in ("", "（預設）") else f
        c = self.v["color"].get().strip()
        if c:
            try:
                self.winfo_rgb(c)
                d["color"] = c
                self.swatch.configure(bg=c)
            except tk.TclError:
                pass
        for k in self.b:
            d[k] = bool(self.b[k].get())
        self.refresh_tree()
        self.apply_soon()

    def apply_soon(self):
        self.app.save_state_soon()
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
        self._job = self.after(250, self.apply)

    def apply(self):
        self._job = None
        self.page.redraw()

    # ================================================================== 動作
    def add(self, text, x, follow=None, color=None):
        defs = self.defs
        d = L.make(defs, text, x, follow, color or QUICK_COLORS[len(defs) % len(QUICK_COLORS)])
        defs.append(d)
        self.refresh_tree()
        self.tree.selection_set(d["id"])
        self.tree.see(d["id"])
        self.apply_soon()
        self.hint.configure(text=f"已新增「{text}」（{x:g} cm⁻¹）；可以在下面改文字、顏色、大小、字型", fg=T.MUTED)
        return d

    def delete(self):
        sel = self.tree.selection()
        if not sel:
            return
        defs = self.defs
        i = next((k for k, d in enumerate(defs) if d["id"] == sel[0]), None)
        if i is None:
            return
        gone = defs.pop(i)
        self._undo = (i, gone)
        self.refresh_tree()
        kids = self.tree.get_children()
        if kids:
            self.tree.selection_set(kids[min(i, len(kids) - 1)])
        self.apply_soon()
        self.hint.configure(text=f"已刪除「{gone['text']}」　", fg=T.MUTED)
        self._undo_link()

    def _undo_link(self):
        lk = getattr(self, "_undo_lbl", None)
        if lk is None:
            lk = tk.Label(self.hint, text="復原", fg=T.accent(self.key)["text"], bg=T.CARD, cursor="hand2",
                          font=T.font(9, "bold"))
            lk.bind("<Button-1>", lambda e: self.undo_delete())
            self._undo_lbl = lk
        lk.place(relx=1.0, x=-4, rely=0.5, anchor="e")

    def undo_delete(self):
        if getattr(self, "_undo", None) is None:
            return
        i, d = self._undo
        self._undo = None
        self.defs.insert(i, d)
        self.refresh_tree()
        self.tree.selection_set(d["id"])
        self.apply_soon()
        self.hint.configure(text=f"已復原「{d['text']}」", fg=T.MUTED)
        if getattr(self, "_undo_lbl", None) is not None:
            self._undo_lbl.place_forget()

    def reset(self):
        self.app.state["raman_labels"] = L.defaults()
        self.reset_positions(quiet=True)
        self.refresh_tree()
        kids = self.tree.get_children()
        if kids:
            self.tree.selection_set(kids[0])
        self.apply_soon()
        self.hint.configure(text="已恢復預設的標註（G、2D、hBN、D）", fg=T.MUTED)

    def reset_positions(self, quiet=False):
        for ov in self.page.st.get("fig", {}).values():
            ann = ov.get("annot") or {}
            for k in [k for k in ann if k.startswith("peak:")]:
                ann.pop(k)
        self.apply_soon()
        if not quiet:
            self.hint.configure(text="標註回到預設位置（峰的正上方）", fg=T.MUTED)

    def style_to_all(self):
        sel = self.tree.selection()
        src = self._find(sel[0]) if sel else None
        if src is None:
            return
        for d in self.defs:
            for k in ("size", "font", "bold", "italic"):
                d[k] = L.full(src)[k]
        self.refresh_tree()
        self.apply_soon()

    def choose_color(self):
        c = colorchooser.askcolor(color=self.v["color"].get() or "#374151", parent=self, title="標註顏色")
        if c and c[1]:
            self.v["color"].set(c[1])

    def pick(self):
        """點圖上的峰 → 新增標註（自動對到附近最高點）。"""
        fig_panel = self.page.right
        canvas = fig_panel.canvas
        if not any(L.is_raman_axes(ax) for ax in fig_panel.fig.axes):
            self.hint.configure(text="目前的圖沒有 Raman shift 軸（先畫光譜或 G / 2D 峰的圖）", fg=T.WARNING)
            return
        fig_panel.picking = True
        self.hint.configure(text="在圖上點一下要標註的峰（Esc 取消）", fg=T.accent(self.key)["text"])
        self.app.status("在圖上點一下要標註的峰", "info")

        def done(cid):
            canvas.mpl_disconnect(cid)
            fig_panel.picking = False

        def on_click(event):
            if event.inaxes is None or event.xdata is None or not L.is_raman_axes(event.inaxes):
                return
            done(holder["cid"])
            x = L.snap_to_peak(event.inaxes, event.xdata)
            self.add(f"峰 {x:.0f}", round(x, 1))
            self.lift()
            self.w_text.focus_set()
            self.w_text.select_range(0, "end")
        holder = {"cid": canvas.mpl_connect("button_press_event", on_click)}
        self.bind("<Escape>", lambda e: (done(holder["cid"]), self.hint.configure(text="已取消")))

    def close(self):
        if self._job is not None:
            self.apply()
        self.destroy()

    def snapshot(self):
        return copy.deepcopy(self.defs)
