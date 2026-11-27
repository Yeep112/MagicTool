"""製程 → 樣品頁：左 = 樣品清單、中 = 製程時間軸、右 = 步驟細節（參數、子步驟、資料夾、照片、資料檔）。

資料來源：樣品資料夾（主要紀錄，每個樣品一個 <資料夾名稱>.json）＋ 試算表（匯入初版、之後只當總覽）。
v0.6：瀏覽、從試算表匯入建立紀錄檔、待確認清單。
v0.7：新增 / 編輯 / 搬移 / 刪除步驟（samples_edit.py）、擱置 / 放棄、結果、新樣品、自動更新試算表。
"""
from __future__ import annotations

import copy
import os
import sys
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..core import settings as S
from ..fab import edit as E
from ..fab import folders as F
from ..fab import records as R
from ..fab import sheet as SH
from ..fab import steps as K
from . import theme as T
from . import samples_edit as SE
from .samples_edit import _Dialog
from .widgets import Chip, Paned, ScrollFrame, section_title

KEY = "Samples"
COLOR = "#db2777"
THUMB = (132, 96)
MAX_THUMBS = 24
STATE_FILTERS = [("全部", None)] + [(v[0], k) for k, v in K.STATES.items()]


class _NoFigure:
    """主視窗改圖表樣式時會呼叫每頁的 right.sync_view()；樣品頁沒有圖。"""

    def sync_view(self):
        pass

    def restyle(self):
        pass


def sample_settings(settings):
    s = dict((settings or {}).get("samples") or {})
    s.setdefault("user", "")
    s.setdefault("root", "")
    s.setdefault("record_name", R.DEFAULT_RECORD_NAME)
    s.setdefault("folder_rule", F.DEFAULT_RULE)
    s.setdefault("sheet", "")
    s.setdefault("service_account", "")
    s.setdefault("sheet_sync", False)
    s.setdefault("sheet_script_url", "")
    s.setdefault("sheet_token", "")
    return s


def open_external(path):
    try:
        if os.name == "nt":
            os.startfile(path)                             # noqa: S606
        else:
            import subprocess
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path])
        return True
    except Exception:
        return False


def _date_text(a, b=""):
    """2025-04-12, 2025-04-15 → 2025/04/12–15；跨月 → 2025/04/28–05/03；跨年 → 2025/12/30–2026/01/02"""
    if not a:
        return ""
    a2 = a.replace("-", "/")
    if b and b != a:
        b2 = b.replace("-", "/")
        if b2[:7] == a2[:7]:
            return f"{a2}–{b2[8:]}"
        return f"{a2}–{b2[5:] if b2[:4] == a2[:4] else b2}"
    return a2


class SamplePage:
    key = KEY

    def __init__(self, app):
        self.app = app
        self.busy = None
        self._restyle_pending = False
        self.st = app.state.setdefault("pages", {}).setdefault(KEY, {})
        self.right = _NoFigure()
        self.lib = None
        self.sample = None
        self.step_id = None
        self._thumb_cache = {}
        self._imgs = []
        self._scan_gen = 0
        self.scanning = False
        self._scan_listeners = []
        import threading
        self._sync_lock = threading.Lock()
        self.cfg = sample_settings(app.settings)
        self._build()

    # ================================================================== 主視窗用的介面
    def frames(self):
        return self.left, self.mid, self.detail

    def restore(self):
        self.rescan()

    def on_show(self):
        pass

    def restyle(self):
        pass

    def plot(self):
        self.rescan()

    def save_figure(self):
        self.app.status("樣品頁沒有圖可以存（一鍵匯出 PPT 會在之後的版本加入）", "warn")

    export = save_figure

    # ================================================================== 版面
    def _build(self):
        app = self.app
        a = T.accent(KEY)
        # ---------------- 左：樣品清單
        self.left = tk.Frame(app.left_host, bg=T.CARD)
        head = tk.Frame(self.left, bg=T.CARD)
        head.pack(fill="x")
        row, _ = section_title(head, "樣品", "◆", a["main"])
        row.pack(side="left")
        self.count = Chip(head, "")
        self.count.pack(side="right")
        self.root_lab = tk.Label(self.left, text="", bg=T.CHIP, fg=T.MUTED, font=T.font(9), anchor="w", justify="left",
                                 padx=8, pady=4, wraplength=T.px(240))
        self.root_lab.pack(fill="x", pady=(8, 4))
        br = tk.Frame(self.left, bg=T.CARD)
        br.pack(fill="x")
        ttk.Button(br, text="選資料夾", style=f"{KEY}.Small.TButton", command=self.pick_root).pack(side="left")
        ttk.Button(br, text="↻", width=3, style=f"{KEY}.Small.TButton", command=self.rescan).pack(side="left", padx=4)
        ttk.Button(br, text="⚙ 樣品設定", style=f"{KEY}.Small.TButton", command=self.open_settings).pack(side="right")
        fr = tk.Frame(self.left, bg=T.CARD)
        fr.pack(fill="x", pady=(8, 4))
        tk.Label(fr, text="⌕", bg=T.CARD, fg=T.MUTED, font=T.font(11)).pack(side="left", padx=(0, 4))
        self.filter_var = tk.StringVar()
        ttk.Entry(fr, textvariable=self.filter_var, width=10).pack(side="left", fill="x", expand=True)
        self.state_var = tk.StringVar(value=STATE_FILTERS[0][0])
        cb = ttk.Combobox(fr, textvariable=self.state_var, values=[x[0] for x in STATE_FILTERS], state="readonly", width=6)
        cb.pack(side="left", padx=(4, 0))
        self.filter_var.trace_add("write", lambda *x: self.refresh_list())
        cb.bind("<<ComboboxSelected>>", lambda e: self.refresh_list())
        lf = tk.Frame(self.left, bg=T.CARD)
        lf.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(lf, columns=("label", "type", "state"), show="headings", selectmode="browse",
                                 style=f"{KEY}.Treeview")
        for c, t, w in (("label", "編號", 70), ("type", "類型", 90), ("state", "狀態", 64)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=T.px(w), anchor="w", stretch=c == "type")
        for st, (zh, en, col) in K.STATES.items():
            self.tree.tag_configure(st, foreground=col if st != "abandoned" else T.FAINT)
        self.tree.tag_configure("nofolder", foreground=T.FAINT)
        sb = ttk.Scrollbar(lf, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._on_pick_sample())
        tk.Label(self.left, text="灰色 = 放棄　「·」= 沒有資料夾（紀錄存在這台電腦）", bg=T.CARD, fg=T.FAINT,
                 font=T.font(8), anchor="w").pack(fill="x", pady=(2, 0))
        bf = tk.Frame(self.left, bg=T.CARD)
        bf.pack(fill="x", pady=(8, 0))
        b0 = tk.Frame(bf, bg=T.CARD)
        b0.pack(fill="x", pady=(0, 6))
        ttk.Button(b0, text="＋ 新樣品", style=f"{KEY}.Ghost.TButton", command=self.open_new_sample).pack(
            side="left", fill="x", expand=True)
        self.sync_btn = ttk.Button(b0, text="☁ 試算表", style=f"{KEY}.Ghost.TButton", command=self.open_sync)
        self.sync_btn.pack(side="left", padx=(6, 0))
        ttk.Button(bf, text="📥 從試算表匯入", style=f"{KEY}.Accent.TButton", command=self.open_import).pack(fill="x")
        b2 = tk.Frame(bf, bg=T.CARD)
        b2.pack(fill="x", pady=(6, 0))
        self.review_btn = ttk.Button(b2, text="⚠ 待確認", style=f"{KEY}.Ghost.TButton", command=self.open_reviews)
        self.review_btn.pack(side="left", fill="x", expand=True)
        self.demo_btn = ttk.Button(b2, text="範例樣品", style=f"{KEY}.Small.TButton", command=self.open_demo)
        self.demo_btn.pack(side="left", padx=(6, 0))

        # ---------------- 中：樣品資訊 + 時間軸
        self.mid = tk.Frame(app.mid_host, bg=T.CARD)
        card = tk.Frame(self.mid, bg=T.SUBTLE, padx=12, pady=10)
        card.pack(fill="x")
        top = tk.Frame(card, bg=T.SUBTLE)
        top.pack(fill="x")
        self.s_title = tk.Label(top, text="選一個樣品", bg=T.SUBTLE, fg=T.TEXT, font=T.font(18, "bold"), anchor="w")
        self.s_title.pack(side="left")
        self.s_state = Chip(top, "", bg=T.CARD)
        self.s_state.pack(side="left", padx=10)
        self.s_sub = tk.Label(card, text="", bg=T.SUBTLE, fg=T.MUTED, font=T.font(9), anchor="w", justify="left")
        self.s_sub.pack(fill="x", pady=(2, 0))
        self.s_res = tk.Label(card, text="", bg=T.SUBTLE, fg=a["text"], font=T.font(10, "bold"), anchor="w",
                              justify="left")
        self.s_res.pack(fill="x", pady=(4, 0))
        cbtn = tk.Frame(card, bg=T.SUBTLE)
        cbtn.pack(fill="x", pady=(8, 0))
        self.open_btn = ttk.Button(cbtn, text="📂 開啟樣品資料夾", style=f"{KEY}.Small.TButton", command=self.open_sample_dir)
        self.open_btn.pack(side="left")
        self.make_btn = ttk.Button(cbtn, text="建立紀錄檔", style=f"{KEY}.Small.TButton", command=self.create_record)
        self.res_btn = ttk.Button(cbtn, text="✎ 結果", style=f"{KEY}.Small.TButton", command=self.open_results)
        self.res_btn.pack(side="right")
        self.ab_btn = ttk.Button(cbtn, text="✕ 放棄", style=f"{KEY}.Small.TButton", command=lambda: self.toggle_state("abandoned"))
        self.ab_btn.pack(side="right", padx=(0, 4))
        self.hold_btn = ttk.Button(cbtn, text="⏸ 擱置", style=f"{KEY}.Small.TButton", command=lambda: self.toggle_state("hold"))
        self.hold_btn.pack(side="right", padx=(0, 4))
        self.prev_lab = tk.Label(self.mid, text="", bg=T.CARD, fg=T.WARNING, font=T.font(9), anchor="w", justify="left",
                                 wraplength=T.px(440))
        self.prev_lab.pack(fill="x", pady=(6, 0))

        vp = Paned(self.mid, orient="vertical", bg=T.CARD)
        vp.pack(fill="both", expand=True, pady=(6, 0))
        tlf = tk.Frame(vp, bg=T.CARD)
        rvf = tk.Frame(vp, bg=T.CARD)
        vp.add_pane(tlf, stretch=True, minsize=T.px(160))
        vp.add_pane(rvf, stretch=False, size=T.px(150), minsize=T.px(70))
        th = tk.Frame(tlf, bg=T.CARD)
        th.pack(fill="x", pady=(0, 4))
        row, _ = section_title(th, "製程時間軸", "⋮", a["main"])
        row.pack(side="left")
        self.tl_btns = []
        for txt, cmd in (("🗑", self.delete_selected_step), ("↓", lambda: self.move_selected(1)),
                         ("↑", lambda: self.move_selected(-1)), ("✎ 編輯", self.edit_selected_step),
                         ("＋ 新增步驟", self.new_step)):
            b = ttk.Button(th, text=txt, style=f"{KEY}.Small.TButton", command=cmd, width=len(txt) + 1 if len(txt) > 2 else 3)
            b.pack(side="right", padx=(4, 0))
            self.tl_btns.append(b)
        tf = tk.Frame(tlf, bg=T.CARD)
        tf.pack(fill="both", expand=True)
        self.tl = ttk.Treeview(tf, columns=("step", "date", "dirs", "info"), show="headings", selectmode="browse",
                               style=f"{KEY}.Treeview")
        for c, t, w in (("step", "步驟", 130), ("date", "日期", 118), ("dirs", "資料夾", 62), ("info", "內容", 200)):
            self.tl.heading(c, text=t)
            self.tl.column(c, width=T.px(w), anchor="w", stretch=c == "info")
        for cat, (zh, en, col) in K.CATEGORIES.items():
            self.tl.tag_configure(cat, background=T.mix_color(col, "#ffffff", 0.88))
        self.tl.tag_configure("sheetonly", foreground=T.MUTED)
        tsb = ttk.Scrollbar(tf, orient="vertical", command=self.tl.yview)
        self.tl.configure(yscrollcommand=tsb.set)
        self.tl.pack(side="left", fill="both", expand=True)
        tsb.pack(side="right", fill="y")
        self.tl.bind("<<TreeviewSelect>>", lambda e: self._on_pick_step())
        self.tl.bind("<Double-Button-1>", lambda e: self.edit_selected_step())
        rh = tk.Frame(rvf, bg=T.CARD)
        rh.pack(fill="x", pady=(6, 2))
        self.rv_title = tk.Label(rh, text="⚠ 待確認", bg=T.CARD, fg=T.WARNING, font=T.font(10, "bold"))
        self.rv_title.pack(side="left")
        ttk.Button(rh, text="✓ 已確認", style=f"{KEY}.Small.TButton", command=self.resolve_selected).pack(side="right")
        self.rv_list = tk.Listbox(rvf, height=4, bd=0, highlightthickness=1, highlightbackground=T.BORDER,
                                  font=T.font(9), activestyle="none", selectbackground=T.mix_color(COLOR, "#ffffff", 0.75),
                                  selectforeground=T.TEXT)
        self.rv_list.pack(fill="both", expand=True)
        self.rv_list.bind("<Double-Button-1>", lambda e: self._jump_review())
        self.rv_list.bind("<<ListboxSelect>>", lambda e: self._show_review_text())
        self.rv_full = tk.Label(rvf, text="", bg=T.CARD, fg=T.TEXT, font=T.font(9), anchor="w", justify="left",
                                wraplength=T.px(440))
        self.rv_full.pack(fill="x", pady=(4, 0))

        # ---------------- 右：步驟細節
        self.detail = tk.Frame(app.right_host, bg=T.CARD)
        self.sf = ScrollFrame(self.detail)
        self.sf.pack(fill="both", expand=True)
        self.body = self.sf.body
        self._show_empty()

    # ================================================================== 掃描
    def _make_lib(self):
        c = self.cfg
        return R.Library(S.data_dir(), c.get("user") or "me", c.get("root"), c.get("folder_rule"), c.get("record_name"))

    def rescan(self, select=None):
        """在背景找樣品資料夾、讀紀錄檔（雲端硬碟可能要幾秒），完成後更新清單。"""
        self.cfg = sample_settings(self.app.settings)
        root = self.cfg.get("root")
        self.root_lab.configure(text=(f"使用者：{self.cfg.get('user') or '（未設定）'}\n" +
                                      (root if root else "還沒有選樣品根目錄（例如 …\\00 Users\\01 Yeep\\00 Samples）")))
        lib = self._make_lib()
        self._scan_gen += 1
        gen = self._scan_gen
        self.scanning = True
        self.count.set("掃描中…")
        want = select or (self.sample["key"] if self.sample else self.st.get("sample"))

        def work():
            try:
                lib.scan()
                err = None
            except Exception as e:                     # 不讓掃描錯誤把介面卡住
                err = str(e)
            self.app.post(("call", lambda: self._scanned(gen, lib, err, want)))
        self.app.submit(work)

    def _scanned(self, gen, lib, err, want):
        if gen != self._scan_gen:
            return
        self.scanning = False
        self.lib = lib
        if err:
            self.app.status(f"掃描樣品資料夾失敗：{err}", "error")
        if lib.errors:
            self.app.log("樣品紀錄讀取錯誤：\n" + "\n".join(lib.errors))
            self.app.status(f"{len(lib.errors)} 個紀錄檔讀不了（細節在錯誤紀錄）", "warn")
        self.demo_btn.pack_forget() if self.cfg.get("root") else self.demo_btn.pack(side="left", padx=(6, 0))
        self.refresh_list(select=want)
        self._update_review_btn()
        self._update_sync_btn()
        for cb in self._scan_listeners:
            cb()
        self._scan_listeners = []

    def _filtered(self):
        if not self.lib:
            return []
        q = self.filter_var.get().strip().lower()
        want = dict(STATE_FILTERS).get(self.state_var.get())
        out = []
        for s in self.lib.samples:
            if want and R.state_of(s) != want:
                continue
            if q:
                sh = s.get("sheet") or {}
                rec = s.get("rec") or {}
                hay = " ".join([s["label"], s.get("project", ""), sh.get("type", ""), rec.get("type", "")]).lower()
                if q not in hay:
                    continue
            out.append(s)
        return out

    def refresh_list(self, select=None):
        items = self._filtered()
        self.tree.delete(*self.tree.get_children())
        for s in items:
            st = R.state_of(s)
            rec = s.get("rec") or {}
            typ = rec.get("type") or (s.get("sheet") or {}).get("type", "")
            tags = [st] + ([] if s["has_folder"] else ["nofolder"])
            mark = "" if s["has_folder"] else " ·"
            self.tree.insert("", "end", iid=s["key"], values=(s["label"] + mark, typ, K.state_label(st)), tags=tags)
        n_all = len(self.lib.samples) if self.lib else 0
        n_dir = sum(1 for s in self.lib.samples if s["has_folder"]) if self.lib else 0
        self.count.set(f"{len(items)} / {n_all} 個（{n_dir} 有資料夾）" if n_all else "0 個")
        key = select or (self.sample["key"] if self.sample else None)
        if key and self.tree.exists(key):
            self.tree.selection_set(key)
            self.tree.see(key)
        elif not items:
            self.sample = None
            self._show_sample(None)

    def find(self, key_or_label):
        for s in (self.lib.samples if self.lib else []):
            if s["key"] == key_or_label or s["label"] == key_or_label:
                return s
        return None

    # ================================================================== 樣品 / 步驟
    def _on_pick_sample(self):
        sel = self.tree.selection()
        s = self.find(sel[0]) if sel else None
        if s is None:
            return
        same = self.sample is not None and self.sample["key"] == s["key"]
        self.sample = s
        self.st["sample"] = s["key"]
        self.app.save_state_soon()
        self._show_sample(s, keep_step=same)

    def record(self, s=None):
        s = s or self.sample
        if not s or not self.lib:
            return None
        return self.lib.preview(s)

    def _show_sample(self, s, keep_step=False):
        self.tl.delete(*self.tl.get_children())
        self.rv_list.delete(0, "end")
        self.make_btn.pack_forget()
        on = ["!disabled"] if s is not None else ["disabled"]
        for b in [self.hold_btn, self.ab_btn, self.res_btn] + self.tl_btns:
            b.state(on)
        if s is None:
            self.s_title.configure(text="選一個樣品")
            self.s_state.set("")
            self.s_sub.configure(text="")
            self.s_res.configure(text="")
            self.prev_lab.configure(text="")
            self._show_empty()
            return
        rec = self.record(s)
        st = rec.get("status") or {}
        state = st.get("state", "active")
        self.hold_btn.configure(text="▶ 繼續製作" if state == "hold" else "⏸ 擱置")
        self.ab_btn.configure(text="↺ 取消放棄" if state == "abandoned" else "✕ 放棄")
        self.s_title.configure(text=s["label"])
        self.s_state.set(K.state_label(state), fg="#ffffff", bg=K.STATES.get(state, K.STATES["active"])[2])
        sub = [rec.get("type") or "", f"開始 {rec['start'].replace('-', '/')}" if rec.get("start") else "",
               s.get("project", ""), "" if s["has_folder"] else "沒有資料夾（紀錄存在這台電腦）"]
        extra = []
        if st.get("reason") and state in ("hold", "abandoned"):
            extra.append(f"原因：{st['reason']}")
        if st.get("next"):
            extra.append(f"下一步：{st['next']}" + (f"（{st['next_date'].replace('-', '/')}）" if st.get("next_date") else ""))
        elif st.get("next_date") and state == "hold":
            extra.append(f"預定：{st['next_date'].replace('-', '/')}")
        self.s_sub.configure(text=" · ".join(x for x in sub if x) + ("\n" + "　".join(extra) if extra else ""))
        res = rec.get("results") or {}
        parts = []
        if res.get("r_ohm") is not None:
            parts.append(f"低溫電阻 {res['r_ohm']:g} Ω")
        if res.get("sc_contact"):
            parts.append("超導 contact" + (f"（on {res['sc_on']}）" if res.get("sc_on") else ""))
        if res.get("tc_k") is not None:
            parts.append(f"Tc {res['tc_k']:g} K")
        sync = rec.get("sync") or {}
        if sync.get("state") == "pending":
            parts.append("☁ 試算表待更新")
        elif sync.get("state") == "error":
            parts.append("☁ 試算表更新失敗（按左下「☁ 試算表」重試）")
        self.s_res.configure(text="　".join(parts))
        self.open_btn.state(["!disabled"] if s["has_folder"] else ["disabled"])
        if s.get("rec") is None:
            self.prev_lab.configure(text="還沒有紀錄檔：下面是依資料夾與試算表自動產生的初版，按「建立紀錄檔」或"
                                         "「📥 從試算表匯入」存起來。")
            self.make_btn.pack(side="left", padx=(6, 0))
        else:
            self.prev_lab.configure(text="")
        rv_steps = {r.get("step") for r in R.open_reviews(rec)}
        stop = st.get("stopped_at")
        for step in rec.get("steps", []):
            name = K.label(step["kind"]) + (f" #{step.get('n', 1)}" if step["kind"] in K.GROUP_KINDS else "")
            if step["id"] in rv_steps:
                name = "⚠ " + name
            if step["id"] == stop:
                name += "　⛔ 停在這裡"
            info = K.summary(step)
            dirs = " + ".join(f.split(" ", 1)[0] for f in step.get("folders", []))
            tags = [K.category(step["kind"])]
            if "folder" not in step.get("source", []) and s["has_folder"]:
                tags.append("sheetonly")
                dirs = "—"
                info = "（只有試算表）" + info
            self.tl.insert("", "end", iid=step["id"], values=(f"{K.icon(step['kind'])} {name}",
                                                              _date_text(step.get("date", ""), step.get("date_end", "")),
                                                              dirs, info), tags=tags)
        self._fill_reviews(rec)
        if keep_step and self.step_id and self.tl.exists(self.step_id):
            self.tl.selection_set(self.step_id)
        else:
            self.step_id = None
            self._show_overview(s, rec)

    def _show_review_text(self):
        sel = self.rv_list.curselection()
        i = sel[0] if sel else 0
        items = getattr(self, "_rv_items", [])
        self.rv_full.configure(text=items[i]["msg"] + ("　（雙擊跳到那一步）" if items[i].get("step") else "")
                               if i < len(items) else "")

    def _fill_reviews(self, rec):
        self.rv_list.delete(0, "end")
        self._rv_items = R.open_reviews(rec)
        for r in self._rv_items:
            self.rv_list.insert("end", r["msg"])
        self._show_review_text()
        n = len(self._rv_items)
        self.rv_title.configure(text=f"⚠ 待確認（{n}）" if n else "✓ 沒有待確認的地方",
                                fg=T.WARNING if n else T.SUCCESS)

    def _on_pick_step(self):
        sel = self.tl.selection()
        if not sel or not self.sample:
            return
        self.step_id = sel[0]
        rec = self.record()
        step = next((x for x in rec.get("steps", []) if x["id"] == sel[0]), None)
        if step:
            self._show_step(self.sample, rec, step)

    def select_step(self, sid):
        if self.tl.exists(sid):
            self.tl.selection_set(sid)
            self.tl.see(sid)
            self._on_pick_step()

    # ================================================================== 右欄
    def _clear(self):
        for w in self.body.winfo_children():
            w.destroy()
        self._imgs = []
        self._thumb_labels = {}

    def _show_empty(self):
        self._clear()
        tk.Label(self.body, text="製程紀錄", bg=T.CARD, fg=T.TEXT, font=T.font(14, "bold"), anchor="w").pack(fill="x")
        tk.Label(self.body, bg=T.CARD, fg=T.MUTED, font=T.font(10), anchor="w", justify="left", wraplength=T.px(520),
                 text="每個樣品資料夾（例如 …\\09 TaS2 project\\102）就是一個樣品，裡面的「NN 步驟名稱」子資料夾"
                      "（01 Transfer、05 Lithography…）就是一步一步的照片與資料。\n\n"
                      "1. 左邊「選資料夾」選樣品根目錄\n2. 「📥 從試算表匯入」把試算表的製程紀錄合進來，"
                      "每個樣品建立一個紀錄檔\n3. 對不起來的地方會列在「⚠ 待確認」\n\n"
                      "沒有資料想先看看：按「範例樣品」（合成資料）。").pack(fill="x", pady=(6, 0))

    def _h(self, text, top=14):
        tk.Label(self.body, text=text, bg=T.CARD, fg=T.TEXT, font=T.font(11, "bold"), anchor="w").pack(
            fill="x", pady=(top, 4))

    def _kv(self, parent, rows, wrap=380):
        g = tk.Frame(parent, bg=parent.cget("bg"))
        g.pack(fill="x")
        for r, (k, v) in enumerate(rows):
            tk.Label(g, text=k, bg=g.cget("bg"), fg=T.MUTED, font=T.font(9), anchor="nw").grid(row=r, column=0,
                                                                                               sticky="nw", pady=1)
            tk.Label(g, text=v, bg=g.cget("bg"), fg=T.TEXT, font=T.font(10, "bold"), anchor="w", justify="left",
                     wraplength=T.px(wrap)).grid(row=r, column=1, sticky="w", padx=(12, 0), pady=1)
        return g

    def _show_overview(self, s, rec):
        self._clear()
        tk.Label(self.body, text=f"樣品 {s['label']}", bg=T.CARD, fg=T.TEXT, font=T.font(14, "bold"), anchor="w").pack(
            fill="x")
        tk.Label(self.body, text="在中間的時間軸點一步，看參數、照片與資料檔", bg=T.CARD, fg=T.MUTED, font=T.font(9),
                 anchor="w").pack(fill="x")
        steps = rec.get("steps", [])
        n_img = 0
        if s["has_folder"]:
            for f in F.step_folders(s["dir"], self.cfg.get("folder_rule"), rec.get("start", "")):
                n_img += len(f["images"])
        cats = {}
        for x in steps:
            cats[K.category(x["kind"])] = cats.get(K.category(x["kind"]), 0) + 1
        self._h("概況")
        rows = [("步驟", f"{len(steps)} 步（" + "、".join(f"{K.CATEGORIES[c][0]} {n}" for c, n in cats.items()) + "）"),
                ("照片", f"{n_img} 張" if s["has_folder"] else "沒有資料夾"),
                ("紀錄檔", s["path"] if s.get("rec") is not None else "（還沒有建立）")]
        self._kv(self.body, rows)
        if s["has_folder"]:
            loose = F.loose_files(s["dir"])
            loose = [p for p in loose if os.path.normcase(p) != os.path.normcase(s["path"])]
            if loose:
                self._h("樣品資料夾裡的檔案")
                self._file_rows(loose)
        sh = rec.get("sheet") or {}
        if sh:
            self._h("試算表原文")
            txt = f"狀態：{sh.get('status') or '（空白）'}\n" + " → ".join(sh.get("process") or [])
            if sh.get("remark"):
                txt += f"\n備註：{sh['remark']}"
            tk.Label(self.body, text=txt, bg=T.TEXT_BG, fg=T.TEXT, font=T.font(9), anchor="w", justify="left",
                     wraplength=T.px(520), padx=8, pady=6).pack(fill="x")
        if rec.get("notes"):
            self._h("備註")
            tk.Label(self.body, text=rec["notes"], bg=T.CARD, fg=T.TEXT, font=T.font(10), anchor="w", justify="left",
                     wraplength=T.px(520)).pack(fill="x")

    def _show_step(self, s, rec, step):
        self._clear()
        kind = step["kind"]
        col = K.color(kind)
        head = tk.Frame(self.body, bg=T.CARD)
        head.pack(fill="x")
        tk.Label(head, text=K.icon(kind), bg=col, fg="#ffffff", font=T.font(14, "bold"), width=2).pack(side="left")
        name = K.label(kind) + (f" #{step.get('n', 1)}" if kind in K.GROUP_KINDS else "")
        tk.Label(head, text=name, bg=T.CARD, fg=T.TEXT, font=T.font(15, "bold")).pack(side="left", padx=(10, 6))
        Chip(head, K.CATEGORIES[K.category(kind)][0], fg="#ffffff", bg=col).pack(side="left")
        ttk.Button(head, text="✎ 編輯這一步", style=f"{KEY}.Small.TButton",
                   command=lambda: self.open_step_editor(s, rec, step)).pack(side="right")
        src = step.get("source", [])
        srct = ("手動新增" if "manual" in src else "資料夾＋試算表" if len(src) == 2 else
                "只有資料夾" if "folder" in src else "只有試算表") + ("（在軟體裡改過）" if step.get("edited") else "")
        dt = _date_text(step.get("date", ""), step.get("date_end", ""))
        tk.Label(self.body, text="　".join(x for x in (dt or "（照片檔名沒有日期）", srct) if x), bg=T.CARD, fg=T.MUTED,
                 font=T.font(9), anchor="w").pack(fill="x", pady=(4, 0))
        msgs = [r["msg"] for r in R.open_reviews(rec) if r.get("step") == step["id"]]
        for m in msgs:
            tk.Label(self.body, text="⚠ " + m, bg="#fffbeb", fg=T.WARNING, font=T.font(9), anchor="w", justify="left",
                     wraplength=T.px(520), padx=8, pady=4).pack(fill="x", pady=(6, 0))
        if kind in K.GROUP_KINDS or kind == "litho_group":
            self._h("子步驟（可以選填）")
            have = {}
            for sub in step.get("substeps", []):
                have.setdefault(sub["kind"], []).append(sub)
            order = list(K.SUBSTEPS.get(kind, []))
            order += [k for k in have if k not in order]
            order.sort(key=lambda k: K.SUB_ORDER.get(k, 99))
            for k in order:
                for sub in have.get(k, [None]):
                    self._sub_row(k, sub)
        pr = K.params_text(kind, step.get("params"))
        if pr:
            self._h("參數")
            self._kv(self.body, pr)
        imgs, data = [], []
        if s["has_folder"] and step.get("folders"):
            self._h("資料夾")
            for fname in step["folders"]:
                path = os.path.join(s["dir"], fname)
                info = F.scan_folder(path, rec.get("start", ""))
                imgs += [(fname, p) for p in info["images"]]
                data += info["data"]
                r = tk.Frame(self.body, bg=T.CARD)
                r.pack(fill="x", pady=1)
                tk.Label(r, text=fname, bg=T.CARD, fg=T.TEXT, font=T.font(10, "bold")).pack(side="left")
                tk.Label(r, text=f"　{len(info['images'])} 張照片、{len(info['data'])} 個資料檔", bg=T.CARD, fg=T.MUTED,
                         font=T.font(9)).pack(side="left")
                ttk.Button(r, text="📂", width=3, style=f"{KEY}.Small.TButton",
                           command=lambda p=path: open_external(p)).pack(side="right")
        if imgs:
            self._h(f"照片（{len(imgs)}）")
            self._thumb_grid(imgs[:MAX_THUMBS])
            if len(imgs) > MAX_THUMBS:
                tk.Label(self.body, text=f"…還有 {len(imgs) - MAX_THUMBS} 張，按 📂 看全部", bg=T.CARD, fg=T.MUTED,
                         font=T.font(9), anchor="w").pack(fill="x")
        if data:
            self._h(f"資料檔（{len(data)}）")
            self._file_rows(data)
        if step.get("raw"):
            self._h("試算表原文")
            tk.Label(self.body, text=" → ".join(step["raw"]), bg=T.TEXT_BG, fg=T.TEXT, font=T.font(9), anchor="w",
                     justify="left", wraplength=T.px(520), padx=8, pady=6).pack(fill="x")
        if step.get("notes"):
            self._h("備註")
            tk.Label(self.body, text=step["notes"], bg=T.CARD, fg=T.TEXT, font=T.font(10), anchor="w", justify="left",
                     wraplength=T.px(520)).pack(fill="x")

    def _sub_row(self, k, sub):
        r = tk.Frame(self.body, bg=T.SUBTLE if sub else T.CARD, padx=8, pady=4)
        r.pack(fill="x", pady=1)
        tk.Label(r, text="✓" if sub else "○", bg=r.cget("bg"), fg=K.color(k) if sub else T.FAINT,
                 font=T.font(10, "bold"), width=2).pack(side="left")
        tk.Label(r, text=K.label(k), bg=r.cget("bg"), fg=T.TEXT if sub else T.FAINT, font=T.font(10, "bold"),
                 width=14, anchor="w").pack(side="left")
        if sub:
            txt = "　".join(f"{a} {b}" for a, b in K.params_text(k, sub.get("params")))
            if sub.get("folders"):
                txt = (txt + "　" if txt else "") + "📷 " + "、".join(sub["folders"])
            tk.Label(r, text=txt or "（有做，沒有記參數）", bg=r.cget("bg"), fg=T.TEXT if txt else T.MUTED, font=T.font(9),
                     anchor="w", justify="left", wraplength=T.px(330)).pack(side="left", fill="x", expand=True)
        else:
            tk.Label(r, text="沒有紀錄（之後可以補填）", bg=r.cget("bg"), fg=T.FAINT, font=T.font(9), anchor="w").pack(
                side="left")

    def _file_rows(self, paths):
        for p in paths:
            r = tk.Frame(self.body, bg=T.CARD)
            r.pack(fill="x", pady=1)
            tk.Label(r, text=os.path.basename(p), bg=T.CARD, fg=T.TEXT, font=T.font(9), anchor="w").pack(
                side="left", fill="x", expand=True)
            ext = os.path.splitext(p)[1].lower()
            if ext in (".dat", ".txt", ".csv"):
                ttk.Button(r, text="在 Magic Tool 開啟", style=f"{KEY}.Small.TButton",
                           command=lambda p=p: self.app.open_path(p)).pack(side="right")
            ttk.Button(r, text="開啟", style=f"{KEY}.Small.TButton",
                       command=lambda p=p: open_external(p)).pack(side="right", padx=(0, 4))

    # ---- 照片縮圖：背景讀檔縮小，主執行緒建立 PhotoImage
    def _thumb_grid(self, items):
        g = tk.Frame(self.body, bg=T.CARD)
        g.pack(fill="x")
        cols = 3
        todo = []
        for i, (fname, path) in enumerate(items):
            cell = tk.Frame(g, bg=T.CARD)
            cell.grid(row=i // cols, column=i % cols, sticky="nw", padx=(0, 8), pady=(0, 6))
            lab = tk.Label(cell, text="…", bg=T.SUBTLE, fg=T.FAINT, width=T.px(THUMB[0]) // 8, height=5, cursor="hand2")
            lab.pack()
            tk.Label(cell, text=os.path.basename(path)[:22], bg=T.CARD, fg=T.MUTED, font=T.font(8)).pack(anchor="w")
            lab.bind("<Button-1>", lambda e, p=path, f=fname: self.show_photo(p, f))
            self._thumb_labels[path] = lab
            if path in self._thumb_cache:
                self._set_thumb(path, self._thumb_cache[path])
            else:
                todo.append(path)
        if todo:
            self.app.submit(lambda: self._load_thumbs(todo))

    def _load_thumbs(self, paths):
        try:
            from PIL import Image
        except ImportError:
            return
        size = (T.px(THUMB[0]), T.px(THUMB[1]))
        for p in paths:
            img = None
            if F.is_cloud_only(p):                          # 不要為了縮圖把雲端的照片一張張下載下來
                self.app.post(("call", lambda p=p: self._got_thumb(p, "cloud")))
                continue
            try:
                with Image.open(p) as im:
                    im.draft("RGB", size)
                    im = im.convert("RGB")
                    im.thumbnail(size)
                    img = im.copy()
            except Exception:
                img = False
            self.app.post(("call", lambda p=p, img=img: self._got_thumb(p, img)))

    def _got_thumb(self, path, img):
        self._thumb_cache[path] = img
        if len(self._thumb_cache) > 400:                     # 不要無限制佔記憶體
            for k in list(self._thumb_cache)[:100]:
                self._thumb_cache.pop(k, None)
        self._set_thumb(path, img)

    def _set_thumb(self, path, img):
        lab = getattr(self, "_thumb_labels", {}).get(path)
        if lab is None or not lab.winfo_exists():
            return
        if img == "cloud":
            lab.configure(text="☁ 只在雲端\n點一下下載", fg=T.MUTED)
            return
        if not img:
            lab.configure(text="（無法預覽）")
            return
        try:
            from PIL import ImageTk
            ph = ImageTk.PhotoImage(img)
        except Exception:
            lab.configure(text="（無法預覽）")
            return
        self._imgs.append(ph)
        lab.configure(image=ph, text="", width=0, height=0)

    def show_photo(self, path, title=""):
        from .om_images import OMViewer
        OMViewer(self.app.root, [(title or os.path.basename(path), path)], KEY, title=os.path.basename(path))

    # ================================================================== 動作
    def open_sample_dir(self):
        if self.sample and self.sample["has_folder"]:
            open_external(self.sample["dir"])

    def pick_root(self):
        d = filedialog.askdirectory(parent=self.app.root, title="選樣品根目錄（裡面是各個樣品資料夾，或專案資料夾）",
                                    initialdir=self.cfg.get("root") or None)
        if d:
            self.save_cfg(root=os.path.normpath(d))

    def save_cfg(self, rescan=True, **changes):
        new = dict(self.app.settings)
        sm = sample_settings(new)
        sm.update(changes)
        new["samples"] = sm
        self.app.settings = new
        self.cfg = sm
        S.save_settings(new)
        if rescan:
            self.rescan()

    def open_settings(self):
        SampleSettings(self)

    def create_record(self, s=None):
        s = s or self.sample
        if not s or not self.lib:
            return None
        rec = self.lib.preview(s)
        try:
            R.save(rec, s["path"])
        except OSError as e:
            messagebox.showerror("建立紀錄檔", f"寫不進去：{e}", parent=self.app.root)
            return None
        s["rec"] = rec
        s.pop("rec_preview", None)
        self.app.status(f"已建立紀錄檔：{s['path']}", "ok")
        self._show_sample(s, keep_step=True)
        self.refresh_list()
        return s["path"]

    def resolve_selected(self):
        sel = self.rv_list.curselection()
        if not sel or not self.sample:
            return
        self.resolve(self.sample, self._rv_items[sel[0]]["id"])

    def resolve(self, s, rid):
        """標記已確認：寫進紀錄檔（還沒有紀錄檔的樣品會順便建立）。"""
        rec = self.lib.preview(s)
        for r in rec.get("review", []):
            if r["id"] == rid:
                r["resolved"] = True
                r["resolved_at"] = time.strftime("%Y-%m-%d %H:%M")
        try:
            R.save(rec, s["path"])
        except OSError as e:
            messagebox.showerror("待確認", f"寫不進紀錄檔：{e}", parent=self.app.root)
            return
        s["rec"] = rec
        s.pop("rec_preview", None)
        if self.sample and self.sample["key"] == s["key"]:
            self._show_sample(s, keep_step=True)
        self._update_review_btn()

    def _jump_review(self):
        sel = self.rv_list.curselection()
        if sel and self._rv_items[sel[0]].get("step"):
            self.select_step(self._rv_items[sel[0]]["step"])

    def _update_review_btn(self):
        n = len(self.lib.reviews()) if self.lib else 0
        self.review_btn.configure(text=f"⚠ 待確認（{n}）" if n else "✓ 沒有待確認")

    def open_reviews(self):
        if self.lib:
            ReviewDialog(self)

    def open_import(self):
        ImportDialog(self)

    def open_demo(self):
        from ..testdata import write_samples
        d = S.data_dir() / "demo_samples"
        p = write_samples(str(d))
        self.save_cfg(root=p["root"], sheet=p["sheet"], user=self.cfg.get("user") or "demo")
        self.app.status(f"已產生範例樣品（合成資料）：{p['root']}", "ok", open_path=p["root"])
        return p

    # ---- 匯入（對話框與自我測試共用）
    def fetch_sheet(self, source):
        sa = self.cfg.get("service_account") or str(S.service_account_path(self.app.settings))
        if (self.cfg.get("sheet_script_url") or "").strip() and SH.sheet_key(source) == SH.sheet_key(self.cfg.get("sheet", "")) \
                and "docs.google.com" in source:
            try:                                                # 試算表不公開也讀得到
                return SH.parse_table(self.sheet_writer().values())
            except Exception:
                pass
        rows = SH.parse_table(SH.fetch(source, sa))
        return rows

    def apply_sheet(self, rows, source):
        """存試算表快取並重新掃描（可以在背景執行緒呼叫；回傳新的 Library，介面更新交給呼叫的人）。"""
        lib = self._make_lib()
        lib.save_cache(rows, source)
        lib.scan()
        return lib

    def use_lib(self, lib):
        self._scan_gen += 1                                  # 進行中的掃描結果作廢
        self.scanning = False
        self.lib = lib
        self.refresh_list()
        self._update_review_btn()

    # ================================================================== v0.7：編輯
    def user(self):
        return self.cfg.get("user") or "me"

    def _selected_step(self):
        sel = self.tl.selection()
        return sel[0] if sel else None

    def open_step_editor(self, s, rec, step=None, after=None):
        return SE.StepEditor(self, s, copy.deepcopy(rec), copy.deepcopy(step) if step else None, after)

    def new_step(self):
        if not self.sample:
            return None
        rec = self.record()
        after = self._selected_step() or (rec["steps"][-1]["id"] if rec.get("steps") else None)
        return self.open_step_editor(self.sample, rec, None, after)

    def edit_selected_step(self):
        sid = self._selected_step()
        if not self.sample or not sid:
            return None
        rec = self.record()
        step = E.find(rec, sid)
        return self.open_step_editor(self.sample, rec, step) if step else None

    def add_step(self, s, new, after=None):
        rec = copy.deepcopy(self.lib.preview(s))
        sid = E.insert_step(rec, new, after, self.user())
        self.commit(s, rec, f"已新增 {K.step_name(E.find(rec, sid))}", select_step=sid)
        return sid

    def edit_step(self, s, sid, new):
        rec = copy.deepcopy(self.lib.preview(s))
        step = E.update_step(rec, sid, new, self.user())
        self.commit(s, rec, f"已修改 {K.step_name(step)}", select_step=sid)

    def delete_selected_step(self, confirm=True):
        sid = self._selected_step()
        if not self.sample or not sid:
            return
        rec = copy.deepcopy(self.record())
        step = E.find(rec, sid)
        if confirm and not messagebox.askyesno("刪除步驟", f"刪除「{K.step_name(step)}」？\n（資料夾和照片不會被刪，只是紀錄裡拿掉這一步）",
                                               parent=self.app.root):
            return
        E.delete_step(rec, sid, self.user())
        self.commit(self.sample, rec, f"已刪除 {K.step_name(step)}")

    def move_selected(self, delta):
        sid = self._selected_step()
        if not self.sample or not sid:
            return
        rec = copy.deepcopy(self.record())
        if E.move_step(rec, sid, delta, self.user()):
            self.commit(self.sample, rec, "", select_step=sid)

    def toggle_state(self, which):
        if not self.sample:
            return None
        state = (self.record().get("status") or {}).get("state", "active")
        if which == state:                                   # 繼續製作 / 取消放棄
            self.change_state(self.sample, "active")
            return None
        return SE.StateDialog(self, self.sample, which)

    def change_state(self, s, state, reason="", next_date=None):
        rec = copy.deepcopy(self.lib.preview(s))
        E.set_state(rec, state, reason, next_date, user=self.user())
        self.commit(s, rec, f"{s['label']}：{K.state_label(state)}")

    def open_results(self, source_page=None):
        return SE.ResultDialog(self, self.sample, source_page)

    def save_results(self, s, vals, source=""):
        rec = copy.deepcopy(self.lib.preview(s))
        E.set_results(rec, source=source, user=self.user(), **vals)
        self.commit(s, rec, f"{s['label']}：已更新結果")

    def open_new_sample(self):
        return SE.NewSampleDialog(self)

    def create_sample(self, label, typ="", start="", project=""):
        """project = None → 存在這台電腦；"" → 根目錄底下；其他 → 那個專案資料夾底下。"""
        if self.lib and any(x["label"].lower() == label.lower() for x in self.lib.samples):
            raise ValueError(f"已經有「{label}」這個樣品了")
        if project is None or not self.cfg.get("root"):
            d, path = "", R.local_path(S.data_dir(), self.user(), label)
        else:
            parts = [self.cfg["root"]] + [p.strip() for p in project.split(" / ") if p.strip()] + [R.safe_name(label)]
            d = os.path.join(*parts)
            if os.path.isdir(d) and os.listdir(d):
                raise ValueError(f"資料夾已經存在而且不是空的：{d}")
            os.makedirs(d, exist_ok=True)
            path = R.record_path(d, self.cfg.get("record_name"))
        rec = {"label": label, "user": self.user(), "project": project or "", "type": typ, "start": start, "folder": d,
               "status": {"state": "active", "stopped_at": None}, "results": {}, "steps": [], "review": [], "notes": "",
               "created": time.strftime("%Y-%m-%d %H:%M:%S")}
        E.log(rec, "建立樣品", "", self.user())
        s = {"key": R.sample_key(self.user(), label), "label": label, "project": project or "", "dir": d, "path": path,
             "rec": None, "has_folder": bool(d), "sheet": None}
        if self.lib is not None:
            self.lib.samples.append(s)
            self.lib.samples.sort(key=lambda x: R._sort_key(x["label"]))
        self.commit(s, rec, f"已建立樣品 {label}" + (f"：{d}" if d else "（紀錄存在這台電腦）"))
        self.refresh_list(select=s["key"])
        return s

    def commit(self, s, rec, msg="", select_step=None):
        """存紀錄檔 → 更新畫面 → （有開自動更新）背景寫進試算表。"""
        if self.cfg.get("sheet_sync"):
            rec["sync"] = {"state": "pending", "time": time.strftime("%Y-%m-%d %H:%M")}
        try:
            R.save(rec, s["path"])
        except OSError as e:
            messagebox.showerror("樣品紀錄", f"寫不進紀錄檔：{e}", parent=self.app.root)
            return False
        s["rec"] = rec
        s.pop("rec_preview", None)
        if msg:
            self.app.status(msg, "ok")
        if self.sample and self.sample["key"] == s["key"]:
            self.step_id = select_step or self.step_id
            self._show_sample(s, keep_step=True)
            if select_step and self.tl.exists(select_step):
                self.select_step(select_step)
        self.refresh_list()
        self._update_review_btn()
        self._update_sync_btn()
        if self.cfg.get("sheet_sync") and self.can_sync():
            self.sync_many([s])
        return True

    # ---- RIE 時間建議用的蝕刻率
    def etch_rates(self, kind="rie"):
        from ..fab import etchrate as ER
        recs = [x.get("rec") or x.get("rec_preview") for x in (self.lib.samples if self.lib else [])]
        df = None
        try:
            from ..etching import store
            df = store.read_log(S.etching_csv(self.app.settings))
        except Exception:
            df = None
        return ER.rates_for([r for r in recs if r], df, kind)

    # ---- 試算表
    def can_sync(self):
        c = self.cfg
        if (c.get("sheet_script_url") or "").strip():
            return bool((c.get("sheet_token") or "").strip())
        sa = c.get("service_account") or str(S.service_account_path(self.app.settings))
        return bool(c.get("sheet")) and "docs.google.com" in c.get("sheet", "") and os.path.isfile(sa)

    def sheet_writer(self):
        from ..fab import sheet_sync as SS
        return SS.writer(self.cfg, str(S.service_account_path(self.app.settings)))

    def pending_sync(self):
        return [x for x in (self.lib.samples if self.lib else [])
                if (x.get("rec") or {}).get("sync", {}).get("state") in ("pending", "error")]

    def _update_sync_btn(self):
        n = len(self.pending_sync())
        self.sync_btn.configure(text=f"☁ 試算表（{n}）" if n else "☁ 試算表")

    def sync_many(self, samples, done=None):
        """背景把幾個樣品寫進試算表（一次讀整張表，再一個一個寫）。"""
        jobs = [(x, copy.deepcopy(x["rec"])) for x in samples if x.get("rec") is not None]
        if not jobs:
            return

        def work():
            with self._sync_lock:                              # 一次只寫一批（不然同時新增可能重複加一列）
                results, err = self._push_jobs(jobs)
            self.app.post(("call", lambda: self._synced(results, err, done)))
        self.app.submit(work)

    def _push_jobs(self, jobs):
        from ..fab import sheet_sync as SS
        results, err = [], None
        try:
            sh = self.sheet_writer()
            values = sh.values()
            for s, rec in jobs:
                try:
                    act, row = SS.push(rec, sh, values)
                    results.append((s, "ok", f"{act} {row}"))
                    if act == "append" or getattr(sh, "_values_dirty", False):   # 加了列 / 插了欄 → 重新讀
                        values = sh.values()
                        sh._values_dirty = False
                except Exception as e:
                    results.append((s, "error", str(e)))
        except Exception as e:
            err = str(e)
            results = [(s, "error", err) for s, _ in jobs]
        return results, err

    def _synced(self, results, err, done=None):
        ok = 0
        for s, state, info in results:
            rec = s.get("rec")
            if rec is None:
                continue
            rec["sync"] = {"state": state, "time": time.strftime("%Y-%m-%d %H:%M"), "info": info}
            try:
                R.save(rec, s["path"])
            except OSError:
                pass
            ok += state == "ok"
        bad = len(results) - ok
        msg = f"試算表：已更新 {ok} 個樣品" + (f"，{bad} 個失敗：{err or results[-1][2]}" if bad else "")
        self.app.status(msg, "ok" if not bad else "warn")
        if bad:
            self.app.log("樣品試算表更新失敗：\n" + "\n".join(f"{s['label']}：{i}" for s, st, i in results if st != "ok"))
        self._update_sync_btn()
        if self.sample:
            self._show_sample(self.sample, keep_step=True)
        if done:
            done(msg)

    def open_sync(self):
        return SE.SyncDialog(self)


class SampleSettings(_Dialog):
    """⚙ 樣品設定：使用者、根目錄、紀錄檔名稱、資料夾命名規則、試算表。"""

    def __init__(self, page):
        super().__init__(page.app.root)
        self.page = page
        self.title("樣品設定")
        self.configure(bg=T.CARD, padx=16, pady=14)
        self.transient(page.app.root)
        c = sample_settings(page.app.settings)
        self.vars = {k: tk.StringVar(value=str(c.get(k, ""))) for k in ("user", "root", "record_name", "sheet",
                                                                        "service_account", "sheet_script_url",
                                                                        "sheet_token")}
        self.sync = tk.BooleanVar(value=bool(c.get("sheet_sync")))
        rule = c.get("folder_rule") or F.DEFAULT_RULE
        preset = next((n for n, r in F.RULE_PRESETS if r == rule), "自訂（正規表示式）")
        self.rule_choice = tk.StringVar(value=preset)
        self.rule_var = tk.StringVar(value=rule)
        rows = [("使用者名稱", "user", "每個人的樣品分開記；編號只要在同一個人底下不重複就好"),
                ("樣品根目錄", "root", "例如 …\\SynologyDrive\\00 Users\\01 Yeep\\00 Samples（底下可以有專案資料夾）"),
                ("紀錄檔名稱", "record_name", "{folder} = 樣品資料夾名稱，例如「{folder}.json」「{folder}_製程.json」"),
                ("試算表", "sheet", "Google Sheet 網址，或下載的 .xlsx / .csv 檔"),
                ("服務帳號金鑰", "service_account", "空白 = 和蝕刻紀錄共用（secrets\\service_account.json）"),
                ("Apps Script 網址", "sheet_script_url", "裝在「樣品試算表」裡的 Apps Script（…/exec）；和蝕刻紀錄的是不同一份"),
                ("通行碼", "sheet_token", "Apps Script 執行 setupToken 後顯示的通行碼（只存在這台電腦）")]
        for r, (lab, key, hint) in enumerate(rows):
            tk.Label(self, text=lab, bg=T.CARD, fg=T.TEXT, font=T.font(10, "bold")).grid(row=2 * r, column=0, sticky="w",
                                                                                       pady=(6, 0))
            ttk.Entry(self, textvariable=self.vars[key], width=58).grid(row=2 * r, column=1, sticky="we", pady=(6, 0))
            if key == "root":
                ttk.Button(self, text="選…", style=f"{KEY}.Small.TButton", command=self._pick_root).grid(
                    row=2 * r, column=2, padx=(4, 0), pady=(6, 0))
            if key in ("sheet", "service_account"):
                ttk.Button(self, text="選…", style=f"{KEY}.Small.TButton",
                           command=lambda k=key: self._pick_file(k)).grid(row=2 * r, column=2, padx=(4, 0), pady=(6, 0))
            tk.Label(self, text=hint, bg=T.CARD, fg=T.MUTED, font=T.font(8)).grid(row=2 * r + 1, column=1, sticky="w")
        r = 2 * len(rows)
        tk.Label(self, text="資料夾命名規則", bg=T.CARD, fg=T.TEXT, font=T.font(10, "bold")).grid(row=r, column=0,
                                                                                           sticky="w", pady=(6, 0))
        cb = ttk.Combobox(self, textvariable=self.rule_choice, state="readonly", width=40,
                          values=[n for n, _ in F.RULE_PRESETS] + ["自訂（正規表示式）"])
        cb.grid(row=r, column=1, sticky="w", pady=(6, 0))
        cb.bind("<<ComboboxSelected>>", lambda e: self._preset())
        ttk.Entry(self, textvariable=self.rule_var, width=58).grid(row=r + 1, column=1, sticky="we")
        tk.Label(self, text="自訂：第一組 = 編號、第二組 = 名稱（或用 (?P<no>…)、(?P<name>…)）", bg=T.CARD, fg=T.MUTED,
                 font=T.font(8)).grid(row=r + 2, column=1, sticky="w")
        sf = tk.Frame(self, bg=T.CARD)
        sf.grid(row=r + 3, column=1, columnspan=2, sticky="w", pady=(10, 0))
        ttk.Checkbutton(sf, text="自動更新試算表（新增 / 修改步驟、狀態、結果時寫進試算表）", variable=self.sync,
                        style=f"{KEY}.TCheckbutton").pack(side="left")
        ttk.Button(sf, text="📋 複製 Apps Script 程式碼", style=f"{KEY}.Small.TButton", command=self._copy_script).pack(
            side="left", padx=(8, 0))
        self.msg = tk.Label(self, text="", bg=T.CARD, fg=T.MUTED, font=T.font(8), anchor="w")
        self.msg.grid(row=r + 4, column=1, columnspan=2, sticky="w")
        bf = tk.Frame(self, bg=T.CARD)
        bf.grid(row=r + 5, column=0, columnspan=3, sticky="e", pady=(14, 0))
        ttk.Button(bf, text="取消", style=f"{KEY}.Ghost.TButton", command=self.destroy).pack(side="right")
        ttk.Button(bf, text="儲存", style=f"{KEY}.Accent.TButton", command=self.save).pack(side="right", padx=(0, 6))
        self.columnconfigure(1, weight=1)

    def _copy_script(self):
        from ..etching import gsync
        self.clipboard_clear()
        self.clipboard_append(gsync.script_code())
        self.msg.configure(text="已複製。打開樣品試算表 → 擴充功能 → Apps Script → 貼上 → 執行 setupToken → 部署成網頁應用程式"
                                "（步驟和蝕刻紀錄一樣，見「Google Sheet 團隊設定.md」）", fg=T.SUCCESS)

    def _preset(self):
        r = dict(F.RULE_PRESETS).get(self.rule_choice.get())
        if r:
            self.rule_var.set(r)

    def _pick_root(self):
        d = filedialog.askdirectory(parent=self, initialdir=self.vars["root"].get() or None)
        if d:
            self.vars["root"].set(os.path.normpath(d))

    def _pick_file(self, key):
        types = [("試算表", "*.xlsx *.csv *.tsv"), ("全部", "*.*")] if key == "sheet" else [("JSON", "*.json")]
        p = filedialog.askopenfilename(parent=self, filetypes=types)
        if p:
            self.vars[key].set(os.path.normpath(p))

    def save(self):
        import re
        try:
            re.compile(self.rule_var.get() or F.DEFAULT_RULE)
        except re.error as e:
            messagebox.showerror("樣品設定", f"命名規則不是有效的正規表示式：{e}", parent=self)
            return
        name = self.vars["record_name"].get().strip() or R.DEFAULT_RECORD_NAME
        if "{folder}" not in name and "{label}" not in name:
            if not messagebox.askyesno("樣品設定", "紀錄檔名稱沒有 {folder}：每個樣品的紀錄檔會同名（仍然各自放在自己的資料夾）。"
                                                    "要繼續嗎？", parent=self):
                return
        self.page.save_cfg(**{k: v.get().strip() for k, v in self.vars.items()}, folder_rule=self.rule_var.get().strip(),
                           record_name=name, sheet_sync=bool(self.sync.get()))
        self.destroy()


class ImportDialog(_Dialog):
    """📥 從試算表匯入：讀試算表 → 預覽（會建立幾個紀錄檔、幾個待確認）→ 建立紀錄檔。"""

    def __init__(self, page):
        super().__init__(page.app.root)
        self.page = page
        self.rows = None
        self.title("從試算表匯入")
        self.configure(bg=T.CARD, padx=16, pady=14)
        self.transient(page.app.root)
        c = sample_settings(page.app.settings)
        tk.Label(self, text="📥 從試算表匯入", bg=T.CARD, fg=T.TEXT, font=T.font(13, "bold"), anchor="w").pack(fill="x")
        tk.Label(self, bg=T.CARD, fg=T.MUTED, font=T.font(9), anchor="w", justify="left", wraplength=T.px(560),
                 text="讀試算表的製程紀錄，和樣品資料夾合併，替每個樣品建立一個紀錄檔（資料夾裡的照片、試算表本身都不會被修改；"
                      "已經有紀錄檔的樣品不會動）。").pack(fill="x", pady=(2, 8))
        r = tk.Frame(self, bg=T.CARD)
        r.pack(fill="x")
        self.src = tk.StringVar(value=c.get("sheet", ""))
        ttk.Entry(r, textvariable=self.src, width=60).pack(side="left", fill="x", expand=True)
        ttk.Button(r, text="選檔案", style=f"{KEY}.Small.TButton", command=self._pick).pack(side="left", padx=(4, 0))
        ttk.Button(r, text="讀取", style=f"{KEY}.Accent.TButton", command=self.read).pack(side="left", padx=(4, 0))
        tk.Label(self, bg=T.CARD, fg=T.FAINT, font=T.font(8), anchor="w", justify="left", wraplength=T.px(560),
                 text=("Google Sheet：貼網址。試算表要共用給服務帳號（和蝕刻紀錄同一個金鑰），或「知道連結的人可以檢視」。"
                       "也可以在 Google Sheet 選「檔案 → 下載 → .xlsx」，再按「選檔案」。").replace(" ", "\u00a0")).pack(
            fill="x", pady=(4, 0))
        self.info = tk.Label(self, text="", bg=T.SUBTLE, fg=T.TEXT, font=T.font(10), anchor="w", justify="left",
                             wraplength=T.px(560), padx=10, pady=8)
        self.info.pack(fill="x", pady=(10, 0))
        bf = tk.Frame(self, bg=T.CARD)
        bf.pack(fill="x", pady=(12, 0))
        ttk.Button(bf, text="關閉", style=f"{KEY}.Ghost.TButton", command=self.destroy).pack(side="right")
        self.go = ttk.Button(bf, text="建立紀錄檔", style=f"{KEY}.Accent.TButton", command=self.create)
        self.go.pack(side="right", padx=(0, 6))
        self.go.state(["disabled"])

    def _pick(self):
        p = filedialog.askopenfilename(parent=self, filetypes=[("試算表", "*.xlsx *.csv *.tsv"), ("全部", "*.*")])
        if p:
            self.src.set(os.path.normpath(p))

    def read(self):
        src = self.src.get().strip()
        self.info.configure(text="讀取中…", fg=T.TEXT)

        def work():                                     # 讀試算表、掃描資料夾、產生預覽都在背景（雲端硬碟可能要幾秒）
            lib = text = None
            try:
                rows = self.page.fetch_sheet(src)
                lib = self.page.apply_sheet(rows, src)
                text = self.preview_text(lib)
                err = None
            except Exception as e:
                err = str(e)
            self.page.app.post(("call", lambda: self._read_done(src, lib, text, err)))
        self.page.app.submit(work)

    def _read_done(self, src, lib, text, err):
        if not self.winfo_exists():
            return
        if err:
            self.info.configure(text=err, fg=T.ERROR)
            return
        self.page.save_cfg(rescan=False, sheet=src)
        self.page.use_lib(lib)
        self.info.configure(text=text, fg=T.TEXT)
        self.go.state(["!disabled"])

    @staticmethod
    def preview_text(lib):
        new_dir = [s for s in lib.samples if s.get("rec") is None and s["has_folder"]]
        new_loc = [s for s in lib.samples if s.get("rec") is None and not s["has_folder"]]
        kept = [s for s in lib.samples if s.get("rec") is not None]
        n_rv = sum(len(R.open_reviews(lib.preview(s))) for s in lib.samples)
        only_dir = [s for s in lib.samples if s["has_folder"] and not s.get("sheet")]
        return (f"試算表 {len(lib.sheet_rows)} 個樣品；找到 {sum(1 for s in lib.samples if s['has_folder'])} 個樣品資料夾。\n\n"
                f"會建立：資料夾裡 {len(new_dir)} 個紀錄檔、這台電腦 {len(new_loc)} 個（試算表有、找不到資料夾）\n"
                f"不會動：{len(kept)} 個已經有紀錄檔\n"
                f"只有資料夾、試算表沒有：{len(only_dir)} 個\n"
                f"對不起來、需要確認：{n_rv} 項（建立後在「⚠ 待確認」逐一看）")

    def create(self):
        lib = self.page.lib
        if lib is None:
            return
        self.go.state(["disabled"])
        self.info.configure(text="建立紀錄檔中…", fg=T.TEXT)

        def work():
            res = lib.import_all()
            self.page.app.post(("call", lambda: self._created(*res)))
        self.page.app.submit(work)

    def _created(self, made, kept, failed):
        msg = f"已建立 {len(made)} 個紀錄檔，{len(kept)} 個原本就有（沒有動）。"
        if failed:
            msg += "\n\n建立失敗：\n" + "\n".join(failed[:10])
        if self.winfo_exists():
            self.info.configure(text=msg, fg=T.ERROR if failed else T.SUCCESS)
        self.page.refresh_list()
        self.page._update_review_btn()
        if self.page.sample:
            self.page._show_sample(self.page.sample)
        self.page.app.status(f"匯入完成：建立 {len(made)} 個紀錄檔", "ok" if not failed else "warn")


class ReviewDialog(_Dialog):
    """⚠ 待確認：所有樣品對不起來的地方。雙擊跳到那個樣品 / 步驟；「已確認」寫進紀錄檔。"""

    def __init__(self, page):
        super().__init__(page.app.root)
        self.page = page
        self.title("待確認")
        self.configure(bg=T.CARD, padx=12, pady=12)
        self.transient(page.app.root)
        self.geometry(f"{T.px(860)}x{T.px(520)}")
        self.head = tk.Label(self, text="", bg=T.CARD, fg=T.TEXT, font=T.font(12, "bold"), anchor="w")
        self.head.pack(fill="x")
        tk.Label(self, text="雙擊一列跳到那個樣品；看過、沒問題就按「已確認」（會記在樣品的紀錄檔裡）。"
                            "要修改步驟的話，編輯功能在下一版。", bg=T.CARD, fg=T.MUTED, font=T.font(9), anchor="w").pack(fill="x")
        f = tk.Frame(self, bg=T.CARD)
        f.pack(fill="both", expand=True, pady=(8, 0))
        self.tree = ttk.Treeview(f, columns=("sample", "msg"), show="headings", style=f"{KEY}.Treeview")
        self.tree.heading("sample", text="樣品")
        self.tree.heading("msg", text="需要確認的地方")
        self.tree.column("sample", width=T.px(80), stretch=False)
        self.tree.column("msg", width=T.px(700))
        sb = ttk.Scrollbar(f, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Double-Button-1>", lambda e: self.jump())
        bf = tk.Frame(self, bg=T.CARD)
        bf.pack(fill="x", pady=(8, 0))
        ttk.Button(bf, text="關閉", style=f"{KEY}.Ghost.TButton", command=self.destroy).pack(side="right")
        ttk.Button(bf, text="✓ 已確認", style=f"{KEY}.Accent.TButton", command=self.resolve).pack(side="right", padx=(0, 6))
        ttk.Button(bf, text="跳到樣品", style=f"{KEY}.Small.TButton", command=self.jump).pack(side="left")
        self.fill()

    def fill(self):
        self.items = {}
        self.tree.delete(*self.tree.get_children())
        for i, (s, r) in enumerate(self.page.lib.reviews()):
            iid = f"r{i}"
            self.items[iid] = (s, r)
            self.tree.insert("", "end", iid=iid, values=(s["label"], r["msg"]))
        self.head.configure(text=f"⚠ 待確認（{len(self.items)}）" if self.items else "✓ 沒有待確認的地方")

    def jump(self):
        sel = self.tree.selection()
        if not sel:
            return
        s, r = self.items[sel[0]]
        p = self.page
        p.filter_var.set("")
        p.state_var.set(STATE_FILTERS[0][0])
        p.refresh_list(select=s["key"])
        p.app.segment.select(KEY)
        if r.get("step"):
            p.select_step(r["step"])

    def resolve(self):
        for iid in self.tree.selection():
            s, r = self.items[iid]
            self.page.resolve(s, r["id"])
        self.fill()
