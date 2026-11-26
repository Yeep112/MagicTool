"""蝕刻示意圖（Tkinter Canvas）：製程七個步驟的剖面、蝕刻動畫、AFM 量測位置。

‧ 依使用者輸入的數字畫（材料、marker、SiO2 凹陷用同一個比例；光阻和 SiO2 基板不按比例）
‧ 每個量測都有一個尺寸箭頭，tag = 欄位名稱：點箭頭 → 跳到欄位；游標在欄位 → 箭頭亮起來
‧ 動畫：電漿粒子落到沒有光阻的地方，材料與 SiO2 依算出來的速率往下退；分段蝕刻時中間會暫停
"""
from __future__ import annotations

import math
import random
import tkinter as tk

from . import theme as TH

STAGES = [
    ("①", "準備樣品", "材料（hBN 等）轉移到 SiO2 基板上，旁邊有曝光對位用的 marker（Cr/Au）。"
                     "這時先用 AFM 量材料厚度 T 和 marker 厚度 T_m（塗光阻後就量不到了）。"),
    ("②", "塗光阻", "旋轉塗佈光阻（PMMA、S1813…），整片蓋住。光阻是蝕刻時保護樣品的「遮罩」。"),
    ("③", "曝光", "E-beam（或 UV）照到的地方，正光阻的分子鏈被打斷，顯影時會被溶掉。"
                 "照射的圖案寬度就是 pattern 線寬（被蝕刻的開口寬度）。"),
    ("④", "顯影", "被照射的光阻溶掉，露出要蝕刻的區域；沒照到的光阻留下來保護底下的材料。"),
    ("⑤", "蝕刻", "腔體通入氣體（SF6、CHF3 + O2…），ICP / RF 功率把氣體變成電漿，離子與自由基往下打到"
                 "沒有光阻的地方。開口越窄，電漿越不容易進去，蝕刻通常越慢。"),
    ("⑥", "去光阻", "用丙酮（或去光阻液）洗掉光阻。被保護的地方高度不變，被蝕刻的地方變低。"),
    ("⑦", "量測", "用 AFM 掃描台階（或膜厚儀量 SiO2 厚度）。紅色箭頭是「從蝕刻後的 SiO2 表面」量上去的高度。"),
]

C = dict(
    sio2="#e5e7eb", sio2_edge="#9ca3af", mat="#bbf7d0", mat_edge="#16a34a", mat_dark="#15803d",
    marker="#fed7aa", marker_edge="#ea580c", resist="#ddd6fe", resist_edge="#7c3aed", resist_exp="#f5f3ff",
    ion="#ec4899", radical="#3b82f6", red="#dc2626", black="#111827", beam="#f59e0b", tip="#475569",
)


class Geometry:
    """依數值算出各區塊的像素座標。數值缺少時用示意值。"""

    def __init__(self, w, h, vals):
        self.W, self.H = w, h
        self.v = vals
        T_mat = vals.get("T", 60.0)
        T_m = vals.get("T_m", 50.0)
        d_s = max(vals.get("d_sio2", 5.0), 0.0)
        top_nm = max(T_mat, T_m + d_s, 30.0)
        self.s = min(2.4, (h * 0.30) / top_nm)            # px / nm（材料、marker、SiO2 凹陷共用）
        self.base = h * 0.62                               # 蝕刻前 SiO2 表面
        self.resist_px = min(46.0, max(26.0, h * 0.085))      # 光阻膜厚（不按比例；薄一點才看得出丘陵狀）
        X = lambda f: w * f                                # noqa: E731
        self.sub = (X(0.03), X(0.97))
        self.prot_sio2 = (X(0.04), X(0.11))                # 光阻保護的 SiO2（量 SiO2 台階用）
        self.flake = (X(0.21), X(0.69))
        lw = vals.get("line_width")
        gap = 0.07 if not lw else min(0.12, max(0.025, 0.035 + 0.03 * math.log10(max(lw, 10) / 100)))
        c1, c2 = X(0.36), X(0.54)
        self.openings_flake = [(c1 - X(gap) / 2, c1 + X(gap) / 2), (c2 - X(gap) / 2, c2 + X(gap) / 2)]
        self.marker = (X(0.77), X(0.92))
        self.marker_cover = (X(0.77), X(0.845))
        # 被保護的區塊（顯影後還有光阻）
        self.resist_blocks = [self.prot_sio2,
                              (self.flake[0] + X(0.02), self.openings_flake[0][0]),
                              (self.openings_flake[0][1], self.openings_flake[1][0]),
                              (self.openings_flake[1][1], self.flake[1] - X(0.02)),
                              self.marker_cover]

    def y(self, nm_above_base):
        return self.base - nm_above_base * self.s

    def covered(self, x0, x1):
        return any(a <= x0 and x1 <= b for a, b in self.resist_blocks)


class Schematic(tk.Canvas):
    def __init__(self, parent, on_arrow_click=None):
        super().__init__(parent, bg="white", highlightthickness=0, bd=0)
        self.on_arrow_click = on_arrow_click
        self.stage = 0
        self.tau = 0.0
        self.vals = {}
        self.highlight = None
        self.particles = []
        self.tip_x = None
        self.bind("<Configure>", lambda e: self.redraw())

    # ------------------------------------------------------------------ 狀態
    def set_values(self, vals):
        self.vals = dict(vals)
        self.redraw()

    def set_stage(self, stage, tau=None):
        self.stage = stage
        if tau is not None:
            self.tau = tau
        if stage != 4:
            self.particles = []
        self.redraw()

    def set_highlight(self, key):
        self.highlight = key
        self.redraw()

    # ------------------------------------------------------------------ 蝕刻進度
    def depths(self, tau):
        """時間 tau（電漿開著的時間）時：材料蝕刻深度、SiO2 凹陷、開口內 SiO2 凹陷（蝕穿後）。"""
        v = self.vals
        T = v.get("T", 60.0)
        t_tot = max(v.get("t", 30.0), 1e-9)
        f = min(max(tau / t_tot, 0.0), 1.0)
        r_m = v.get("d_mat", T * 0.5) / t_tot
        r_s = max(v.get("d_sio2", 5.0), 0.0) / t_tot
        d_mat = r_m * tau if f < 1 else v.get("d_mat", T * 0.5)
        d_s = r_s * tau
        under = 0.0
        if d_mat >= T and r_m > 0:
            t_through = T / r_m
            under = r_s * max(tau - t_through, 0.0)
            d_mat = T
        return min(d_mat, T), d_s, under

    # ------------------------------------------------------------------ 畫圖
    def redraw(self):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 50 or h < 50:
            return
        self.delete("all")
        g = Geometry(w, h, self.vals)
        st = self.stage
        etched = st >= 4
        tau = self.tau if st == 4 else (self.vals.get("t", 30.0) if st > 4 else 0.0)
        d_mat, d_s, under = self.depths(tau) if etched else (0.0, 0.0, 0.0)
        frac = float(self.vals.get("resist_frac", 0.0) or 0.0)       # 光阻最後被吃掉的比例
        self._thin = frac * min(tau / max(self.vals.get("t", 30.0), 1e-9), 1.0) if st == 4 else 0.0
        T = self.vals.get("T", 60.0)
        T_m = self.vals.get("T_m", 50.0)
        own = self.vals.get("marker_etched", 0.0) if etched else 0.0
        self._substrate(g, d_s, under)
        # 材料：被保護的地方厚度 T；開口處 T − d
        fx0, fx1 = g.flake
        self.create_rectangle(fx0, g.y(T), fx1, g.base, fill=C["mat"], outline=C["mat_edge"], width=1.5)
        if etched:
            for a, b in g.openings_flake:
                self.create_rectangle(a, g.y(T) - 1, b, g.y(T - d_mat), fill="white", outline="")
                if d_mat < T:
                    self.create_rectangle(a, g.y(T - d_mat), b, g.base, fill=C["mat"], outline=C["mat_edge"])
                else:
                    self.create_rectangle(a, g.base, b, g.y(-under), fill="white", outline="")
            for a, b in ((fx0, g.resist_blocks[1][0]), (g.resist_blocks[3][1], fx1)):    # 材料兩端沒被蓋住的部分
                self.create_rectangle(a, g.y(T) - 1, b, g.y(T - d_mat), fill="white", outline="")
                if d_mat < T:
                    self.create_rectangle(a, g.y(T - d_mat), b, g.base, fill=C["mat"], outline=C["mat_edge"])
        # marker
        mx0, mx1 = g.marker
        self.create_rectangle(mx0, g.y(T_m), mx1, g.base, fill=C["marker"], outline=C["marker_edge"], width=1.5)
        if etched and own > 0:
            cx = g.marker_cover[1]
            self.create_rectangle(cx, g.y(T_m) - 1, mx1, g.y(T_m - own), fill="white", outline="")
            self.create_rectangle(cx, g.y(T_m - own), mx1, g.base, fill=C["marker"], outline=C["marker_edge"])
        self._labels(g, T, T_m)
        if 1 <= st <= 4:
            self._resist(g, st, T, T_m)
        if st == 2:
            self._beams(g)
        if st == 4:
            self._plasma(g, d_mat, d_s)
        if st == 6:
            self._arrows_after(g, T, T_m, d_mat, d_s, own)
            self._afm_tip(g, T, d_mat, d_s)
        if st == 0:
            self._arrows_before(g, T, T_m)
        self._caption(g)

    def _substrate(self, g, d_s, under):
        x0, x1 = g.sub
        bot = g.base + g.H * 0.26
        self.create_rectangle(x0, g.base, x1, bot, fill=C["sio2"], outline=C["sio2_edge"], width=1.5)
        # 沒被保護、也不在材料 / marker 底下的 SiO2 → 凹下去
        if d_s > 0:
            covered = [g.prot_sio2, g.flake, g.marker]
            xs = sorted([x0] + [p for a, b in covered for p in (a, b)] + [x1])
            for a, b in zip(xs[::2], xs[1::2]):
                if b - a > 1:
                    self.create_rectangle(a + 1, g.base - 1, b - 1, g.y(-d_s), fill="white", outline="")
                    self.create_line(a, g.y(-d_s), b, g.y(-d_s), fill=C["sio2_edge"], width=1.5)
                    self.create_line(a, g.base, a, g.y(-d_s), fill=C["sio2_edge"], width=1.5)
                    self.create_line(b, g.base, b, g.y(-d_s), fill=C["sio2_edge"], width=1.5)
        mid = (x0 + x1) / 2
        for dx in (-6, 6):                                  # 斷裂符號：基板不按比例
            self.create_line(mid + dx - 8, bot - 18, mid + dx + 8, bot - 6, fill=C["sio2_edge"], width=2)
        self.create_text(x0 + 10, bot - 12, text="SiO2 / Si 基板（厚度不按比例）", anchor="w",
                         font=TH.font(8), fill=TH.MUTED)

    def _labels(self, g, T, T_m):
        fx0, fx1 = g.flake
        name = self.vals.get("material", "hBN") or "材料"
        self.create_text((fx0 + fx1) / 2, g.base + 14, text=name, font=TH.font(9, "bold"), fill=C["mat_dark"])
        self.create_text(sum(g.marker) / 2, g.base + 14, text="marker", font=TH.font(9, "bold"), fill=C["marker_edge"])

    # ------------------------------------------------------------------ 光阻（貼在樣品上的保護膜）
    def resist_profile(self, g, T, T_m):
        """旋轉塗佈的光阻像一層保護膜：底面貼著樣品（基板、材料、marker），頂面在材料和 marker 上方
        鼓起來（像丘陵，邊緣是平滑的斜坡），越高的東西上面光阻越薄。回傳 (xs, 底面 y, 頂面 y)。"""
        import numpy as np
        x0, x1 = g.sub
        xs = np.arange(x0, x1 + 1.0, 2.0)
        h = np.zeros_like(xs)
        for (a, b), hh in ((g.flake, T), (g.marker, T_m)):
            h[(xs >= a) & (xs <= b)] = max(hh, 0.0) * g.s
        bottom = g.base - h
        t = g.resist_px                                         # 膜厚（不按比例）
        r = max(int(0.5 * t / 2.0), 1)                          # 膜蓋過邊緣時往外延伸的距離（點數，每點 2 px）
        pad = np.pad(h, r, mode="edge")
        win = np.lib.stride_tricks.sliding_window_view(pad, 2 * r + 1)
        hd = win.max(axis=1)                                    # 先往外擴（膜在邊緣像帳篷一樣蓋過去）
        k = max(int(0.75 * t / 2.0), 2)
        ker = np.hanning(2 * k + 1)
        ker /= ker.sum()
        hs = np.convolve(np.pad(hd, k, mode="edge"), ker, mode="same")[k:-k]   # 再平滑 → 圓弧的肩、丘陵
        top = g.base - t - hs
        top = np.minimum(top, bottom - 0.8 * t)                 # 任何地方的膜厚都至少 0.8 t
        thin = float(getattr(self, "_thin", 0.0) or 0.0)        # 蝕刻時光阻被吃掉的比例（有光阻蝕刻率才有）
        if thin > 0:
            top = top + (bottom - top) * min(thin, 0.9)
        return xs, bottom, top

    def _resist_poly(self, xs, bottom, top, a, b, **kw):
        m = (xs >= a) & (xs <= b)
        if m.sum() < 2:
            return
        xa, ba, ta = xs[m], bottom[m], top[m]
        pts = [a, ta[0]] + [v for x, y in zip(xa, ta) for v in (x, y)] + [b, ta[-1], b, ba[-1]] + \
              [v for x, y in zip(xa[::-1], ba[::-1]) for v in (x, y)] + [a, ba[0]]
        self.create_polygon(*pts, **kw)

    def _resist(self, g, st, T, T_m):
        xs, bottom, top = self.resist_profile(g, T, T_m)
        name = self.vals.get("resist", "PMMA") or "光阻"
        style = dict(fill=C["resist"], outline=C["resist_edge"], width=1.2, stipple="gray50")
        if st in (1, 2):
            x0, x1 = g.sub
            self._resist_poly(xs, bottom, top, x0, x1, **style)
            if st == 2:
                for a, b in self._exposed(g):
                    self._resist_poly(xs, bottom, top, a, b, fill=C["resist_exp"], outline="", stipple="gray50")
            self.create_text(x0 + 8, float(top[0]) + 10, text=f"{name}（不按比例）", anchor="w", font=TH.font(8),
                             fill=C["resist_edge"])
        else:
            for a, b in g.resist_blocks:
                self._resist_poly(xs, bottom, top, a, b, **style)
            a0 = g.resist_blocks[0][0]
            self.create_text(a0, float(top.min()) - 8, text=f"{name} 遮罩", anchor="w", font=TH.font(8),
                             fill=C["resist_edge"])

    def resist_top(self, g, x):
        """x 位置的光阻頂面（粒子落下的高度）。"""
        import numpy as np
        T, T_m = self.vals.get("T", 60.0), self.vals.get("T_m", 50.0)
        key = (g.W, g.H, T, T_m, getattr(self, "_thin", 0.0))
        if getattr(self, "_rp_key", None) != key:
            self._rp = self.resist_profile(g, T, T_m)
            self._rp_key = key
        xs, _, top = self._rp
        return float(np.interp(x, xs, top))

    def _exposed(self, g):
        x0, x1 = g.sub
        edges = sorted([x0] + [p for a, b in g.resist_blocks for p in (a, b)] + [x1])
        return [(a, b) for a, b in zip(edges[::2], edges[1::2]) if b - a > 1]

    def _beams(self, g):
        top = g.H * 0.06
        for a, b in self._exposed(g):
            for x in (a + (b - a) * f for f in (0.3, 0.7)):
                self.create_line(x, top, x, self.resist_top(g, x) - 4, fill=C["beam"], width=2, arrow="last")
        self.create_text(g.W / 2, top - 2, text="e-beam", font=TH.font(9, "bold"), fill=C["beam"], anchor="s")

    def surface_y(self, g, x, d_mat, d_s):
        """粒子落下的高度：有光阻 → 光阻頂；材料開口 → 材料表面；其他 → SiO2 表面。"""
        T, T_m = self.vals.get("T", 60.0), self.vals.get("T_m", 50.0)
        for a, b in g.resist_blocks:
            if a <= x <= b:
                return self.resist_top(g, x)
        if g.flake[0] <= x <= g.flake[1]:
            return g.y(T - d_mat)
        if g.marker[0] <= x <= g.marker[1]:
            return g.y(T_m)
        return g.y(-d_s)

    def _plasma(self, g, d_mat, d_s):
        rnd = random.Random(int(self.tau * 50))
        if not self.particles:
            self.particles = [[rnd.uniform(*g.sub), rnd.uniform(g.H * 0.04, g.base - 60), rnd.uniform(4, 9),
                               rnd.random() < 0.5] for _ in range(46)]
        self.create_rectangle(g.sub[0], g.H * 0.02, g.sub[1], g.H * 0.15, fill="#fdf2f8", outline="")
        self.create_text(g.W / 2, g.H * 0.085, text="電漿（離子 ● 往下加速、自由基 ○ 擴散）", font=TH.font(9),
                         fill=C["ion"])
        for p in self.particles:
            x, y, vy, ion = p
            r = 3
            if ion:
                self.create_oval(x - r, y - r, x + r, y + r, fill=C["ion"], outline="")
            else:
                self.create_oval(x - r, y - r, x + r, y + r, outline=C["radical"], width=1.5)

    def step_particles(self):
        if self.stage != 4 or not self.particles:
            return
        g = Geometry(self.winfo_width(), self.winfo_height(), self.vals)
        d_mat, d_s, _ = self.depths(self.tau)
        for p in self.particles:
            p[1] += p[2] * (1.0 if p[3] else 0.6)
            if not p[3]:
                p[0] += random.uniform(-2, 2)
            if p[1] >= self.surface_y(g, p[0], d_mat, d_s) - 2:
                p[0] = random.uniform(*g.sub)
                p[1] = g.H * random.uniform(0.04, 0.12)

    def _afm_tip(self, g, T, d_mat, d_s):
        if self.tip_x is None:
            return
        x = self.tip_x
        # 去光阻後的表面
        if g.flake[0] <= x <= g.flake[1]:
            inside = any(a <= x <= b for a, b in g.openings_flake) or not (g.resist_blocks[1][0] <= x <= g.resist_blocks[3][1])
            y = g.y(T - d_mat) if inside else g.y(T)
        elif g.marker[0] <= x <= g.marker[1]:
            y = g.y(self.vals.get("T_m", 50.0) - (self.vals.get("marker_etched", 0.0) if x > g.marker_cover[1] else 0))
        elif g.prot_sio2[0] <= x <= g.prot_sio2[1]:
            y = g.base
        else:
            y = g.y(-d_s)
        self.create_polygon(x, y - 2, x - 7, y - 20, x + 7, y - 20, fill=C["tip"], outline="")
        self.create_rectangle(x - 18, y - 30, x + 18, y - 20, fill=C["tip"], outline="")
        self.create_text(x, y - 38, text="AFM", font=TH.font(8, "bold"), fill=C["tip"])

    # ------------------------------------------------------------------ 尺寸箭頭
    def _arrow(self, key, x, y0, y1, color, label, side="e"):
        hi = key == self.highlight
        width = 3.5 if hi else 1.6
        col = TH.accent("Etching")["main"] if hi else color
        tag = ("arrow", f"k_{key}")
        self.create_line(x, y0, x, y1, arrow="both", fill=col, width=width, tags=tag)
        off = 6 if side == "e" else -6
        self.create_text(x + off, (y0 + y1) / 2, text=label, anchor="w" if side == "e" else "e",
                         font=TH.font(9, "bold" if hi else "normal"), fill=col, tags=tag)
        if hi:
            self.create_rectangle(x - 4, min(y0, y1) - 4, x + 4, max(y0, y1) + 4, outline=col, width=1, dash=(2, 2))
        self.tag_bind(f"k_{key}", "<Button-1>", lambda e, k=key: self.on_arrow_click and self.on_arrow_click(k))
        self.tag_bind(f"k_{key}", "<Enter>", lambda e: self.configure(cursor="hand2"))
        self.tag_bind(f"k_{key}", "<Leave>", lambda e: self.configure(cursor=""))

    def _arrows_before(self, g, T, T_m):
        self._arrow("mat_before", g.flake[0] + 18, g.base, g.y(T), C["mat_edge"], "T（蝕刻前）")
        self._arrow("marker_before", g.marker[1] + 8, g.base, g.y(T_m), C["marker_edge"], "T_m")

    def _arrows_after(self, g, T, T_m, d_mat, d_s, own):
        o0, o1 = g.openings_flake[0]
        # 材料：保護區 T、開口 T'、台階 S
        px = g.resist_blocks[2][0] + 10
        self._arrow("mat_before", px, g.base, g.y(T), C["mat_edge"], "T")
        if d_mat < T:
            self._arrow("mat_step", (o0 + o1) / 2, g.y(T), g.y(T - d_mat), C["mat_dark"], "S = T − T'", side="w")
        # 從基板量到材料頂端（材料左端被蝕刻的部分）
        lx = g.flake[0] - 10
        self._arrow("mat_out", lx, g.y(-d_s), g.y(T - d_mat), C["red"], "H_out", side="w")
        # SiO2 台階（左邊光阻保護區）
        self._arrow("sio2_step", g.prot_sio2[1] + 10, g.base, g.y(-d_s), C["black"], "SiO2 台階")
        # 膜厚儀：SiO2 總厚度
        bot = g.base + g.H * 0.26
        self._arrow("sio2_after", g.sub[1] - 40, g.y(-d_s), bot, C["black"], "h'", side="w")
        self._arrow("sio2_before", g.prot_sio2[0] + 8, g.base, bot, "#6b7280", "h")
        # marker
        self._arrow("marker_before", g.marker[0] + 10, g.base, g.y(T_m), C["marker_edge"], "T_m")
        self._arrow("marker_after_own", g.marker_cover[1] + 12, g.base, g.y(T_m - own), C["marker_edge"], "T'_m")
        self._arrow("marker_out", g.marker[1] + 10, g.y(-d_s), g.y(T_m - own), C["red"], "H_m,out")

    def _caption(self, g):
        if self.vals.get("_demo"):
            self.create_text(g.W - 8, g.H - 6, text="（還沒輸入數字：示意值）", anchor="se", font=TH.font(8), fill=TH.FAINT)
        if self.stage == 4:
            steps = self.vals.get("steps", [self.vals.get("t", 30.0)])
            k = 0
            acc = 0.0
            for i, s in enumerate(steps):
                acc += s
                if self.tau <= acc + 1e-9:
                    k = i
                    break
            seg = f"（第 {k + 1} / {len(steps)} 段）" if len(steps) > 1 else ""
            self.create_text(8, g.H - 6, anchor="sw", font=TH.font(10, "bold"), fill=TH.TEXT,
                             text=f"t = {self.tau:.1f} / {self.vals.get('t', 30.0):g} s {seg}")
