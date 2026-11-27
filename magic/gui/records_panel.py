"""中欄上方（Etching）：蝕刻紀錄表 ＋「新增紀錄」精靈（etch_wizard：流程示意圖、量法、即時結果）。

舊格式（v1，20 欄）的紀錄會顯示提示列，可以先升級（會先備份）；或第一次寫入新紀錄時再升級。
"""
from __future__ import annotations

import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..core import settings as S
from ..etching import gsync, store
from . import theme as T
from .widgets import Chip, WrapRow, fit_label, fit_window, section_title

COLS = [("#", "#", 40, "e"), ("DateTime", "日期", 142, "w"), ("Material", "材料", 56, "w"),
        ("Method", "機台", 62, "w"), ("Gas", "氣體", 70, "w"), ("Power", "功率", 110, "w"),
        ("Pressure", "壓力", 62, "w"), ("Line width (nm)", "線寬", 52, "e"), ("Etch steps (s)", "時間 (s)", 66, "e"),
        ("R_hBN(nm/sec)", "R_材料", 64, "e"), ("σ R_material (nm/sec)", "±", 46, "e"),
        ("R_SiO2(nm/sec)", "R_SiO2", 64, "e"), ("Etched through", "蝕穿", 40, "center"), ("OM after", "OM", 36, "center"),
        ("Name", "操作者", 64, "w")]
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

        bar = WrapRow(self, bg=T.CARD, padx=6)                     # 欄位窄的時候自動換行（按鈕不會被擠扁）
        bar.pack(fill="x", pady=(8, 4))
        bar.add(ttk.Button(bar, text="＋ 新增紀錄", style=f"{key}.Accent.TButton", command=self.new_record))
        bar.add(ttk.Button(bar, text="↻", width=3, style=f"{key}.Small.TButton", command=self.reload))
        self.source_var = tk.StringVar(value=SOURCES[0])
        cb = ttk.Combobox(bar, textvariable=self.source_var, values=SOURCES, state="readonly", width=10)
        bar.add(cb)
        cb.bind("<<ComboboxSelected>>", lambda e: self.reload())
        sync_b = ttk.Button(bar, text="☁ 同步", style=f"{key}.Small.TButton", command=self.sync_dialog)
        bar.add(sync_b)
        from .params_panel import Tooltip
        Tooltip(sync_b, "比對本機 CSV 和 Google Sheet：把 Google Sheet 的舊紀錄加到本機，或把本機的紀錄補上傳")
        bar2 = WrapRow(self, bg=T.CARD, padx=4)
        bar2.pack(fill="x", pady=(0, 4))
        for text, cmd, tip in (("✎ 修改", self.edit_selected, "修改選取的那一筆（也可以在表格上雙擊）；修改前的值會留在修改歷史"),
                               ("🗑 刪除", self.delete_selected, "刪除選取的紀錄；刪掉的紀錄會留在修改歷史，可以還原"),
                               ("🕘 修改歷史", self.show_history, "看修改、刪除過哪些紀錄，可以還原"),
                               ("🖼 OM", self.show_om, "看選取那一筆的蝕刻前 / 後 OM 照片"),
                               ("複製條件", self.new_from_selected, "用選取那一筆的條件開新紀錄（量測值留空）"),
                               ("匯出 Excel", self.export_xlsx, "")):
            b = bar2.add(ttk.Button(bar2, text=text, style=f"{key}.Small.TButton", command=cmd))
            if tip:
                Tooltip(b, tip)

        self.path_lab = tk.Label(self, text="", bg=T.CHIP, fg=T.MUTED, font=T.font(9), anchor="w", justify="left",
                                 padx=8, pady=3)
        self.path_lab.pack(fill="x", pady=(0, 4))
        fit_label(self.path_lab, 16)
        self.banner = tk.Frame(self, bg="#fef3c7", padx=8, pady=4)
        self.banner_lab = fit_label(tk.Label(self.banner, text="", bg="#fef3c7", fg="#92400e", font=T.font(9),
                                             anchor="w", justify="left", wraplength=T.px(330)))
        self.banner_lab.pack(side="left", fill="x", expand=True)
        ttk.Button(self.banner, text="備份並升級", style=f"{key}.Small.TButton", command=self.upgrade).pack(side="right")

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
        self.tree.bind("<Double-1>", lambda e: self.edit_selected() if self.tree.identify_row(e.y) else None)
        self.tree.bind("<Delete>", lambda e: self.delete_selected())
        if sys.platform == "darwin":                                  # Mac 鍵盤的 delete 鍵 = BackSpace
            self.tree.bind("<BackSpace>", lambda e: self.delete_selected())
            self.tree.bind("<Command-a>", lambda e: (self.tree.selection_set(self.tree.get_children()), "break")[1])

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

    def reload(self, select_last=False, select_id=None):
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
                    df, how = gsync.read(settings)
                    label = f"Google Sheet（{how}{'' if gsync.can_write(settings) else '，唯讀'}）：" \
                        f"{store.parse_sheet_key(et.get('gsheet_key', '')) or '（未設定）'}"
                    self.app.post(("call", lambda: gen == self._gen and self.path_lab.winfo_exists()
                                   and self.path_lab.configure(text=label)))
                elif src == SOURCES[2]:
                    from ..etching.store import file_schema
                    if file_schema(demo) != "v2":
                        from ..testdata import etching_csv_v2
                        etching_csv_v2(str(demo))
                    df = store.read_log(demo)
                else:
                    df = store.read_log(self.csv_path())
                self.app.post(("records", (self, gen, df, None, select_id or select_last)))
            except Exception as e:
                self.app.post(("records", (self, gen, None, str(e), select_id or select_last)))
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
        self._update_banner()
        self.populate()
        if isinstance(select_last, str) and len(df):            # 選 Record ID 那一筆
            hit = df[df["Record ID"].astype(str) == select_last]
            if len(hit):
                iid = str(int(hit["#"].iloc[0]))
                if self.tree.exists(iid):
                    self.tree.selection_set([iid])
                    self.tree.see(iid)
        elif select_last and len(df):
            last = str(int(df["#"].iloc[-1]))
            if self.tree.exists(last):
                self.tree.selection_set([last])
                self.tree.see(last)

    def _update_banner(self):
        v1 = self.source_var.get() == SOURCES[0] and store.file_schema(self.csv_path()) == "v1"   # 0.2 的格式會自動補欄位
        if v1:
            self.banner_lab.configure(text="這份紀錄是舊格式（20 欄）。可以照常檢視；寫入新紀錄前會先備份、"
                                           "再把新欄位加在最後面（舊欄位與 Google Sheet 對應不變）。")
            self.banner.pack(fill="x", pady=(0, 4), after=self.path_lab)
        else:
            self.banner.pack_forget()

    def upgrade(self):
        path = self.csv_path()
        if not messagebox.askyesno("升級紀錄檔", f"先備份，再把新欄位加在最後面？\n\n{path}", parent=self):
            return
        try:
            backup = store.upgrade_file(path)
        except OSError as e:
            messagebox.showerror("升級紀錄檔", f"失敗（檔案是不是被 Excel 開著？）：{e}", parent=self)
            return
        self.app.status(f"已升級；舊檔備份在 {backup}", "ok", open_path=os.path.dirname(str(path)))
        self.reload()

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
                if c == "Etched through":
                    v = "▲" if bool(v) else ""
                elif c == "OM after":
                    v = "📷" if (str(r.get("OM before", "")).strip() or str(v).strip()) else ""
                elif isinstance(v, float):
                    v = "" if v != v else (f"{v:.4g}" if ("R_" in c or "σ" in c) else f"{v:g}")
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
    def new_record(self, prefill=None):
        from .etch_wizard import EtchWizard
        return EtchWizard(self, prefill)

    def new_from_selected(self):
        """以選取的那一筆的條件（材料、機台、氣體、功率…）開新紀錄，量測值留空。"""
        from .etch_wizard import prefill_from_record
        sel = self.tree.selection()
        if not sel or self.df is None:
            messagebox.showinfo("複製條件", "先在表格選一筆紀錄：會用它的材料、機台、氣體、功率、時間開一筆新紀錄（量測值留空）",
                                parent=self)
            return
        row = self.df[self.df["#"] == int(sel[0])].iloc[0].to_dict()
        return self.new_record(prefill_from_record(row))

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

    # ------------------------------------------------------------------ 修改 / 刪除 / 歷史
    def _local_rows(self, action):
        """選取的列（只能改本機 CSV）。回傳 [(編號, 那一筆 dict)]，或 None。"""
        if self.source_var.get() != SOURCES[0]:
            messagebox.showinfo(action, "只能修改「本機 CSV」的紀錄（Google Sheet 會跟著同步；範例資料是唯讀的）。\n"
                                        "請把上面的來源切回「本機 CSV」。", parent=self)
            return None
        sel = [int(i) for i in self.tree.selection()]
        if not sel or self.df is None:
            messagebox.showinfo(action, "先在表格選紀錄", parent=self)
            return None
        path = self.csv_path()
        sch = store.file_schema(path)
        if sch == "v1":
            if not messagebox.askyesno(action, "這份紀錄是舊格式（20 欄）。要先備份、再升級成新格式才能修改。\n要繼續嗎？",
                                       parent=self):
                return None
            store.upgrade_file(path)
        elif sch == "v2old":
            store.upgrade_file(path)
        if store.ensure_ids(path) or sch in ("v1", "v2old"):
            fresh = store.read_log(path)                       # 剛補上 Record ID：重新讀一次
        else:
            fresh = self.df
        out = []
        for n in sel:
            hit = fresh[fresh["#"] == n]
            if len(hit):
                out.append((n, hit.iloc[0].to_dict()))
        return out

    def edit_selected(self):
        rows = self._local_rows("修改紀錄")
        if not rows:
            return None
        if len(rows) > 1:
            self.app.status("一次修改一筆：先改第一筆選取的紀錄", "warn")
        n, row = rows[0]
        from .etch_wizard import EtchWizard
        return EtchWizard(self, edit={"rid": row["Record ID"], "row": row, "n": n})

    def delete_selected(self, confirm=True):
        rows = self._local_rows("刪除紀錄")
        if not rows:
            return 0
        desc = "\n".join(f"#{n}　{r.get('DateTime', '')}　{r.get('Material', '')}　"
                         f"r = {r.get('R_hBN(nm/sec)', float('nan')):.4g} nm/s" for n, r in rows[:8])
        more = f"\n…等 {len(rows)} 筆" if len(rows) > 8 else ""
        if confirm and not messagebox.askyesno(
                "刪除紀錄", f"刪除這 {len(rows)} 筆紀錄？\n\n{desc}{more}\n\n刪掉的紀錄會留在「🕘 修改歷史」，可以還原。",
                parent=self):
            return 0
        path = self.csv_path()
        gone = []
        for n, r in rows:
            try:
                gone.append(store.delete_record(path, r["Record ID"]))
            except (store.RecordNotFound, OSError) as e:
                messagebox.showerror("刪除紀錄", f"#{n}：{e}", parent=self)
        et = self.app.settings.get("etching", {})
        if gone and et.get("xlsx_mirror"):
            try:
                store.export_xlsx(store.read_log(path), os.path.splitext(str(path))[0] + ".xlsx")
            except Exception:
                pass
        if gone and et.get("gsheet_enabled"):
            settings = self.app.settings

            def work():
                bad = 0
                for old in gone:
                    try:
                        gsync.delete(old.get("Record ID", ""), old, settings)
                    except Exception:
                        bad += 1
                self.app.post(("status", ("Google Sheet 也已刪除" if not bad else
                                          f"Google Sheet 有 {bad} 筆找不到，請手動刪除（本機 CSV 已刪除）",
                                          "ok" if not bad else "warn")))
            self.app.submit(work)
        self.app.status(f"已刪除 {len(gone)} 筆（可以在「🕘 修改歷史」還原）", "ok")
        self.reload()
        return len(gone)

    def sync_dialog(self):
        """☁ 同步：比對本機 CSV 和 Google Sheet，兩邊互補（不會刪任何東西）。"""
        settings = self.app.settings
        et = settings.get("etching", {})
        if not (et.get("gsheet_key") or et.get("gsheet_script_url")):
            if messagebox.askyesno("☁ 同步", "還沒有設定 Google Sheet。\n\n要打開 ⚙ 設定 → 蝕刻紀錄，貼上試算表網址或團隊設定碼嗎？",
                                   parent=self):
                self.app.open_settings("蝕刻紀錄")
            return None
        win = tk.Toplevel(self)
        win.title("☁ 同步蝕刻紀錄")
        win.configure(bg=T.CARD, padx=16, pady=14)
        top = self.winfo_toplevel()
        win.transient(top)
        win.geometry(f"+{top.winfo_rootx() + T.px(360)}+{top.winfo_rooty() + T.px(160)}")
        msg = tk.Label(win, text="比對中…（讀取 Google Sheet 和本機 CSV）", bg=T.CARD, fg=T.TEXT, font=T.font(10),
                       justify="left", anchor="w", wraplength=T.px(520))
        msg.pack(fill="x")
        bf = tk.Frame(win, bg=T.CARD)
        bf.pack(fill="x", pady=(12, 0))
        win.result = None
        path = self.csv_path()

        def busy(text):
            msg.configure(text=text)
            for w in bf.winfo_children():
                w.configure(state="disabled")

        def show(res):
            if not win.winfo_exists():
                return
            win.result = res
            for w in bf.winfo_children():
                w.destroy()
            if res.get("error"):
                msg.configure(text=f"讀不到：{res['error']}", fg=T.ERROR)
            else:
                only_sheet, only_local, how = res["only_sheet"], res["only_local"], res["how"]
                lines = [f"Google Sheet（{how}）：{res['n_sheet']} 筆　·　本機 CSV：{res['n_local']} 筆",
                         f"‧ 只有 Google Sheet 有：{len(only_sheet)} 筆（例如以前直接填在試算表的紀錄、同事的紀錄）",
                         f"‧ 只有本機有：{len(only_local)} 筆（例如沒開同步時存的、寫入失敗的）"]
                if res.get("done"):
                    lines.append("")
                    lines.append(res["done"])
                if not gsync.can_write(settings) and only_local:
                    lines.append("\n上傳需要寫入權限：⚙ 設定 → 蝕刻紀錄，貼上團隊設定碼（Apps Script）或指定金鑰。")
                msg.configure(text="\n".join(lines), fg=T.TEXT)
                if only_sheet:
                    ttk.Button(bf, text=f"⬇ 加到本機 CSV（{len(only_sheet)} 筆）", style=f"{self.key}.Accent.TButton",
                               command=win.do_import).pack(side="left")
                if only_local and gsync.can_write(settings):
                    ttk.Button(bf, text=f"⬆ 上傳到 Google Sheet（{len(only_local)} 筆）", style=f"{self.key}.Small.TButton",
                               command=win.do_upload).pack(side="left", padx=(6, 0))
            ttk.Button(bf, text="關閉", style=f"{self.key}.Ghost.TButton", command=win.destroy).pack(side="right")

        def compare(done=""):
            def work():
                try:
                    sheet_df, how = gsync.read(settings)
                    local = store.read_log(path)
                    only_sheet, only_local = gsync.diff(local, sheet_df)
                    res = dict(how=how, n_sheet=len(sheet_df), n_local=len(local), only_sheet=only_sheet,
                               only_local=only_local, done=done)
                except Exception as e:
                    res = dict(error=str(e), done=done)
                self.app.post(("call", lambda: show(res)))
            self.app.submit(work)

        def do_import():
            recs = (win.result or {}).get("only_sheet") or []
            if not recs:
                return
            busy(f"加到本機 CSV 中…（{len(recs)} 筆；會先備份）")

            def work():
                try:
                    n, backup = gsync.import_to_local(recs, path)
                    done = f"✓ 已把 {n} 筆加到本機 CSV（依日期排序）" + (f"；原本的檔案備份在 {backup.name}" if backup else "")
                except Exception as e:
                    done = f"✗ 加到本機失敗（檔案是不是被 Excel 開著？）：{e}"
                self.app.post(("call", lambda: (self.reload(), compare(done))))
            self.app.submit(work)

        def do_upload():
            recs = (win.result or {}).get("only_local") or []
            if not recs:
                return
            busy(f"上傳到 Google Sheet 中…（{len(recs)} 筆）")

            def work():
                try:
                    sheet = gsync.writer(settings)
                    for k in range(0, len(recs), 40):
                        gsync.append_records(sheet, recs[k:k + 40])
                    done = f"✓ 已上傳 {len(recs)} 筆到 Google Sheet（加在最後面；原本的資料沒有動）"
                except Exception as e:
                    done = f"✗ 上傳失敗：{e}"
                self.app.post(("call", lambda: (self.reload() if self.source_var.get() == SOURCES[1] else None,
                                                compare(done))))
            self.app.submit(work)
        win.do_import, win.do_upload, win.compare = do_import, do_upload, compare
        compare()
        return win

    def show_history(self):
        path = self.csv_path()
        win = tk.Toplevel(self)
        win.title("修改歷史")
        win.configure(bg=T.CARD)
        win.transient(self.winfo_toplevel())
        fit_window(win, T.px(860), T.px(460), 520, 300)
        tk.Label(win, text=f"修改、刪除過的紀錄（最新的在上面）：{store.history_path(path).name}", bg=T.CARD, fg=T.MUTED,
                 font=T.font(9), anchor="w").pack(fill="x", padx=12, pady=(10, 4))
        f = tk.Frame(win, bg=T.CARD)
        f.pack(fill="both", expand=True, padx=12)
        cols = [("Changed at", "時間", 140), ("Action", "動作", 70), ("Row #", "#", 40), ("Changed fields", "改了什麼", 560)]
        tree = ttk.Treeview(f, columns=[c for c, _, _ in cols], show="headings", selectmode="browse")
        for c, t, w in cols:
            tree.heading(c, text=t)
            tree.column(c, width=T.px(w), stretch=c == "Changed fields", anchor="w")
        sb = ttk.Scrollbar(f, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        hist = store.read_history(path)
        entries = hist.to_dict("records")[::-1]
        for i, e in enumerate(entries):
            what = e.get("Changed fields") or ("整筆紀錄" if e.get("Action") in ("刪除", "還原刪除") else "")
            tree.insert("", "end", iid=str(i), values=(e.get("Changed at"), e.get("Action"), e.get("Row #"), what))
        if not entries:
            tree.insert("", "end", values=("", "", "", "還沒有修改或刪除過紀錄"))
        bf = tk.Frame(win, bg=T.CARD)
        bf.pack(fill="x", padx=12, pady=10)

        def restore():
            sel = tree.selection()
            if not sel or not entries:
                return
            e = entries[int(sel[0])]
            if e.get("Action") not in ("修改", "刪除", "還原"):
                messagebox.showinfo("還原", "這一筆是還原的紀錄，不需要再還原", parent=win)
                return
            msg = ("把這筆紀錄改回修改前的值？" if e["Action"] != "刪除" else "把刪除的紀錄放回原來的位置？") + \
                "\n（目前的值也會留在修改歷史）"
            if not messagebox.askyesno("還原", msg, parent=win):
                return
            try:
                back = store.restore_history(path, e)
            except (store.RecordNotFound, OSError, ValueError) as err:
                messagebox.showerror("還原", str(err), parent=win)
                return
            et = self.app.settings.get("etching", {})
            if et.get("gsheet_enabled"):
                settings = self.app.settings

                def work():
                    try:
                        if e["Action"] == "刪除":
                            gsync.append(back, settings)
                        else:
                            gsync.update(e["Record ID"], back, None, settings)
                        self.app.post(("status", ("Google Sheet 也已還原", "ok")))
                    except Exception as err:
                        self.app.post(("status", (f"Google Sheet 還原失敗，請手動修改（本機 CSV 已還原）：{err}", "warn")))
                self.app.submit(work)
            self.app.status("已還原", "ok")
            win.destroy()
            self.reload(select_id=e["Record ID"])
        ttk.Button(bf, text="還原這一筆", style=f"{self.key}.Accent.TButton", command=restore).pack(side="right")
        ttk.Button(bf, text="關閉", style=f"{self.key}.Ghost.TButton", command=win.destroy).pack(side="right", padx=6)
        win.restore = restore
        win.tree = tree
        win.entries = entries
        return win

    def show_om(self):
        """並排看選取那一筆的 OM 照片。"""
        sel = self.tree.selection()
        if not sel or self.df is None:
            messagebox.showinfo("OM 照片", "先在表格選一筆紀錄", parent=self)
            return None
        row = self.df[self.df["#"] == int(sel[0])].iloc[0]
        src = self.source_path()
        base = src if src != "Google Sheet" else str(self.csv_path())
        items = []
        for which, title in (("before", "蝕刻前"), ("after", "蝕刻後")):
            rel = str(row.get(f"OM {which}", "") or "")
            p = store.resolve_image(base, rel) or store.resolve_image(self.csv_path(), rel)
            items.append((f"{title}　#{sel[0]}", str(p) if p else (f"找不到：{rel}" if rel else None)))
        if not any(p for _, p in items):
            messagebox.showinfo("OM 照片", "這筆紀錄沒有 OM 照片（可以 ✎ 修改 加上去）", parent=self)
            return None
        from .om_images import OMViewer
        return OMViewer(self.winfo_toplevel(), items, self.key, title=f"OM 照片 — 第 {sel[0]} 筆")
