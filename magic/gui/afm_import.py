"""📈 從 AFM line profile 檔自動找台階高度，填進蝕刻精靈的欄位（每條 profile 一個值 → 平均 ± 標準差）。

‧ 支援 Gwyddion「匯出文字」與 NanoScope Analysis 的 section 匯出（.txt / .csv）；一個檔案可以有好幾條 profile
‧ 自動：低、高兩個平台 ＋ 整條的傾斜一起擬合，台階邊緣附近的點不用
‧ 手動：拖曳選「低的平台」與「高的平台」範圍（例如邊緣有殘膠時）
‧ 勾選要用的 profile → 「填入」：每條一個值，寫進欄位（可以選擇取代或加在後面）
"""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, ttk

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib.widgets import SpanSelector

from ..etching.afm import read_profiles, step_height
from . import theme as T
from .widgets import fit_window

# 每個欄位：低、高平台分別是什麼（給使用者看的說明）
WHAT = {
    "sio2_step": ("蝕刻後的 SiO2（蝕刻區）", "光阻保護的 SiO2"),
    "mat_step": ("材料的蝕刻區", "材料被光阻保護的地方"),
    "mat_out": ("蝕刻後的 SiO2 表面", "材料頂端"),
    "mat_before": ("SiO2 基板", "材料頂端（蝕刻前）"),
    "marker_before": ("SiO2 基板", "marker 頂端（蝕刻前）"),
    "marker_out": ("蝕刻後的 SiO2 表面", "marker 頂端"),
    "marker_after_own": ("marker 旁邊被保護的表面", "marker 頂端（蝕刻後）"),
    "resist_thickness": ("基板", "光阻頂端（蝕刻前）"),
    "resist_after": ("基板 / 材料", "光阻頂端（蝕刻後）"),
}


class AfmImportDialog(tk.Toplevel):
    def __init__(self, wizard, key, label=""):
        super().__init__(wizard)
        self.wizard = wizard
        self.app = wizard.app
        self.field = key
        self.k = wizard.key
        self.title(f"從 AFM profile 找台階 — {label or key}")
        self.configure(bg=T.CARD)
        self.transient(wizard)
        fit_window(self, T.px(1080), T.px(700), T.px(820), T.px(520))
        self.profiles = []          # [dict(profile, result, use, manual=(lo, hi))]
        self.cur = None
        a = T.accent(self.k)
        head = tk.Frame(self, bg=a["main"], padx=14, pady=7)
        head.pack(fill="x")
        tk.Label(head, text=f"📈 {label or key}", bg=a["main"], fg="white", font=T.font(12, "bold")).pack(side="left")
        lo, hi = WHAT.get(key, ("低的平台", "高的平台"))
        tk.Label(head, text=f"　低 = {lo}；高 = {hi}", bg=a["main"], fg=T.mix_color("#ffffff", a["main"], 0.2),
                 font=T.font(9)).pack(side="left")

        bottom = tk.Frame(self, bg=T.SUBTLE, highlightthickness=1, highlightbackground=T.BORDER)
        bottom.pack(side="bottom", fill="x")
        self.summary = tk.Label(bottom, text="", bg=T.SUBTLE, fg=T.TEXT, font=T.font(11, "bold"), anchor="w")
        self.summary.pack(side="left", padx=12, pady=8)
        self.append_var = tk.BooleanVar(value=False)
        ttk.Button(bottom, text="取消", style=f"{self.k}.Ghost.TButton", command=self.destroy).pack(side="right", padx=(4, 12),
                                                                                                pady=6)
        self.ok_btn = ttk.Button(bottom, text="填入", style=f"{self.k}.Accent.TButton", command=self.fill)
        self.ok_btn.pack(side="right", padx=4)
        ttk.Checkbutton(bottom, text="加在欄位原本的值後面（不勾 = 取代）", variable=self.append_var,
                        style=f"{self.k}.TCheckbutton").pack(side="right", padx=8)

        body = tk.Frame(self, bg=T.CARD)
        body.pack(fill="both", expand=True, padx=10, pady=8)
        left = tk.Frame(body, bg=T.CARD, width=T.px(340))
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        bar = tk.Frame(left, bg=T.CARD)
        bar.pack(fill="x")
        ttk.Button(bar, text="選檔案…", style=f"{self.k}.Accent.TButton", command=self.choose).pack(side="left")
        ttk.Button(bar, text="清空", style=f"{self.k}.Small.TButton", command=self.clear).pack(side="left", padx=6)
        tk.Label(left, text="勾選 = 用這條（雙擊切換）", bg=T.CARD, fg=T.MUTED, font=T.font(8), anchor="w").pack(fill="x",
                                                                                                    pady=(6, 0))
        tf = tk.Frame(left, bg=T.CARD)
        tf.pack(fill="both", expand=True, pady=(2, 0))
        cols = [("use", "用", 30), ("name", "profile", 150), ("h", "h (nm)", 70), ("s", "±", 50)]
        self.tree = ttk.Treeview(tf, columns=[c for c, _, _ in cols], show="headings", selectmode="browse")
        for c, t, w in cols:
            self.tree.heading(c, text=t)
            self.tree.column(c, width=T.px(w), anchor="w" if c == "name" else "center", stretch=c == "name")
        sb = ttk.Scrollbar(tf, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.show())
        self.tree.bind("<Double-1>", lambda e: self.toggle())
        self.tree.bind("<space>", lambda e: self.toggle())

        right = tk.Frame(body, bg=T.CARD)
        right.pack(side="left", fill="both", expand=True, padx=(10, 0))
        mb = tk.Frame(right, bg=T.SUBTLE, highlightthickness=1, highlightbackground=T.BORDER)
        mb.pack(fill="x")
        self.mode_var = tk.StringVar(value="auto")
        tk.Label(mb, text="找台階", bg=T.SUBTLE, fg=T.MUTED, font=T.font(9, "bold")).pack(side="left", padx=(8, 6))
        ttk.Radiobutton(mb, text="自動", value="auto", variable=self.mode_var, style=f"{self.k}.TRadiobutton",
                        command=self.mode_changed).pack(side="left", padx=4, pady=4)
        ttk.Radiobutton(mb, text="手動：拖曳選範圍", value="manual", variable=self.mode_var,
                        style=f"{self.k}.TRadiobutton", command=self.mode_changed).pack(side="left", padx=4)
        self.which_var = tk.StringVar(value="low")
        self.which = []
        for v, text in (("low", "▭ 低的平台"), ("high", "▭ 高的平台")):
            rb = ttk.Radiobutton(mb, text=text, value=v, variable=self.which_var, style=f"{self.k}.TRadiobutton")
            rb.pack(side="left", padx=4)
            self.which.append(rb)
        self.fig = Figure(figsize=(7, 4.6), layout="constrained")
        self.ax = self.fig.add_subplot()
        self.canvas = FigureCanvasTkAgg(self.fig, master=right)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, pady=(6, 0))
        from .widgets import keep_figure_fit
        self._fit = keep_figure_fit(self.canvas)       # 螢幕縮放時圖不會比視窗大（跑版）
        self.span = SpanSelector(self.ax, self._spanned, "horizontal", useblit=True, interactive=False,
                                 props=dict(alpha=0.2, facecolor="#2563eb"))
        self.info = tk.Label(right, text="", bg=T.CARD, fg=T.MUTED, font=T.font(9), anchor="w", justify="left",
                             wraplength=T.px(640))
        self.info.pack(fill="x", pady=(4, 0))
        self.mode_changed()
        self.update_summary()
        self.after(100, self._ask_first)
        try:
            self.grab_set()                 # 精靈本身是 modal：這個視窗要接手，關掉時再還給精靈
        except tk.TclError:
            pass

    def destroy(self):
        try:
            self.grab_release()
        except tk.TclError:
            pass
        super().destroy()
        try:
            if self.wizard.winfo_exists():
                self.wizard.grab_set()
        except tk.TclError:
            pass

    def _ask_first(self):
        if not self.profiles and not getattr(self, "_no_ask", False):
            self.choose()

    # ================================================================== 檔案
    def choose(self):
        init = self.app.state.get("afm_dir") or os.path.expanduser("~")
        fps = filedialog.askopenfilenames(parent=self, title="選 AFM line profile 檔（可以多選）", initialdir=init,
                                          filetypes=[("文字檔", "*.txt *.csv *.dat *.asc"), ("全部", "*.*")])
        if fps:
            self.app.state["afm_dir"] = os.path.dirname(fps[0])
            self.add_files(fps)

    def add_files(self, paths):
        errors = []
        for fp in paths:
            try:
                for pr in read_profiles(fp):
                    self.profiles.append(dict(profile=pr, result=step_height(pr.x, pr.z), use=True, manual=None))
            except Exception as e:
                errors.append(f"{os.path.basename(fp)}：{e}")
        for d in self.profiles:
            if not d["result"]["ok"]:
                d["use"] = False
        self.refresh()
        kids = self.tree.get_children()
        if kids and not self.tree.selection():
            self.tree.selection_set(kids[0])
        if errors:
            self.info.configure(text="讀不到：" + "；".join(errors), fg=T.ERROR)

    def clear(self):
        self.profiles = []
        self.cur = None
        self.refresh()
        self.ax.cla()
        self.canvas.draw_idle()

    def refresh(self):
        sel = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for i, d in enumerate(self.profiles):
            r = d["result"]
            h = f"{r['h']:.2f}" if r["ok"] else "—"
            s = f"{r['s_h']:.2f}" if r["ok"] and np.isfinite(r["s_h"]) else ""
            name = d["profile"].name + ("（手動）" if d["manual"] else "")
            self.tree.insert("", "end", iid=str(i), values=("✓" if d["use"] else "", name, h, s))
        if sel and self.tree.exists(sel[0]):
            self.tree.selection_set(sel[0])
        self.update_summary()

    def toggle(self):
        sel = self.tree.selection()
        if not sel:
            return
        d = self.profiles[int(sel[0])]
        if not d["result"]["ok"] and not d["use"]:
            self.info.configure(text="這條找不到台階：改用「手動：拖曳選範圍」", fg=T.WARNING)
            return
        d["use"] = not d["use"]
        self.refresh()

    def values(self):
        return [d["result"]["h"] for d in self.profiles if d["use"] and d["result"]["ok"]]

    def update_summary(self):
        v = self.values()
        if not v:
            self.summary.configure(text="還沒有選到台階")
            self.ok_btn.state(["disabled"])
            return
        m = float(np.mean(v))
        sd = float(np.std(v, ddof=1)) if len(v) > 1 else 0.0
        self.summary.configure(text=f"{len(v)} 條：h = {m:.2f} ± {sd:.2f} nm" if len(v) > 1 else f"1 條：h = {m:.2f} nm")
        self.ok_btn.configure(text=f"填入（{len(v)} 個值）")
        self.ok_btn.state(["!disabled"])

    # ================================================================== 手動範圍
    def mode_changed(self):
        manual = self.mode_var.get() == "manual"
        self.span.set_active(manual)
        for rb in self.which:
            rb.state(["!disabled"] if manual else ["disabled"])
        if not manual and self.cur is not None:
            d = self.profiles[self.cur]
            if d["manual"]:
                d["manual"] = None
                pr = d["profile"]
                d["result"] = step_height(pr.x, pr.z)
                self.refresh()
        self.info.configure(fg=T.MUTED, text=(
            "先選「低的平台」拖曳一段範圍，再選「高的平台」拖曳一段範圍（避開台階邊緣與殘膠）" if manual else
            "自動：兩個平台 ＋ 傾斜一起擬合，邊緣附近的點不用。藍色 = 低的平台、橘色 = 高的平台"))
        self.show()

    def _spanned(self, x0, x1):
        if self.cur is None or abs(x1 - x0) <= 0:
            return
        d = self.profiles[self.cur]
        lo, hi = d["manual"] or (None, None)
        if self.which_var.get() == "low":
            lo = (x0, x1)
            self.which_var.set("high")
        else:
            hi = (x0, x1)
            self.which_var.set("low")
        d["manual"] = (lo, hi)
        if lo and hi:
            pr = d["profile"]
            d["result"] = step_height(pr.x, pr.z, low_range=lo, high_range=hi)
            d["use"] = d["result"]["ok"]
            self.refresh()
        self.show()

    # ================================================================== 畫圖
    def show(self):
        sel = self.tree.selection()
        if not sel:
            return
        self.cur = int(sel[0])
        d = self.profiles[self.cur]
        pr, r = d["profile"], d["result"]
        ax = self.ax
        ax.cla()
        xu = pr.x / 1000.0
        ax.plot(xu, pr.z, color="#9ca3af", lw=1, label="profile")
        if r["ok"]:
            for m, c, lab in ((r["low"], "#2563eb", "低的平台"), (r["high"], "#f2a541", "高的平台")):
                ax.plot(xu[m], pr.z[m], ".", color=c, ms=3, label=lab)
            xx = np.array([pr.x.min(), pr.x.max()])
            base = r["a"] + r["slope"] * (xx - r["xm"])
            ax.plot(xx / 1000, base, "--", color="#2563eb", lw=1.2)
            ax.plot(xx / 1000, base + r["h"], "--", color="#f2a541", lw=1.2)
            xe = (r["edges"][0] if r["edges"] else pr.x.mean())
            y0 = r["a"] + r["slope"] * (xe - r["xm"])
            ax.annotate("", (xe / 1000, y0 + r["h"]), (xe / 1000, y0),
                        arrowprops=dict(arrowstyle="<->", color="#dc2626", lw=1.6))
            ax.text(xe / 1000, y0 + r["h"] / 2, f"  h = {r['h']:.2f} ± {r['s_h']:.2f} nm", color="#dc2626",
                    fontsize=11, va="center", fontweight="bold")
            msg = r["reason"] or (f"雜訊約 {r['noise']:.2f} nm；傾斜 {r['slope'] * 1000:.3f} nm/µm（已扣掉）")
            self.info.configure(text=msg, fg=T.WARNING if r["reason"] else T.MUTED)
        else:
            self.info.configure(text=f"找不到台階：{r['reason']}", fg=T.WARNING)
        if d["manual"]:
            for rng, c in zip(d["manual"], ("#2563eb", "#f2a541")):
                if rng:
                    ax.axvspan(min(rng) / 1000, max(rng) / 1000, color=c, alpha=0.12)
        ax.set_xlabel("位置 (µm)")
        ax.set_ylabel("高度 (nm)")
        ax.set_title(pr.name + ("　｜　" + pr.notes[0] if pr.notes else ""), fontsize=9, loc="left")
        ax.legend(fontsize=8, loc="best")
        self.canvas.draw_idle()

    # ================================================================== 填入
    def fill(self):
        v = self.values()
        if not v:
            return
        var = self.wizard.vars[self.field]
        new = ", ".join(f"{x:.2f}" for x in v)
        old = var.get().strip()
        var.set(f"{old}, {new}" if (self.append_var.get() and old) else new)
        self.wizard.app.status(f"已填入 {len(v)} 個台階高度（{self.field}）", "ok")
        self.destroy()
