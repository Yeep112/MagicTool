"""⚙ 設定：資料夾、輸出、蝕刻紀錄（CSV / Excel / Google Sheet）、介面大小、更新。

存在 %LOCALAPPDATA%\\MagicTool\\settings.toml（不在工具資料夾，更新與上傳 GitHub 都不會碰到）。
"""
from __future__ import annotations

import copy
import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .. import __version__
from ..core import settings as S
from . import theme as T
from .widgets import ScrollFrame


def sheet_status(cfg):
    """測試連線：讀得到嗎？能寫嗎？第一次寫入會加幾個欄位？回傳 (訊息, 是否成功)。"""
    from ..etching import gsync
    lines, ok = [], True
    try:
        values, how = gsync.read_values(cfg)
        n = max(0, len([r for r in values[1:] if any(str(c).strip() for c in r)]))
        lines.append(f"✓ 讀得到（{how}）：{n} 列資料")
        try:
            _, width, missing = gsync.plan(values[0] if values else [])
            if missing and width:
                lines.append(f"‧ 原本 {width} 欄不會動；第一次寫入時會在最後面加 {len(missing)} 個欄位")
        except gsync.SheetError as e:
            lines.append(f"✗ {e}")
            ok = False
    except gsync.SheetError as e:
        return f"✗ {e}", False
    if gsync.can_write(cfg):
        try:
            sh = gsync.writer(cfg)
            if isinstance(sh, gsync.ScriptSheet):
                res = sh.call("ping")
                lines.append(f"✓ 可以寫入（Apps Script → {res.get('title', '')} / {res.get('sheet', '')}）")
            else:
                lines.append(f"✓ 可以寫入（服務帳號 → {sh.title}）")
        except Exception as e:
            lines.append(f"✗ 寫入：{e}")
            ok = False
    else:
        lines.append("‧ 唯讀：要寫入請貼上團隊設定碼（Apps Script）或指定服務帳號金鑰")
    return "\n".join(lines), ok


class SettingsDialog(tk.Toplevel):
    def __init__(self, app, tab=None):
        super().__init__(app.root)
        self.app = app
        self.cfg = copy.deepcopy(app.settings)
        self.title("設定")
        self.configure(bg=T.CARD)
        self.transient(app.root)
        self.geometry(f"{T.px(720)}x{T.px(560)}")
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=10, pady=10)
        self.nb = nb
        self.vars = {}
        self._tabs = {}
        self._folders_tab(nb)
        self._etching_tab(nb)
        self._look_tab(nb)
        self._update_tab(nb)
        bf = tk.Frame(self, bg=T.CARD)
        bf.pack(fill="x", padx=12, pady=(0, 12))
        tk.Label(bf, text=f"設定檔：{S.settings_path()}", bg=T.CARD, fg=T.FAINT, font=T.font(8)).pack(side="left")
        ttk.Button(bf, text="儲存", style="Neutral.Accent.TButton", command=self.save).pack(side="right")
        ttk.Button(bf, text="取消", style="Neutral.Ghost.TButton", command=self.destroy).pack(side="right", padx=6)
        if tab in self._tabs:
            nb.select(self._tabs[tab])
        self.bind("<Escape>", lambda e: self.destroy())

    # ------------------------------------------------------------------ 共用
    def _tab(self, nb, title):
        outer = tk.Frame(nb, bg=T.CARD)
        nb.add(outer, text=title)
        self._tabs[title] = outer
        sf = ScrollFrame(outer)
        sf.pack(fill="both", expand=True, padx=8, pady=8)
        body = sf.body
        body.columnconfigure(1, weight=1)
        return body

    def _row_path(self, body, r, label, key, value, folder=True, save=False, filetypes=None, hint=""):
        tk.Label(body, text=label, bg=T.CARD, fg=T.TEXT, font=T.font(10)).grid(row=r, column=0, sticky="w", pady=4,
                                                                             padx=(0, 8))
        var = tk.StringVar(value=value or "")
        ttk.Entry(body, textvariable=var).grid(row=r, column=1, sticky="ew", pady=4)

        def browse():
            cur = var.get() or os.path.expanduser("~")
            if folder:
                p = filedialog.askdirectory(parent=self, initialdir=cur if os.path.isdir(cur) else None)
            elif save:
                p = filedialog.asksaveasfilename(parent=self, initialdir=os.path.dirname(cur) or None,
                                                 initialfile=os.path.basename(cur) or "etch_rate_log.csv",
                                                 defaultextension=".csv", filetypes=filetypes or [])
            else:
                p = filedialog.askopenfilename(parent=self, initialdir=os.path.dirname(cur) or None,
                                               filetypes=filetypes or [])
            if p:
                var.set(os.path.normpath(p))
        ttk.Button(body, text="瀏覽…", style="Neutral.Small.TButton", command=browse).grid(row=r, column=2, padx=(6, 0))
        if hint:
            tk.Label(body, text=hint, bg=T.CARD, fg=T.MUTED, font=T.font(8), wraplength=T.px(560), justify="left",
                     anchor="w").grid(row=r + 1, column=1, columnspan=2, sticky="w")
        self.vars[key] = var
        return var

    # ------------------------------------------------------------------ 分頁
    def _folders_tab(self, nb):
        body = self._tab(nb, "資料夾")
        r = 0
        tk.Label(body, text="每台機台第一次開啟時的資料夾（之後會記住上次用的）", bg=T.CARD, fg=T.FAINT,
                 font=T.font(9, "bold")).grid(row=r, column=0, columnspan=3, sticky="w", pady=(0, 6))
        r += 1
        for key in ("PPMS", "SQUID", "Raman"):
            self._row_path(body, r, f"{key} 資料夾", f"folders.{key}", self.cfg["folders"].get(key, ""))
            r += 1
        tk.Label(body, text="分析結果", bg=T.CARD, fg=T.FAINT, font=T.font(9, "bold")).grid(
            row=r, column=0, columnspan=3, sticky="w", pady=(14, 6))
        r += 1
        self._row_path(body, r, "輸出資料夾", "output_root", self.cfg.get("output_root", ""),
                       hint=f"「存圖」「匯出結果」存放的位置（每台機台一個子資料夾）。空白 = {S.output_root({})}\n"
                            "不會寫進原始資料夾。")
        r += 2
        tk.Label(body, text="圖片格式", bg=T.CARD, fg=T.TEXT, font=T.font(10)).grid(row=r, column=0, sticky="w", pady=4)
        fv = tk.StringVar(value=self.cfg.get("fig_format", "png"))
        ttk.Combobox(body, textvariable=fv, values=["png", "jpg", "pdf", "svg"], state="readonly", width=8).grid(
            row=r, column=1, sticky="w")
        self.vars["fig_format"] = fv
        r += 1
        tk.Label(body, text="解析度 (dpi)", bg=T.CARD, fg=T.TEXT, font=T.font(10)).grid(row=r, column=0, sticky="w", pady=4)
        dv = tk.StringVar(value=str(self.cfg.get("dpi", 200)))
        ttk.Entry(body, textvariable=dv, width=8).grid(row=r, column=1, sticky="w")
        self.vars["dpi"] = dv
        r += 1
        tk.Label(body, text="私人分析功能（不會上傳 GitHub）放在：", bg=T.CARD, fg=T.MUTED, font=T.font(9)).grid(
            row=r, column=0, columnspan=3, sticky="w", pady=(16, 0))
        r += 1
        from ..core.registry import plugin_dir
        pd = plugin_dir()
        row = tk.Frame(body, bg=T.CARD)
        row.grid(row=r, column=0, columnspan=3, sticky="w")
        tk.Label(row, text=pd, bg=T.CHIP, fg=T.TEXT, font=T.font(9), padx=6).pack(side="left")
        ttk.Button(row, text="開啟", style="Neutral.Small.TButton", command=lambda: self.app.open_folder(pd)).pack(
            side="left", padx=6)

    def _etching_tab(self, nb):
        body = self._tab(nb, "蝕刻紀錄")
        et = self.cfg.get("etching", {})
        r = 0
        self._row_path(body, r, "紀錄 CSV", "etching.csv_path", et.get("csv_path", ""), folder=False, save=True,
                       filetypes=[("CSV", "*.csv")],
                       hint=f"可以指向原本的 etch_rate_log.csv：舊格式會在第一次寫入前先備份、再把新欄位加在最後面。"
                            f"空白 = {S.etching_csv({})}")
        r += 2
        xv = tk.BooleanVar(value=bool(et.get("xlsx_mirror")))
        ttk.Checkbutton(body, text="每次寫入也更新同名的 .xlsx", variable=xv, style="Neutral.TCheckbutton").grid(
            row=r, column=1, sticky="w", pady=4)
        self.vars["etching.xlsx_mirror"] = xv
        r += 1
        tk.Label(body, text="Google Sheet（團隊共用紀錄，選用）", bg=T.CARD, fg=T.FAINT, font=T.font(9, "bold")).grid(
            row=r, column=0, columnspan=3, sticky="w", pady=(14, 2))
        r += 1
        tk.Label(body, text="同事只要按「📥 貼上團隊設定碼」就設定好了（設定碼由試算表擁有者在這裡按「📋 複製」產生）。".replace(
                     " ", "\u00a0"),
                 bg=T.CARD, fg=T.MUTED, font=T.font(9), justify="left", wraplength=T.px(560)).grid(
            row=r, column=0, columnspan=3, sticky="w", pady=(0, 4))
        r += 1
        row = tk.Frame(body, bg=T.CARD)
        row.grid(row=r, column=1, columnspan=2, sticky="w", pady=4)
        ttk.Button(row, text="📥 貼上團隊設定碼", style="Neutral.Small.TButton", command=self.paste_code).pack(side="left")
        ttk.Button(row, text="📋 複製團隊設定碼", style="Neutral.Small.TButton", command=self.copy_code).pack(
            side="left", padx=6)
        ttk.Button(row, text="📖 設定教學", style="Neutral.Small.TButton", command=self.open_sheet_guide).pack(side="left")
        r += 1
        gv = tk.BooleanVar(value=bool(et.get("gsheet_enabled")))
        ttk.Checkbutton(body, text="新增 / 修改 / 刪除紀錄時也同步到 Google Sheet", variable=gv,
                        style="Neutral.TCheckbutton").grid(row=r, column=1, columnspan=2, sticky="w", pady=4)
        self.vars["etching.gsheet_enabled"] = gv
        r += 1
        tk.Label(body, text="試算表網址", bg=T.CARD, fg=T.TEXT, font=T.font(10)).grid(row=r, column=0, sticky="w", pady=4)
        kv = tk.StringVar(value=et.get("gsheet_key", ""))
        ttk.Entry(body, textvariable=kv).grid(row=r, column=1, columnspan=2, sticky="ew", pady=4)
        self.vars["etching.gsheet_key"] = kv
        r += 1
        tk.Label(body, text=("直接貼瀏覽器上的網址（含 #gid=… 就會讀那一張）。只要「看」以前的紀錄，"
                             "試算表設成「知道連結的人可以檢視」就不需要其他設定。").replace(" ", "\u00a0"),
                 bg=T.CARD, fg=T.MUTED, font=T.font(9), justify="left", wraplength=T.px(520)).grid(
            row=r, column=1, columnspan=2, sticky="w")
        r += 1
        tk.Label(body, text="工作表名稱", bg=T.CARD, fg=T.TEXT, font=T.font(10)).grid(row=r, column=0, sticky="w", pady=4)
        wv = tk.StringVar(value=et.get("gsheet_worksheet", ""))
        ttk.Entry(body, textvariable=wv, width=20).grid(row=r, column=1, sticky="w", pady=4)
        self.vars["etching.gsheet_worksheet"] = wv
        r += 1
        tk.Label(body, text="寫入 ①　Apps Script（推薦：同事不需要金鑰）", bg=T.CARD, fg=T.FAINT,
                 font=T.font(9, "bold")).grid(row=r, column=0, columnspan=3, sticky="w", pady=(12, 2))
        r += 1
        tk.Label(body, text="Apps Script 網址", bg=T.CARD, fg=T.TEXT, font=T.font(10)).grid(row=r, column=0, sticky="w",
                                                                                         pady=4)
        uv = tk.StringVar(value=et.get("gsheet_script_url", ""))
        ttk.Entry(body, textvariable=uv).grid(row=r, column=1, columnspan=2, sticky="ew", pady=4)
        self.vars["etching.gsheet_script_url"] = uv
        r += 1
        tk.Label(body, text="通行碼", bg=T.CARD, fg=T.TEXT, font=T.font(10)).grid(row=r, column=0, sticky="w", pady=4)
        tv = tk.StringVar(value=et.get("gsheet_token", ""))
        row = tk.Frame(body, bg=T.CARD)
        row.grid(row=r, column=1, columnspan=2, sticky="w", pady=4)
        tok = ttk.Entry(row, textvariable=tv, width=30, show="•")
        tok.pack(side="left")
        ttk.Button(row, text="👁", width=3, style="Neutral.Small.TButton",
                   command=lambda: tok.configure(show="" if tok.cget("show") else "•")).pack(side="left", padx=4)
        ttk.Button(row, text="📋 複製 Apps Script 程式碼", style="Neutral.Small.TButton",
                   command=self.copy_script).pack(side="left", padx=(8, 0))
        self.vars["etching.gsheet_token"] = tv
        r += 1
        tk.Label(body, text="寫入 ②　服務帳號金鑰（沒有填 Apps Script 時才用）", bg=T.CARD, fg=T.FAINT,
                 font=T.font(9, "bold")).grid(row=r, column=0, columnspan=3, sticky="w", pady=(12, 2))
        r += 1
        self._row_path(body, r, "金鑰檔", "etching.service_account", et.get("service_account", ""), folder=False,
                       filetypes=[("JSON", "*.json")],
                       hint=f"服務帳號的 service_account.json。空白 = {S.secrets_dir() / 'service_account.json'}\n"
                            "金鑰不要放在工具資料夾或會同步、分享的資料夾。試算表要共用給金鑰裡的 client_email（編輯者）。")
        r += 2
        row = tk.Frame(body, bg=T.CARD)
        row.grid(row=r, column=1, columnspan=2, sticky="w", pady=(8, 0))
        self.test_lab = tk.Label(row, text="", bg=T.CARD, fg=T.MUTED, font=T.font(9), justify="left",
                                 wraplength=T.px(460))
        ttk.Button(row, text="測試連線", style="Neutral.Small.TButton", command=self.test_sheet).pack(side="left")
        self.test_lab.pack(side="left", padx=8)

    def _look_tab(self, nb):
        body = self._tab(nb, "外觀")
        tk.Label(body, text="介面大小", bg=T.CARD, fg=T.TEXT, font=T.font(10)).grid(row=0, column=0, sticky="w", pady=4)
        cur = self.app.state.get("ui_scale", "auto")
        label = next((l for l, v in T.SCALE_CHOICES if v == cur), T.SCALE_CHOICES[0][0])
        sv = tk.StringVar(value=label)
        ttk.Combobox(body, textvariable=sv, values=[l for l, _ in T.SCALE_CHOICES], state="readonly", width=20).grid(
            row=0, column=1, sticky="w")
        self.vars["_ui_scale"] = sv
        tk.Label(body, text="重新開啟軟體後套用。", bg=T.CARD, fg=T.MUTED, font=T.font(9)).grid(row=1, column=1, sticky="w")
        av = tk.BooleanVar(value=self.app.state.get("auto_update_check", True))
        ttk.Checkbutton(body, text="開啟時與每 30 分鐘自動檢查更新", variable=av, style="Neutral.TCheckbutton").grid(
            row=2, column=1, sticky="w", pady=(12, 0))
        self.vars["_auto_update"] = av

    def _update_tab(self, nb):
        from .. import updater
        body = self._tab(nb, "更新")
        rel = updater.read_release()
        tk.Label(body, text=f"目前版本 v{__version__}", bg=T.CARD, fg=T.TEXT, font=T.font(12, "bold")).grid(
            row=0, column=0, sticky="w")
        tk.Label(body, text=f"更新來源：github.com/{rel.get('repo', '（未設定）')}（{rel.get('branch', 'main')}）",
                 bg=T.CARD, fg=T.MUTED, font=T.font(9)).grid(row=1, column=0, columnspan=3, sticky="w")
        row = tk.Frame(body, bg=T.CARD)
        row.grid(row=2, column=0, columnspan=3, sticky="w", pady=8)
        ttk.Button(row, text="檢查更新", style="Neutral.Small.TButton", command=self.app.check_update_manual).pack(side="left")
        ttk.Button(row, text="還原上一版", style="Neutral.Small.TButton", command=self.rollback).pack(side="left", padx=6)
        rep = tk.Frame(body, bg="#fef3c7", padx=10, pady=8)
        rep.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        tk.Label(rep, text="出問題了嗎？", bg="#fef3c7", fg="#92400e", font=T.font(10, "bold")).pack(anchor="w")
        tk.Label(rep, text="把 error.log、crash.log 和電腦環境打包成一個 zip（放在桌面），直接傳給維護軟體的人。"
                           "不包含量測資料、蝕刻紀錄和金鑰。", bg="#fef3c7", fg="#92400e", font=T.font(9),
                 wraplength=T.px(520), justify="left").pack(anchor="w", pady=(2, 6))
        ttk.Button(rep, text="📦 打包錯誤紀錄", style="Neutral.Small.TButton", command=self.make_report).pack(anchor="w")
        txt = tk.Text(body, height=16, wrap="word", font=T.font(9), bg=T.TEXT_BG, bd=0, highlightthickness=1,
                      highlightbackground=T.BORDER)
        txt.grid(row=3, column=0, columnspan=3, sticky="nsew")
        for v, d, notes in updater.all_notes(rel):
            txt.insert("end", f"v{v}" + (f"　{d}" if d else "") + "\n")
            for n in notes:
                txt.insert("end", f"  ‧ {n}\n")
            txt.insert("end", "\n")
        txt.configure(state="disabled")

    # ------------------------------------------------------------------ 動作
    def collect(self):
        cfg = copy.deepcopy(self.cfg)
        for key, var in self.vars.items():
            if key.startswith("_"):
                continue
            val = var.get()
            if "." in key:
                a, b = key.split(".", 1)
                cfg.setdefault(a, {})[b] = val
            else:
                cfg[key] = val
        try:
            cfg["dpi"] = int(float(cfg.get("dpi", 200)))
        except ValueError:
            cfg["dpi"] = 200
        return cfg

    def save(self):
        cfg = self.collect()
        st = self.app.state
        label = self.vars["_ui_scale"].get()
        new_scale = next((v for l, v in T.SCALE_CHOICES if l == label), "auto")
        restart_needed = new_scale != st.get("ui_scale", "auto")
        st["ui_scale"] = new_scale
        st["auto_update_check"] = bool(self.vars["_auto_update"].get())
        self.app.save_state_soon()
        self.app.apply_settings(cfg)
        self.destroy()
        self.app.status("設定已儲存" + ("（介面大小重新開啟後套用）" if restart_needed else ""), "ok")

    def test_sheet(self):
        cfg = self.collect()
        self.test_lab.configure(text="連線中…", fg=T.MUTED)

        def work():
            msg, ok = sheet_status(cfg)
            self.app.post(("call", lambda: self.test_lab.winfo_exists() and self.test_lab.configure(
                text=msg, fg=T.SUCCESS if ok else T.ERROR)))
        threading.Thread(target=work, daemon=True).start()

    def paste_code(self, text=None):
        from ..etching import gsync
        if text is None:
            try:
                text = self.clipboard_get()
            except tk.TclError:
                text = ""
        try:
            d = gsync.parse_code(text)
        except gsync.SheetError as e:
            messagebox.showerror("團隊設定碼", f"{e}\n\n請先把設定碼整段複製起來，再按這個按鈕。", parent=self)
            return False
        for k, v in d.items():
            self.vars[f"etching.{k}"].set(v)
        self.vars["etching.gsheet_enabled"].set(True)
        self.test_lab.configure(text="已貼上設定碼（按「儲存」才會生效），正在測試…", fg=T.MUTED)
        self.test_sheet()
        return True

    def copy_code(self):
        from ..etching import gsync
        try:
            code = gsync.make_code(self.collect())
        except gsync.SheetError as e:
            messagebox.showinfo("團隊設定碼", str(e), parent=self)
            return None
        self.clipboard_clear()
        self.clipboard_append(code)
        messagebox.showinfo("團隊設定碼", "已複製。請私下傳給同事（LINE、email…），他們在這裡按「📥 貼上團隊設定碼」。\n\n"
                                     "設定碼裡有通行碼，不要貼在公開的地方（GitHub、公開群組）。", parent=self)
        return code

    def copy_script(self):
        from ..etching import gsync
        self.clipboard_clear()
        self.clipboard_append(gsync.script_code())
        messagebox.showinfo("Apps Script 程式碼", "已複製。\n\n打開試算表 → 擴充功能 → Apps Script → 把原本的程式刪掉、貼上 → 儲存，"
                                           "接著照「📖 設定教學」做（執行 setupToken、部署成網頁應用程式）。", parent=self)

    def open_sheet_guide(self):
        from ..core.settings import TOOL_ROOT
        p = os.path.join(str(TOOL_ROOT), "Google Sheet 團隊設定.md")
        self.app.open_path(p)

    def make_report(self, note=""):
        from ..core.report import make_report, open_folder
        try:
            fp = make_report(note=note)
        except Exception as e:
            messagebox.showerror("打包錯誤紀錄", f"打包失敗：{e}", parent=self)
            return None
        try:
            self.clipboard_clear()
            self.clipboard_append(str(fp))
        except tk.TclError:
            pass
        self.app.status(f"已打包錯誤紀錄：{fp}", "ok", open_path=str(fp.parent))
        if messagebox.askyesno("打包錯誤紀錄", f"已存好：\n{fp}\n\n（路徑已複製）把這個 zip 傳給維護軟體的人就可以了。\n\n要打開資料夾嗎？",
                               parent=self):
            open_folder(fp.parent)
        return fp

    def rollback(self):
        from .. import updater
        if updater.is_dev_folder():
            messagebox.showinfo("還原", "這是開發用資料夾（有 .git），請用 GitHub Desktop 還原。", parent=self)
            return
        if not messagebox.askyesno("還原上一版", "要還原到上一次更新前的版本嗎？", parent=self):
            return
        try:
            name = updater.rollback()
        except Exception as e:
            messagebox.showerror("還原", str(e), parent=self)
            return
        messagebox.showinfo("還原", f"已還原：{name}\n接下來會重新開啟軟體。", parent=self)
        self.app.restart()
