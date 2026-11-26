"""中欄上方（PPMS / SQUID / Raman）：資料夾裡的檔案清單。掃描與判斷檔案種類都在背景進行。"""
from __future__ import annotations

import fnmatch
import os
import sys
import time
import tkinter as tk
from tkinter import filedialog, ttk

from . import theme as T
from .widgets import Chip, section_title

KIND_NAMES = {"PPMS": "PPMS", "SQUID": "SQUID", "QD": "QD", "Raman": "光譜", "?": "?", "": "…"}


def _size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


class FilePanel(tk.Frame):
    def __init__(self, parent, page):
        super().__init__(parent, bg=T.CARD)
        self.page = page
        self.app = page.app
        key = page.inst.key
        self.key = key
        self.folder = ""
        self.files = []                     # [dict(path, name, size, mtime, kind)]
        self._scan_gen = 0
        a = T.accent(key)

        head = tk.Frame(self, bg=T.CARD)
        head.pack(fill="x")
        row, _ = section_title(head, f"{page.inst.title} 資料", "☰", a["main"])
        row.pack(side="left")
        self.count = Chip(head, "")
        self.count.pack(side="right")

        fr = tk.Frame(self, bg=T.CARD)
        fr.pack(fill="x", pady=(8, 4))
        self.folder_lab = tk.Label(fr, text="（還沒有選資料夾）", bg=T.CHIP, fg=T.MUTED, font=T.font(9), anchor="w",
                                   padx=8, pady=4)
        self.folder_lab.pack(side="left", fill="x", expand=True)
        ttk.Button(fr, text="↻", width=3, style=f"{key}.Small.TButton", command=self.rescan).pack(side="right", padx=(4, 0))
        ttk.Button(fr, text="選檔案", style=f"{key}.Small.TButton", command=self.pick_files).pack(side="right", padx=(4, 0))
        ttk.Button(fr, text="選資料夾", style=f"{key}.Small.TButton", command=self.pick_folder).pack(side="right", padx=(4, 0))

        ff = tk.Frame(self, bg=T.CARD)
        ff.pack(fill="x", pady=(0, 4))
        tk.Label(ff, text="⌕", bg=T.CARD, fg=T.MUTED, font=T.font(11)).pack(side="left", padx=(0, 4))
        self.filter_var = tk.StringVar()
        ent = ttk.Entry(ff, textvariable=self.filter_var)
        ent.pack(side="left", fill="x", expand=True)
        self.filter_var.trace_add("write", lambda *a: self._schedule_filter())
        self._filter_job = None
        self.sub_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(ff, text="含子資料夾", variable=self.sub_var, style=f"{key}.TCheckbutton",
                        command=self.rescan).pack(side="left", padx=(8, 0))

        tf = tk.Frame(self, bg=T.CARD)
        tf.pack(fill="both", expand=True)
        cols = ("name", "kind", "size", "mtime")
        self.tree = ttk.Treeview(tf, columns=cols, show="headings", selectmode="extended", style=f"{key}.Treeview")
        for c, title, w, anchor, stretch in (("name", "檔名", 190, "w", True), ("kind", "種類", 52, "center", False),
                                             ("size", "大小", 66, "e", False), ("mtime", "修改時間", 118, "w", False)):
            self.tree.heading(c, text=title, command=lambda c=c: self.sort_by(c))
            self.tree.column(c, width=T.px(w), anchor=anchor, stretch=stretch)
        sb = ttk.Scrollbar(tf, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(tf, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=sb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tf.rowconfigure(0, weight=1)
        tf.columnconfigure(0, weight=1)
        self.tree.tag_configure("other", foreground=T.FAINT)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.page.on_selection())
        self.tree.bind("<Control-a>", lambda e: (self.select_all(), "break")[1])
        if sys.platform == "darwin":
            self.tree.bind("<Command-a>", lambda e: (self.select_all(), "break")[1])
        self._sort = ("mtime", True)

        self.empty = tk.Frame(tf, bg=T.CARD)
        self.empty_title = tk.Label(self.empty, text="選一個放資料檔的資料夾", bg=T.CARD, fg=T.TEXT,
                                    font=T.font(11, "bold"))
        self.empty_title.pack(pady=(30, 4))
        tk.Label(self.empty, text=f"{page.inst.help}（{'、'.join(page.inst.patterns)}）", bg=T.CARD, fg=T.MUTED,
                 font=T.font(9), wraplength=T.px(320)).pack()
        ttk.Button(self.empty, text="選資料夾", style=f"{key}.Accent.TButton", command=self.pick_folder).pack(pady=10)
        ttk.Button(self.empty, text="先用範例資料試試看", style=f"{key}.Ghost.TButton",
                   command=self.app.open_demo).pack()
        self.empty.grid(row=0, column=0, sticky="nsew")

    # ------------------------------------------------------------------ 資料夾
    def pick_folder(self):
        start = self.folder or self.app.settings.get("folders", {}).get(self.key) or os.path.expanduser("~")
        d = filedialog.askdirectory(title=f"選擇 {self.page.inst.title} 資料夾", initialdir=start, parent=self)
        if d:
            self.set_folder(d)

    def pick_files(self):
        start = self.folder or os.path.expanduser("~")
        pats = " ".join(self.page.inst.patterns)
        fps = filedialog.askopenfilenames(title=f"選擇 {self.page.inst.title} 檔案", initialdir=start, parent=self,
                                          filetypes=[(f"{self.page.inst.title} 檔案", pats), ("所有檔案", "*.*")])
        if fps:
            self.set_folder(os.path.dirname(fps[0]), select=[os.path.normpath(p) for p in fps])

    def set_folder(self, folder, select=None):
        folder = os.path.normpath(folder)
        self.folder = folder
        self.folder_lab.configure(text=self._short(folder), fg=T.TEXT)
        self.page.remember(folder=folder)
        self.rescan(select=select)

    @staticmethod
    def _short(path, n=60):
        return path if len(path) <= n else "…" + path[-(n - 1):]

    def rescan(self, select=None):
        if not self.folder:
            return
        if select is None:
            select = self.selected_paths()
        self._scan_gen += 1
        gen, folder, deep = self._scan_gen, self.folder, bool(self.sub_var.get())
        pats = [p.lower() for p in self.page.inst.patterns]
        self.count.set("掃描中…", fg=T.WARNING)

        def work():
            found = []
            try:
                errs = []
                walker = os.walk(folder, onerror=errs.append) if deep else [(folder, [], os.listdir(folder))]
                for root, dirs, names in walker:
                    if deep:
                        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "MagicTool 輸出"]
                    for n in names:
                        if any(fnmatch.fnmatch(n.lower(), p) for p in pats):
                            fp = os.path.join(root, n)
                            try:
                                st = os.stat(fp)
                            except OSError:
                                continue
                            found.append(dict(path=os.path.normpath(fp),
                                              name=os.path.relpath(fp, folder) if deep else n,
                                              size=st.st_size, mtime=st.st_mtime, kind=""))
                    if len(found) > 5000:
                        break
                if deep and errs and not found and isinstance(errs[0], PermissionError):
                    raise errs[0]
            except OSError as e:
                from .launcher import permission_hint
                self.app.post(("status", (f"讀不到資料夾：{e}{permission_hint(e)}", "error")))
                return
            self.app.post(("files", (self, gen, found, select)))
            # 判斷種類（讀檔頭）：慢一點，分批回報
            from ..readers import detect
            batch = []
            for f in found:
                if gen != self._scan_gen:
                    return
                batch.append((f["path"], detect(f["path"])))
                if len(batch) >= 40:
                    self.app.post(("kinds", (self, gen, batch)))
                    batch = []
            if batch:
                self.app.post(("kinds", (self, gen, batch)))
        self.app.submit(work)

    def on_files(self, gen, found, select):
        if gen != self._scan_gen:
            return
        self.files = found
        if not found:
            self.empty_title.configure(text=f"這個資料夾裡沒有 {'、'.join(self.page.inst.patterns)} 檔案")
            self.empty.grid()
            self.empty.tkraise()
            self.count.set("沒有符合的檔案", fg=T.WARNING)
            self.tree.delete(*self.tree.get_children())
            self.page.on_selection()
            return
        self.empty.grid_remove()
        self.populate(select)

    def on_kinds(self, gen, batch):
        if gen != self._scan_gen:
            return
        by = {f["path"]: f for f in self.files}
        own = self.page.inst.key
        for path, kind in batch:
            f = by.get(path)
            if f is None:
                continue
            f["kind"] = kind
            if self.tree.exists(path):
                self.tree.set(path, "kind", KIND_NAMES.get(kind, kind))
                other = (own in ("PPMS", "SQUID") and kind in ("PPMS", "SQUID") and kind != own) or \
                        (own == "Raman" and kind not in ("Raman", ""))
                self.tree.item(path, tags=("other",) if other else ())

    def visible_files(self):
        q = self.filter_var.get().strip().lower()
        fs = self.files
        if q:
            terms = q.split()
            fs = [f for f in fs if all(t in f["name"].lower() for t in terms)]
        key, rev = self._sort
        return sorted(fs, key=lambda f: (f[key] if key != "kind" else f["kind"]), reverse=rev)

    def populate(self, select=None):
        keep = set(select if select is not None else self.selected_paths())
        self.tree.delete(*self.tree.get_children())
        vis = self.visible_files()
        for f in vis:
            self.tree.insert("", "end", iid=f["path"],
                             values=(f["name"], KIND_NAMES.get(f["kind"], f["kind"]), _size(f["size"]),
                                     time.strftime("%Y-%m-%d %H:%M", time.localtime(f["mtime"]))))
        sel = [p for p in keep if self.tree.exists(p)]
        self.count.set(f"{len(vis)} 個檔案" + (f"（共 {len(self.files)}）" if len(vis) != len(self.files) else ""),
                       fg=T.MUTED)
        if sel:
            self.tree.selection_set(sel)
            self.tree.see(sel[0])
        else:
            self.page.on_selection()

    def _schedule_filter(self):
        if self._filter_job:
            self.after_cancel(self._filter_job)
        self._filter_job = self.after(150, self.populate)

    def sort_by(self, col):
        key = {"name": "name", "kind": "kind", "size": "size", "mtime": "mtime"}[col]
        cur, rev = self._sort
        self._sort = (key, not rev if cur == key else key in ("mtime", "size"))
        self.populate()

    def selected_paths(self):
        return list(self.tree.selection())

    def select_all(self):
        self.tree.selection_set(self.tree.get_children())
