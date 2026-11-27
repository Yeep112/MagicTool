"""介面配色、字型、介面大小（取自 LowTempAnalysis 的 theme.py；主色改成每台機台一個）。"""
from __future__ import annotations

import sys

from .colors import mix, shades

BG = "#eef2f8"
CARD = "#ffffff"
BORDER = "#dfe5ef"
HEADER = "#18223d"
HEADER_2 = "#253257"
HEADER_TEXT = "#ffffff"
HEADER_MUTED = "#9fb0d6"
TEXT = "#1f2937"
MUTED = "#6b7280"
FAINT = "#9ca3af"
HOVER = "#f3f6fc"
STRIPE = "#f8fafd"
SUBTLE = "#f6f8fc"
FIELD = "white"
CHIP = "#f1f4f9"
TEXT_BG = "#f8fafc"
SUCCESS = "#16a34a"
WARNING = "#d97706"
ERROR = "#dc2626"

ACCENTS: dict = {}


def set_accents(instruments):
    """每台機台一個主色（registry 的 Instrument.color）。"""
    for key, inst in instruments.items():
        a = shades(inst.color)
        a["on"] = "#ffffff"
        ACCENTS[key] = a


def accent(key):
    return ACCENTS.get(key) or {**shades("#2563eb"), "on": "#ffffff"}


FONT_FAMILY = "TkDefaultFont"
MONO_FAMILY = "Consolas"


def pick_fonts(tkfont):
    global FONT_FAMILY, MONO_FAMILY
    fams = set(tkfont.families())
    for f in ("Microsoft JhengHei UI", "Microsoft JhengHei", "PingFang TC", "Heiti TC", "Noto Sans CJK TC",
              "Noto Sans TC", "Noto Sans CJK JP", "Segoe UI"):
        if f in fams:
            FONT_FAMILY = f
            break
    for f in ("Cascadia Mono", "Consolas", "Menlo", "SF Mono", "Monaco", "Noto Sans Mono CJK TC", "DejaVu Sans Mono"):
        if f in fams:
            MONO_FAMILY = f
            break


def mix_color(c1, c2, t):
    return mix(c1, c2, t)


def font(size=10, weight="normal"):
    return (FONT_FAMILY, size, weight)


# ---------------------------------------------------------------------------
# 介面大小（依螢幕自動判斷，或在設定裡選 80%–175%）
# ---------------------------------------------------------------------------
UI_FACTOR = 1.0
PX = 1.0
SCREEN = {}
_BASE_DPI = None
SCALE_CHOICES = [("自動（依螢幕判斷）", "auto"), ("80%", 0.8), ("90%", 0.9), ("100%", 1.0), ("110%", 1.1),
                 ("125%", 1.25), ("150%", 1.5), ("175%", 1.75)]


def px(n):
    return int(round(n * PX))


def px_min(n):
    """最小視窗大小：螢幕縮放（125%、150%）時跟著放大；小螢幕（介面縮到 90%）時不跟著縮小，維持 100% 的大小。"""
    return int(round(n * max(PX, 1.0)))


def detect_screen(root):
    global _BASE_DPI
    if _BASE_DPI is None:
        try:
            _BASE_DPI = float(root.winfo_fpixels("1i"))
        except Exception:
            _BASE_DPI = 96.0
        if not (48 <= _BASE_DPI <= 480):
            _BASE_DPI = 96.0
        if sys.platform == "darwin":
            _BASE_DPI = 96.0      # macOS 的座標是「點」（Retina 也一樣），版面照 Windows 100% 的尺寸排
    try:
        sw, sh = int(root.winfo_screenwidth()), int(root.winfo_screenheight())
    except Exception:
        sw, sh = 1920, 1080
    win_scale = _BASE_DPI / 96.0
    lw, lh = sw / win_scale, sh / win_scale
    if sys.platform == "darwin":
        lh -= 110                 # 選單列與 Dock
    if lh >= 2000:
        auto = 1.5
    elif lh >= 1600:
        auto = 1.25
    elif lw < 1400 or lh < 820:
        auto = 0.9
    else:
        auto = 1.0
    return dict(width=sw, height=sh, dpi=_BASE_DPI, win_scale=win_scale, logical=(round(lw), round(lh)), auto=auto)


def apply_scaling(root, setting="auto"):
    global UI_FACTOR, PX, SCREEN
    SCREEN = detect_screen(root)
    try:
        f = SCREEN["auto"] if setting in (None, "", "auto") else float(setting)
    except (TypeError, ValueError):
        f = SCREEN["auto"]
    f = min(max(f, 0.6), 2.5)
    UI_FACTOR = f
    PX = SCREEN["win_scale"] * f
    try:
        root.tk.call("tk", "scaling", SCREEN["dpi"] / 72.0 * f)
    except Exception:
        pass
    return SCREEN


def setup_ttk(style, key=None, prefix=""):
    """ttk 元件樣式（clam 主題可以自由上色）。

    每台機台各有一組樣式（prefix = "PPMS." 等），啟動時一次設定好；
    換機台時不用重新設定樣式，介面不會因為整個重畫而卡頓。"""
    a = accent(key)
    if not prefix:
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure(".", background=CARD, foreground=TEXT, font=font(10), bordercolor=BORDER,
                        focuscolor=a["main"])
        style.configure("TFrame", background=CARD)
        style.configure("TLabel", background=CARD, foreground=TEXT)
        style.configure("Muted.TLabel", background=CARD, foreground=MUTED, font=font(9))
        style.configure("TEntry", fieldbackground=FIELD, foreground=TEXT, insertcolor=TEXT, bordercolor=BORDER,
                        lightcolor=BORDER, darkcolor=BORDER, padding=(6, 4))
        style.map("TEntry", bordercolor=[("focus", a["main"])], lightcolor=[("focus", a["main"])])
        style.configure("Bad.TEntry", fieldbackground="#fef2f2", bordercolor=ERROR, lightcolor=ERROR,
                        darkcolor=ERROR)
        style.configure("TCombobox", fieldbackground=FIELD, background=FIELD, foreground=TEXT, bordercolor=BORDER,
                        lightcolor=BORDER, darkcolor=BORDER, arrowcolor=MUTED, padding=(6, 3))
        style.map("TCombobox", fieldbackground=[("readonly", FIELD)], bordercolor=[("focus", a["main"])],
                  selectbackground=[("readonly", FIELD)], selectforeground=[("readonly", TEXT)])
        style.configure("Header.TButton", background=HEADER_2, foreground=HEADER_TEXT, borderwidth=0,
                        padding=(12, 6))
        style.map("Header.TButton", background=[("active", "#33416b"), ("pressed", "#3b4a78")])
        for orient in ("Vertical", "Horizontal"):
            style.configure(f"{orient}.TScrollbar", background=BORDER, troughcolor=CARD, borderwidth=0,
                            arrowcolor=MUTED, gripcount=0)
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=SUBTLE, foreground=MUTED, padding=(12, 5))
        style.map("TNotebook.Tab", background=[("selected", CARD)], foreground=[("selected", a["text"])])
    p = prefix
    style.configure(f"{p}TCheckbutton", background=CARD, foreground=TEXT)
    style.map(f"{p}TCheckbutton", background=[("active", CARD)],
              indicatorcolor=[("selected", a["main"]), ("!selected", FIELD)])
    style.configure(f"{p}TRadiobutton", background=CARD, foreground=TEXT)
    style.map(f"{p}TRadiobutton", background=[("active", CARD)],
              indicatorcolor=[("selected", a["main"]), ("!selected", FIELD)])
    style.configure(f"{p}Accent.TButton", background=a["main"], foreground=a.get("on", "white"), borderwidth=0,
                    focusthickness=0, padding=(16, 8), font=font(10, "bold"))
    style.map(f"{p}Accent.TButton", background=[("pressed", a["dark"]), ("active", a["dark"]),
                                                ("disabled", BORDER)])
    style.configure(f"{p}Ghost.TButton", background=CARD, foreground=a["text"], borderwidth=1, bordercolor=BORDER,
                    lightcolor=CARD, darkcolor=CARD, padding=(10, 7))
    style.map(f"{p}Ghost.TButton", background=[("active", a["soft"])], bordercolor=[("active", a["main"])])
    style.configure(f"{p}Small.TButton", background=CARD, foreground=MUTED, borderwidth=1, bordercolor=BORDER,
                    lightcolor=CARD, darkcolor=CARD, padding=(8, 3), font=font(9))
    style.map(f"{p}Small.TButton", background=[("active", a["soft"])], foreground=[("active", a["text"])])
    style.configure(f"{p}Treeview", background=CARD, fieldbackground=CARD, foreground=TEXT, rowheight=px(26),
                    borderwidth=0, font=font(10))
    style.map(f"{p}Treeview", background=[("selected", a["soft"])], foreground=[("selected", a["text"])])
    style.configure(f"{p}Treeview.Heading", background=SUBTLE, foreground=MUTED, relief="flat", borderwidth=0,
                    font=font(9, "bold"), padding=(4, 5))
    style.map(f"{p}Treeview.Heading", background=[("active", a["soft"])])
    style.configure(f"{p}Horizontal.TProgressbar", background=a["main"], troughcolor=CHIP, borderwidth=0,
                    lightcolor=a["main"], darkcolor=a["main"])
    return a


def setup_all(style, keys):
    setup_ttk(style, None, "")
    setup_ttk(style, None, "Neutral.")
    for k in keys:
        setup_ttk(style, k, f"{k}.")
