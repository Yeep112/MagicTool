"""顏色工具：解析 HEX / RGB、產生主色的深淺變化、介面配色預設組。"""
from __future__ import annotations

import re


def parse_color(text):
    """接受 '#e4572e'、'e4572e'、'#e52'、'rgb(228, 87, 46)'、'228,87,46'、'228 87 46'、
    '0.89, 0.34, 0.18'（0–1 小數）→ 回傳 '#rrggbb'。看不懂就丟出 ValueError。"""
    s = str(text).strip().lower()
    if not s:
        raise ValueError("沒有輸入顏色")
    m = re.fullmatch(r"#?([0-9a-f]{6})", s)
    if m:
        return "#" + m.group(1)
    m = re.fullmatch(r"#?([0-9a-f]{3})", s)
    if m:
        return "#" + "".join(c * 2 for c in m.group(1))
    nums = re.findall(r"[-+]?\d*\.?\d+", s)
    if len(nums) == 3:
        vals = [float(n) for n in nums]
        if all(0 <= v <= 1 for v in vals) and any("." in n for n in nums):
            vals = [v * 255 for v in vals]
        if all(0 <= v <= 255 for v in vals):
            return "#" + "".join(f"{int(round(v)):02x}" for v in vals)
    raise ValueError(f"看不懂的顏色：{text}（請用 #RRGGBB 或 R, G, B）")


def to_rgb(hex_color):
    h = parse_color(hex_color)[1:]
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def to_hex(rgb):
    return "#" + "".join(f"{max(0, min(255, int(round(v)))):02x}" for v in rgb)


def mix(c1, c2, t):
    """c1 與 c2 混合，t=0 → c1、t=1 → c2"""
    a, b = to_rgb(c1), to_rgb(c2)
    return to_hex([x + (y - x) * t for x, y in zip(a, b)])


def shades(main):
    """由一個主色產生 main / dark / soft / text 四種變化（介面用）。"""
    main = parse_color(main)
    return dict(main=main, dark=mix(main, "#000000", 0.18), soft=mix(main, "#ffffff", 0.88),
                text=mix(main, "#000000", 0.35))


def rgb_text(hex_color):
    r, g, b = to_rgb(hex_color)
    return f"{r}, {g}, {b}"


# 介面配色預設組：標題列、背景、1D 主色、2D 主色
THEME_PRESETS = {
    "藍紫（預設）": dict(header="#18223d", bg="#eef2f8", accent_1d="#2563eb", accent_2d="#7c3aed"),
    "青綠": dict(header="#0f2f2e", bg="#edf5f4", accent_1d="#0d9488", accent_2d="#0284c7"),
    "暖橘": dict(header="#2c1c14", bg="#f7f2ec", accent_1d="#ea580c", accent_2d="#db2777"),
    "石墨": dict(header="#111827", bg="#f1f2f4", accent_1d="#475569", accent_2d="#6366f1"),
    "森林": dict(header="#14261b", bg="#eff4ef", accent_1d="#15803d", accent_2d="#a16207"),
}

DEFAULT_CYCLE = ["#2563eb", "#e4572e", "#17a398", "#f2a541", "#7c3aed", "#ef476f",
                 "#118ab2", "#8d6a9f", "#06d6a0", "#5c6b73"]


# ---------------------------------------------------------------------------
# 一個顏色 → 整套介面配色（設定 → 外觀）
# ---------------------------------------------------------------------------
import colorsys

# 名稱 → 基準色。淺色當背景、飽和色當主色、很深的顏色自動切成深色版面
SWATCHES = {
    "預設藍": "#eef2f8",
    "薰衣草紫": "#e9e5fb",
    "晴空藍": "#dfeafb",
    "薄荷綠": "#dff3e6",
    "蜜桃粉": "#fde4e4",
    "奶油黃": "#fbf2d3",
    "霧灰": "#eceef1",
    "深紫": "#5b4bc4",
    "夜藍": "#1c2638",
}


def _hls(c):
    r, g, b = (v / 255 for v in to_rgb(c))
    return colorsys.rgb_to_hls(r, g, b)


def _from_hls(h, l, s):
    return to_hex([v * 255 for v in colorsys.hls_to_rgb(h % 1.0, max(0, min(1, l)), max(0, min(1, s)))])


def luminance(c):
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = to_rgb(c)
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(c1, c2):
    a, b = sorted((luminance(c1), luminance(c2)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def readable_on(bg, prefer="#ffffff", dark="#111827"):
    """bg 上看得清楚的文字顏色。"""
    return prefer if contrast(bg, prefer) >= contrast(bg, dark) else dark


def describe_base(base):
    h, l, s = _hls(parse_color(base))
    if l <= 0.25:
        return "深色版面"
    if l >= 0.80:
        return "淺色背景"
    return "主色"


def _readable_accent(h, l, s, on="#ffffff", need=3.6):
    """同色相下，調暗到白字看得清楚為止。"""
    c = _from_hls(h, l, s)
    while contrast(c, on) < need and l > 0.18:
        l -= 0.03
        c = _from_hls(h, l, s)
    return c


def _second_hue(h):
    """2D 主色：暖色往洋紅偏，其他往藍紫偏。"""
    return h - 0.10 if (h < 0.2 or h > 0.9) else h + 0.11


def derive_theme(base, accent_1d=None, accent_2d=None):
    """由一個基準色產生介面需要的所有顏色。

    淺色（亮度 ≥ 0.80）→ 直接當背景，主色取同色相的飽和色；
    中間 → 當主色，背景用同色相的淡色；
    很深（亮度 ≤ 0.25）→ 深色版面。文字顏色依對比自動選。"""
    base = parse_color(base)
    h, l, s = _hls(base)
    grey = s < 0.12
    if l <= 0.25:                                   # ---- 深色版面
        bg = base
        card = _from_hls(h, l + 0.05, s * 0.8)
        acc = accent_1d or ("#60a5fa" if grey else _from_hls(h, 0.66, max(s, 0.65)))
        acc2 = accent_2d or ("#a78bfa" if grey else _from_hls(_second_hue(h), 0.68, max(s, 0.6)))
        t = dict(dark=True, BG=bg, CARD=card, BORDER=_from_hls(h, l + 0.14, s * 0.6),
                 HEADER=_from_hls(h, max(l - 0.05, 0.04), s), TEXT="#e5e7eb", MUTED="#a3acbd",
                 FAINT="#7b8496", HOVER=_from_hls(h, l + 0.09, s * 0.8),
                 STRIPE=_from_hls(h, l + 0.07, s * 0.8), SUBTLE=_from_hls(h, l + 0.08, s * 0.7),
                 FIELD=_from_hls(h, l + 0.10, s * 0.7), CHIP=_from_hls(h, l + 0.12, s * 0.6),
                 TEXT_BG=_from_hls(h, l + 0.03, s * 0.8))
        a1, a2 = acc, acc2
        acc_soft = lambda c: mix(c, card, 0.78)                     # noqa: E731
        acc_text = lambda c: mix(c, "#ffffff", 0.25)                # noqa: E731
    else:
        if l >= 0.80:                               # ---- 淺色：當背景
            bg = base
            a1 = accent_1d or ("#475569" if grey else _readable_accent(h, 0.46, max(s, 0.7)))
            hh = h
        else:                                       # ---- 中間：當主色
            a1 = accent_1d or base
            bg = _from_hls(h, 0.95, min(max(s, 0.25), 0.45)) if not grey else "#f1f2f4"
            hh = h
        a2 = accent_2d or ("#6366f1" if grey else _readable_accent(_second_hue(hh), 0.50, max(s, 0.6)))
        card = "#ffffff"
        t = dict(dark=False, BG=bg, CARD=card, BORDER=mix(bg, "#94a3b8", 0.28),
                 HEADER=_from_hls(hh, 0.15, 0.42 if not grey else 0.12), TEXT="#1f2937",
                 MUTED="#6b7280", FAINT="#9ca3af", HOVER=mix(bg, "#ffffff", 0.55),
                 STRIPE=mix(bg, "#ffffff", 0.75), SUBTLE=mix(bg, "#ffffff", 0.6), FIELD="#ffffff",
                 CHIP=mix(bg, "#ffffff", 0.35), TEXT_BG=mix(bg, "#ffffff", 0.82))
        acc_soft = lambda c: mix(c, "#ffffff", 0.88)                # noqa: E731
        acc_text = lambda c: mix(c, "#000000", 0.35)                # noqa: E731
    t["HEADER_TEXT"] = readable_on(t["HEADER"])
    t["HEADER_2"] = mix(t["HEADER"], "#ffffff", 0.12)
    t["HEADER_MUTED"] = mix(t["HEADER"], t["HEADER_TEXT"], 0.62)
    t["ACCENTS"] = {}
    for key, c in (("1D", a1), ("2D", a2)):
        c = parse_color(c)
        t["ACCENTS"][key] = dict(main=c, dark=mix(c, "#000000", 0.18), soft=acc_soft(c), text=acc_text(c),
                                 on=readable_on(c))
    return t


# 舊版設定（標題列、背景、1D、2D 四色）也還能用
def legacy_theme(header, bg, accent_1d, accent_2d):
    t = derive_theme(bg, accent_1d, accent_2d)
    t["HEADER"] = parse_color(header)
    t["HEADER_TEXT"] = readable_on(t["HEADER"])
    t["HEADER_2"] = mix(t["HEADER"], "#ffffff", 0.12)
    t["HEADER_MUTED"] = mix(t["HEADER"], t["HEADER_TEXT"], 0.62)
    return t
