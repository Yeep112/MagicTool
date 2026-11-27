"""蝕刻紀錄 ↔ Google 試算表：測試連線（含欄位對照）、第一次開 Etching 的「貼團隊設定碼」、一步一步接 Apps Script。

‧ 團隊設定碼裡有通行碼，所以不內建在程式裡（GitHub 是公開的）：同事第一次開 Etching 時跳出視窗請他貼上
‧ 要用自己的試算表：⚙ 設定 → 蝕刻紀錄 → 🧭 一步一步接 Apps Script（每完成一步打勾，填好網址就自動測試連線）
"""
from __future__ import annotations

import copy
import re
import threading
import tkinter as tk
import webbrowser
from tkinter import ttk

from . import theme as T
from .widgets import ScrollFrame, WrapRow, fit_label, fit_window

ETCH = "Etching"
URL_RE = re.compile(r"^https://script\.google\.com/\S+/exec/?$")


# ---------------------------------------------------------------------------
# 測試連線
# ---------------------------------------------------------------------------
def sheet_check(cfg):
    """讀得到嗎？能寫嗎？第一次寫入會加哪些欄位？回傳 (訊息, 是否成功, 欄位對照文字或 None)。"""
    from ..etching import gsync
    lines, ok, cols = [], True, None
    try:
        values, how = gsync.read_values(cfg)
        n = max(0, len([r for r in values[1:] if any(str(c).strip() for c in r)]))
        lines.append(f"✓ 讀得到（{how}）：{n} 列資料")
        try:
            rep = gsync.columns_report(values[0] if values else [])
            cols = gsync.columns_text(rep)
            if rep["added"] and rep["width"]:
                lines.append(f"‧ 原本 {rep['width']} 欄不會動；第一次寫入時會在最後面加 {len(rep['added'])} 個欄位（下面有對照）")
            elif not rep["width"]:
                lines.append(f"‧ 工作表是空的：第一次寫入時會寫上 {len(rep['added'])} 個欄位名稱")
        except gsync.SheetError as e:
            lines.append(f"✗ {e}")
            ok = False
    except gsync.SheetError as e:
        return f"✗ {e}", False, None
    except Exception as e:                                   # 網路斷線等
        return f"✗ 讀不到：{e}", False, None
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
    return "\n".join(lines), ok, cols


def run_check(app, cfg, done, check=None):
    """背景測試連線，做完在主執行緒呼叫 done(msg, ok, cols)。"""
    check = check or sheet_check

    def work():
        try:
            res = check(cfg)
        except Exception as e:
            res = (f"✗ {e}", False, None)
        app.post(("call", lambda: done(*res)))
    threading.Thread(target=work, daemon=True).start()


class ColumnsView(tk.Frame):
    """欄位對照：試算表目前的欄位、Magic Tool 會加的欄位（可以複製，方便先在 AppSheet 那邊對好）。"""

    def __init__(self, parent, bg=None):
        bg = bg or parent.cget("bg")
        super().__init__(parent, bg=bg)
        head = WrapRow(self, bg=bg, padx=6)
        head.pack(fill="x")
        head.add(tk.Label(head, text="欄位對照（先在 AppSheet 對好欄位再開始寫入）", bg=bg, fg=T.TEXT,
                          font=T.font(9, "bold")), padx=0)
        self.copy_btn = head.add(ttk.Button(head, text="📋 複製欄位清單", style="Neutral.Small.TButton",
                                            command=self.copy), side="right", compact="📋")
        box = tk.Frame(self, bg=bg)
        box.pack(fill="both", expand=True, pady=(4, 0))
        self.text = tk.Text(box, height=12, width=40, font=T.font(9), bg=T.TEXT_BG, fg=T.TEXT, bd=0, wrap="none",
                            highlightthickness=1, highlightbackground=T.BORDER, padx=6, pady=4)
        ys = ttk.Scrollbar(box, orient="vertical", command=self.text.yview)
        xs = ttk.Scrollbar(box, orient="horizontal", command=self.text.xview)
        self.text.configure(yscrollcommand=ys.set, xscrollcommand=xs.set, state="disabled")
        xs.pack(side="bottom", fill="x")
        ys.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        self.value = ""

    def show(self, text):
        self.value = text or ""
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", self.value)
        self.text.configure(state="disabled")

    def copy(self):
        try:
            self.clipboard_clear()
            self.clipboard_append(self.value)
        except tk.TclError:
            pass
        return self.value


def _header(win, title, sub):
    a = T.accent(ETCH)
    head = tk.Frame(win, bg=a["main"], padx=16, pady=8)
    head.pack(fill="x")
    tk.Label(head, text=title, bg=a["main"], fg="white", font=T.font(12, "bold")).pack(anchor="w")
    if sub:
        fit_label(tk.Label(head, text=sub, bg=a["main"], fg=T.mix_color("#ffffff", a["main"], 0.25), font=T.font(9),
                           anchor="w", justify="left")).pack(fill="x")


# ---------------------------------------------------------------------------
# 第一次開 Etching：貼上團隊設定碼
# ---------------------------------------------------------------------------
class TeamCodePrompt(tk.Toplevel):
    """還沒接上實驗室的蝕刻紀錄表單時跳出來：貼上團隊設定碼 → 測試 → 儲存。"""

    def __init__(self, app, check=None):
        super().__init__(app.root)
        self.app = app
        self._check = check
        self.code = None
        self.title("接上實驗室的蝕刻紀錄表單")
        self.configure(bg=T.CARD)
        self.transient(app.root)
        fit_window(self, T.px(620), T.px(460), T.px_min(460), T.px_min(340))
        _header(self, "☁ 接上實驗室的蝕刻紀錄表單",
                "接上之後，每次在 Etching 按「寫入紀錄」都會自動加到實驗室共用的 Google 試算表，也看得到大家以前的數據。")
        bf = WrapRow(self, bg=T.CARD, padx=6)                  # 按鈕先放在最下面（視窗矮時不會被擠掉）
        bf.pack(side="bottom", fill="x", padx=14, pady=(0, 12))
        bf.add(ttk.Button(bf, text="不要再問", style="Neutral.Ghost.TButton", command=lambda: self.close("never")),
               padx=0)
        bf.add(ttk.Button(bf, text="以後再說", style="Neutral.Ghost.TButton", command=lambda: self.close("later")))
        self.save_btn = bf.add(ttk.Button(bf, text="儲存並開始使用", style="Neutral.Accent.TButton", command=self.save),
                               side="right")
        self.save_btn.state(["disabled"])
        sf = ScrollFrame(self)
        sf.pack(fill="both", expand=True, padx=14, pady=10)
        b = sf.body
        steps = ("1. 向表單管理者要「團隊設定碼」（開頭是 MAGIC-SHEET:，用 LINE、email 私下傳）\n"
                 "2. 整段複製起來，按下面的「📥 貼上團隊設定碼」（或貼在框框裡）\n"
                 "3. 顯示「✓ 可以寫入」就按「儲存並開始使用」")
        fit_label(tk.Label(b, text=steps, bg=T.CARD, fg=T.TEXT, font=T.font(10), anchor="w", justify="left")).pack(
            fill="x")
        row = WrapRow(b, bg=T.CARD, padx=6)
        row.pack(fill="x", pady=(10, 4))
        row.add(ttk.Button(row, text="📥 貼上團隊設定碼", style="Neutral.Small.TButton", command=self.paste), padx=0)
        self.entry_var = tk.StringVar()
        ent = ttk.Entry(row, textvariable=self.entry_var, width=34)
        row.add(ent, expand=True)
        ent.bind("<Return>", lambda e: self.use_text(self.entry_var.get()))
        ent.bind("<<Paste>>", lambda e: self.after(30, lambda: self.use_text(self.entry_var.get())))
        self.msg = fit_label(tk.Label(b, text="", bg=T.CARD, fg=T.MUTED, font=T.font(9), anchor="w", justify="left"))
        self.msg.pack(fill="x", pady=(6, 0))
        tip = ("設定碼裡有通行碼：請不要貼在公開的地方。之後要改：⚙ 設定 → 蝕刻紀錄。\n"
               "要用自己的試算表（自己當管理者）：⚙ 設定 → 蝕刻紀錄 → 🧭 一步一步接 Apps Script。")
        fit_label(tk.Label(b, text=tip, bg=T.CARD, fg=T.FAINT, font=T.font(8), anchor="w", justify="left")).pack(
            fill="x", pady=(14, 0))
        self.protocol("WM_DELETE_WINDOW", lambda: self.close("later"))
        self.bind("<Escape>", lambda e: self.close("later"))
        if getattr(app, "prompts", False):
            self.from_clipboard()

    def from_clipboard(self):
        """剪貼簿裡已經有團隊設定碼（剛從 LINE / email 複製）→ 直接帶進來測試，不用再按貼上。"""
        from ..etching import gsync
        try:
            text = self.clipboard_get()
        except tk.TclError:
            return False
        if gsync.CODE_PREFIX not in str(text):
            return False
        self.entry_var.set(str(text).strip())
        return self.use_text(text)

    def paste(self):
        try:
            text = self.clipboard_get()
        except tk.TclError:
            text = ""
        self.entry_var.set(text.strip())
        return self.use_text(text)

    def use_text(self, text):
        from ..etching import gsync
        try:
            d = gsync.parse_code(text)
        except gsync.SheetError as e:
            self.code = None
            self.save_btn.state(["disabled"])
            self.msg.configure(text=f"✗ {e}", fg=T.ERROR)
            return False
        self.code = d
        self.save_btn.state(["!disabled"])
        self.msg.configure(text="已讀到設定碼，正在測試連線…", fg=T.MUTED)
        run_check(self.app, self._cfg(), self._tested, self._check)
        return True

    def _cfg(self):
        cfg = copy.deepcopy(self.app.settings)
        et = cfg.setdefault("etching", {})
        et.update(self.code or {})
        et["gsheet_enabled"] = True
        return cfg

    def _tested(self, msg, ok, cols):
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        self.msg.configure(text=msg + ("" if ok else "\n（還是可以先儲存，之後在 ⚙ 設定 → 蝕刻紀錄 按「測試連線」）"),
                           fg=T.SUCCESS if ok else T.WARNING)

    def save(self):
        if not self.code:
            return False
        self.app.apply_settings(self._cfg())
        self.close("done")
        self.app.status("已接上實驗室的蝕刻紀錄表單：之後「寫入紀錄」會自動加到 Google 試算表", "ok")
        return True

    def close(self, how):
        self.app.state["etch_sheet_prompt"] = how
        try:
            self.app.save_state_soon()
        except Exception:
            pass
        self.result = how
        self.destroy()


def should_prompt(app):
    """要不要跳出「貼上團隊設定碼」：還沒設定寫入、使用者沒有選過「不要再問」。"""
    from ..etching import gsync
    if app.state.get("etch_sheet_prompt") in ("never", "done"):
        return False
    try:
        return not gsync.can_write(app.settings)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 一步一步接 Apps Script（自己當管理者、用自己的試算表）
# ---------------------------------------------------------------------------
class ScriptGuide(tk.Toplevel):
    """每完成一步打勾；試算表網址、通行碼、Apps Script 網址都填好就自動測試連線。"""

    STEPS = [
        ("試算表", "貼上試算表的網址（瀏覽器網址列整段），工作表名稱填下方分頁的名字（例如 etching rate）。"),
        ("複製程式碼", "按「📋 複製 Apps Script 程式碼」→ 在試算表點「擴充功能 → Apps Script」→ "
                  "把原本的 function myFunction() {…} 全部刪掉 → 貼上 → 💾 儲存。"),
        ("產生通行碼", "上方函式選單選 setupToken → ▶ 執行 → 授權（審查權限 → 選帳號 → 進階 → 前往…（不安全）→ 允許）。"
                  "下方「執行記錄」會出現「Magic Tool 通行碼：…」，把通行碼貼到這裡。"),
        ("部署", "右上角「部署 → 新增部署作業」→ ⚙ 選「網頁應用程式」→ 執行身分：我、誰可以存取：所有人 → 部署 → "
               "複製「網頁應用程式網址」（…/exec 結尾）貼到這裡。"),
        ("測試連線", "上面都填好會自動測試：讀得到、可以寫入，就會打勾。下面列出欄位對照，可以先在 AppSheet 對好欄位。"),
        ("套用", "按「套用並儲存」寫進設定；再按「📋 複製團隊設定碼」私下傳給同事（裡面有通行碼，不要公開張貼）。"),
    ]

    def __init__(self, app, dialog=None, check=None):
        super().__init__(app.root if dialog is None else dialog)
        self.app = app
        self.dialog = dialog
        self._check = check
        self._job = None
        self._tested_key = None
        self.ok = False
        self.applied = False
        self.copied_script = False
        self.title("一步一步接 Apps Script")
        self.configure(bg=T.CARD)
        self.transient(app.root if dialog is None else dialog)
        fit_window(self, T.px(760), T.px(720), T.px_min(560), T.px_min(420))
        _header(self, "🧭 一步一步接 Apps Script",
                "用自己的 Google 試算表當蝕刻紀錄：做完一步就會打勾。只需要試算表的擁有者（或編輯者）做一次。")
        bf = WrapRow(self, bg=T.CARD, padx=6)
        bf.pack(side="bottom", fill="x", padx=14, pady=(0, 12))
        bf.add(ttk.Button(bf, text="關閉", style="Neutral.Ghost.TButton", command=self.destroy), side="right")
        self.progress = bf.add(tk.Label(bf, text="", bg=T.CARD, fg=T.MUTED, font=T.font(9)), padx=0)
        sf = ScrollFrame(self)
        sf.pack(fill="both", expand=True, padx=14, pady=10)
        body = sf.body
        et = self._current()
        self.v = {k: tk.StringVar(value=et.get(k, "") or "") for k in
                  ("gsheet_key", "gsheet_worksheet", "gsheet_token", "gsheet_script_url")}
        self.marks, self.cards = [], []
        for i, (title, text) in enumerate(self.STEPS):
            card = tk.Frame(body, bg=T.SUBTLE, highlightthickness=1, highlightbackground=T.BORDER, padx=10, pady=8)
            card.pack(fill="x", pady=(0, 8))
            top = tk.Frame(card, bg=T.SUBTLE)
            top.pack(fill="x")
            mark = tk.Label(top, text="○", bg=T.SUBTLE, fg=T.FAINT, font=T.font(13, "bold"), width=2)
            mark.pack(side="left")
            tk.Label(top, text=f"{i + 1}. {title}", bg=T.SUBTLE, fg=T.TEXT, font=T.font(10, "bold")).pack(side="left")
            fit_label(tk.Label(card, text=text, bg=T.SUBTLE, fg=T.MUTED, font=T.font(9), anchor="w",
                               justify="left")).pack(fill="x", pady=(2, 4))
            self.marks.append(mark)
            self.cards.append(card)
        self._build_controls()
        for var in self.v.values():
            var.trace_add("write", lambda *a: self._changed())
        self._changed()

    # ---- 每一步的欄位、按鈕
    def _field(self, card, label, var, width=None, show=None):
        r = tk.Frame(card, bg=T.SUBTLE)
        r.pack(fill="x", pady=2)
        tk.Label(r, text=label, bg=T.SUBTLE, fg=T.TEXT, font=T.font(9), width=10, anchor="w").pack(side="left")
        e = ttk.Entry(r, textvariable=var, width=width or 20, show=show or "")
        e.pack(side="left", fill="x", expand=width is None)
        return e

    def _build_controls(self):
        c = self.cards
        self._field(c[0], "試算表網址", self.v["gsheet_key"])
        self._field(c[0], "工作表名稱", self.v["gsheet_worksheet"], width=20)
        r = WrapRow(c[0], bg=T.SUBTLE, padx=6)
        r.pack(fill="x", pady=(4, 0))
        r.add(ttk.Button(r, text="🌐 打開試算表", style="Neutral.Small.TButton", command=self.open_sheet), padx=0)
        r = WrapRow(c[1], bg=T.SUBTLE, padx=6)
        r.pack(fill="x")
        r.add(ttk.Button(r, text="📋 複製 Apps Script 程式碼", style="Neutral.Small.TButton", command=self.copy_script),
              padx=0)
        r.add(ttk.Button(r, text="🌐 打開試算表", style="Neutral.Small.TButton", command=self.open_sheet))
        self._field(c[2], "通行碼", self.v["gsheet_token"], width=30)
        self._field(c[3], "網址", self.v["gsheet_script_url"])
        r = WrapRow(c[4], bg=T.SUBTLE, padx=6)
        r.pack(fill="x")
        r.add(ttk.Button(r, text="重新測試", style="Neutral.Small.TButton", command=lambda: self.test(force=True)),
              padx=0)
        self.test_lab = fit_label(tk.Label(c[4], text="", bg=T.SUBTLE, fg=T.MUTED, font=T.font(9), anchor="w",
                                           justify="left"))
        self.test_lab.pack(fill="x", pady=(4, 0))
        self.cols = ColumnsView(c[4], bg=T.SUBTLE)
        r = WrapRow(c[5], bg=T.SUBTLE, padx=6)
        r.pack(fill="x")
        self.apply_btn = r.add(ttk.Button(r, text="套用並儲存", style="Neutral.Accent.TButton", command=self.apply),
                               padx=0)
        r.add(ttk.Button(r, text="📋 複製團隊設定碼", style="Neutral.Small.TButton", command=self.copy_code))
        self.apply_lab = fit_label(tk.Label(c[5], text="", bg=T.SUBTLE, fg=T.MUTED, font=T.font(9), anchor="w",
                                            justify="left"))
        self.apply_lab.pack(fill="x", pady=(4, 0))

    # ---- 狀態
    def _current(self):
        if self.dialog is not None:
            try:
                return self.dialog.collect().get("etching", {})
            except Exception:
                pass
        return dict(self.app.settings.get("etching", {}) or {})

    def values(self):
        d = {k: v.get().strip() for k, v in self.v.items()}
        m = re.search(r"通行碼[:：]\s*(\S+)", d["gsheet_token"])       # 整行「Magic Tool 通行碼：xxxx」貼進來也可以
        if m:
            d["gsheet_token"] = m.group(1)
        return d

    def done_steps(self):
        from ..etching import gsync
        d = self.values()
        return [bool(gsync.parse_sheet_key(d["gsheet_key"])),
                self.copied_script or bool(d["gsheet_token"]),
                bool(re.fullmatch(r"[A-Za-z0-9_-]{12,}", d["gsheet_token"])),
                bool(URL_RE.match(d["gsheet_script_url"])),
                self.ok and self._tested_key == self._key(),
                self.applied]

    def _key(self):
        d = self.values()
        return (d["gsheet_key"], d["gsheet_worksheet"], d["gsheet_token"], d["gsheet_script_url"])

    def _refresh_marks(self):
        steps = self.done_steps()
        for mark, card, ok in zip(self.marks, self.cards, steps):
            mark.configure(text="✓" if ok else "○", fg=T.SUCCESS if ok else T.FAINT)
            card.configure(highlightbackground=T.SUCCESS if ok else T.BORDER)
        n = sum(steps)
        self.progress.configure(text=f"完成 {n} / {len(steps)} 步" + ("　🎉 全部完成" if n == len(steps) else ""))
        return steps

    def _changed(self):
        if self._tested_key is not None and self._tested_key != self._key():
            self.ok = False
            self.applied = False
        steps = self._refresh_marks()
        if all(steps[:4]) and self._tested_key != self._key():
            if self._job:
                try:
                    self.after_cancel(self._job)
                except Exception:
                    pass
            self._job = self.after(800, self.test)

    def _cfg(self):
        cfg = copy.deepcopy(self.app.settings)
        et = cfg.setdefault("etching", {})
        et.update(self.values())
        et["gsheet_enabled"] = True
        return cfg

    def test(self, force=False):
        self._job = None
        key = self._key()
        if not force and self._tested_key == key:
            return
        self._tested_key = key
        self.ok = False
        self.test_lab.configure(text="連線中…", fg=T.MUTED)
        self._refresh_marks()
        run_check(self.app, self._cfg(), lambda m, o, c, k=key: self._tested(k, m, o, c), self._check)

    def _tested(self, key, msg, ok, cols):
        try:
            if not self.winfo_exists() or key != self._key():
                return
        except tk.TclError:
            return
        self.ok = bool(ok)
        self.test_lab.configure(text=msg, fg=T.SUCCESS if ok else T.ERROR)
        if cols:
            self.cols.show(cols)
            self.cols.pack(fill="both", expand=True, pady=(6, 0))
        else:
            self.cols.pack_forget()
        self._refresh_marks()

    # ---- 按鈕
    def open_sheet(self):
        url = self.values()["gsheet_key"]
        if url.startswith("http"):
            try:
                webbrowser.open(url)
            except Exception:
                pass

    def copy_script(self):
        from ..etching import gsync
        try:
            self.clipboard_clear()
            self.clipboard_append(gsync.script_code())
        except tk.TclError:
            pass
        self.copied_script = True
        self._refresh_marks()

    def apply(self):
        d = self.values()
        if self.dialog is not None and self.dialog.winfo_exists():
            for k, v in d.items():
                self.dialog.vars[f"etching.{k}"].set(v)
            self.dialog.vars["etching.gsheet_enabled"].set(True)
            cfg = self.dialog.collect()
            self.dialog.cfg = copy.deepcopy(cfg)
        else:
            cfg = self._cfg()
        self.app.apply_settings(cfg)
        self.app.state["etch_sheet_prompt"] = "done"
        self.applied = True
        self.apply_lab.configure(text="✓ 已寫進設定。接下來按「📋 複製團隊設定碼」私下傳給同事。", fg=T.SUCCESS)
        self._refresh_marks()
        return cfg

    def copy_code(self):
        from ..etching import gsync
        try:
            code = gsync.make_code(self._cfg())
        except gsync.SheetError as e:
            self.apply_lab.configure(text=f"✗ {e}", fg=T.ERROR)
            return None
        try:
            self.clipboard_clear()
            self.clipboard_append(code)
        except tk.TclError:
            pass
        self.apply_lab.configure(text="✓ 已複製團隊設定碼：請私下傳給同事（LINE、email），不要貼在公開的地方。", fg=T.SUCCESS)
        return code
