"""新增蝕刻紀錄（v2）：製程時間軸 ＋ 示意圖動畫 ＋ 依量法顯示的輸入欄位 ＋ 即時結果。

左邊：①～⑦製程步驟（點一下看那一步的剖面與說明）、示意圖、▶ 播放蝕刻、▶▶ 播放全流程
右邊：樣品 → 蝕刻製程 → SiO2 蝕刻深度 → 材料蝕刻深度（只顯示選到的量法需要的欄位）
下面：蝕刻率 ± 誤差、選擇比、檢查（蝕穿、marker…）、代入數字的算式；「寫入紀錄」才存檔
游標放在欄位上，示意圖對應的箭頭會亮；點示意圖上的箭頭，會跳到對應的欄位。
"""
from __future__ import annotations

import json
import os
import tkinter as tk
from dataclasses import fields
from tkinter import messagebox, ttk

from ..etching import store
from ..etching.model import (GASES, INSTRUMENTS, MAT_METHODS, MATERIALS, RESISTS, SIO2_METHODS, EtchInput,
                             EtchInputError, compute, parse_steps, parse_values)
from . import theme as T
from .etch_schematic import STAGES, Schematic
from .params_panel import Tooltip
from .widgets import Paned, ScrollFrame

# 欄位 → 屬於第幾個製程步驟（0 起算）
FIELD_STAGE = {
    "material": 0, "mat_before": 0, "marker_before": 0, "sample_type": 0, "name": 0,
    "resist": 1, "resist_thickness": 1, "line_width": 2,
    "instrument": 4, "icp_power": 4, "rf_power": 4, "dc_bias": 4, "pressure": 4, "steps": 4, "gas": 4,
    "sio2_step": 6, "sio2_before": 6, "sio2_after": 6, "marker_out": 6, "marker_after_own": 6,
    "mat_step": 6, "mat_out": 6, "resist_after": 6,
}
MULTI = {"sio2_step", "sio2_before", "sio2_after", "marker_before", "marker_out", "marker_after_own",
         "mat_before", "mat_step", "mat_out", "resist_thickness", "resist_after"}
AFM_FIELDS = {"sio2_step", "marker_before", "marker_out", "marker_after_own", "mat_before", "mat_step", "mat_out",
              "resist_thickness", "resist_after"}
HINT_MULTI = "可以輸入好幾個點（逗號或空白分開），會自動取平均 ± 標準差"
KEEP_FIELDS = ("material", "resist", "resist_thickness", "line_width", "sample_type", "name", "instrument",
               "icp_power", "rf_power", "dc_bias", "pressure", "pressure_unit", "steps", "sio2_method", "mat_method")


class EtchWizard(tk.Toplevel):
    def __init__(self, panel, prefill=None, edit=None):
        """edit = {"rid": Record ID, "row": 表格裡那一筆, "n": 編號} → 修改模式。"""
        super().__init__(panel)
        self.edit = edit
        self.panel = panel
        self.app = panel.app
        self.key = panel.key
        self.title("修改蝕刻紀錄" if edit else "新增蝕刻紀錄")
        self.configure(bg=T.CARD)
        self.transient(panel.winfo_toplevel())
        try:
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        except Exception:
            sw, sh = 1600, 1000
        self.geometry(f"{min(T.px(1360), sw - 60)}x{min(T.px(900), sh - 80)}")
        self.minsize(min(T.px(980), sw - 60), min(T.px(640), sh - 100))   # 介面縮放時跟著放大
        self.vars = {}
        self.widgets = {}
        self.labels_text = {}
        self.stats = {}
        self.result = None
        self._job = None
        self._anim = None
        self._play_all = False
        self._pause_until = 0.0
        a = T.accent(self.key)
        self.acc = a

        head = tk.Frame(self, bg=a["main"], padx=16, pady=8)
        head.pack(fill="x")
        tk.Label(head, text=f"修改紀錄 #{edit['n']}" if edit else "新增蝕刻紀錄", bg=a["main"], fg="white",
                 font=T.font(13, "bold")).pack(side="left")
        tk.Label(head, text="　改好後按「儲存修改」；修改前的值會留在修改歷史，可以還原" if edit else
                 "　左邊看實驗流程與量測位置，右邊填數字；下面即時算出蝕刻率，按「寫入紀錄」才會存檔",
                 bg=a["main"], fg=T.mix_color("#ffffff", a["main"], 0.25), font=T.font(9)).pack(side="left")

        self._build_bottom()
        body = Paned(self, orient="horizontal", bg=T.CARD)
        body.pack(fill="both", expand=True, padx=10, pady=(8, 0))
        left = tk.Frame(body, bg=T.CARD)
        right = tk.Frame(body, bg=T.CARD)
        body.add_pane(left, stretch=True, minsize=T.px(520))
        body.add_pane(right, stretch=False, size=T.px(500), minsize=T.px(420))
        self._build_left(left)
        self._build_form(right)
        if edit:
            self._load(store.record_to_inputs(edit["row"]))
            for which, slot in self.om_slots.items():
                rel = str(edit["row"].get(f"OM {which}", "") or "")
                found = store.resolve_image(panel.csv_path(), rel)
                slot.set(str(found) if found else (rel or None), notify=False)
            self.ok_btn.configure(text="儲存修改")
            self.keep_box.pack_forget()
        else:
            last = dict(self.app.state.get("etch_last2", {}))
            self._load(last)
        if prefill:
            self._load(prefill)
        self._method_changed()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda e: self.close())
        self.after(50, self.refresh)
        self.select_stage(0)
        try:
            self.grab_set()
        except tk.TclError:
            pass

    # ================================================================== 左：流程與示意圖
    def _build_left(self, parent):
        tl = tk.Frame(parent, bg=T.CARD)
        tl.pack(fill="x")
        self.stage_btns = []
        for i, (num, name, _) in enumerate(STAGES):
            b = tk.Label(tl, text=f"{num} {name}", bg=T.CHIP, fg=T.MUTED, font=T.font(9, "bold"), padx=8, pady=5,
                         cursor="hand2")
            b.grid(row=0, column=2 * i, sticky="ew")
            b.bind("<Button-1>", lambda e, i=i: self.select_stage(i))
            tl.columnconfigure(2 * i, weight=1)
            if i < len(STAGES) - 1:
                tk.Label(tl, text="›", bg=T.CARD, fg=T.FAINT, font=T.font(11)).grid(row=0, column=2 * i + 1)
            self.stage_btns.append(b)
        self.stage_text = tk.Label(parent, text="", bg=T.SUBTLE, fg=T.TEXT, font=T.font(9), justify="left",
                                   anchor="w", padx=10, pady=6, wraplength=T.px(760))
        self.stage_text.pack(fill="x", pady=(6, 4))
        from .widgets import set_if_changed
        parent.bind("<Configure>", lambda e: set_if_changed(self.stage_text, wraplength=max(e.width - 30, 200)))
        self.canvas = Schematic(parent, on_arrow_click=self.focus_field)
        self.canvas.pack(fill="both", expand=True)
        ctl = tk.Frame(parent, bg=T.CARD)
        ctl.pack(fill="x", pady=(4, 0))
        ttk.Button(ctl, text="▶ 播放蝕刻", style=f"{self.key}.Small.TButton", command=self.play_etch).pack(side="left")
        ttk.Button(ctl, text="▶▶ 播放全流程", style=f"{self.key}.Small.TButton", command=self.play_all).pack(
            side="left", padx=4)
        ttk.Button(ctl, text="■ 停止", style=f"{self.key}.Small.TButton", command=self.stop).pack(side="left")
        self.tau_var = tk.DoubleVar(value=0.0)
        self.scale = ttk.Scale(ctl, from_=0, to=30, variable=self.tau_var, command=lambda v: self._scrub())
        self.scale.pack(side="left", fill="x", expand=True, padx=10)
        self.tau_lab = tk.Label(ctl, text="", bg=T.CARD, fg=T.MUTED, font=T.font(9), width=16, anchor="w")
        self.tau_lab.pack(side="left")

    def select_stage(self, i, redraw=True):
        self.stage = i
        for k, b in enumerate(self.stage_btns):
            on = k == i
            b.configure(bg=self.acc["main"] if on else (self.acc["soft"] if k < i else T.CHIP),
                        fg="white" if on else (self.acc["text"] if k < i else T.MUTED))
        num, name, text = STAGES[i]
        self.stage_text.configure(text=f"{num} {name}：{text}")
        tau = self.tau_var.get() if i == 4 else None
        self.canvas.tip_x = None if i != 6 else self.canvas.tip_x
        self.canvas.set_stage(i, tau, redraw=redraw)

    def _scrub(self):
        if self.stage != 4:
            self.select_stage(4)
        self.canvas.tau = float(self.tau_var.get())
        self.tau_lab.configure(text=f"t = {self.canvas.tau:.1f} s")
        self.canvas.redraw()

    def stop(self):
        if self._anim:
            try:
                self.after_cancel(self._anim)
            except Exception:
                pass
        self._anim = None
        self._play_all = False

    def play_etch(self):
        self.stop()
        self.select_stage(4, redraw=False)            # 下面的第一格會畫，不用先畫一次（第一格不會多花一倍時間）
        self.tau_var.set(0.0)
        self.canvas.tau = 0.0
        self.canvas.particles = []
        self._seg_ends = self._segment_ends()
        self._t_total = self._seg_ends[-1] if self._seg_ends else 30.0
        self._tick()

    def play_all(self):
        self.stop()
        self._play_all = True
        self._all_stage = 0
        self._advance_all()

    def _advance_all(self):
        if not self._play_all or not self.winfo_exists():
            return
        i = self._all_stage
        if i == 4:
            self._play_all_after_etch = True
            self.play_etch()
            self._play_all = True
            return
        if i > 6:
            self._play_all = False
            return
        self.select_stage(i)
        if i == 6:
            self._tip_sweep(0)
            return
        self._all_stage += 1
        self._anim = self.after(1300, self._advance_all)

    def _tip_sweep(self, k):
        """⑦ 量測：AFM 探針沿著表面掃過去。"""
        if not self.winfo_exists() or self.stage != 6:
            return
        w = self.canvas.winfo_width()
        n = 90
        if k > n:
            self.canvas.tip_x = None
            self.canvas.redraw()
            self._play_all = False
            return
        self.canvas.tip_x = w * (0.04 + 0.92 * k / n)
        self.canvas.redraw()
        self._anim = self.after(30, lambda: self._tip_sweep(k + 1))

    def _segment_ends(self):
        try:
            steps = parse_steps(self.vars["steps"].get())
        except EtchInputError:
            steps = [30.0]
        out, acc = [], 0.0
        for s in steps:
            acc += s
            out.append(acc)
        return out

    def _tick(self):
        import time
        if not self.winfo_exists():
            return
        now = time.perf_counter()
        if now < self._pause_until:                    # 分段之間暫停
            self._anim = self.after(33, self._tick)
            return
        dt = self._t_total / 150.0                     # 整段約 5 秒播完
        tau = min(self.canvas.tau + dt, self._t_total)
        for end in self._seg_ends[:-1]:
            if self.canvas.tau < end <= tau:
                tau = end
                self._pause_until = now + 0.7
                self.tau_lab.configure(text=f"第 {self._seg_ends.index(end) + 1} 段結束，暫停")
                break
        else:
            self.tau_lab.configure(text=f"t = {tau:.1f} / {self._t_total:g} s")
        self.canvas.tau = tau
        self.tau_var.set(tau)
        self.canvas.step_particles()
        self.canvas.redraw()
        if tau >= self._t_total - 1e-9:
            self._anim = None
            if self._play_all:
                self._all_stage = 5
                self._anim = self.after(900, self._advance_all)
            return
        self._anim = self.after(33, self._tick)

    # ================================================================== 右：表單
    def _section(self, body, title, icon, hint=""):
        f = tk.Frame(body, bg=T.CARD)
        f.pack(fill="x", pady=(12, 2))
        tk.Label(f, text=f"{icon} {title}", bg=T.CARD, fg=self.acc["text"], font=T.font(11, "bold"), anchor="w").pack(
            fill="x")
        if hint:
            tk.Label(f, text=hint, bg=T.CARD, fg=T.MUTED, font=T.font(8), anchor="w", justify="left",
                     wraplength=T.px(440)).pack(fill="x")
        grid = tk.Frame(body, bg=T.CARD)
        grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)
        return grid

    def _field(self, grid, r, key, label, kind="entry", values=None, tip="", width=14):
        lab = tk.Label(grid, text=label, bg=T.CARD, fg=T.TEXT, font=T.font(9), anchor="w")
        lab.grid(row=r, column=0, sticky="w", padx=(0, 8), pady=2)
        var = self.vars.get(key) or tk.StringVar(value="")
        self.vars[key] = var
        if kind == "combo":
            w = ttk.Combobox(grid, textvariable=var, values=values or [], width=width)
        elif kind == "readonly":
            w = ttk.Combobox(grid, textvariable=var, values=values or [], width=width, state="readonly")
        else:
            w = ttk.Entry(grid, textvariable=var, width=width)
        w.grid(row=r, column=1, sticky="ew", pady=2)
        holder = tk.Frame(grid, bg=T.CARD)
        holder.grid(row=r, column=2, sticky="w", padx=(4, 0))
        if key in AFM_FIELDS:
            b = ttk.Button(holder, text="📈", width=3, style=f"{self.key}.Small.TButton",
                           command=lambda k=key: self.import_afm(k))
            b.pack(side="left", padx=(0, 2))
            Tooltip(b, "從 AFM line profile 檔（Gwyddion / NanoScope 匯出的文字檔）自動找台階高度；可以一次選好幾條")
        st = tk.Label(holder, text="", bg=T.CARD, fg=T.MUTED, font=T.font(8), anchor="w", width=13)
        st.pack(side="left")
        self.stats[key] = st
        extra = ()
        tips = [t for t in (tip, HINT_MULTI if key in MULTI else "") if t]
        if tips:
            Tooltip(lab, "\n".join(tips))
            Tooltip(w, "\n".join(tips))
        var.trace_add("write", lambda *a: self.schedule())
        w.bind("<FocusIn>", lambda e, k=key: self._focus(k), add="+")
        self.widgets[key] = (lab, w, holder) + extra
        self.labels_text[key] = label
        return w

    def _build_form(self, parent):
        sf = ScrollFrame(parent)
        sf.pack(fill="both", expand=True)
        self.form_scroll = sf
        body = sf.body
        g = self._section(body, "樣品", "①", "材料、光阻與 pattern")
        self._field(g, 0, "material", "要蝕刻的材料", "combo", MATERIALS, "可以直接打其他材料名稱")
        self._field(g, 1, "resist", "光阻", "combo", RESISTS)
        self._field(g, 2, "resist_thickness", "光阻厚度 (nm，選填)", tip="蝕刻前的光阻厚度；蝕刻後也量的話（⑦ 光阻）可以算光阻蝕刻率")
        self._field(g, 3, "line_width", "pattern 線寬 (nm)", tip="被蝕刻的開口寬度。可以寫 500 或 0.5 um。"
                                                              "比較不同線寬的蝕刻率時一定要填")
        self._field(g, 4, "sample_type", "樣品類型（選填）", "combo", ["pattern", "direct", "test"])
        self._field(g, 5, "name", "操作者")

        g = self._section(body, "蝕刻製程", "⑤", "ICP、RF 功率沒有的可以不填；氣體最多三種")
        self._field(g, 0, "instrument", "機台", "combo", INSTRUMENTS)
        self.gas_vars = []
        gf = tk.Frame(g, bg=T.CARD)
        tk.Label(g, text="氣體 / 流量 (sccm)", bg=T.CARD, fg=T.TEXT, font=T.font(9)).grid(row=1, column=0, sticky="nw",
                                                                                     pady=2)
        gf.grid(row=1, column=1, columnspan=2, sticky="w")
        for i in range(3):
            gv, fv = tk.StringVar(), tk.StringVar()
            cb = ttk.Combobox(gf, textvariable=gv, values=[""] + GASES, width=6)
            cb.grid(row=i // 2, column=2 * (i % 2), padx=(0, 2), pady=(0, 2))       # 兩個一排，窄視窗也放得下
            e = ttk.Entry(gf, textvariable=fv, width=5)
            e.grid(row=i // 2, column=2 * (i % 2) + 1, padx=(0, 8), pady=(0, 2))
            for v in (gv, fv):
                v.trace_add("write", lambda *a: self.schedule())
            for w in (cb, e):
                w.bind("<FocusIn>", lambda ev: self._focus("gas"), add="+")
            self.gas_vars.append((gv, fv))
        self._field(g, 2, "icp_power", "ICP 功率 (W)", tip="ICP-RIE 的 coil / source 功率；RIE 沒有就空白")
        self._field(g, 3, "rf_power", "RF 功率 (W)", tip="platen / bias 功率")
        self._field(g, 4, "dc_bias", "DC bias (V，選填)")
        self._field(g, 5, "pressure", "壓力")
        self.vars["pressure_unit"] = tk.StringVar(value="Pa")
        ttk.Combobox(g, textvariable=self.vars["pressure_unit"], values=["Pa", "mTorr", "Torr", "mbar"], width=7,
                     state="readonly").grid(row=5, column=2, sticky="w", padx=(6, 0))
        self.vars["pressure_unit"].trace_add("write", lambda *a: self.schedule())
        self.widgets["pressure"][2].grid_remove()
        self._field(g, 6, "steps", "蝕刻時間 (s)", tip="一次蝕刻：30；分段：20+20+20 或 3x20；也可以寫 1.5min")

        g = self._section(body, "SiO2 蝕刻深度", "⑦", "選一種量法（大部分用 AFM 台階）")
        self.vars["sio2_method"] = tk.StringVar(value="marker")
        rf = tk.Frame(g, bg=T.CARD)
        rf.grid(row=0, column=0, columnspan=3, sticky="w")
        for i, (k, text) in enumerate(SIO2_METHODS.items()):
            ttk.Radiobutton(rf, text=text, value=k, variable=self.vars["sio2_method"], style=f"{self.key}.TRadiobutton",
                            command=self._method_changed).grid(row=i, column=0, sticky="w")
        self.vars["cross_check"] = tk.BooleanVar(value=False)
        cc = ttk.Checkbutton(rf, text="⇄ 交叉檢查：也用其他量法量了（例如 marker 和 AFM 台階都有）",
                             variable=self.vars["cross_check"], style=f"{self.key}.TCheckbutton",
                             command=self._method_changed)
        cc.grid(row=len(SIO2_METHODS), column=0, sticky="w", pady=(2, 0))
        Tooltip(cc, "勾選後會顯示其他量法的欄位：每一種都算一次 d_SiO2（材料也是），和上面選的主要量法比較，"
                    "差超過 max(1 nm, 2σ) 會提醒")
        self._field(g, 1, "sio2_step", "SiO2 台階 (nm)", tip="光阻保護的 SiO2 與蝕刻區之間的 AFM 台階")
        self._field(g, 2, "sio2_before", "SiO2 蝕刻前 h (nm)", tip="膜厚儀 / 橢偏儀量的絕對厚度")
        self._field(g, 3, "sio2_after", "SiO2 蝕刻後 h' (nm)")
        self._field(g, 4, "marker_before", "marker 蝕刻前 T_m (nm)", tip="塗光阻前，從 SiO2 量到 marker 頂端")
        self._field(g, 5, "marker_out", "H_m,out (nm)", tip="蝕刻、去光阻後，從蝕刻後的 SiO2 表面量到 marker 頂端（紅色箭頭）")
        self._field(g, 6, "marker_after_own", "marker 蝕刻後 T'_m（選填）",
                    tip="Cr/Au 通常不會被蝕刻，空白 = 等於 T_m。有量 marker 自己的台階才填")
        self.sio2_rows = {"afm_step": ["sio2_step"], "ellipsometer": ["sio2_before", "sio2_after"],
                          "marker": ["marker_before", "marker_out", "marker_after_own"], "none": []}

        g = self._section(body, "材料蝕刻深度", "⑦", "選一種量法；「從基板量」需要上面的 SiO2 蝕刻深度")
        self.vars["mat_method"] = tk.StringVar(value="outside")
        rf = tk.Frame(g, bg=T.CARD)
        rf.grid(row=0, column=0, columnspan=3, sticky="w")
        for i, (k, text) in enumerate(MAT_METHODS.items()):
            ttk.Radiobutton(rf, text=text, value=k, variable=self.vars["mat_method"], style=f"{self.key}.TRadiobutton",
                            command=self._method_changed).grid(row=i, column=0, sticky="w")
        self._field(g, 1, "mat_before", "材料蝕刻前 T (nm)", tip="塗光阻前量的材料厚度（從 SiO2 量到材料頂端）。"
                                                              "「圖案內台階」也建議填，才能判斷有沒有蝕穿")
        self._field(g, 2, "mat_step", "圖案內台階 S (nm)", tip="去光阻後，材料上「被保護區 − 蝕刻區」的台階 = T − T'")
        self._field(g, 3, "mat_out", "H_out (nm)", tip="從蝕刻後的 SiO2 表面量到材料頂端（紅色箭頭）")
        self.mat_rows = {"inside": ["mat_step"], "outside": ["mat_out"]}

        g = self._section(body, "光阻蝕刻率（選填）", "⑦", "蝕刻後也量了光阻厚度才填（蝕刻前厚度填在 ① 的「光阻厚度」）："
                                                        "算光阻蝕刻率、材料 / 光阻選擇比，判斷光阻夠不夠厚")
        self._field(g, 0, "resist_after", "光阻蝕刻後厚度 (nm)", tip="蝕刻後、去光阻前，用 AFM 或膜厚儀量的光阻厚度")

        g = self._section(body, "OM 照片（選填）", "📷", "光學顯微鏡照片，蝕刻前、後各一張；沒有可以空白。"
                                                        "照片會複製到紀錄旁邊的 _images 資料夾，原始檔不會被修改")
        from .om_images import OMSlot
        of = tk.Frame(g, bg=T.CARD)
        of.grid(row=0, column=0, columnspan=4, sticky="w")
        self.om_slots = {}
        for k, (which, title) in enumerate((("before", "蝕刻前"), ("after", "蝕刻後"))):
            slot = OMSlot(of, f"OM {title}", self.key, on_change=self.schedule, size=(200, 140))
            slot.grid(row=0, column=k, padx=(0, 8), sticky="n")
            self.om_slots[which] = slot

        g = self._section(body, "備註", "✎")
        self._field(g, 0, "notes", "備註（選填）", width=30)

    def _method_changed(self):
        sm, mm = self.vars["sio2_method"].get(), self.vars["mat_method"].get()
        cross = bool(self.vars["cross_check"].get())
        for rows, cur in ((self.sio2_rows, sm), (self.mat_rows, mm)):
            for m, keys in rows.items():
                for k in keys:
                    show = m == cur or (cross and m != "none")
                    for w in self.widgets[k]:
                        (w.grid() if show else w.grid_remove())
                    other = show and m != cur
                    self.widgets[k][0].configure(text=("⇄ " if other else "") + self.labels_text[k],
                                                 fg=T.MUTED if other else T.TEXT)
        lab = self.widgets["mat_before"][0]
        lab.configure(text="材料蝕刻前 T (nm)" + ("" if mm == "outside" else "（建議填）"))
        self.schedule()

    def _focus(self, key):
        stage = FIELD_STAGE.get(key)
        if stage is not None and stage != self.stage and not self._anim:
            self.select_stage(stage)
        self.canvas.set_highlight(key)

    def focus_field(self, key):
        """點示意圖上的箭頭 → 選好量法、跳到欄位。"""
        if key in ("sio2_step",):
            self.vars["sio2_method"].set("afm_step")
        elif key in ("sio2_before", "sio2_after"):
            self.vars["sio2_method"].set("ellipsometer")
        elif key in ("marker_out", "marker_after_own"):
            self.vars["sio2_method"].set("marker")
        elif key == "mat_step":
            self.vars["mat_method"].set("inside")
        elif key == "mat_out":
            self.vars["mat_method"].set("outside")
        self._method_changed()
        if key in self.widgets:
            w = self.widgets[key][1]
            w.focus_set()
            try:
                self.update_idletasks()
                y = w.winfo_rooty() - self.form_scroll.body.winfo_rooty()
                h = max(self.form_scroll.body.winfo_height(), 1)
                self.form_scroll.canvas.yview_moveto(max(0, (y - 80) / h))
            except tk.TclError:
                pass
        self.canvas.set_highlight(key)

    # ================================================================== 下：結果
    def _build_bottom(self):
        bf = tk.Frame(self, bg=T.CARD, padx=12, pady=8, highlightthickness=1, highlightbackground=T.BORDER)
        bf.pack(side="bottom", fill="x")
        left = tk.Frame(bf, bg=T.CARD)
        left.pack(side="left", fill="y")
        self.big = tk.Label(left, text="—", bg=T.CARD, fg=self.acc["text"] if hasattr(self, "acc") else T.TEXT,
                            font=T.font(16, "bold"), anchor="w")
        self.big.pack(anchor="w")
        self.small = tk.Label(left, text="", bg=T.CARD, fg=T.TEXT, font=T.font(10), anchor="w", justify="left")
        self.small.pack(anchor="w")
        self.checks = tk.Label(left, text="", bg=T.CARD, fg=T.MUTED, font=T.font(9), anchor="w", justify="left")
        self.checks.pack(anchor="w", pady=(4, 0))
        mid = tk.Frame(bf, bg=T.CARD)
        mid.pack(side="left", fill="both", expand=True, padx=(16, 8))
        tk.Label(mid, text="算式（代入你的數字）", bg=T.CARD, fg=T.FAINT, font=T.font(8, "bold"), anchor="w").pack(fill="x")
        self.explain = tk.Text(mid, height=5, font=(T.MONO_FAMILY, 9), bg=T.TEXT_BG, fg=T.TEXT, bd=0, wrap="word",
                               highlightthickness=1, highlightbackground=T.BORDER, padx=6, pady=4)
        self.explain.pack(fill="both", expand=True)
        self.explain.tag_configure("warn", foreground=T.WARNING)
        right = tk.Frame(bf, bg=T.CARD)
        right.pack(side="right", fill="y")
        self.ok_btn = ttk.Button(right, text="寫入紀錄", style=f"{self.key}.Accent.TButton", command=self.save)
        self.ok_btn.pack(fill="x")
        ttk.Button(right, text="取消", style=f"{self.key}.Ghost.TButton", command=self.close).pack(fill="x", pady=4)
        self.keep_var = tk.BooleanVar(value=False)
        self.keep_box = ttk.Checkbutton(right, text="寫入後繼續新增", variable=self.keep_var,
                                        style=f"{self.key}.TCheckbutton")
        self.keep_box.pack(anchor="w")

    def schedule(self):
        if self._job:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
        self._job = self.after(150, self.refresh)

    def inputs(self) -> EtchInput:
        v = {k: (var.get() if isinstance(var, tk.BooleanVar) else var.get().strip()) for k, var in self.vars.items()}
        kw = {f.name: v[f.name] for f in fields(EtchInput) if f.name in v}
        kw["gases"] = [(g.get().strip(), f.get().strip()) for g, f in self.gas_vars if g.get().strip()]
        return EtchInput(**kw)

    def _update_stats(self):
        for key in MULTI:
            st = self.stats.get(key)
            if st is None:
                continue
            try:
                m = parse_values(self.vars[key].get(), key)
                st.configure(text="" if m is None else ("單點" if m.n == 1 else f"{m.mean:.2f} ± {m.std:.2f}（{m.n}）"),
                             fg=T.MUTED)
            except EtchInputError:
                st.configure(text="看不懂", fg=T.ERROR)
        st = self.stats.get("steps")
        try:
            steps = parse_steps(self.vars["steps"].get())
            st.configure(text=f"{len(steps)} 段，共 {sum(steps):g} s" if len(steps) > 1 else f"共 {sum(steps):g} s",
                         fg=T.MUTED)
        except EtchInputError:
            st.configure(text="看不懂", fg=T.ERROR)

    def refresh(self):
        self._job = None
        if not self.winfo_exists():
            return
        self._update_stats()
        inp = self.inputs()
        vals = {"material": inp.material, "resist": inp.resist}
        try:
            res = compute(inp)
            self.result = res
            vals.update(t=res.t_total, steps=res.t_steps, d_mat=res.d_mat, d_sio2=res.d_sio2 or 0.0,
                        line_width=res.line_width_nm, marker_etched=max(res.marker_etched or 0.0, 0.0))
            T_ = res.measures.get("mat_before")
            vals["T"] = T_.mean if T_ else max(res.d_mat * 1.6, 10.0)
            tm = res.measures.get("marker_before")
            vals["T_m"] = tm.mean if tm else 50.0
            rb = res.measures.get("resist_thickness")
            if res.d_resist is not None and rb is not None and rb.mean > 0:
                vals["resist_frac"] = max(0.0, min(res.d_resist / rb.mean, 1.0))   # 動畫裡光阻跟著變薄
            mat = inp.material or "材料"
            bound = "≥ " if res.lower_bound else ""
            self.big.configure(text=f"r_{mat} = {bound}{res.r_mat:.4g} ± {res.sr_mat:.2g} nm/s",
                               fg=T.WARNING if res.lower_bound else self.acc["text"])
            sio2 = "SiO2：沒有量" if res.r_sio2 is None else f"r_SiO2 = {res.r_sio2:.4g} ± {res.sr_sio2:.2g} nm/s"
            sel = "" if res.selectivity is None else f"　選擇比 {res.selectivity:.3g}"
            resist = ""
            if res.r_resist is not None:
                resist = (f"\nr_光阻 = {'≥ ' if res.resist_through else ''}{res.r_resist:.4g} nm/s"
                          + (f"　材料 / 光阻 = {res.sel_resist:.3g}" if res.sel_resist else "")
                          + (f"　光阻約撐 {res.resist_life:.0f} s" if res.resist_life else ""))
            self.small.configure(text=f"{sio2}{sel}　｜　t = {res.t_total:g} s{resist}")
            order = sorted(res.checks, key=lambda c: c[0])                # 有問題的排前面
            self.checks.configure(text="\n".join(("✓ " if ok else "⚠ ") + txt for ok, txt in order[:5]),
                                  fg=T.WARNING if res.warnings else T.MUTED)
            self.explain.delete("1.0", "end")
            self.explain.insert("end", "\n".join(res.explain))
            for w in res.warnings:
                self.explain.insert("end", "\n⚠ " + w, "warn")
            self.ok_btn.state(["!disabled"])
        except EtchInputError as e:
            self.result = None
            try:
                vals["steps"] = parse_steps(inp.steps)
                vals["t"] = sum(vals["steps"])
            except EtchInputError:
                vals["t"] = 30.0
            vals["_demo"] = True
            self.big.configure(text="還不能算", fg=T.MUTED)
            self.small.configure(text=str(e))
            self.checks.configure(text="")
            self.explain.delete("1.0", "end")
            self.explain.insert("end", "依照右邊選的量法填好欄位，這裡會顯示代入數字的算式。")
            self.ok_btn.state(["disabled"])
        if "T" not in vals:
            try:
                m = parse_values(self.vars["mat_before"].get())
                vals["T"] = m.mean if m else 60.0
            except EtchInputError:
                vals["T"] = 60.0
        self.canvas.set_values(vals)
        t_total = vals.get("t", 30.0)
        self.scale.configure(to=max(t_total, 1e-6))

    # ================================================================== 存檔
    def _load(self, d):
        for k, v in (d or {}).items():
            if k == "gases":
                for i, (gv, fv) in enumerate(self.gas_vars):
                    g, f = (v[i] if i < len(v) else ("", ""))
                    gv.set(g)
                    fv.set(f)
            elif k in self.vars and v is not None:
                if isinstance(self.vars[k], tk.BooleanVar):
                    self.vars[k].set(bool(v))
                else:
                    self.vars[k].set(str(v))
        if not any(g.get() for g, _ in self.gas_vars):
            self.gas_vars[0][0].set("SF6")
        for k, default in (("material", "hBN"), ("resist", "PMMA"), ("instrument", "ICP-RIE"), ("steps", "30")):
            if not self.vars[k].get():
                self.vars[k].set(default)

    def save(self):
        from .. import __version__
        try:
            inp = self.inputs()
            res = compute(inp)
        except EtchInputError as e:
            messagebox.showwarning("新增蝕刻紀錄", str(e), parent=self)
            return
        if res.lower_bound and not messagebox.askyesno(
                "已蝕穿", "材料已經蝕穿，這筆只能得到蝕刻率的下限。\n還是要寫入嗎？（紀錄會標記為「蝕穿」）", parent=self):
            return
        rec = store.make_record(inp, res, version=__version__)
        path = self.panel.csv_path()
        if self.edit:
            self._save_edit(rec, path)
            return
        try:
            existing = store.read_log(path)
        except Exception:
            existing = None
        dup = store.find_duplicates(existing, rec)
        if dup and not messagebox.askyesno(
                "可能重複", f"第 {', '.join(map(str, dup))} 筆的輸入和這筆完全一樣。\n還是要寫入嗎？", parent=self):
            return
        notes = []
        rec["Record ID"] = store.new_id()
        rec["Revision"] = 1
        notes += self._attach_om(rec, path)
        try:
            rec = store.append_record(rec, path)
        except store.NeedsUpgrade:
            if store.file_schema(path) != "v1":
                messagebox.showerror("新增蝕刻紀錄", f"紀錄檔的欄位看不懂，沒有寫入：\n{path}", parent=self)
                return
            if not messagebox.askyesno(
                    "升級紀錄檔", "這份紀錄是舊格式（20 個欄位）。\n\n要先備份，再把新欄位（材料、線寬、ICP / RF、"
                                 "氣體流量、誤差…）加在最後面嗎？舊欄位與舊紀錄都不會改變。", parent=self):
                return
            backup = store.upgrade_file(path)
            notes.append(f"舊紀錄已備份：{os.path.basename(str(backup))}")
            rec = store.append_record(rec, path)
        except OSError as e:
            messagebox.showerror("新增蝕刻紀錄", f"寫入 CSV 失敗（檔案是不是被 Excel 開著？）：\n{e}", parent=self)
            return
        notes.insert(0, f"已寫入 {os.path.basename(str(path))}")
        et = self.app.settings.get("etching", {})
        if et.get("xlsx_mirror"):
            try:
                store.append_xlsx(rec, os.path.splitext(str(path))[0] + ".xlsx")
                notes.append("Excel 也已更新")
            except Exception as e:
                notes.append(f"Excel 更新失敗：{e}")
        if et.get("gsheet_enabled"):
            settings = self.app.settings

            def work():
                try:
                    from ..etching import gsync
                    gsync.append(rec, settings)
                    self.app.post(("status", ("Google Sheet 也已寫入", "ok")))
                except Exception as e:
                    self.app.post(("status", (f"Google Sheet 寫入失敗（本機 CSV 已存好；之後可以按 ☁ 同步 補上）：{e}",
                                              "error")))
            self.app.submit(work)
            notes.append("Google Sheet 寫入中…")
        keep = {k: self.vars[k].get() for k in KEEP_FIELDS if k in self.vars}
        keep["gases"] = [(g.get(), f.get()) for g, f in self.gas_vars]
        self.app.state["etch_last2"] = keep
        self.app.save_state_soon()
        self.app.status("；".join(notes), "ok")
        self.panel.source_var.set("本機 CSV")
        self.panel.reload(select_last=True)
        if self.keep_var.get():
            for k in (MULTI - {"resist_thickness"}) | {"notes"}:
                self.vars[k].set("")
            for slot in self.om_slots.values():
                slot.set(None, notify=False)
        else:
            self.close()

    def _attach_om(self, rec, path, rid=None):
        """把選的 OM 照片複製到紀錄旁邊的 _images 資料夾，路徑寫進 rec。回傳要顯示的訊息。"""
        rid = rid or rec["Record ID"]
        msgs = []
        for which, slot in self.om_slots.items():
            src = slot.value
            if not src:
                rec[f"OM {which}"] = ""
                continue
            if not os.path.isfile(src):                  # 修改時原本的照片不見了：保留原本的路徑
                rec[f"OM {which}"] = (self.edit or {}).get("row", {}).get(f"OM {which}", "") if self.edit else ""
                msgs.append(f"找不到 OM 照片：{os.path.basename(src)}")
                continue
            try:
                rec[f"OM {which}"] = store.attach_image(path, rid, which, src)
            except OSError as e:
                rec[f"OM {which}"] = ""
                msgs.append(f"OM 照片複製失敗：{e}")
        if any(rec.get(f"OM {w}") for w in self.om_slots):
            msgs.append("OM 照片已存到 " + store.images_dir(path).name)
        return msgs

    def import_afm(self, key):
        """📈：從 AFM line profile 檔找台階高度，填進這個欄位。"""
        from .afm_import import AfmImportDialog
        win = AfmImportDialog(self, key, self.labels_text.get(key, key))
        self._afm = win
        return win

    def _save_edit(self, rec, path):
        """修改模式：取代那一筆（舊值寫進修改歷史），同步 Excel / Google Sheet。"""
        rid, n = self.edit["rid"], self.edit["n"]
        extra = self._attach_om(rec, path, rid)
        try:
            old, new = store.replace_record(path, rid, rec)
        except store.RecordNotFound as e:
            messagebox.showerror("修改紀錄", str(e), parent=self)
            return
        except OSError as e:
            messagebox.showerror("修改紀錄", f"寫入 CSV 失敗（檔案是不是被 Excel 開著？）：\n{e}", parent=self)
            return
        notes = [f"第 {n} 筆已修改（修改前的值在「修改歷史」，可以還原）"] + extra
        et = self.app.settings.get("etching", {})
        if et.get("xlsx_mirror"):
            try:
                store.export_xlsx(store.read_log(path), os.path.splitext(str(path))[0] + ".xlsx")
                notes.append("Excel 也已更新")
            except Exception as e:
                notes.append(f"Excel 更新失敗：{e}")
        if et.get("gsheet_enabled"):
            settings = self.app.settings

            def work():
                try:
                    from ..etching import gsync
                    gsync.update(rid, new, old, settings)
                    self.app.post(("status", ("Google Sheet 也已修改", "ok")))
                except Exception as e:
                    self.app.post(("status", (f"Google Sheet 修改失敗（本機 CSV 已改好）：{e}", "error")))
            self.app.submit(work)
            notes.append("Google Sheet 修改中…")
        self.app.status("；".join(notes), "ok")
        self.panel.reload(select_id=rid)
        self.close()

    def close(self):
        self.stop()
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()


def prefill_from_record(row):
    """從表格裡的一筆紀錄取出「條件」（不含量測值），給「以這筆為範本」用。"""
    raw = row.get("Raw inputs", "")
    try:
        d = json.loads(raw)
    except (TypeError, ValueError):
        d = {}
    if not d:                                   # 舊紀錄：從舊欄位推
        d = {"material": row.get("Material") or "hBN", "instrument": row.get("Method", ""),
             "name": row.get("Name", ""), "sample_type": row.get("Type", ""),
             "steps": f"{row.get('T (sec)'):g}" if isinstance(row.get("T (sec)"), float) and row.get("T (sec)") == row.get("T (sec)") else "",
             "gases": [(g, "") for g in str(row.get("Gas", "")).split("+") if g]}
    out = {k: v for k, v in d.items() if k in KEEP_FIELDS or k == "gases"}
    if "gases" in out:
        out["gases"] = [tuple(x) for x in out["gases"]]
    return out
