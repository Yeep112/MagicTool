"""滑鼠移到圖上時，顯示最近的資料點（曲線）或色圖的數值。適用於所有分析，不用個別寫。

讀值框用 blitting 畫（只重畫讀值框，不重畫整張圖），滑鼠移動很順；也不會被存進圖檔。"""
from __future__ import annotations

import numpy as np


def _clean(label):
    return (label or "").replace("$", "").replace(r"\mu", "μ").replace(r"\Omega", "Ω") \
        .replace(r"\log_{10}", "log10").replace(r"\perp", "⊥").replace("_", "").strip()


class Hover:
    def __init__(self, canvas, max_px=40):
        self.canvas = canvas
        self.max_px = max_px
        self.boxes = {}
        self.bg = None
        self.paused = False
        self.cid = canvas.mpl_connect("motion_notify_event", self.on_move)
        canvas.mpl_connect("draw_event", self._on_draw)

    def reset(self):
        """重畫圖（fig.clear()）之後呼叫。"""
        self.boxes = {}
        self.bg = None

    def _on_draw(self, event=None):
        try:
            self.bg = self.canvas.copy_from_bbox(self.canvas.figure.bbox)
        except Exception:
            self.bg = None

    def _blit(self):
        """只重畫讀值框；不支援時退回整張重畫。"""
        if self.bg is None:
            self.canvas.draw_idle()
            return
        try:
            self.canvas.restore_region(self.bg)
            for ax, (ann, dot) in self.boxes.items():
                if ann.get_visible():
                    ax.draw_artist(dot)
                    ax.draw_artist(ann)
            self.canvas.blit(self.canvas.figure.bbox)
        except Exception:
            self.bg = None
            self.canvas.draw_idle()

    def _box(self, ax):
        if ax not in self.boxes:
            ann = ax.annotate("", xy=(0, 0), xytext=(12, 12), textcoords="offset points",
                              fontsize=9, zorder=1000, annotation_clip=False,
                              bbox=dict(boxstyle="round", fc="white", ec="gray", alpha=0.92),
                              animated=True)
            ann.set_visible(False)
            dot, = ax.plot([], [], "o", ms=7, mfc="none", mec="black", mew=1.2,
                           zorder=999, gid="nohover", animated=True)
            self.boxes[ax] = (ann, dot)
        return self.boxes[ax]

    def _hide_all(self):
        changed = False
        for ann, dot in self.boxes.values():
            if ann.get_visible():
                ann.set_visible(False)
                dot.set_data([], [])
                changed = True
        return changed

    @staticmethod
    def _xlabel(ax):
        """共用 X 軸的上方子圖沒有 xlabel，借用同組的。"""
        lab = ax.get_xlabel()
        if not lab:
            for sib in ax.get_shared_x_axes().get_siblings(ax):
                if sib.get_xlabel():
                    return sib.get_xlabel()
        return lab

    def lookup(self, ax, event):
        """回傳 (x, y, 文字) 或 None。"""
        # 色圖
        for coll in ax.collections:
            grid = getattr(coll, "lta_grid", None)
            if grid is not None:
                X, Y, Z, zlabel = grid
                i = int(np.argmin(np.abs(X - event.xdata)))
                j = int(np.argmin(np.abs(Y - event.ydata)))
                return (event.xdata, event.ydata,
                        f"{_clean(self._xlabel(ax))} = {X[i]:+.4g}\n"
                        f"{_clean(ax.get_ylabel())} = {Y[j]:+.4g}\n"
                        f"{_clean(zlabel)} = {Z[i, j]:+.5g}")
        # 曲線與散點
        best = None
        mouse = np.array([event.x, event.y])
        cands = []
        for ln in ax.lines:
            if ln.get_gid() == "nohover" or not ln.get_visible():
                continue
            if ln.get_transform() is not ax.transData:      # axvline/axhline 等參考線
                continue
            x, y = (np.asarray(a, float) for a in ln.get_data())
            if x.size:
                cands.append((x, y, ln.get_label()))
        for coll in ax.collections:
            if (getattr(coll, "lta_grid", None) is None and hasattr(coll, "get_offsets")
                    and coll.get_offset_transform() is ax.transData):
                off = np.asarray(coll.get_offsets(), float)
                if off.ndim == 2 and len(off):
                    cands.append((off[:, 0], off[:, 1], coll.get_label()))
        for x, y, label in cands:
            ok = np.isfinite(x) & np.isfinite(y)
            if not ok.any():
                continue
            pts = ax.transData.transform(np.column_stack([x[ok], y[ok]]))
            d = np.hypot(*(pts - mouse).T)
            k = int(np.argmin(d))
            if best is None or d[k] < best[0]:
                best = (d[k], x[ok][k], y[ok][k], label)
        if best is None or best[0] > self.max_px:
            return None
        _, x, y, label = best
        head = "" if (not label or label.startswith("_")) else f"{label}\n"
        return (x, y, f"{head}{_clean(self._xlabel(ax)) or 'x'} = {x:+.5g}\n"
                      f"{_clean(ax.get_ylabel()) or 'y'} = {y:+.5g}")

    def on_move(self, event):
        if self.paused:
            return
        ax = event.inaxes
        if ax is None or event.xdata is None:
            if self._hide_all():
                self._blit()
            return
        try:
            hit = self.lookup(ax, event)
        except Exception:
            hit = None
        for other, (ann, dot) in self.boxes.items():
            if other is not ax and ann.get_visible():
                ann.set_visible(False)
                dot.set_data([], [])
        ann, dot = self._box(ax)
        if hit is None:
            if ann.get_visible():
                ann.set_visible(False)
                dot.set_data([], [])
                self._blit()
            return
        x, y, text = hit
        ann.xy = (x, y)
        right = event.x > ax.bbox.x0 + 0.6 * ax.bbox.width
        top = event.y > ax.bbox.y0 + 0.7 * ax.bbox.height
        ann.set_position((-12 if right else 12, -12 if top else 12))
        ann.set_ha("right" if right else "left")
        ann.set_va("top" if top else "bottom")
        ann.set_text(text)
        ann.set_visible(True)
        has_grid = any(getattr(c, "lta_grid", None) is not None for c in ax.collections)
        dot.set_data([] if has_grid else [x], [] if has_grid else [y])
        self._blit()
