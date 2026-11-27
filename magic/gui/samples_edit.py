"""樣品頁的編輯對話框（v0.7）：步驟編輯（步驟庫、contact 子步驟、RIE 時間建議）、擱置 / 放棄、結果、新樣品、
試算表同步。存檔與寫回試算表由 SamplePage 處理（commit），這裡只負責輸入。
"""
from __future__ import annotations

import os
import re
import time
import tkinter as tk
from tkinter import messagebox, ttk

from ..fab import edit as E
from ..fab import etchrate as ER
from ..fab import folders as F
from ..fab import steps as K
from . import theme as T
from .widgets import ScrollFrame

KEY = "Samples"


class _Dialog(tk.Toplevel):
    """關閉時在主執行緒放掉 StringVar 等變數：不然有時會在背景執行緒被回收，回收時又呼叫 Tk 而出錯。"""

    def destroy(self):
        super().destroy()
        for k, v in list(vars(self).items()):
            if isinstance(v, tk.Variable) or (isinstance(v, dict) and v and
                                              all(isinstance(x, tk.Variable) for x in v.values())):
                setattr(self, k, None)
            elif isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
                setattr(self, k, None)


def norm_date(text):
    """「2026/3/5」「20260305」「2026-03-05」→ 2026-03-05；空白 → ""；看不懂 → ValueError。"""
    t = str(text or "").strip()
    if not t:
        return ""
    m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", t) or re.fullmatch(r"(\d{4})(\d{2})(\d{2})", t)
    if not m:
        raise ValueError(t)
    y, mo, d = (int(x) for x in m.groups())
    time.strptime(f"{y}-{mo}-{d}", "%Y-%m-%d")
    return f"{y:04d}-{mo:02d}-{d:02d}"


def _val_text(typ, v):
    if v is None:
        return ""
    if typ == "layers":
        return K.format_layers(v)
    if typ == "stack":
        return K.format_layers(v, "stack")
    if typ == "method":
        return {"E": "E 蒸鍍", "S": "S 濺鍍"}.get(v, "")
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v)


HINT = {"layers": "例：Cr/Au 10/70（nm）", "stack": "由下往上，例：hBN 20 / TaS2 / hBN 40（厚度不知道可以不填）"}


class FieldSet:
    """一組參數欄位（一種步驟或一個子步驟）。"""

    def __init__(self, parent, kind, params, row0=0, col0=1, on_rie=None):
        self.kind = kind
        self.orig = dict(params or {})
        self.vars = {}
        self.specs = K.PARAMS.get(kind, [])
        bg = parent.cget("bg")
        c = col0
        for key, zh, en, unit, typ in self.specs:
            f = tk.Frame(parent, bg=bg)
            f.grid(row=row0, column=c, sticky="w", padx=(0, 10), pady=1)
            c += 1
            tk.Label(f, text=zh, bg=bg, fg=T.MUTED, font=T.font(8)).pack(anchor="w")
            line = tk.Frame(f, bg=bg)
            line.pack(anchor="w")
            var = tk.StringVar(value=_val_text(typ, self.orig.get(key)))
            self.vars[key] = var
            if typ == "method":
                ttk.Combobox(line, textvariable=var, values=["", "E 蒸鍍", "S 濺鍍"], state="readonly", width=7).pack(
                    side="left")
            elif typ == "tool":
                ttk.Combobox(line, textvariable=var, values=K.TOOLS, width=8).pack(side="left")
            else:
                w = {"num": 7, "text": 10, "layers": 16, "stack": 30}.get(typ, 10)
                ttk.Entry(line, textvariable=var, width=w).pack(side="left")
            if unit:
                tk.Label(line, text=unit, bg=bg, fg=T.MUTED, font=T.font(8)).pack(side="left", padx=(2, 0))
            if typ in HINT:
                tk.Label(f, text=HINT[typ], bg=bg, fg=T.FAINT, font=T.font(8)).pack(anchor="w")
        if kind in ("rie", "icp") and on_rie:
            f = tk.Frame(parent, bg=bg)
            f.grid(row=row0, column=c, sticky="w")
            ttk.Button(f, text="💡 建議時間", style=f"{KEY}.Small.TButton", command=lambda: on_rie(self)).pack(anchor="w")
            self.sug_lab = tk.Label(parent, text="", bg=bg, fg=T.TEXT, font=T.font(8), anchor="w", justify="left")
            self.sug_lab.grid(row=row0 + 1, column=col0, columnspan=6, sticky="w")
            self.sug_btn = ttk.Button(parent, text="", style=f"{KEY}.Small.TButton")
            self.sug = None

    def get(self):
        """回傳參數 dict；看不懂的欄位 → ValueError(欄位名稱)。"""
        out = {k: v for k, v in self.orig.items() if k not in self.vars}     # 不在表單上的欄位留著
        for key, zh, en, unit, typ in self.specs:
            t = self.vars[key].get().strip()
            if not t:
                continue
            if typ == "num":
                try:
                    out[key] = E.num(t)
                except ValueError:
                    raise ValueError(f"{K.label(self.kind)}「{zh}」要填數字（現在是「{t}」）")
            elif typ in ("layers", "stack"):
                ly = K.parse_layers(t)
                if ly is None:
                    raise ValueError(f"{K.label(self.kind)}「{zh}」看不懂（{HINT[typ]}）")
                out[key] = ly
            elif typ == "method":
                out[key] = t[0]
            else:
                out[key] = t
        return out


class StepEditor(_Dialog):
    """新增 / 編輯一步。contact / marker / top gate 有固定的子步驟（勾選有做的、選填參數）。"""

    def __init__(self, page, s, rec, step=None, after=None):
        super().__init__(page.app.root)
        self.page, self.s, self.rec, self.after = page, s, rec, after
        self.step = step
        self.new = step is None
        self.title("新增步驟" if self.new else f"編輯：{K.step_name(step)}")
        self.configure(bg=T.CARD, padx=14, pady=12)
        self.transient(page.app.root)
        self.geometry(f"{T.px(900)}x{T.px(640)}")
        self.minsize(T.px(640), T.px(420))
        self.prev_afm = self._prev_afm()
        top = tk.Frame(self, bg=T.CARD)
        top.pack(fill="x")
        tk.Label(top, text="種類", bg=T.CARD, fg=T.TEXT, font=T.font(10, "bold")).pack(side="left")
        self.kinds = list(K.LIBRARY)
        if step and step["kind"] not in self.kinds:
            self.kinds.append(step["kind"])
        names = [f"{K.icon(k)} {K.label(k)}" for k in self.kinds]
        kind0 = step["kind"] if step else "contact"
        self.kind_var = tk.StringVar(value=names[self.kinds.index(kind0)])
        cb = ttk.Combobox(top, textvariable=self.kind_var, values=names, state="readonly", width=18)
        cb.pack(side="left", padx=(6, 16))
        cb.bind("<<ComboboxSelected>>", lambda e: self._build_body())
        tk.Label(top, text="日期", bg=T.CARD, fg=T.TEXT, font=T.font(10, "bold")).pack(side="left")
        self.d1 = tk.StringVar(value=(step or {}).get("date", "") or ("" if step else time.strftime("%Y-%m-%d")))
        self.d2 = tk.StringVar(value=(step or {}).get("date_end", ""))
        ttk.Entry(top, textvariable=self.d1, width=11).pack(side="left", padx=(6, 2))
        tk.Label(top, text="～", bg=T.CARD, fg=T.MUTED).pack(side="left")
        ttk.Entry(top, textvariable=self.d2, width=11).pack(side="left", padx=(2, 4))
        tk.Label(top, text="（結束日可以空白）", bg=T.CARD, fg=T.FAINT, font=T.font(8)).pack(side="left")
        self.sf = ScrollFrame(self)
        self.sf.pack(fill="both", expand=True, pady=(10, 0))
        self.body = self.sf.body
        bf = tk.Frame(self, bg=T.CARD)
        bf.pack(fill="x", pady=(10, 0))
        ttk.Button(bf, text="取消", style=f"{KEY}.Ghost.TButton", command=self.destroy).pack(side="right")
        ttk.Button(bf, text="儲存", style=f"{KEY}.Accent.TButton", command=self.save).pack(side="right", padx=(0, 6))
        self.err = tk.Label(bf, text="", bg=T.CARD, fg=T.ERROR, font=T.font(9), anchor="w", justify="left",
                            wraplength=T.px(560))
        self.err.pack(side="left", fill="x", expand=True)
        self._build_body()

    def destroy(self):
        self.main = None
        self.subrows = None
        super().destroy()

    @property
    def kind(self):
        names = [f"{K.icon(k)} {K.label(k)}" for k in self.kinds]
        return self.kinds[names.index(self.kind_var.get())]

    def _prev_afm(self):
        """這一步之前最近一次 AFM 的 hBN 厚度（RIE 自動帶入）。"""
        stop = self.step["id"] if self.step else None
        val = None
        for st in self.rec.get("steps", []):
            if stop and st.get("id") == stop:
                break
            if st.get("kind") == "afm" and (st.get("params") or {}).get("hbn_nm") is not None:
                val = st["params"]["hbn_nm"]
            if not stop and self.after and st.get("id") == self.after:
                break
        return val

    def _section(self, text, top=10):
        tk.Label(self.body, text=text, bg=T.CARD, fg=T.TEXT, font=T.font(11, "bold"), anchor="w").pack(
            fill="x", pady=(top, 4))

    def _build_body(self):
        for w in self.body.winfo_children():
            w.destroy()
        kind = self.kind
        same = self.step is not None and self.step["kind"] == kind
        base = self.step if same else E.new_step(kind, self.rec)
        self.main = None
        self.subrows = []
        if K.PARAMS.get(kind):
            self._section("參數", 0)
            g = tk.Frame(self.body, bg=T.CARD)
            g.pack(fill="x")
            params = dict(base.get("params") or {})
            if kind == "rie" and params.get("hbn_nm") is None and self.prev_afm is not None:
                params["hbn_nm"] = self.prev_afm
            self.main = FieldSet(g, kind, params, on_rie=self.suggest)
        if kind in K.SUBSTEPS:
            self._section("子步驟（勾選有做的；參數都可以不填）", 0 if not self.main else 12)
            have = list(base.get("substeps") or [])
            kinds_have = {x["kind"] for x in have}
            rows = [(x["kind"], x) for x in have] + [(k, None) for k in K.SUBSTEPS[kind] if k not in kinds_have]
            if kind == "contact" and "icp" not in kinds_have:
                rows.append(("icp", None))
            rows.sort(key=lambda r: K.SUB_ORDER.get(r[0], 99))
            g = tk.Frame(self.body, bg=T.CARD)
            g.pack(fill="x")
            for i, (k, sub) in enumerate(rows):
                bg = T.SUBTLE if i % 2 == 0 else T.CARD
                fr = tk.Frame(g, bg=bg, padx=6, pady=4)
                fr.pack(fill="x")
                on = tk.BooleanVar(value=sub is not None)
                tk.Checkbutton(fr, variable=on, bg=bg, activebackground=bg, text=f"{K.icon(k)} {K.label(k)}",
                               font=T.font(10, "bold"), fg=K.color(k), selectcolor=T.FIELD, anchor="w", width=16,
                               ).grid(row=0, column=0, sticky="nw")
                p = dict((sub or {}).get("params") or {})
                if k == "rie" and p.get("hbn_nm") is None and self.prev_afm is not None:
                    p["hbn_nm"] = self.prev_afm
                fs = FieldSet(fr, k, p, on_rie=self.suggest) if K.PARAMS.get(k) else None
                if not K.PARAMS.get(k):
                    tk.Label(fr, text="照片放在對應的資料夾（下面「資料夾」勾選）", bg=bg, fg=T.FAINT,
                             font=T.font(8)).grid(row=0, column=1, sticky="w")
                if sub and sub.get("folders"):
                    tk.Label(fr, text="📷 " + "、".join(sub["folders"]), bg=bg, fg=T.MUTED, font=T.font(8)).grid(
                        row=2, column=1, columnspan=5, sticky="w")
                self.subrows.append({"kind": k, "on": on, "fs": fs, "orig": sub})
        # 資料夾
        self.folder_names = []
        if self.s.get("has_folder"):
            self._section("資料夾（這一步的照片、資料在哪幾個資料夾）")
            used = {}
            for st in self.rec.get("steps", []):
                if self.step and st.get("id") == self.step.get("id"):
                    continue
                for f in st.get("folders", []):
                    used[f] = K.step_name(st)
            entries = F.step_folders(self.s["dir"], self.page.cfg.get("folder_rule"), self.rec.get("start", ""))
            names = [e["folder"] for e in entries]
            mine = list((base or {}).get("folders") or [])
            names += [m for m in mine if m not in names]
            lf = tk.Frame(self.body, bg=T.CARD)
            lf.pack(fill="x")
            self.folder_list = tk.Listbox(lf, selectmode="multiple", height=min(8, max(3, len(names))), bd=0,
                                          highlightthickness=1, highlightbackground=T.BORDER, font=T.font(9),
                                          exportselection=False, activestyle="none",
                                          selectbackground=T.mix_color(T.accent(KEY)["main"], "#ffffff", 0.7),
                                          selectforeground=T.TEXT)
            for i, n in enumerate(names):
                self.folder_list.insert("end", n + (f"　（已用在 {used[n]}）" if n in used else ""))
                if n in mine:
                    self.folder_list.selection_set(i)
            self.folder_list.pack(side="left", fill="x", expand=True)
            self.folder_names = names
            if not names:
                tk.Label(self.body, text="樣品資料夾裡還沒有「NN 名稱」的子資料夾", bg=T.CARD, fg=T.FAINT,
                         font=T.font(9)).pack(anchor="w")
        self._section("備註")
        self.notes = tk.Text(self.body, height=3, font=T.font(10), bd=0, highlightthickness=1,
                             highlightbackground=T.BORDER, wrap="word")
        self.notes.insert("1.0", (base or {}).get("notes", ""))
        self.notes.pack(fill="x")

    # ---- RIE 時間建議
    def suggest(self, fs):
        p = {}
        for key in ("hbn_nm", "oe_nm"):
            t = fs.vars[key].get().strip() if key in fs.vars else ""
            try:
                p[key] = E.num(t)
            except ValueError:
                p[key] = None
        if p.get("hbn_nm") is None:
            fs.sug_lab.configure(text="先填 hBN 厚度（AFM 量到的），再按「建議時間」", fg=T.WARNING)
            return
        rates, src = self.page.etch_rates(fs.kind)
        sug = ER.suggest(p["hbn_nm"], p.get("oe_nm") or 0, rates, src)
        if not sug:
            fs.sug_lab.configure(text="還沒有可以參考的蝕刻率：過去樣品沒有記 RIE 時間與 hBN 厚度，Etching 紀錄也沒有這種機台",
                                 fg=T.WARNING)
            return
        fs.sug_lab.configure(text=sug["text"], fg=T.TEXT)
        fs.sug_btn.configure(text=f"套用 {sug['time_s']} s", command=lambda: fs.vars["time_s"].set(str(sug["time_s"])))
        fs.sug_btn.grid(row=int(fs.sug_lab.grid_info()["row"]) + 1, column=1, sticky="w", pady=(2, 4))
        fs.sug = sug

    # ---- 儲存
    def collect(self):
        kind = self.kind
        new = {"kind": kind, "params": {}, "substeps": [], "notes": self.notes.get("1.0", "end").strip()}
        new["date"] = norm_date(self.d1.get())
        new["date_end"] = norm_date(self.d2.get())
        if new["date_end"] and new["date"] and new["date_end"] < new["date"]:
            raise ValueError("結束日期比開始日期早")
        if self.main:
            new["params"] = self.main.get()
        elif self.step and self.step["kind"] == kind:
            new["params"] = dict(self.step.get("params") or {})
        for r in self.subrows:
            if not r["on"].get():
                continue
            sub = dict(r["orig"] or {"kind": r["kind"], "raw": "", "folders": []})
            sub["kind"] = r["kind"]
            sub["params"] = r["fs"].get() if r["fs"] else dict(sub.get("params") or {})
            new["substeps"].append(sub)
        if self.folder_names:
            new["folders"] = [self.folder_names[i] for i in self.folder_list.curselection()]
        else:
            new["folders"] = list((self.step or {}).get("folders") or [])
        return new

    def save(self):
        try:
            new = self.collect()
        except ValueError as e:
            msg = str(e)
            if re.fullmatch(r"[\d/\-.]+|.*time data.*", msg) or "does not match" in msg:
                msg = "日期請寫成 2026-03-05（或 2026/3/5、20260305）"
            self.err.configure(text=msg)
            return
        if self.new:
            self.page.add_step(self.s, new, self.after)
        else:
            self.page.edit_step(self.s, self.step["id"], new)
        self.destroy()


class StateDialog(_Dialog):
    """⏸ 擱置 / ✕ 放棄：原因（和擱置的預定日期）。"""

    def __init__(self, page, s, state):
        super().__init__(page.app.root)
        self.page, self.s, self.state = page, s, state
        rec = page.record(s)
        st = rec.get("status") or {}
        zh = K.state_label(state)
        self.title(zh)
        self.configure(bg=T.CARD, padx=16, pady=14)
        self.transient(page.app.root)
        tk.Label(self, text=f"{s['label']}：{zh}", bg=T.CARD, fg=T.TEXT, font=T.font(13, "bold"), anchor="w").grid(
            row=0, column=0, columnspan=2, sticky="w")
        tip = ("放棄的樣品會留在清單裡（變灰），之後可以按「取消放棄」恢復。" if state == "abandoned"
               else "擱置 = 暫停，之後會繼續；可以寫預定什麼時候繼續。")
        tk.Label(self, text=tip, bg=T.CARD, fg=T.MUTED, font=T.font(9), anchor="w").grid(row=1, column=0, columnspan=2,
                                                                                       sticky="w", pady=(2, 8))
        tk.Label(self, text="原因", bg=T.CARD, fg=T.TEXT, font=T.font(10, "bold")).grid(row=2, column=0, sticky="w")
        self.reason = tk.StringVar(value=st.get("reason", "") if st.get("state") == state else "")
        ttk.Entry(self, textvariable=self.reason, width=44).grid(row=2, column=1, sticky="we", pady=2)
        self.date = tk.StringVar(value=st.get("next_date", "") if state == "hold" else "")
        if state == "hold":
            tk.Label(self, text="預定日期", bg=T.CARD, fg=T.TEXT, font=T.font(10, "bold")).grid(row=3, column=0,
                                                                                            sticky="w")
            ttk.Entry(self, textvariable=self.date, width=14).grid(row=3, column=1, sticky="w", pady=2)
        self.err = tk.Label(self, text="", bg=T.CARD, fg=T.ERROR, font=T.font(9))
        self.err.grid(row=4, column=0, columnspan=2, sticky="w")
        bf = tk.Frame(self, bg=T.CARD)
        bf.grid(row=5, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(bf, text="取消", style=f"{KEY}.Ghost.TButton", command=self.destroy).pack(side="right")
        ttk.Button(bf, text=zh, style=f"{KEY}.Accent.TButton", command=self.ok).pack(side="right", padx=(0, 6))

    def ok(self):
        try:
            d = norm_date(self.date.get())
        except ValueError:
            self.err.configure(text="日期請寫成 2026-03-05（或 2026/3/5）")
            return
        self.page.change_state(self.s, self.state, self.reason.get().strip(), d)
        self.destroy()


def candidates_from(page_obj):
    """量測頁最後一次分析 → [(說明, {tc_k, r_ohm})]（PPMS 的低溫端電阻才帶入 R）。"""
    last = getattr(page_obj, "last", None) or {}
    rows = last.get("data") if isinstance(last.get("data"), list) else []
    out = []
    inst = getattr(getattr(page_obj, "inst", None), "key", "") or getattr(page_obj, "key", "")
    for r in rows:
        if not isinstance(r, dict) or "tc" not in r:
            continue
        res = r.get("res") or {}
        tc = r.get("tc")
        vals = {}
        if tc is not None and tc == tc:
            vals["tc_k"] = round(float(tc), 3)
        ys = res.get("y_s")
        if inst == "PPMS" and ys is not None and ys == ys:
            vals["r_ohm"] = round(float(ys), 3)
        if vals:
            desc = f"{r['item'].label}｜{r.get('name', '')}：" + "、".join(
                ([f"Tc {vals['tc_k']:g} K"] if "tc_k" in vals else []) +
                ([f"低溫端 {vals['r_ohm']:g} Ω"] if "r_ohm" in vals else []))
            out.append((desc, vals, r["item"].path))
    return out


class ResultDialog(_Dialog):
    """✎ 結果：低溫電阻、是否超導 contact（在哪個材料上）、Tc。也可以從量測頁的分析結果帶入。"""

    def __init__(self, page, s=None, source_page=None):
        super().__init__(page.app.root)
        self.page = page
        self.title("樣品結果")
        self.configure(bg=T.CARD, padx=16, pady=14)
        self.transient(page.app.root)
        self.cands = candidates_from(source_page) if source_page else []
        self.source = (getattr(source_page, "current", None) and
                       f"{source_page.key}｜{source_page.current.name}") if source_page else ""
        r = 0
        tk.Label(self, text="📌 樣品結果", bg=T.CARD, fg=T.TEXT, font=T.font(13, "bold"), anchor="w").grid(
            row=r, column=0, columnspan=3, sticky="w")
        r += 1
        tk.Label(self, text="樣品", bg=T.CARD, fg=T.TEXT, font=T.font(10, "bold")).grid(row=r, column=0, sticky="w",
                                                                                     pady=(8, 2))
        self.samples = [x for x in (page.lib.samples if page.lib else [])]
        self.labels = [x["label"] + (f"（{x['project']}）" if x.get("project") else "") for x in self.samples]
        self.sample_var = tk.StringVar()
        self.sample_cb = ttk.Combobox(self, textvariable=self.sample_var, values=self.labels, state="readonly", width=30)
        self.sample_cb.grid(row=r, column=1, sticky="w", pady=(8, 2))
        self.sample_cb.bind("<<ComboboxSelected>>", lambda e: self._load())
        r += 1
        if self.cands:
            tk.Label(self, text="從分析結果帶入", bg=T.CARD, fg=T.TEXT, font=T.font(10, "bold")).grid(row=r, column=0,
                                                                                               sticky="w")
            self.cand_var = tk.StringVar(value=self.cands[0][0])
            cb = ttk.Combobox(self, textvariable=self.cand_var, values=[c[0] for c in self.cands], state="readonly",
                              width=52)
            cb.grid(row=r, column=1, columnspan=2, sticky="w", pady=2)
            cb.bind("<<ComboboxSelected>>", lambda e: self._apply_cand())
            r += 1
        self.v = {k: tk.StringVar() for k in ("r_ohm", "sc_on", "tc_k", "note")}
        self.sc = tk.BooleanVar(value=False)
        for lab, key, unit in (("低溫電阻", "r_ohm", "Ω"), ("Tc", "tc_k", "K")):
            tk.Label(self, text=lab, bg=T.CARD, fg=T.TEXT, font=T.font(10, "bold")).grid(row=r, column=0, sticky="w")
            f = tk.Frame(self, bg=T.CARD)
            f.grid(row=r, column=1, sticky="w", pady=2)
            ttk.Entry(f, textvariable=self.v[key], width=12).pack(side="left")
            tk.Label(f, text=unit, bg=T.CARD, fg=T.MUTED).pack(side="left", padx=(4, 0))
            r += 1
        f = tk.Frame(self, bg=T.CARD)
        f.grid(row=r, column=1, sticky="w", pady=2)
        ttk.Checkbutton(f, text="超導 contact", variable=self.sc, style=f"{KEY}.TCheckbutton").pack(side="left")
        tk.Label(f, text="　在哪個材料上", bg=T.CARD, fg=T.MUTED, font=T.font(9)).pack(side="left")
        ttk.Entry(f, textvariable=self.v["sc_on"], width=10).pack(side="left", padx=(4, 0))
        r += 1
        tk.Label(self, text="備註", bg=T.CARD, fg=T.TEXT, font=T.font(10, "bold")).grid(row=r, column=0, sticky="w")
        ttk.Entry(self, textvariable=self.v["note"], width=44).grid(row=r, column=1, columnspan=2, sticky="we", pady=2)
        r += 1
        self.err = tk.Label(self, text="", bg=T.CARD, fg=T.ERROR, font=T.font(9))
        self.err.grid(row=r, column=0, columnspan=3, sticky="w")
        r += 1
        bf = tk.Frame(self, bg=T.CARD)
        bf.grid(row=r, column=0, columnspan=3, sticky="e", pady=(10, 0))
        ttk.Button(bf, text="取消", style=f"{KEY}.Ghost.TButton", command=self.destroy).pack(side="right")
        ttk.Button(bf, text="儲存", style=f"{KEY}.Accent.TButton", command=self.ok).pack(side="right", padx=(0, 6))
        guess = s or self._guess()
        if guess is not None and guess in self.samples:
            self.sample_var.set(self.labels[self.samples.index(guess)])
        self._load()
        if self.cands:
            self._apply_cand()

    def _guess(self):
        """量測檔案在哪個樣品資料夾裡 → 預設選那個樣品；不然選目前在樣品頁選的。"""
        for _, _, path in self.cands:
            ap = os.path.normcase(os.path.abspath(path))
            for x in self.samples:
                if x.get("dir") and ap.startswith(os.path.normcase(os.path.abspath(x["dir"])) + os.sep):
                    return x
        return self.page.sample

    def current(self):
        t = self.sample_var.get()
        return self.samples[self.labels.index(t)] if t in self.labels else None

    def _load(self):
        s = self.current()
        if s is None:
            return
        res = (self.page.record(s) or {}).get("results") or {}
        for k in ("r_ohm", "tc_k"):
            self.v[k].set("" if res.get(k) is None else f"{res[k]:g}")
        self.v["sc_on"].set(res.get("sc_on") or "")
        self.v["note"].set(res.get("note") or "")
        self.sc.set(bool(res.get("sc_contact")))

    def _apply_cand(self):
        d = next((c[1] for c in self.cands if c[0] == self.cand_var.get()), {})
        for k, v in d.items():
            self.v[k].set(f"{v:g}")

    def ok(self):
        s = self.current()
        if s is None:
            self.err.configure(text="先選樣品")
            return
        try:
            r = E.num(self.v["r_ohm"].get())
            tc = E.num(self.v["tc_k"].get())
        except ValueError:
            self.err.configure(text="電阻、Tc 要填數字")
            return
        self.page.save_results(s, dict(r_ohm=r, sc_contact=bool(self.sc.get()) or None, sc_on=self.v["sc_on"].get().strip(),
                                       tc_k=tc, note=self.v["note"].get().strip()), self.source)
        self.destroy()


class NewSampleDialog(_Dialog):
    """＋ 新樣品：編號、類型、開始日期、放在哪個專案資料夾（可以順便建立樣品資料夾）。"""

    def __init__(self, page):
        super().__init__(page.app.root)
        self.page = page
        self.title("新樣品")
        self.configure(bg=T.CARD, padx=16, pady=14)
        self.transient(page.app.root)
        root = page.cfg.get("root")
        projs = sorted({x["project"] for x in (page.lib.samples if page.lib else []) if x.get("project")})
        self.places = (["樣品根目錄"] + [f"專案：{p}" for p in projs] if root else []) + ["這台電腦（先不建資料夾）"]
        self.projs = ([""] + projs if root else []) + [None]
        self.v = {"label": tk.StringVar(), "type": tk.StringVar(), "start": tk.StringVar(value=time.strftime("%Y-%m-%d")),
                  "place": tk.StringVar(value=self.places[min(1, len(self.places) - 1)] if len(projs) else self.places[0])}
        tk.Label(self, text="＋ 新樣品", bg=T.CARD, fg=T.TEXT, font=T.font(13, "bold"), anchor="w").grid(
            row=0, column=0, columnspan=2, sticky="w")
        rows = [("編號", "label", "同一個使用者底下不要重複（例如 950、al 012）"),
                ("類型", "type", "例如 Tri-TaS2、Quad-NbSe2（剖面圖會用來猜材料）"),
                ("開始日期", "start", "")]
        r = 1
        for lab, key, hint in rows:
            tk.Label(self, text=lab, bg=T.CARD, fg=T.TEXT, font=T.font(10, "bold")).grid(row=r, column=0, sticky="w",
                                                                                       pady=(6, 0))
            ttk.Entry(self, textvariable=self.v[key], width=32).grid(row=r, column=1, sticky="w", pady=(6, 0))
            if hint:
                tk.Label(self, text=hint, bg=T.CARD, fg=T.FAINT, font=T.font(8)).grid(row=r + 1, column=1, sticky="w")
            r += 2
        tk.Label(self, text="放在", bg=T.CARD, fg=T.TEXT, font=T.font(10, "bold")).grid(row=r, column=0, sticky="w",
                                                                                     pady=(6, 0))
        ttk.Combobox(self, textvariable=self.v["place"], values=self.places, state="readonly", width=40).grid(
            row=r, column=1, sticky="w", pady=(6, 0))
        tk.Label(self, text="選資料夾的話會建立「<專案>\\<編號>」樣品資料夾和紀錄檔", bg=T.CARD, fg=T.FAINT,
                 font=T.font(8)).grid(row=r + 1, column=1, sticky="w")
        self.err = tk.Label(self, text="", bg=T.CARD, fg=T.ERROR, font=T.font(9))
        self.err.grid(row=r + 2, column=0, columnspan=2, sticky="w")
        bf = tk.Frame(self, bg=T.CARD)
        bf.grid(row=r + 3, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(bf, text="取消", style=f"{KEY}.Ghost.TButton", command=self.destroy).pack(side="right")
        ttk.Button(bf, text="建立", style=f"{KEY}.Accent.TButton", command=self.ok).pack(side="right", padx=(0, 6))

    def ok(self):
        lab = self.v["label"].get().strip()
        if not lab:
            self.err.configure(text="要填編號")
            return
        try:
            start = norm_date(self.v["start"].get())
        except ValueError:
            self.err.configure(text="日期請寫成 2026-03-05")
            return
        proj = self.projs[self.places.index(self.v["place"].get())]
        try:
            self.page.create_sample(lab, self.v["type"].get().strip(), start, proj)
        except (ValueError, OSError) as e:
            self.err.configure(text=str(e))
            return
        self.destroy()


class SyncDialog(_Dialog):
    """☁ 試算表：待更新的樣品、全部重新寫入、測試連線。"""

    def __init__(self, page):
        super().__init__(page.app.root)
        self.page = page
        self.title("更新試算表")
        self.configure(bg=T.CARD, padx=16, pady=14)
        self.transient(page.app.root)
        tk.Label(self, text="☁ 樣品試算表", bg=T.CARD, fg=T.TEXT, font=T.font(13, "bold"), anchor="w").pack(fill="x")
        tk.Label(self, bg=T.CARD, fg=T.MUTED, font=T.font(9), anchor="w", justify="left", wraplength=T.px(560),
                 text="試算表當總覽：每個樣品一列，軟體只寫 Status、Type、Start Time、Process 那一段和備註，其他欄位不動。"
                      "修改前會再確認那一列還是同一個樣品。").pack(fill="x", pady=(2, 8))
        self.info = tk.Label(self, text="", bg=T.SUBTLE, fg=T.TEXT, font=T.font(10), anchor="w", justify="left",
                             wraplength=T.px(560), padx=10, pady=8)
        self.info.pack(fill="x")
        bf = tk.Frame(self, bg=T.CARD)
        bf.pack(fill="x", pady=(12, 0))
        ttk.Button(bf, text="關閉", style=f"{KEY}.Ghost.TButton", command=self.destroy).pack(side="right")
        self.b_all = ttk.Button(bf, text="全部樣品重新寫入", style=f"{KEY}.Small.TButton", command=self.push_all)
        self.b_all.pack(side="left")
        ttk.Button(bf, text="測試連線", style=f"{KEY}.Small.TButton", command=self.test).pack(side="left", padx=(6, 0))
        self.b_go = ttk.Button(bf, text="⬆ 更新待更新的樣品", style=f"{KEY}.Accent.TButton", command=self.push_pending)
        self.b_go.pack(side="right", padx=(0, 6))
        self.refresh()

    def refresh(self, extra=""):
        pend = self.page.pending_sync()
        cfg = self.page.cfg
        how = ("Apps Script" if cfg.get("sheet_script_url") else "服務帳號金鑰") if self.page.can_sync() else "（還沒有設定寫入方式）"
        txt = (f"自動更新：{'開' if cfg.get('sheet_sync') else '關'}　寫入方式：{how}\n"
               f"待更新：{len(pend)} 個樣品" + (f"（{'、'.join(x['label'] for x in pend[:12])}" +
                                            ("…" if len(pend) > 12 else "") + "）" if pend else ""))
        self.info.configure(text=txt + ("\n\n" + extra if extra else ""), fg=T.TEXT)
        self.b_go.state(["!disabled"] if pend and self.page.can_sync() else ["disabled"])

    def _run(self, samples, label):
        self.info.configure(text=f"{label}中…")
        self.b_go.state(["disabled"])
        self.page.sync_many(samples, lambda msg: self.winfo_exists() and self.refresh(msg))

    def push_pending(self):
        self._run(self.page.pending_sync(), "更新")

    def push_all(self):
        lib = self.page.lib
        todo = [x for x in (lib.samples if lib else []) if x.get("rec") is not None]
        if not todo:
            self.refresh("還沒有任何紀錄檔")
            return
        if not messagebox.askyesno("更新試算表", f"把 {len(todo)} 個樣品全部重新寫進試算表？\n"
                                             "沒有在軟體裡改過的步驟會照抄原本的文字；改過的會換成軟體產生的寫法。",
                                   parent=self):
            return
        self._run(todo, "寫入")

    def test(self):
        self.info.configure(text="連線中…")

        def work():
            try:
                vals = self.page.sheet_writer().values()
                from ..fab import sheet_sync as SS
                ci = SS.columns(vals[0] if vals else [])
                msg = f"✓ 連得上：{len(vals) - 1} 列；Label 在第 {ci['label'] + 1} 欄、Process 從第 {ci['process'] + 1} 欄開始"
            except Exception as e:
                msg = f"✗ {e}"
            self.page.app.post(("call", lambda: self.winfo_exists() and self.refresh(msg)))
        self.page.app.submit(work)


class ExportDialog(_Dialog):
    """📤 匯出 PPT：選樣品（一顆或多顆比較）、語言、要放哪些段落；目前樣品的模板（標題、每一步放不放、給教授的說明）。"""

    def __init__(self, page):
        from ..fab import report_ppt as RP
        super().__init__(page.app.root)
        self.page, self.RP = page, RP
        self.title("匯出 PPT")
        self.configure(bg=T.CARD, padx=14, pady=12)
        self.transient(page.app.root)
        self.geometry(f"{T.px(980)}x{T.px(660)}")
        self.minsize(T.px(760), T.px(520))
        tk.Label(self, text="📤 一鍵匯出 PPT", bg=T.CARD, fg=T.TEXT, font=T.font(13, "bold"), anchor="w").pack(fill="x")
        tk.Label(self, text="選一顆 = 單一樣品報告；選好幾顆 = 同一份裡比較（Ctrl / Shift 多選）。模板會存在每顆樣品的紀錄檔，下次匯出沿用。",
                 bg=T.CARD, fg=T.MUTED, font=T.font(9), anchor="w").pack(fill="x", pady=(2, 8))
        body = tk.Frame(self, bg=T.CARD)
        body.pack(fill="both", expand=True)
        # ---- 左：樣品、語言、段落
        left = tk.Frame(body, bg=T.CARD)
        left.pack(side="left", fill="y")
        tk.Label(left, text="樣品", bg=T.CARD, fg=T.TEXT, font=T.font(10, "bold"), anchor="w").pack(fill="x")
        self.samples = list(page.lib.samples if page.lib else [])
        self.slist = tk.Listbox(left, selectmode="extended", height=10, width=22, exportselection=False, bd=0,
                                highlightthickness=1, highlightbackground=T.BORDER, font=T.font(10), activestyle="none",
                                selectbackground=T.mix_color(T.accent(KEY)["main"], "#ffffff", 0.7), selectforeground=T.TEXT)
        for x in self.samples:
            self.slist.insert("end", x["label"] + ("" if x.get("rec") is not None else "（初版）"))
        if page.sample in self.samples:
            i = self.samples.index(page.sample)
            self.slist.selection_set(i)
            self.slist.see(i)
        self.slist.pack(fill="x")
        self.slist.bind("<<ListboxSelect>>", lambda e: self._load_tpl())
        tk.Label(left, text="語言", bg=T.CARD, fg=T.TEXT, font=T.font(10, "bold"), anchor="w").pack(fill="x", pady=(10, 0))
        self.lang = tk.StringVar(value=page.st.get("ppt_lang", "zh"))
        for code, name in RP.LANGS:
            ttk.Radiobutton(left, text=name, value=code, variable=self.lang, style=f"{KEY}.TRadiobutton").pack(anchor="w")
        tk.Label(left, text="要放的內容", bg=T.CARD, fg=T.TEXT, font=T.font(10, "bold"), anchor="w").pack(fill="x",
                                                                                                    pady=(10, 0))
        saved = set(page.st.get("ppt_sections") or RP.DEFAULT_ON)
        self.sec = {}
        for k, zh, en in RP.SECTIONS:
            v = tk.BooleanVar(value=k in saved)
            self.sec[k] = v
            ttk.Checkbutton(left, text=zh, variable=v, style=f"{KEY}.TCheckbutton").pack(anchor="w")
        # ---- 右：模板
        right = tk.Frame(body, bg=T.CARD)
        right.pack(side="left", fill="both", expand=True, padx=(16, 0))
        self.tpl_head = tk.Label(right, text="", bg=T.CARD, fg=T.TEXT, font=T.font(11, "bold"), anchor="w")
        self.tpl_head.pack(fill="x")
        g = tk.Frame(right, bg=T.CARD)
        g.pack(fill="x", pady=(4, 6))
        self.t_title = tk.StringVar()
        self.t_sub = tk.StringVar()
        for r, (lab, var, hint) in enumerate((("標題", self.t_title, "空白 = 「樣品 102 製程報告」"),
                                              ("副標題", self.t_sub, "空白 = 類型 · 使用者"))):
            tk.Label(g, text=lab, bg=T.CARD, fg=T.TEXT, font=T.font(10)).grid(row=r, column=0, sticky="w")
            ttk.Entry(g, textvariable=var, width=48).grid(row=r, column=1, sticky="we", pady=1)
            tk.Label(g, text=hint, bg=T.CARD, fg=T.FAINT, font=T.font(8)).grid(row=r, column=2, sticky="w", padx=(6, 0))
        g.columnconfigure(1, weight=1)
        tk.Label(right, text="每一步：點「放」那一欄切換要不要放進 PPT；選一步可以寫給教授看的說明", bg=T.CARD, fg=T.MUTED,
                 font=T.font(9), anchor="w").pack(fill="x")
        tf = tk.Frame(right, bg=T.CARD)
        tf.pack(fill="both", expand=True, pady=(4, 0))
        self.steps = ttk.Treeview(tf, columns=("on", "step", "date", "note"), show="headings", selectmode="browse",
                                  style=f"{KEY}.Treeview", height=9)
        for c, t, w in (("on", "放", 36), ("step", "步驟", 150), ("date", "日期", 96), ("note", "說明", 260)):
            self.steps.heading(c, text=t)
            self.steps.column(c, width=T.px(w), anchor="center" if c == "on" else "w", stretch=c == "note")
        sb = ttk.Scrollbar(tf, orient="vertical", command=self.steps.yview)
        self.steps.configure(yscrollcommand=sb.set)
        self.steps.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.steps.bind("<ButtonRelease-1>", self._click)
        self.steps.bind("<<TreeviewSelect>>", lambda e: self._show_note())
        self.note = tk.Text(right, height=3, font=T.font(10), bd=0, highlightthickness=1, highlightbackground=T.BORDER,
                            wrap="word")
        self.note.pack(fill="x", pady=(6, 0))
        self.note.bind("<KeyRelease>", lambda e: self._note_changed())
        # ---- 下
        self.info = tk.Label(self, text="", bg=T.CARD, fg=T.MUTED, font=T.font(9), anchor="w", justify="left",
                             wraplength=T.px(900))
        self.info.pack(fill="x", pady=(8, 0))
        bf = tk.Frame(self, bg=T.CARD)
        bf.pack(fill="x", pady=(6, 0))
        ttk.Button(bf, text="關閉", style=f"{KEY}.Ghost.TButton", command=self.destroy).pack(side="right")
        self.go = ttk.Button(bf, text="📤 匯出 PPT", style=f"{KEY}.Accent.TButton", command=self.export)
        self.go.pack(side="right", padx=(0, 6))
        ttk.Button(bf, text="儲存模板", style=f"{KEY}.Small.TButton", command=self.save_tpl).pack(side="left")
        self.cur = None
        self.tpl = None
        self._load_tpl()

    def selected(self):
        return [self.samples[i] for i in self.slist.curselection()]

    def _load_tpl(self):
        self._stash()
        sel = self.selected()
        self.cur = sel[0] if sel else None
        self.steps.delete(*self.steps.get_children())
        self.note.delete("1.0", "end")
        if not self.cur:
            self.tpl_head.configure(text="模板（先選樣品）")
            return
        rec = self.page.record(self.cur)
        self.tpl = self.RP.template(rec)
        if "skip_steps" not in (rec.get("ppt") or {}):
            self.tpl["skip_steps"] = self.RP.default_skip(rec)
        self.tpl_head.configure(text=f"模板：{self.cur['label']}" + (f"（另外選了 {len(sel) - 1} 顆，各自用自己的模板）"
                                                                    if len(sel) > 1 else ""))
        self.t_title.set(self.tpl["title"])
        self.t_sub.set(self.tpl["subtitle"])
        for st in rec.get("steps", []):
            self.steps.insert("", "end", iid=st["id"], values=(
                "—" if st["id"] in self.tpl["skip_steps"] else "✓", K.step_name(st),
                (st.get("date") or "").replace("-", "/"), self.tpl["step_notes"].get(st["id"], "")))

    def _stash(self):
        """切換樣品前，把正在編輯的模板記在記憶體（按「儲存模板」或匯出時才寫檔）。"""
        if self.cur is not None and self.tpl is not None:
            self.tpl["title"] = self.t_title.get().strip()
            self.tpl["subtitle"] = self.t_sub.get().strip()
            self.page.ppt_drafts[self.cur["key"]] = dict(self.tpl)

    def _click(self, e):
        if self.steps.identify_column(e.x) != "#1":
            return
        iid = self.steps.identify_row(e.y)
        if iid:
            self.toggle(iid)

    def toggle(self, sid):
        sk = self.tpl["skip_steps"]
        if sid in sk:
            sk.remove(sid)
        else:
            sk.append(sid)
        self.steps.set(sid, "on", "—" if sid in sk else "✓")

    def _show_note(self):
        sel = self.steps.selection()
        self.note.delete("1.0", "end")
        if sel:
            self.note.insert("1.0", self.tpl["step_notes"].get(sel[0], ""))

    def _note_changed(self):
        sel = self.steps.selection()
        if not sel:
            return
        t = self.note.get("1.0", "end").strip()
        if t:
            self.tpl["step_notes"][sel[0]] = t
        else:
            self.tpl["step_notes"].pop(sel[0], None)
        self.steps.set(sel[0], "note", t.replace("\n", " "))

    def save_tpl(self, quiet=False):
        self._stash()
        n = 0
        for key, tpl in list(self.page.ppt_drafts.items()):
            s = next((x for x in self.samples if x["key"] == key), None)
            if s:
                self.page.save_template(s, tpl)
                n += 1
        self.page.ppt_drafts.clear()
        if not quiet:
            self.info.configure(text=f"已儲存 {n} 顆樣品的模板（存在各自的紀錄檔）", fg=T.SUCCESS)
        return n

    def export(self, path=None):
        sel = self.selected()
        if not sel:
            self.info.configure(text="先選樣品", fg=T.ERROR)
            return None
        self.save_tpl(quiet=True)
        sections = [k for k, v in self.sec.items() if v.get()]
        lang = self.lang.get()
        self.page.st["ppt_lang"] = lang
        self.page.st["ppt_sections"] = sections
        if path is None:
            from tkinter import filedialog
            if len(sel) == 1:
                name = f"{sel[0]['label']}_製程報告.pptx"
                where = sel[0]["dir"] or os.path.expanduser("~")
            else:
                name = "樣品比較_" + "_".join(x["label"] for x in sel[:6]) + ".pptx"
                where = os.path.expanduser("~")
            path = filedialog.asksaveasfilename(parent=self, initialdir=where, initialfile=name, defaultextension=".pptx",
                                                filetypes=[("PowerPoint", "*.pptx")])
            if not path:
                return None
        self.go.state(["disabled"])
        self.info.configure(text="匯出中…（照片會縮小後放進去）", fg=T.TEXT)
        self.page.export_ppt(sel, path, lang, sections, done=self._done)
        return path

    def _done(self, path, n, err):
        if not self.winfo_exists():
            return
        self.go.state(["!disabled"])
        if err:
            self.info.configure(text=f"匯出失敗：{err}", fg=T.ERROR)
        else:
            self.info.configure(text=f"✓ 已匯出 {n} 頁：{path}", fg=T.SUCCESS)
