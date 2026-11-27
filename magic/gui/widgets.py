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


def keep_figure_fit(canvas):
    """額外視窗裡的 matplotlib 圖：視窗出現後，把圖的大小對齊畫布的實際大小。

    Windows 螢幕縮放（125%、150%…）時，舊版 matplotlib 在視窗出現（<Map>）時會依縮放把圖放大，
    但畫布被版面限制住、沒有收到 <Configure>，圖就比畫布大、下面被切掉（跑版）。
    回傳 fit()，需要時也可以直接呼叫。"""
    w = canvas.get_tk_widget()

    def fit():
        try:
            ww, wh = int(w.winfo_width()), int(w.winfo_height())
        except tk.TclError:
            return False
        if ww < 20 or wh < 20:
            return False
        try:
            fw, fh = canvas.get_width_height(physical=True)
        except TypeError:                      # 很舊的 matplotlib
            fw, fh = (int(v) for v in canvas.figure.bbox.size)
        if abs(fw - ww) <= 1 and abs(fh - wh) <= 1:
            return False

        class _Size:
            width, height = ww, wh
        canvas.resize(_Size())
        canvas.draw_idle()
        return True

    def later(_=None):
        w.after_idle(fit)
        w.after(200, fit)                      # 有些電腦視窗出現後還會再調整一次大小
    w.bind("<Map>", later, add="+")
    return fit


def set_if_changed(widget, **opts):
    """只有設定值真的改變時才 configure：頁面每次重新顯示都會收到 <Configure>，
    無條件重設（例如 wraplength）會讓 Tk 多排版、重畫一輪，切換機台就變慢。"""
    changed = {}
    for k, v in opts.items():
        try:
            if str(widget.cget(k)) != str(v):
                changed[k] = v
        except tk.TclError:
            changed[k] = v
    if changed:
        widget.configure(**changed)


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
        self._sr = None
        self._bw = None
        self.body.bind("<Configure>", self._on_body)
        self.canvas.bind("<Configure>", self._on_canvas)
        for w in (self.canvas, self.body):
            w.bind("<Enter>", self._bind_wheel)
            w.bind("<Leave>", self._unbind_wheel)

    def _on_body(self, _=None):
        sr = self.canvas.bbox("all")
        if sr != self._sr:                    # 沒變就不要重設（重設會讓 Tk 再排版、重畫一次）
            self._sr = sr
            self.canvas.configure(scrollregion=sr)

    def _on_canvas(self, e):
        if e.width != self._bw:
            self._bw = e.width
            self.canvas.itemconfigure(self._win, width=e.width)

    def _bind_wheel(self, _=None):
        self.canvas.bind_all("<MouseWheel>", self._on_wheel)
        self.canvas.bind_all("<Button-4>", lambda e: self._scroll(-2))
        self.canvas.bind_all("<Button-5>", lambda e: self._scroll(2))

    def _unbind_wheel(self, _=None):
        """滑鼠移到裡面的元件上（例如圖、按鈕）也算還在裡面：真的離開才取消滾輪。"""
        def check():
            try:
                w = self.winfo_containing(*self.winfo_pointerxy())
            except Exception:
                w = None
            while w is not None:
                if w is self:
                    return
                w = getattr(w, "master", None)
            for ev in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                try:
                    self.canvas.unbind_all(ev)
                except tk.TclError:
                    pass
        try:
            self.after_idle(check)
        except tk.TclError:
            pass

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


class WrapRow(tk.Frame):
    """一排按鈕：寬度不夠就自動換到下一行（不會被擠扁、文字不會被切掉）。

    row = WrapRow(parent); ttk.Button(row, …) 建好之後 row.add(按鈕, side="left" / "right", expand=False)。
    依目前寬度把元件分到幾行；分法沒變就不重排（切換頁面時不會多做事）。"""

    def __init__(self, parent, bg=None, padx=4, pady=2, **kw):
        super().__init__(parent, bg=bg if bg is not None else parent.cget("bg"), **kw)
        self.padx, self.pady = padx, pady
        self._items = []
        self._rows = []
        self._plan = None
        self._width = 0
        self.bind("<Configure>", self._on_conf, add="+")

    def add(self, w, side="left", expand=False, padx=None):
        self._items.append((w, side, expand, self.padx if padx is None else padx))
        self._plan = None
        self._relayout()
        return w

    def set_visible(self, w, show=True):
        """顯示 / 隱藏其中一個元件（例如「建立紀錄檔」只有還沒有紀錄檔時才出現）。"""
        hidden = getattr(self, "_hidden", set())
        self._hidden = hidden
        if (w not in hidden) == bool(show):
            return
        (hidden.discard if show else hidden.add)(w)
        self._plan = None
        self._relayout()

    def _on_conf(self, e):
        if abs(e.width - self._width) > 1:
            self._width = e.width
            self._relayout()

    def _relayout(self):
        width = self._width if self._width > 1 else 10 ** 6
        rows, used = [[]], 0
        hidden = getattr(self, "_hidden", set())
        for i, (w, side, exp, px) in enumerate(self._items):
            if w in hidden:
                continue
            need = w.winfo_reqwidth() + px
            if rows[-1] and used + need > width:
                rows.append([])
                used = 0
            rows[-1].append(i)
            used += need
        plan = tuple(tuple(r) for r in rows)
        if plan == self._plan:
            return
        self._plan = plan
        while len(self._rows) < len(rows):
            self._rows.append(tk.Frame(self, bg=self.cget("bg")))
        for w, *_ in self._items:
            w.pack_forget()
        for k, fr in enumerate(self._rows):
            if k < len(rows):
                fr.pack(fill="x", pady=(0 if k == 0 else self.pady, 0))
            else:
                fr.pack_forget()
        for k, r in enumerate(rows):
            fr = self._rows[k]
            lefts = [i for i in r if self._items[i][1] != "right"]
            rights = [i for i in r if self._items[i][1] == "right"]
            for n, i in enumerate(lefts):
                w, _, exp, px = self._items[i]
                w.pack(in_=fr, side="left", padx=(0 if n == 0 else px, 0), fill="x" if exp else None, expand=exp)
                w.lift(fr)
            for n, i in enumerate(reversed(rights)):
                w, _, exp, px = self._items[i]
                w.pack(in_=fr, side="right", padx=(px, 0) if n < len(rights) - 1 or lefts else (0, 0),
                       fill="x" if exp else None, expand=exp)
                w.lift(fr)


def fit_label(label, pad=2):
    """文字跟著實際寬度換行（欄位變窄時不會被切掉）。"""
    def on(e):
        try:
            inner = 2 * (int(float(str(label.cget("padx")))) + int(float(str(label.cget("bd")))) +
                         int(float(str(label.cget("highlightthickness")))))
        except (ValueError, tk.TclError):
            inner = 0
        w = e.width - pad - inner
        if w > 30:
            try:
                cur = int(float(str(label.cget("wraplength") or 0)))
            except (ValueError, tk.TclError):
                cur = 0
            if abs(cur - w) > 2:
                label.configure(wraplength=w)
    label.bind("<Configure>", on, add="+")
    return label


def auto_wrap(container, min_len=18):
    """把 container 裡面的長文字 Label 都設成跟著寬度換行。"""
    for w in container.winfo_children():
        if w.winfo_class() == "Label" and not getattr(w, "_no_wrap", False):
            try:
                text = str(w.cget("text") or "")
            except tk.TclError:
                text = ""
            if len(text) >= min_len and not str(w.cget("image") or ""):
                fit_label(w)
        auto_wrap(w, min_len)


def fit_window(win, w, h, minw=None, minh=None, center=True):
    """視窗大小不超過螢幕（扣掉工作列與標題列），放在螢幕裡面。內容比視窗大的部分要用 ScrollFrame 捲動。"""
    try:
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    except tk.TclError:
        return
    w, h = max(200, min(int(w), sw - 40)), max(150, min(int(h), sh - 100))
    geo = f"{w}x{h}"
    if center:
        try:
            m = win.master.winfo_toplevel()
            x = m.winfo_rootx() + (m.winfo_width() - w) // 2
            y = m.winfo_rooty() + (m.winfo_height() - h) // 3
        except (tk.TclError, AttributeError):
            x, y = (sw - w) // 2, (sh - h) // 3
        x, y = max(0, min(x, sw - w - 10)), max(0, min(y, sh - h - 60))
        geo += f"+{x}+{y}"
    win.geometry(geo)
    win.minsize(min(int(minw or 300), w), min(int(minh or 200), h))


def fit_to_content(win, extra_w=0, extra_h=0, minw=None, minh=None):
    """依內容需要的大小開視窗（超過螢幕就縮到螢幕大小，剩下的靠捲動）。"""
    try:
        win.update_idletasks()
        fit_window(win, win.winfo_reqwidth() + extra_w, win.winfo_reqheight() + extra_h, minw, minh)
    except tk.TclError:
        pass


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


class NavBar(Segmented):
    """上方切換列，分組顯示：groups = [(組名, [(key, 標題, 副標), …]), …]。
    用法和 Segmented 一樣（select(key)、buttons、active），只是每組上面有一個小標題（製程 / 量測）。"""

    def __init__(self, parent, groups, command, bg=None):
        bg = bg or T.CHIP
        tk.Frame.__init__(self, parent, bg=bg, padx=3, pady=2)
        self.command = command
        self.buttons = []
        self.active = 0
        self._bg = bg
        self._fg_off = T.HEADER_MUTED if bg == T.HEADER_2 else T.MUTED
        self._sub_off = "#6f80a8" if bg == T.HEADER_2 else T.FAINT
        col = 0
        for gi, (gname, options) in enumerate(groups):
            if gi:
                tk.Frame(self, bg=self._sub_off, width=1).grid(row=0, column=col, rowspan=2, sticky="ns", padx=8, pady=4)
                col += 1
            tk.Label(self, text=gname, bg=bg, fg=self._sub_off, font=T.font(8, "bold"), anchor="w").grid(
                row=0, column=col, columnspan=len(options), sticky="w", padx=(6, 0))
            for key, title, sub in options:
                i = len(self.buttons)
                b = tk.Frame(self, bg=bg, cursor="hand2", padx=12, pady=4)
                t = tk.Label(b, text=title, bg=bg, fg=self._fg_off, font=T.font(11, "bold"), cursor="hand2")
                s_ = tk.Label(b, text=sub, bg=bg, fg=self._sub_off, font=T.font(8), cursor="hand2")
                t.pack(anchor="w")
                s_.pack(anchor="w")
                b.grid(row=1, column=col, sticky="nsew", padx=1)
                self.columnconfigure(col, weight=1, uniform="seg")
                for w in (b, t, s_):
                    w.bind("<Button-1>", lambda e, i=i: self.select(i))
                self.buttons.append((key, b, t, s_))
                col += 1
        self.paint()


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
