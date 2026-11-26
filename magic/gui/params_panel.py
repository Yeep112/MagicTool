"""參數面板：依分析的 P 清單自動產生輸入欄位（數字、勾選、下拉、欄位選擇、範圍）。"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import theme as T


class Tooltip:
    """滑鼠停在元件上 0.5 秒顯示說明。"""

    def __init__(self, widget, text):
        self.widget, self.text, self.tip, self.job = widget, text, None, None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _=None):
        self._cancel()
        self.job = self.widget.after(500, self._show)

    def _cancel(self):
        if self.job:
            try:
                self.widget.after_cancel(self.job)
            except Exception:
                pass
            self.job = None

    def _show(self):
        if self.tip or not self.text:
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tk.Label(tw, text=self.text, bg="#111827", fg="white", font=T.font(9), justify="left",
                 wraplength=T.px(320), padx=8, pady=5).pack()

    def _hide(self, _=None):
        self._cancel()
        if self.tip:
            self.tip.destroy()
            self.tip = None


class ParamPanel(tk.Frame):
    def __init__(self, parent, analysis, prefix, on_change, saved=None):
        super().__init__(parent, bg=T.CARD)
        self.analysis = analysis
        self.on_change = on_change
        self.vars, self.widgets, self.defs = {}, {}, {}
        self._loading = True
        self.columnconfigure(1, weight=1)
        saved = saved or {}
        for r, q in enumerate(analysis.params):
            self.defs[q.key] = q
            lab = tk.Label(self, text=q.label, bg=T.CARD, fg=T.TEXT, font=T.font(9), anchor="w")
            lab.grid(row=r, column=0, sticky="w", padx=(0, 8), pady=3)
            if q.tip:
                lab.configure(text=q.label + " ⓘ")
                Tooltip(lab, q.tip)
            raw = saved.get(q.key, q.to_text(q.default))
            if q.kind == "bool":
                var = tk.BooleanVar(value=bool(raw) if not isinstance(raw, str) else raw.lower() in ("1", "true"))
                w = ttk.Checkbutton(self, variable=var, style=f"{prefix}TCheckbutton")
            elif q.kind == "choice":
                var = tk.StringVar(value=raw if raw in q.choices else q.to_text(q.default))
                w = ttk.Combobox(self, textvariable=var, values=q.choices, state="readonly", width=22)
                w.bind("<MouseWheel>", lambda e: "break")          # 捲動參數面板時不要誤改選項
            elif q.kind == "column":
                var = tk.StringVar(value=raw)
                w = ttk.Combobox(self, textvariable=var, values=[], width=22)
                w.bind("<MouseWheel>", lambda e: "break")
            else:
                var = tk.StringVar(value=str(raw))
                w = ttk.Entry(self, textvariable=var, width=24)
            w.grid(row=r, column=1, sticky="ew", pady=3)
            if q.tip:
                Tooltip(w, q.tip)
            var.trace_add("write", lambda *a, k=q.key: self._changed(k))
            self.vars[q.key] = var
            self.widgets[q.key] = w
        self._loading = False

    def _changed(self, key):
        if self._loading:
            return
        ok = self._validate(key)
        self.on_change(key, ok)

    def _validate(self, key):
        q = self.defs[key]
        w = self.widgets[key]
        if q.kind in ("bool", "choice", "column", "text"):
            return True
        try:
            q.parse(self.vars[key].get())
            w.configure(style="TEntry")
            return True
        except ValueError:
            w.configure(style="Bad.TEntry")
            return False

    def set_columns(self, columns):
        """把所選檔案的欄位名稱放進「欄位」下拉選單。"""
        for key, q in self.defs.items():
            if q.kind == "column":
                self.widgets[key].configure(values=list(columns))

    def values(self):
        """回傳轉好的參數；有錯時丟出 ValueError（訊息會說哪一格）。"""
        out = {}
        for key, q in self.defs.items():
            out[key] = q.parse(self.vars[key].get())
        return out

    def texts(self):
        out = {}
        for key, q in self.defs.items():
            v = self.vars[key].get()
            if q.kind == "bool":
                v = bool(v)
            out[key] = v
        return out

    def changed_texts(self):
        """和預設不同的欄位（存進 gui_state，下次開啟還原）。"""
        out = {}
        for key, q in self.defs.items():
            v = self.vars[key].get()
            d = q.to_text(q.default)
            if (bool(v) != bool(d)) if q.kind == "bool" else (str(v) != str(d)):
                out[key] = bool(v) if q.kind == "bool" else v
        return out

    def reset(self):
        self._loading = True
        for key, q in self.defs.items():
            v = q.to_text(q.default)
            self.vars[key].set(bool(v) if q.kind == "bool" else v)
            if q.kind not in ("bool", "choice", "column", "text"):
                self.widgets[key].configure(style="TEntry")
        self._loading = False
        self.on_change(None, True)
