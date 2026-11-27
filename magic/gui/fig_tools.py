"""圖上的互動（所有機台共用，取自 LowTempAnalysis）：

  ‧ 圖例：拖曳移動位置；點一下某一項 → 隱藏 / 顯示那條資料（疊圖時方便比較）
  ‧ 可拖曳的文字（例如 Raman 的峰標註）：拖曳後記住位置
  ‧ ✎ 標題與軸標籤：自己改文字（空白 = 自動，「-」= 不顯示）

這些設定依「機台 + 分析功能」各自記住（存在 gui_state），重畫、重新開啟軟體都會套用。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import theme as T


def legend_handles(leg):
    return list(getattr(leg, "legend_handles", None) or getattr(leg, "legendHandles", []))


def colorbar_axes(fig):
    out = set()
    for ax in fig.axes:
        for coll in list(ax.collections) + list(ax.images):
            cb = getattr(coll, "colorbar", None)
            if cb is not None:
                out.add(cb.ax)
    return out


def label_axes(fig):
    return [ax for ax in fig.axes if ax.axison and ax.get_visible()]


def place_legend(leg, ax, xa, ya):
    leg.set_bbox_to_anchor((xa, ya), transform=ax.transAxes)
    try:
        leg.set_loc("lower left")
    except Exception:
        leg._loc = 3


def _value(text):
    return "" if text.strip() == "-" else text


TITLE_SCOPES = ["只有這張圖", "這台機台全部", "所有圖"]       # 這個功能 / 這台機台的全部功能 / 所有機台所有功能
PLACEHOLDERS = [("{日期}", "今天的日期，例如 20261126"), ("{時間}", "現在時間，例如 1724"),
                ("{機台}", "PPMS / SQUID / Raman / Etching"), ("{功能}", "分析功能的名稱，例如 背景扣除"),
                ("{檔名}", "第一個檔案的名稱（紀錄類是「N 筆紀錄」）")]


def expand_title(text, ctx):
    """把 {日期}、{時間}、{機台}、{功能}、{檔名} 換成實際內容（其他文字照原樣）。"""
    import re
    import time
    vals = {"日期": time.strftime("%Y%m%d"), "時間": time.strftime("%H%M"), **(ctx or {})}
    return re.sub(r"\{(日期|時間|機台|功能|檔名)\}", lambda m: str(vals.get(m.group(1), "")), text)


def apply_hidden(ax, hidden, rescale=True):
    """圖例名稱在 hidden 裡的資料藏起來（線、散點、誤差棒），圖例那一項變淡；Y 範圍只算看得到的資料。"""
    changed = False
    in_container = set()
    for c in getattr(ax, "containers", []):
        lab = c.get_label() or ""
        kids = [a for a in c.get_children() if a is not None]
        in_container.update(id(a) for a in kids)
        if not lab or lab.startswith("_"):
            continue
        vis = lab not in hidden
        for a in kids:
            if a.get_visible() != vis:
                a.set_visible(vis)
                changed = True
    for art in list(ax.lines) + list(ax.collections) + list(ax.patches):
        if id(art) in in_container:
            continue
        lab = art.get_label()
        if not lab or lab.startswith("_"):
            continue
        vis = lab not in hidden
        if art.get_visible() != vis:
            art.set_visible(vis)
            changed = True
    leg = ax.get_legend()
    if leg is not None:
        for t, h in zip(leg.get_texts(), legend_handles(leg)):
            off = t.get_text() in hidden
            t.set_alpha(0.35 if off else 1.0)
            try:
                h.set_alpha(0.25 if off else 1.0)
            except Exception:
                pass
    if changed and rescale:
        try:
            ax.relim(visible_only=True)
            ax.autoscale_view()
        except Exception:
            pass
    return changed


class FigTools:
    """掛在 FigurePanel 上。get_ov() 回傳目前分析的設定 dict（會被修改），save() 存檔。"""

    def __init__(self, panel):
        self.panel = panel
        self.get_ov = lambda: {}
        self.save = lambda: None
        self.status = lambda text, kind="info": None
        self.title_raw = lambda: ""                 # 目前這張圖要顯示的標題（頁面依套用範圍決定）
        self.title_ctx = lambda: {}
        self.drag = None
        c = panel.canvas
        c.mpl_connect("button_press_event", self.on_press)
        c.mpl_connect("motion_notify_event", self.on_motion)
        c.mpl_connect("button_release_event", self.on_release)

    @property
    def fig(self):
        return self.panel.fig

    @property
    def canvas(self):
        return self.panel.canvas

    def _busy_toolbar(self):
        return bool(str(getattr(self.panel.toolbar, "mode", "")))

    # ================================================================== 套用
    def apply(self):
        """畫完、套完樣式之後呼叫：圖例位置、隱藏的資料、文字位置、自訂標題與軸標籤。"""
        ov = self.get_ov() or {}
        axes = label_axes(self.fig)
        self._auto_labels = {}
        for k, ax in enumerate(axes):
            for kk, v in (("title", ax.get_title()), ("xlabel", ax.get_xlabel()), ("ylabel", ax.get_ylabel())):
                self._auto_labels[(k, kk)] = v
        self.apply_title()
        for idx, d in (ov.get("axes") or {}).items():
            k = int(idx)
            if k >= len(axes):
                continue
            ax = axes[k]
            for key, setter in (("title", ax.set_title), ("xlabel", ax.set_xlabel), ("ylabel", ax.set_ylabel)):
                if d.get(key):
                    setter(_value(d[key]))
        for idx, pos in (ov.get("legend") or {}).items():
            k = int(idx)
            if k < len(axes) and axes[k].get_legend() is not None:
                place_legend(axes[k].get_legend(), axes[k], *pos)
        for idx, hidden in (ov.get("hidden") or {}).items():
            k = int(idx)
            if k < len(axes) and hidden:
                apply_hidden(axes[k], hidden)
        moved = ov.get("annot") or {}
        for ann in self.texts():
            off = moved.get(ann.magic_key)
            if off:
                ann.xyann = tuple(off)

    def apply_title(self):
        """整張圖的標題（⌈圖標題⌋ 那一列）：字體大小、粗體跟著樣式；空白或「-」= 不顯示。"""
        raw = (self.title_raw() or "").strip()
        text = "" if raw in ("", "-") else expand_title(raw, self.title_ctx())
        fig = self.fig
        if text and self.fig.axes:
            st = self.panel.style_dict()
            fig.suptitle(text, fontsize=st.get("suptitle", 15),
                         fontweight="bold" if st.get("suptitle_bold", True) else "normal", color="#111827")
            fig._magic_title = True
        elif getattr(fig, "_magic_title", False) and getattr(fig, "_suptitle", None) is not None:
            fig._suptitle.remove()
            fig._suptitle = None
            fig._magic_title = False
        return text

    def texts(self):
        out = []
        for ax in self.fig.axes:
            for t in ax.texts:
                if getattr(t, "magic_key", None) and hasattr(t, "xyann") and t.get_visible():
                    out.append(t)
        return out

    def hidden_count(self):
        ov = self.get_ov() or {}
        return sum(len(v) for v in (ov.get("hidden") or {}).values())

    def reset(self, what=("legend", "hidden", "annot")):
        ov = self.get_ov()
        for k in what:
            ov.pop(k, None)
        self.save()

    # ================================================================== 滑鼠
    def _legend_at(self, event):
        if event.x is None:
            return None
        for ax in self.fig.axes:
            leg = ax.get_legend()
            if leg is None or not leg.get_visible():
                continue
            try:
                if leg.get_window_extent().contains(event.x, event.y):
                    return leg, ax
            except Exception:
                pass
        return None

    def _text_at(self, event):
        if event.x is None:
            return None
        for t in reversed(self.texts()):
            try:
                if t.get_window_extent().expanded(1.1, 1.3).contains(event.x, event.y):
                    return t
            except Exception:
                pass
        return None

    def on_press(self, event):
        if event.button != 1 or self._busy_toolbar() or self.panel.picking:
            return
        hit = self._legend_at(event)
        if hit is not None:
            leg, ax = hit
            bb = leg.get_window_extent()
            self.drag = dict(kind="legend", art=leg, ax=ax, x=event.x, y=event.y, x0=bb.x0, y0=bb.y0,
                             moved=False, bg=None)
            return
        t = self._text_at(event)
        if t is not None:
            self.drag = dict(kind="text", art=t, ax=t.axes, x=event.x, y=event.y, off0=tuple(t.xyann),
                             moved=False, bg=None)

    def _start_blit(self):
        d = self.drag
        self.panel.hover.paused = True
        self.panel.hover._hide_all()
        try:
            d["art"].set_animated(True)
            self.canvas.draw()
            d["bg"] = self.canvas.copy_from_bbox(self.fig.bbox)
        except Exception:
            d["bg"] = None

    def _blit(self):
        d = self.drag
        if d["bg"] is not None:
            try:
                self.canvas.restore_region(d["bg"])
                d["ax"].draw_artist(d["art"])
                self.canvas.blit(self.fig.bbox)
                return
            except Exception:
                d["bg"] = None
        self.canvas.draw_idle()

    def on_motion(self, event):
        d = self.drag
        if d is None:
            if not self._busy_toolbar() and event.x is not None:
                over = self._legend_at(event) is not None or self._text_at(event) is not None
                try:
                    self.canvas.get_tk_widget().configure(cursor="hand2" if over else "")
                except Exception:
                    pass
            return
        if event.x is None:
            return
        dx, dy = event.x - d["x"], event.y - d["y"]
        if not d["moved"]:
            if abs(dx) + abs(dy) < 4:
                return
            d["moved"] = True
            self._start_blit()
        if d["kind"] == "legend":
            bb = d["art"].get_window_extent()
            fw, fh = self.fig.bbox.width, self.fig.bbox.height
            nx = min(max(d["x0"] + dx, 0), max(fw - bb.width, 0))      # 不要拖到圖外面
            ny = min(max(d["y0"] + dy, 0), max(fh - bb.height, 0))
            xa, ya = d["ax"].transAxes.inverted().transform((nx, ny))
            place_legend(d["art"], d["ax"], xa, ya)
            d["pos"] = (float(xa), float(ya))
        else:
            k = 72.0 / self.fig.dpi                    # 像素 → points
            d["off"] = (d["off0"][0] + dx * k, d["off0"][1] + dy * k)
            d["art"].xyann = d["off"]
        self._blit()

    def on_release(self, event):
        d, self.drag = self.drag, None
        if d is None:
            return
        self.panel.hover.paused = False
        ov = self.get_ov()
        axes = label_axes(self.fig)
        if d["moved"]:
            d["art"].set_animated(False)
            if d["kind"] == "legend":
                idx = str(axes.index(d["ax"])) if d["ax"] in axes else None
                if idx is not None and "pos" in d:
                    ov.setdefault("legend", {})[idx] = [round(v, 4) for v in d["pos"]]
                    self.status("圖例已移動（會記住位置；「↺ 回到初始」可以回到原位）", "ok")
            elif "off" in d:
                ov.setdefault("annot", {})[d["art"].magic_key] = [round(v, 1) for v in d["off"]]
                self.status("文字已移動（會記住位置）", "ok")
            self.save()
            self.canvas.draw_idle()
            return
        if d["kind"] != "legend":
            return
        leg = d["art"]
        label = None
        for t, h in zip(leg.get_texts(), legend_handles(leg)):
            try:
                if t.get_window_extent().contains(d["x"], d["y"]) or h.get_window_extent().contains(d["x"], d["y"]):
                    label = t.get_text()
                    break
            except Exception:
                continue
        idx = str(axes.index(d["ax"])) if d["ax"] in axes else None
        if label is None or idx is None:
            return
        hidden = ov.setdefault("hidden", {}).setdefault(idx, [])
        if label in hidden:
            hidden.remove(label)
        else:
            hidden.append(label)
        apply_hidden(d["ax"], hidden)
        self.panel._home[d["ax"]] = (d["ax"].get_xlim(), d["ax"].get_ylim())
        self.save()
        self.canvas.draw_idle()
        self.status(f"「{label}」{'已隱藏' if label in hidden else '已顯示'}（再點一下圖例可以切換）", "ok")

    # ================================================================== 標題與軸標籤
    def edit_labels(self, parent, key, on_apply):
        """✎ 修改圖的標題與軸標籤（空白 = 自動，「-」= 不顯示）。"""
        if not label_axes(self.fig):
            self.status("先畫出圖，再修改標題與軸標籤", "warn")
            return None
        ov = self.get_ov()
        win = tk.Toplevel(parent)
        win.title("標題與軸標籤")
        win.configure(bg=T.CARD)
        win.transient(parent)
        tk.Label(win, text="空白 = 自動（灰字是目前的自動文字）；輸入「-」= 不顯示；可用 $...$ 寫數學式，例如 $I_c$ (mA)",
                 bg=T.CARD, fg=T.MUTED, font=T.font(9), wraplength=T.px(680), justify="left").pack(
            anchor="w", padx=12, pady=(10, 4))
        body = tk.Frame(win, bg=T.CARD)
        body.pack(fill="both", expand=True, padx=12)
        entries = {}
        sup_var = tk.StringVar(value="" if ov.get("suptitle", "") == "-" else ov.get("suptitle", ""))
        tk.Label(body, text="整張圖的標題\n（只有這張圖）", bg=T.CARD, fg=T.TEXT, font=T.font(10, "bold"),
                 justify="left").grid(row=0, column=0, sticky="w")
        ttk.Entry(body, textvariable=sup_var, width=50).grid(row=0, column=1, columnspan=2, sticky="ew", pady=3)
        cbars = colorbar_axes(self.fig)
        saved = ov.get("axes") or {}
        auto = getattr(self, "_auto_labels", {})
        row = 1
        for k, ax in enumerate(label_axes(self.fig)):
            kind = "色條" if ax in cbars else "子圖"
            tk.Label(body, text=f"{kind} {k + 1}", bg=T.CARD, fg=T.accent(key)["text"],
                     font=T.font(10, "bold")).grid(row=row, column=0, sticky="w", pady=(8, 0))
            row += 1
            keys = (("ylabel", "標籤"),) if ax in cbars else (("title", "標題"), ("xlabel", "X 標籤"), ("ylabel", "Y 標籤"))
            for kk, lab in keys:
                cur = auto.get((k, kk), {"title": ax.get_title(), "xlabel": ax.get_xlabel(), "ylabel": ax.get_ylabel()}[kk])
                var = tk.StringVar(value=saved.get(str(k), {}).get(kk, ""))
                tk.Label(body, text=lab, bg=T.CARD, fg=T.MUTED, font=T.font(9)).grid(row=row, column=0, sticky="w",
                                                                                   padx=(12, 0))
                ttk.Entry(body, textvariable=var, width=36).grid(row=row, column=1, sticky="ew", pady=2)
                tk.Label(body, text=cur[:40], bg=T.CARD, fg=T.FAINT, font=T.font(9)).grid(row=row, column=2, sticky="w",
                                                                                        padx=8)
                entries[(k, kk)] = var
                row += 1
        body.columnconfigure(1, weight=1)

        def apply(close=False):
            if sup_var.get().strip():
                ov["suptitle"] = sup_var.get().strip()
            elif ov.get("suptitle") != "-":
                ov.pop("suptitle", None)
            axes_d = {}
            for (k, kk), var in entries.items():
                if var.get().strip():
                    axes_d.setdefault(str(k), {})[kk] = var.get().strip()
            ov["axes"] = axes_d
            self.save()
            if close:
                win.destroy()
            on_apply()

        def reset():
            sup_var.set("")
            for var in entries.values():
                var.set("")
            apply()
        bf = tk.Frame(win, bg=T.CARD)
        bf.pack(fill="x", padx=12, pady=10)
        ttk.Button(bf, text="完成", style=f"{key}.Accent.TButton", command=lambda: apply(True)).pack(side="right")
        ttk.Button(bf, text="套用", style=f"{key}.Ghost.TButton", command=apply).pack(side="right", padx=6)
        ttk.Button(bf, text="全部恢復自動", style=f"{key}.Ghost.TButton", command=reset).pack(side="left")
        win.apply = apply
        win.entries = entries
        win.sup_var = sup_var
        return win
