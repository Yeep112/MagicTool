"""中欄上方（Etching）：蝕刻紀錄表 ＋「新增紀錄」表單（先預覽、按確認才寫入、重複會提醒）。"""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..core import settings as S
from ..etching import store
from ..etching.calc import EtchInputError, REFERENCES, compute_rates, make_row
from . import theme as T
from .widgets import Chip, section_title

COLS = [("#", "#", 40, "e"), ("DateTime", "日期", 130, "w"), ("Method", "Method", 60, "w"),
        ("Power", "Power", 56, "w"), ("Bias", "Bias", 46, "w"), ("Pressure", "Pressure", 64, "w"),
        ("Gas", "Gas", 52, "w"), ("Type", "Type", 60, "w"), ("Name", "Name", 70, "w"),
        ("T (sec)", "T (s)", 50, "e"), ("R_hBN(nm/sec)", "R_hBN", 70, "e"), ("R_SiO2(nm/sec)", "R_SiO2", 70, "e")]
SOURCES = ["本機 CSV", "Google Sheet", "範例資料（唯讀）"]


class RecordsPanel(tk.Frame):
    def __init__(self, parent, page):
        super().__init__(parent, bg=T.CARD)
        self.page = page
        self.app = page.app
        key = page.inst.key
        self.key = key
        self.df = None
        self._gen = 0
        a = T.accent(key)

        head = tk.Frame(self, bg=T.CARD)
        head.pack(fill="x")
        row, _ = section_title(head, "蝕刻紀錄", "☰", a["main"])
        row.pack(side="left")
        self.count = Chip(head, "")
        self.count.pack(side="right")

        bar = tk.Frame(self, bg=T.CARD)
        bar.pack(fill="x", pady=(8, 4))
        ttk.Button(bar, text="＋ 新增紀錄", style=f"{key}.Accent.TButton", command=self.new_record).pack(side="left")
        ttk.Button(bar, text="↻", width=3, style=f"{key}.Small.TButton", command=self.reload).pack(side="left", padx=(6, 0))
        self.source_var = tk.StringVar(value=SOURCES[0])
        cb = ttk.Combobox(bar, textvariable=self.source_var, values=SOURCES, state="readonly", width=12)
        cb.pack(side="left", padx=(6, 0))
        cb.bind("<<ComboboxSelected>>", lambda e: self.reload())
        ttk.Button(bar, text="匯出 Excel", style=f"{key}.Small.TButton", command=self.export_xlsx).pack(side="right")

        self.path_lab = tk.Label(self, text="", bg=T.CHIP, fg=T.MUTED, font=T.font(9), anchor="w", padx=8, pady=3)
        self.path_lab.pack(fill="x", pady=(0, 4))

        ff = tk.Frame(self, bg=T.CARD)
        ff.pack(fill="x", pady=(0, 4))
        tk.Label(ff, text="⌕", bg=T.CARD, fg=T.MUTED, font=T.font(11)).pack(side="left", padx=(0, 4))
        self.filter_var = tk.StringVar()
        ttk.Entry(ff, textvariable=self.filter_var).pack(side="left", fill="x", expand=True)
        self.filter_var.trace_add("write", lambda *a: self._schedule_filter())
        self._filter_job = None
        tk.Label(self, text="篩選：輸入 ICP、SF6、60W… 多個條件用空白分開；沒選任何列 = 畫篩選後的全部",
                 bg=T.CARD, fg=T.FAINT, font=T.font(8), anchor="w").pack(fill="x")

        tf = tk.Frame(self, bg=T.CARD)
        tf.pack(fill="both", expand=True, pady=(4, 0))
        self.tree = ttk.Treeview(tf, columns=[c[0] for c in COLS], show="headings", selectmode="extended",
                                 style=f"{key}.Treeview")
        for c, title, w, anchor in COLS:
            self.tree.heading(c, text=title)
            self.tree.column(c, width=T.px(w), anchor=anchor, stretch=False)
        sb = ttk.Scrollbar(tf, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(tf, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=sb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tf.rowconfigure(0, weight=1)
        tf.columnconfigure(0, weight=1)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.page.on_selection())
        self.tree.bind("<Control-a>", lambda e: (self.tree.selection_set(self.tree.get_children()), "break")[1])
        self.tree.bind("<Escape>", lambda e: self.tree.selection_remove(self.tree.selection()))

    # ------------------------------------------------------------------ 讀取
    def csv_path(self):
        return S.etching_csv(self.app.settings)

    def demo_path(self):
        return S.data_dir() / "demo" / "Etching" / "etch_rate_log.csv"

    def source_path(self):
        src = self.source_var.get()
        if src == SOURCES[1]:
            return "Google Sheet"
        if src == SOURCES[2]:
            return str(self.demo_path())
        return str(self.csv_path())

    def reload(self, select_last=False):
        self._gen += 1
        gen = self._gen
        src = self.source_var.get()
        settings = self.app.settings
        et = settings.get("etching", {})
        demo = self.demo_path()
        if src == SOURCES[1]:
            self.path_lab.configure(text=f"Google Sheet：{store.parse_sheet_key(et.get('gsheet_key', '')) or '（未設定）'}")
        elif src == SOURCES[2]:
            self.path_lab.configure(text=f"範例（合成資料，唯讀；新增的紀錄仍寫到本機 CSV）：{demo}")
        else:
            self.path_lab.configure(text=f"CSV：{self.csv_path()}")
        self.count.set("讀取中…", fg=T.WARNING)

        def work():
            try:
                if src == SOURCES[1]:
                    df = store.gsheet_read(et.get("gsheet_key", ""), S.service_account_path(settings),
                                           et.get("gsheet_worksheet", ""))
                elif src == SOURCES[2]:
                    if not demo.exists():
                        from ..testdata import etching_csv
                        etching_csv(str(demo))
                    df = store.read_log(demo)
                else:
                    df = store.read_log(self.csv_path())
                self.app.post(("records", (self, gen, df, None, select_last)))
            except Exception as e:
                self.app.post(("records", (self, gen, None, str(e), select_last)))
        self.app.submit(work)

    def on_records(self, gen, df, error, select_last):
        if gen != self._gen:
            return
        if error:
            self.count.set("讀取失敗", fg=T.ERROR)
            self.app.status(f"讀取紀錄失敗：{error}", "error")
            self.df = None
            self.populate()
            return
        self.df = df
        self.populate()
        if select_last and len(df):
            last = str(int(df["#"].iloc[-1]))
            if self.tree.exists(last):
                self.tree.selection_set([last])
                self.tree.see(last)

    def filtered(self):
        if self.df is None:
            return None
        q = self.filter_var.get().strip().lower()
        if not q:
            return self.df
        cols = ["DateTime", "Method", "Power", "Bias", "Pressure", "Gas", "Type", "Name"]
        blob = self.df[cols].astype(str).agg(" ".join, axis=1).str.lower()
        mask = blob.apply(lambda s: all(t in s for t in q.split()))
        return self.df[mask]

    def populate(self):
        keep = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        df = self.filtered()
        if df is None:
            self.count.set("沒有紀錄", fg=T.MUTED)
            self.page.on_selection()
            return
        for _, r in df.iterrows():
            vals = []
            for c, *_ in COLS:
                v = r.get(c, "")
                if isinstance(v, float):
                    v = "" if v != v else (f"{v:.4g}" if "R_" in c else f"{v:g}")
                vals.append(v)
            self.tree.insert("", "end", iid=str(int(r["#"])), values=vals)
        sel = [i for i in keep if self.tree.exists(i)]
        self.count.set(f"{len(df)} 筆" + (f"（共 {len(self.df)}）" if len(df) != len(self.df) else ""), fg=T.MUTED)
        if sel:
            self.tree.selection_set(sel)
        else:
            self.page.on_selection()

    def _schedule_filter(self):
        if self._filter_job:
            self.after_cancel(self._filter_job)
        self._filter_job = self.after(150, self.populate)

    def selection_df(self):
        """選取的列；沒選 = 篩選後的全部。"""
        df = self.filtered()
        if df is None:
            return None
        sel = [int(i) for i in self.tree.selection()]
        if sel:
            return df[df["#"].isin(sel)]
        return df

    def selection_signature(self):
        return (self._gen, self.filter_var.get(), tuple(self.tree.selection()))

    # ------------------------------------------------------------------ 新增 / 匯出
    def new_record(self):
        EtchForm(self)

    def export_xlsx(self):
        df = self.filtered()
        if df is None or df.empty:
            messagebox.showinfo("匯出 Excel", "沒有紀錄可以匯出", parent=self)
            return
        fp = filedialog.asksaveasfilename(parent=self, title="匯出 Excel", defaultextension=".xlsx",
                                          initialfile="etch_rate_log.xlsx", filetypes=[("Excel", "*.xlsx")])
        if not fp:
            return
        try:
            store.export_xlsx(df, fp)
            self.app.status(f"已匯出 {len(df)} 筆到 {fp}", "ok")
        except Exception as e:
            messagebox.showerror("匯出 Excel", f"匯出失敗：{e}", parent=self)


FIELDS = [
    ("method", "Method", "ICP"), ("power", "Power", "60W"), ("bias", "Bias", "5V"), ("pressure", "Pressure", "1Pa"),
    ("gas", "Gas", "SF6"), ("sample_type", "Type", "direct"), ("name", "Name", ""), ("t", "蝕刻時間 T (sec)", "30"),
]
HEIGHTS = [("hbn_before", "hBN 蝕刻前 (nm)"), ("hbn_after", "hBN 蝕刻後 (nm)"),
           ("marker_before", "marker 蝕刻前 (nm)"), ("marker_after", "marker 蝕刻後 (nm)"),
           ("sio2_before", "SiO2 蝕刻前 (nm)"), ("sio2_after", "SiO2 蝕刻後 (nm)")]


class EtchForm(tk.Toplevel):
    """新增一筆蝕刻紀錄。輸入時即時顯示算出的速率；按「寫入」才存檔。"""

    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        self.app = panel.app
        key = panel.key
        self.title("新增蝕刻紀錄")
        self.configure(bg=T.CARD)
        self.transient(panel.winfo_toplevel())
        a = T.accent(key)
        head = tk.Frame(self, bg=a["main"], padx=16, pady=10)
        head.pack(fill="x")
        tk.Label(head, text="新增蝕刻紀錄", bg=a["main"], fg="white", font=T.font(13, "bold")).pack(anchor="w")
        tk.Label(head, text="輸入 AFM 量到的高度；下方會即時算出速率，按「寫入」才會存檔", bg=a["main"],
                 fg=T.mix_color("#ffffff", a["main"], 0.25), font=T.font(9)).pack(anchor="w")
        body = tk.Frame(self, bg=T.CARD, padx=16, pady=10)
        body.pack(fill="both", expand=True)
        last = self.app.state.setdefault("etch_last", {})
        df = panel.df
        self.vars = {}
        tk.Label(body, text="條件", bg=T.CARD, fg=T.FAINT, font=T.font(9, "bold")).grid(row=0, column=0, sticky="w")
        for i, (k, label, default) in enumerate(FIELDS):
            r, c = 1 + i // 2, (i % 2) * 2
            tk.Label(body, text=label, bg=T.CARD, fg=T.TEXT, font=T.font(9)).grid(row=r, column=c, sticky="w",
                                                                                  padx=(0 if c == 0 else 14, 6), pady=3)
            var = tk.StringVar(value=str(last.get(k, default)))
            hist_col = {"method": "Method", "power": "Power", "bias": "Bias", "pressure": "Pressure", "gas": "Gas",
                        "sample_type": "Type", "name": "Name"}.get(k)
            if hist_col and df is not None and hist_col in df.columns:
                values = [v for v in dict.fromkeys(df[hist_col].astype(str)) if v.strip()][-30:]
                w = ttk.Combobox(body, textvariable=var, values=values, width=14)
            else:
                w = ttk.Entry(body, textvariable=var, width=16)
            w.grid(row=r, column=c + 1, sticky="ew", pady=3)
            self.vars[k] = var
        base = 2 + len(FIELDS) // 2
        tk.Label(body, text="高度（AFM）", bg=T.CARD, fg=T.FAINT, font=T.font(9, "bold")).grid(
            row=base, column=0, sticky="w", pady=(10, 0))
        for i, (k, label) in enumerate(HEIGHTS):
            r, c = base + 1 + i // 2, (i % 2) * 2
            tk.Label(body, text=label, bg=T.CARD, fg=T.TEXT, font=T.font(9)).grid(row=r, column=c, sticky="w",
                                                                                  padx=(0 if c == 0 else 14, 6), pady=3)
            var = tk.StringVar(value="")
            ttk.Entry(body, textvariable=var, width=16).grid(row=r, column=c + 1, sticky="ew", pady=3)
            self.vars[k] = var
        rr = base + 1 + len(HEIGHTS) // 2
        tk.Label(body, text="參考層", bg=T.CARD, fg=T.TEXT, font=T.font(9)).grid(row=rr, column=0, sticky="w", pady=(8, 0))
        self.ref_var = tk.StringVar(value=last.get("reference", "auto"))
        rf = tk.Frame(body, bg=T.CARD)
        rf.grid(row=rr, column=1, columnspan=3, sticky="w", pady=(8, 0))
        for ref, text in zip(REFERENCES, ["自動（有 marker 用 marker）", "marker", "SiO2"]):
            ttk.Radiobutton(rf, text=text, value=ref, variable=self.ref_var,
                            style=f"{key}.TRadiobutton").pack(side="left", padx=(0, 10))
        self.preview = tk.Label(body, text="", bg=T.SUBTLE, fg=T.TEXT, font=T.font(10), justify="left", anchor="w",
                                padx=10, pady=8, wraplength=T.px(520))
        self.preview.grid(row=rr + 1, column=0, columnspan=4, sticky="ew", pady=(12, 0))
        body.columnconfigure(1, weight=1)
        body.columnconfigure(3, weight=1)
        bf = tk.Frame(self, bg=T.CARD, padx=16, pady=10)
        bf.pack(fill="x")
        self.keep_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(bf, text="寫入後繼續新增下一筆", variable=self.keep_var,
                        style=f"{key}.TCheckbutton").pack(side="left")
        self.ok_btn = ttk.Button(bf, text="寫入紀錄", style=f"{key}.Accent.TButton", command=self.save)
        self.ok_btn.pack(side="right")
        ttk.Button(bf, text="取消", style=f"{key}.Ghost.TButton", command=self.destroy).pack(side="right", padx=6)
        for v in list(self.vars.values()) + [self.ref_var]:
            v.trace_add("write", lambda *a: self.update_preview())
        self.bind("<Escape>", lambda e: self.destroy())
        self.update_preview()
        self.update_idletasks()
        try:
            root = panel.winfo_toplevel()
            x = root.winfo_rootx() + (root.winfo_width() - self.winfo_reqwidth()) // 2
            y = root.winfo_rooty() + 80
            self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        except Exception:
            pass
        self.grab_set()

    def _inputs(self):
        v = {k: var.get().strip() for k, var in self.vars.items()}
        return v

    def _compute(self):
        v = self._inputs()
        return v, compute_rates(v["hbn_before"], v["hbn_after"], v["t"], v["marker_before"] or None,
                                v["marker_after"] or None, v["sio2_before"] or None, v["sio2_after"] or None,
                                reference=self.ref_var.get())

    def update_preview(self):
        try:
            v, r = self._compute()
        except EtchInputError as e:
            self.preview.configure(text=f"還不能寫入：{e}", fg=T.MUTED)
            self.ok_btn.state(["disabled"])
            return
        lines = [f"R_hBN = {r['R_hBN']:.4g} nm/sec　　R_SiO2 = {r['R_SiO2']:.4g} nm/sec　（參考：{r['reference']}）",
                 f"Δ_hBN = {r['delta_hBN']:.4g} nm、參考層被蝕刻 {r['delta_marker']:.4g} nm"]
        lines += ["⚠ " + w for w in r["warnings"]]
        self.preview.configure(text="\n".join(lines), fg=T.WARNING if r["warnings"] else T.TEXT)
        self.ok_btn.state(["!disabled"])

    def save(self):
        try:
            v, rates = self._compute()
        except EtchInputError as e:
            messagebox.showwarning("新增蝕刻紀錄", str(e), parent=self)
            return
        row = make_row(rates, hbn_before=v["hbn_before"], hbn_after=v["hbn_after"], t=v["t"],
                       marker_before=v["marker_before"] or None, marker_after=v["marker_after"] or None,
                       sio2_before=v["sio2_before"] or None, sio2_after=v["sio2_after"] or None,
                       method=v["method"], power=v["power"], bias=v["bias"], pressure=v["pressure"],
                       sample_type=v["sample_type"], name=v["name"], gas=v["gas"])
        path = self.panel.csv_path()
        try:
            existing = store.read_log(path)
        except Exception:
            existing = None
        dup = store.find_duplicates(existing, row)
        if dup and not messagebox.askyesno(
                "可能重複", f"第 {', '.join(map(str, dup))} 筆的輸入和這筆完全一樣。\n還是要寫入嗎？", parent=self):
            return
        msg = store.header_mismatch(path)
        try:
            store.append_csv(row, path)
        except OSError as e:
            messagebox.showerror("新增蝕刻紀錄", f"寫入 CSV 失敗（檔案是不是被 Excel 開著？）：\n{e}", parent=self)
            return
        et = self.app.settings.get("etching", {})
        notes = [f"已寫入 {os.path.basename(str(path))}"] + ([msg] if msg else [])
        if et.get("xlsx_mirror"):
            try:
                store.append_xlsx(row, os.path.splitext(str(path))[0] + ".xlsx")
                notes.append("Excel 也已更新")
            except Exception as e:
                notes.append(f"Excel 更新失敗：{e}")
        if et.get("gsheet_enabled"):
            settings = self.app.settings

            def work():
                try:
                    store.gsheet_append(row, et.get("gsheet_key", ""), S.service_account_path(settings),
                                        et.get("gsheet_worksheet", ""))
                    self.app.post(("status", ("Google Sheet 也已寫入", "ok")))
                except Exception as e:
                    self.app.post(("status", (f"Google Sheet 寫入失敗（本機 CSV 已存好）：{e}", "error")))
            self.app.submit(work)
            notes.append("Google Sheet 寫入中…")
        last = self.app.state.setdefault("etch_last", {})
        for k, _, _ in FIELDS:
            last[k] = v[k]
        last["reference"] = self.ref_var.get()
        self.app.save_state_soon()
        self.app.status("；".join(notes), "ok")
        self.panel.source_var.set(SOURCES[0])
        self.panel.reload(select_last=True)
        if self.keep_var.get():
            for k, _ in HEIGHTS:
                self.vars[k].set("")
        else:
            self.destroy()
