"""OM（光學顯微鏡）照片：蝕刻前、後各一張（選填）。

‧ 精靈裡的 OMSlot：選圖、預覽縮圖、移除；點縮圖放大看
‧ 紀錄表的「🖼 OM」：選一筆紀錄，並排看蝕刻前 / 後
‧ 照片會複製到紀錄 CSV 旁邊的「<檔名>_images」資料夾（檔名 = Record ID_before / _after），
  CSV 只記相對路徑，整個資料夾搬家也找得到；原始照片不會被修改或移動
"""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, ttk

from . import theme as T
from .widgets import fit_window

FILETYPES = [("圖片", "*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.gif"), ("全部", "*.*")]


def open_image(path):
    """讀圖 → RGB 的 PIL Image（16 bit 的 TIFF 也能看）。失敗回傳 None。"""
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        img = Image.open(path)
        img.load()
    except Exception:
        return None
    if img.mode in ("I;16", "I;16B", "I;16L", "I", "F"):
        import numpy as np
        a = np.asarray(img, dtype=float)
        lo, hi = np.percentile(a, [0.5, 99.5])
        a = np.clip((a - lo) / ((hi - lo) or 1.0) * 255, 0, 255).astype("uint8")
        img = Image.fromarray(a)
    return img.convert("RGB")


def photo(path, box):
    """縮成放得進 box=(寬, 高) 的 PhotoImage（保持長寬比）。"""
    img = open_image(path)
    if img is None:
        return None
    from PIL import ImageTk
    w, h = max(int(box[0]), 10), max(int(box[1]), 10)
    img.thumbnail((w, h))
    return ImageTk.PhotoImage(img)


class OMSlot(tk.Frame):
    """一張照片的位置：縮圖 + 選圖 / 移除。value = 圖檔的絕對路徑或 None。"""

    def __init__(self, parent, title, key, on_change=None, size=(220, 150)):
        super().__init__(parent, bg=T.CARD, highlightthickness=1, highlightbackground=T.BORDER, padx=6, pady=6)
        self.key = key
        self.title = title
        self.size = size
        self.on_change = on_change
        self.value = None
        self._img = None
        tk.Label(self, text=title, bg=T.CARD, fg=T.TEXT, font=T.font(9, "bold"), anchor="w").pack(fill="x")
        self.view = tk.Label(self, text="（沒有照片）\n點「選圖…」", bg=T.SUBTLE, fg=T.FAINT, font=T.font(9),
                             width=T.px(size[0]) // 8, height=6, cursor="hand2")
        self.view.pack(pady=4)
        self.view.bind("<Button-1>", lambda e: self.show_large())
        self.name = tk.Label(self, text="", bg=T.CARD, fg=T.MUTED, font=T.font(8), anchor="w")
        self.name.pack(fill="x")
        bf = tk.Frame(self, bg=T.CARD)
        bf.pack(fill="x", pady=(2, 0))
        ttk.Button(bf, text="選圖…", style=f"{key}.Small.TButton", command=self.choose).pack(side="left")
        self.rm = ttk.Button(bf, text="移除", style=f"{key}.Small.TButton", command=lambda: self.set(None))
        self.rm.pack(side="left", padx=4)
        self.set(None, notify=False)

    def choose(self):
        app = getattr(self.winfo_toplevel(), "app", None)
        state = app.state if app is not None else {}
        fp = filedialog.askopenfilename(parent=self, title=f"選 {self.title}", filetypes=FILETYPES,
                                        initialdir=state.get("om_dir") or os.path.expanduser("~"))
        if fp:
            state["om_dir"] = os.path.dirname(fp)
            self.set(fp)

    def set(self, path, notify=True):
        self.value = path if path else None
        if self.value and os.path.isfile(self.value):
            ph = photo(self.value, (T.px(self.size[0]), T.px(self.size[1])))
            if ph is not None:
                self._img = ph
                self.view.configure(image=ph, text="", width=0, height=0)
            else:
                self._img = None
                self.view.configure(image="", text="（看不了這個格式的預覽）\n仍會存起來", width=T.px(self.size[0]) // 8,
                                    height=6)
            self.name.configure(text=os.path.basename(self.value), fg=T.MUTED)
            self.rm.state(["!disabled"])
        else:
            self._img = None
            missing = bool(path) and not os.path.isfile(path)
            self.view.configure(image="", text="（找不到檔案）" if missing else "（沒有照片）\n點「選圖…」",
                                width=T.px(self.size[0]) // 8, height=6)
            self.name.configure(text=os.path.basename(path) if missing else "選填", fg=T.ERROR if missing else T.FAINT)
            self.rm.state(["disabled"] if not path else ["!disabled"])
        if notify and self.on_change:
            self.on_change()

    def show_large(self):
        if self.value and os.path.isfile(self.value):
            OMViewer(self.winfo_toplevel(), [(self.title, self.value)], self.key)


class OMViewer(tk.Toplevel):
    """並排看照片（跟著視窗大小縮放）。items = [(標題, 路徑或 None)]。"""

    def __init__(self, parent, items, key, title="OM 照片"):
        super().__init__(parent)
        self.title(title)
        self.configure(bg=T.CARD)
        self.transient(parent)
        fit_window(self, T.px(1100 if len(items) > 1 else 760), T.px(620), T.px_min(420), T.px_min(320))
        self.items = items
        self.labels = []
        self._imgs = []
        self._job = None
        body = tk.Frame(self, bg=T.CARD)
        body.pack(fill="both", expand=True, padx=10, pady=10)
        for k, (name, path) in enumerate(items):
            f = tk.Frame(body, bg=T.CARD)
            f.grid(row=0, column=k, sticky="nsew", padx=6)
            body.columnconfigure(k, weight=1)
            tk.Label(f, text=name, bg=T.CARD, fg=T.accent(key)["text"], font=T.font(11, "bold")).pack(anchor="w")
            tk.Label(f, text=path or "（沒有照片）", bg=T.CARD, fg=T.MUTED, font=T.font(8), anchor="w",
                     wraplength=T.px(480)).pack(fill="x")
            lab = tk.Label(f, bg=T.SUBTLE, text="" if path else "沒有照片", fg=T.FAINT)
            lab.pack(fill="both", expand=True, pady=(4, 0))
            self.labels.append((lab, path))
        body.rowconfigure(0, weight=1)
        self.bind("<Configure>", lambda e: self._schedule())
        self.bind("<Escape>", lambda e: self.destroy())
        self.after(80, self._render)

    def _schedule(self):
        if self._job is not None:
            self.after_cancel(self._job)
        self._job = self.after(150, self._render)

    def _render(self):
        self._job = None
        self._imgs = []
        for lab, path in self.labels:
            if not path or not os.path.isfile(path):
                continue
            w, h = max(lab.winfo_width(), 200), max(lab.winfo_height(), 150)
            ph = photo(path, (w - 4, h - 4))
            if ph is None:
                lab.configure(text="看不了這個格式的預覽", image="")
                continue
            self._imgs.append(ph)
            lab.configure(image=ph, text="")
