"""自訂元件（取自 LowTempAnalysis）：卡片、可捲動區塊、機台切換鈕、功能卡片清單、分隔區塊。"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import theme as T


def card(parent, pad=12):
    outer = tk.Frame(parent, bg=T.CARD, highlightthickness=1, highlightbackground=T.BORDER,
                     highlightcolor=T.BORDER, bd=0)
    inner = tk.Frame(outer, bg=T.CARD)
    inner.pack(fill="both", expand=True, padx=pad, pady=pad)
    return outer, inner


def section_title(parent, text, icon=None, color=None):
    row = tk.Frame(parent, bg=T.CARD)
    if icon:
        tk.Label(row, text=icon, bg=T.CARD, fg=color or T.MUTED, font=T.font(12, "bold")).pack(side="left", padx=(0, 6))
    lab = tk.Label(row, text=text, bg=T.CARD, fg=T.TEXT, font=T.font(11, "bold"))
    lab.pack(side="left")
    return row, lab


class Chip(tk.Label):
    def __init__(self, parent, text="", fg=None, bg=None, **kw):
        super().__init__(parent, text=text, fg=fg or T.MUTED, bg=bg or T.CHIP, font=T.font(9, "bold"),
                         padx=8, pady=2, **kw)

    def set(self, text, fg=None, bg=None):
        self.configure(text=text)
        if fg:
            self.configure(fg=fg)
        if bg:
            self.configure(bg=bg)


class ScrollFrame(tk.Frame):
    """可上下捲動的區塊；內容放在 self.body。"""

    def __init__(self, parent, bg=None, **kw):
        bg = bg or T.CARD
        super().__init__(parent, bg=bg, **kw)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.sb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.body = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.canvas.configure(yscrollcommand=self.sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.sb.pack(side="right", fill="y")
        self.body.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        for w in (self.canvas, self.body):
            w.bind("<Enter>", self._bind_wheel)
            w.bind("<Leave>", self._unbind_wheel)

    def _bind_wheel(self, _=None):
        self.canvas.bind_all("<MouseWheel>", self._on_wheel)
        self.canvas.bind_all("<Button-4>", lambda e: self._scroll(-2))
        self.canvas.bind_all("<Button-5>", lambda e: self._scroll(2))

    def _unbind_wheel(self, _=None):
        for ev in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.canvas.unbind_all(ev)

    def _scroll(self, n):
        top, bottom = self.canvas.yview()
        if top <= 0 and bottom >= 1:
            return
        self.canvas.yview_scroll(n, "units")

    def _on_wheel(self, e):
        d = getattr(e, "delta", 0)
        if abs(d) >= 120:                      # Windows：一格 = 120
            self._scroll(int(-d / 120) * 2)
        elif d:                                # macOS：觸控板 / 滑鼠是小的數字（±1…±10）
            self._scroll(-1 if d > 0 else 1)

    def to_top(self):
        self.canvas.yview_moveto(0)


class Segmented(tk.Frame):
    """大型切換鈕（機台）。每個選項有自己的主色。options：[(key, 標題, 副標)]"""

    def __init__(self, parent, options, command, bg=None):
        bg = bg or T.CHIP
        super().__init__(parent, bg=bg, padx=3, pady=3)
        self.command = command
        self.buttons = []
        self.active = 0
        self._bg = bg
        self._fg_off = T.HEADER_MUTED if bg == T.HEADER_2 else T.MUTED
        self._sub_off = "#6f80a8" if bg == T.HEADER_2 else T.FAINT
        for i, (key, title, sub) in enumerate(options):
            b = tk.Frame(self, bg=bg, cursor="hand2", padx=12, pady=5)
            t = tk.Label(b, text=title, bg=bg, fg=self._fg_off, font=T.font(11, "bold"), cursor="hand2")
            s = tk.Label(b, text=sub, bg=bg, fg=self._sub_off, font=T.font(8), cursor="hand2")
            t.pack(anchor="w")
            s.pack(anchor="w")
            b.grid(row=0, column=i, sticky="nsew", padx=1)
            self.columnconfigure(i, weight=1, uniform="seg")
            for w in (b, t, s):
                w.bind("<Button-1>", lambda e, i=i: self.select(i))
            self.buttons.append((key, b, t, s))
        self.paint()

    def index(self, key):
        return next((i for i, b in enumerate(self.buttons) if b[0] == key), 0)

    def select(self, i, notify=True):
        if isinstance(i, str):
            i = self.index(i)
        if i == self.active and notify:
            return
        self.active = i
        self.paint()
        if notify:
            self.command(self.buttons[i][0])

    def paint(self):
        for i, (key, b, t, s) in enumerate(self.buttons):
            if i == self.active:
                a = T.accent(key)
                for w in (b, t, s):
                    w.configure(bg=a["main"])
                t.configure(fg=a.get("on", "#ffffff"))
                s.configure(fg=T.mix_color(a.get("on", "#ffffff"), a["main"], 0.25))
            else:
                for w in (b, t, s):
                    w.configure(bg=self._bg)
                t.configure(fg=self._fg_off)
                s.configure(fg=self._sub_off)


class FeatureList(tk.Frame):
    """依「快速檢視 / 參數萃取 / 批次比較」分組列出分析功能。"""

    def __init__(self, parent, accent_key, on_select):
        super().__init__(parent, bg=T.CARD)
        self.on_select = on_select
        self.cards = {}
        self.selected = None
        self.accent = accent_key
        self._wrap_labels = []
        self._wrap = T.px(210)
        self.bind("<Configure>", self._rewrap)

    def _rewrap(self, event=None):
        w = max((event.width if event is not None else self.winfo_width()) - T.px(70), 120)
        if abs(w - self._wrap) < 6:
            return
        self._wrap = w
        for lab in self._wrap_labels:
            try:
                lab.configure(wraplength=w)
            except tk.TclError:
                pass

    def set_items(self, analyses, selected_name):
        for w in self.winfo_children():
            w.destroy()
        self.cards = {}
        self._wrap_labels = []
        group = None
        for a in analyses:
            if a.group != group:
                group = a.group
                tk.Label(self, text=group, bg=T.CARD, fg=T.FAINT, font=T.font(9, "bold"),
                         anchor="w").pack(fill="x", pady=(10, 3), padx=2)
            self.cards[a.name] = self._make_card(a)
        if selected_name not in self.cards and analyses:
            selected_name = analyses[0].name
        self.select(selected_name, notify=False)

    def _make_card(self, a):
        acc = T.accent(self.accent)
        fr = tk.Frame(self, bg=T.CARD, cursor="hand2")
        fr.pack(fill="x", pady=2)
        bar = tk.Frame(fr, bg=T.CARD, width=4)
        bar.pack(side="left", fill="y")
        icon = tk.Label(fr, text=a.icon, bg=T.CARD, fg=acc["main"], font=T.font(13, "bold"), width=3, cursor="hand2")
        icon.pack(side="left", padx=(4, 2), pady=6)
        txt = tk.Frame(fr, bg=T.CARD, cursor="hand2")
        txt.pack(side="left", fill="x", expand=True, pady=6, padx=(0, 6))
        title = tk.Label(txt, text=a.name, bg=T.CARD, fg=T.TEXT, font=T.font(10, "bold"), anchor="w",
                         justify="left", wraplength=self._wrap, cursor="hand2")
        title.pack(fill="x")
        desc = tk.Label(txt, text=(a.help.split("。")[0] if a.help else ""), bg=T.CARD, fg=T.MUTED,
                        font=T.font(8), anchor="w", justify="left", wraplength=self._wrap, cursor="hand2")
        desc.pack(fill="x")
        self._wrap_labels += [title, desc]
        for w in (fr, txt, icon, title, desc):
            w.bind("<Button-1>", lambda e, n=a.name: self.select(n))
            w.bind("<Enter>", lambda e, n=a.name: self._hover(n, True))
            w.bind("<Leave>", lambda e, n=a.name: self._hover(n, False))
        return dict(frame=fr, bar=bar, icon=icon, title=title, desc=desc, txt=txt)

    def _paint(self, name, bg):
        c = self.cards[name]
        for k in ("frame", "icon", "title", "desc", "txt"):
            c[k].configure(bg=bg)

    def _hover(self, name, inside):
        if name == self.selected or name not in self.cards:
            return
        self._paint(name, T.HOVER if inside else T.CARD)

    def select(self, name, notify=True):
        acc = T.accent(self.accent)
        for n, c in self.cards.items():
            on = n == name
            self._paint(n, acc["soft"] if on else T.CARD)
            c["bar"].configure(bg=acc["main"] if on else T.CARD)
            c["title"].configure(fg=acc["text"] if on else T.TEXT)
        self.selected = name
        if notify:
            self.on_select(name)


class Paned(tk.PanedWindow):
    """可拖曳的分隔區塊。拖曳時只顯示一條線，放開才重新排版 → 不會卡頓。"""

    def __init__(self, parent, orient="horizontal", bg=None):
        super().__init__(parent, orient=orient, opaqueresize=False, sashwidth=T.px(8), sashrelief="flat",
                         bg=bg or T.BG, bd=0, showhandle=False, sashpad=0)
        self._horizontal = orient == "horizontal"

    def add_pane(self, child, stretch=True, size=None, minsize=120):
        kw = {"stretch": "always" if stretch else "never", "minsize": minsize}
        if size:
            kw["width" if self._horizontal else "height"] = size
        self.add(child, **kw)

    def get_sash(self, i):
        try:
            x, y = self.sash_coord(i)
            return int(x if self._horizontal else y)
        except (tk.TclError, TypeError, ValueError):
            return None

    def set_sash(self, i, pos):
        try:
            x, y = self.sash_coord(i)
            if self._horizontal:
                self.sash_place(i, int(pos), y)
            else:
                self.sash_place(i, x, int(pos))
        except (tk.TclError, TypeError, ValueError):
            pass


class Flow(tk.Frame):
    """像文字一樣排列：一組一組往右排，寬度不夠就自動換到下一行（視窗窄的筆電也不會被切掉）。
    用 flow.group() 建一組（裡面用 pack 排），同一組不會被拆開。"""

    def __init__(self, parent, padx=6, pady=2, **kw):
        super().__init__(parent, **kw)
        self._items = []
        self._padx, self._pady = padx, pady
        self._lastw = 0
        self._job = None
        self.configure(height=28)
        self.bind("<Configure>", self._on_configure)

    def group(self):
        f = tk.Frame(self, bg=self.cget("bg"))
        self._items.append(f)
        self.schedule()
        return f

    def _on_configure(self, e):
        if e.width != self._lastw:
            self._lastw = e.width
            self.schedule()

    def schedule(self):
        if self._job is None:
            self._job = self.after_idle(self.relayout)

    def relayout(self):
        self._job = None
        W = self.winfo_width()
        if W <= 1:
            W = 10 ** 6
        x, y, rowh = self._padx, self._pady, 0
        for f in self._items:
            w, h = f.winfo_reqwidth(), f.winfo_reqheight()
            if x + w > W and x > self._padx:
                x, y, rowh = self._padx, y + rowh + self._pady, 0
            f.place(x=x, y=y)
            x += w + self._padx
            rowh = max(rowh, h)
        total = y + rowh + self._pady
        if int(self.cget("height")) != total:
            self.configure(height=total)
