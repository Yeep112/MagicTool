"""一鍵匯出 PPT：沿用「樣品製程報告」模板的版面（深靛藍封面、淡紫卡片、彩色流程節點、分段剖面插圖）。

頁面（每一種都可以在匯出視窗勾選）
  cover 封面（剖面示意 + 報告人）、summary 樣品總覽（最終 OM、基本資料、三個數字、一句話摘要）、
  flow 製程流程（每一步一個彩色節點，依「輪」分行）、steps 步驟頁（分段剖面插圖 + OM 照片 + 參數 / 備註；
  有 RIE / 離子研磨的 contact 用「開窗 → RIE → 離子研磨 → 鍍膜」分段頁）、afm AFM 厚度（長條圖）、
  measure 電性量測（大數字）、discussion 結果 / 問題 / 下一步、appendix 附錄（試算表原文與解讀對照）、
  compare 多樣品比較（兩顆以上）、timeline 製程總覽表（選用）
每顆樣品的模板存在紀錄檔 rec["ppt"]：title、subtitle、reporter、headline（總覽標題一句話）、story（摘要）、
  results / problems / next（三欄的條列）、skip_steps、step_notes、include
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import time

from . import folders as F
from . import sheet as SH
from . import steps as K
from . import visual as V
from .pptx_writer import Deck

SECTIONS = [("cover", "封面", "Cover"), ("summary", "樣品總覽", "Overview"), ("flow", "製程流程", "Process flow"),
            ("steps", "步驟頁（插圖、照片、參數）", "Step pages"), ("afm", "AFM 厚度", "AFM thickness"),
            ("measure", "電性量測", "Measurement"), ("discussion", "結果、問題與下一步", "Results & next steps"),
            ("appendix", "附錄：試算表原文", "Appendix"), ("compare", "多樣品比較", "Comparison"),
            ("timeline", "製程總覽表", "Process table")]
DEFAULT_ON = {"cover", "summary", "flow", "steps", "afm", "measure", "discussion", "appendix", "compare"}
LANGS = [("zh", "中文"), ("en", "English"), ("both", "中英並列")]
# 模板的顏色
DK, TXT, MUT, LT, PUR, GOLD, TEAL, CORAL, BLUE, LINE = ("231E57", "1C1B33", "7C8BA1", "F4F3FB", "5B4FCF", "D9A21B",
                                                       "1FA79A", "E8664F", "9ED3EE", "E4E1F5")
CAT = {"stack": TEAL, "litho": GOLD, "etch": CORAL, "meas": PUR, "other": MUT}
L = {
    "report": ("樣品製程報告", "Fabrication report"), "compare": ("樣品比較", "Sample comparison"),
    "overview": ("樣品總覽", "Overview"), "flow": ("製程流程", "Process flow"), "step": ("步驟", "Step"),
    "afm": ("AFM 厚度", "AFM thickness"), "measure": ("電性量測", "Measurement"),
    "discuss": ("結果、問題與下一步", "Results, issues & next steps"),
    "appendix": ("附錄：試算表製程紀錄", "Appendix: sheet record"),
    "timeline": ("製程總覽", "Process overview"), "label": ("樣品編號", "Sample"), "type": ("類型", "Type"),
    "start": ("開始", "Start"), "done": ("完成量測", "Measured"), "last": ("最近一步", "Latest step"),
    "state": ("狀態", "Status"), "thick": ("厚度（AFM）", "Thickness (AFM)"), "params": ("參數", "Parameters"),
    "notes": ("備註", "Notes"), "date": ("日期", "Date"), "key": ("重點", "Key point"),
    "res": ("目前結果", "Results"), "prob": ("遇到的問題", "Issues"), "next": ("下一步", "Next steps"),
    "cs_caption": ("元件剖面示意（軟體依製程步驟自動產生）", "Device cross-section (generated from the process steps)"),
    "reporter": ("報告人", "Presenter"), "nophoto": ("（這一步的資料夾裡沒有照片）", "(no photos in this step's folder)"),
    "final_om": ("最終元件 OM 照片", "Final device (OM)"), "n_steps": ("製程步驟", "Process steps"),
    "n_photos": ("張照片", "Photos"), "n_contact": ("次電極製作", "Contact rounds"),
    "rec_steps": ("紀錄裡的步驟", "in the record"), "rec_photos": ("各步驟資料夾", "in step folders"),
    "rec_contact": ("marker 不算", "excluding marker"), "how": ("怎麼來的", "Where the numbers come from"),
    "fill_hint": ("（還沒有填：在「📤 匯出 PPT」視窗的模板裡寫）", "(not filled in yet)"),
    "discuss_foot": ("這一頁的內容在「📤 匯出 PPT」視窗填寫，下次匯出沿用", "Edit these in the export dialog"),
    "raw": ("原始紀錄", "Original text"), "meaning": ("解讀（軟體自動整理）", "Interpretation"), "cat": ("類別", "Category"),
    "data": ("資料", "Data"), "analysis": ("分析", "Analysis"), "mdate": ("量測日", "Measured on"),
    "cond": ("條件", "Conditions"), "sample": ("樣品", "Sample"), "content": ("內容", "Details"),
    "metal": ("Contact 金屬", "Contact metals"),
    "rt_ph": ("R–T 圖（PPMS）\n把 Magic Tool 存的圖放進量測資料夾，就會自動帶入",
              "R–T plot\nPut the exported figure in the measurement folder"),
}


def tr(key, lang):
    zh, en = L[key]
    return zh if lang == "zh" else en if lang == "en" else f"{zh} {en}"


def step_label(st, lang):
    if lang == "both":
        zh, en = K.step_name(st, "zh"), K.step_name(st, "en")
        return zh if zh == en else f"{zh} {en}"
    return K.step_name(st, "en" if lang == "en" else "zh")


def _l(lang):
    return "en" if lang == "en" else "zh"


def _date(a, b=""):
    a = (a or "").replace("-", "/")
    b = (b or "").replace("-", "/")
    return f"{a} – {b[5:] if b[:4] == a[:4] else b}" if b and b != a else a


def template(rec):
    t = dict(rec.get("ppt") or {})
    for k in ("title", "subtitle", "reporter", "headline", "story"):
        t.setdefault(k, "")
    for k in ("results", "problems", "next", "skip_steps"):
        t.setdefault(k, [])
    t.setdefault("include", {})
    t.setdefault("step_notes", {})
    return t


SKIP_KINDS = ("design", "cleaning", "bonding", "analysis", "afm", "measurement")


def default_skip(rec, sample_dir=""):
    """預設不放成一頁的步驟：設計、清潔、打線、分析、AFM（有 AFM 頁）、量測（有量測頁），而且沒有寫說明。"""
    return [st["id"] for st in rec.get("steps", []) if st.get("kind") in SKIP_KINDS and not st.get("notes")]


# ---------------------------------------------------------------------------
# 照片
# ---------------------------------------------------------------------------
def folder_photos(sample_dir, rec, folders):
    out = []
    for fname in folders or []:
        info = F.scan_folder(os.path.join(sample_dir, fname), rec.get("start", ""))
        out += [p for p in info["images"] if not F.is_cloud_only(p)]
    return out


def step_photos(sample_dir, rec, st, limit=4):
    if not sample_dir:
        return []
    folders = list(st.get("folders") or [])
    for sub in st.get("substeps") or []:
        folders += [f for f in sub.get("folders") or [] if f not in folders]
    out = folder_photos(sample_dir, rec, folders)
    if len(out) > limit:
        step = (len(out) - 1) / (limit - 1)
        out = [out[round(i * step)] for i in range(limit)]
    return out


def shrink(path, tmp, max_px=1400):
    try:
        from PIL import Image
    except ImportError:
        return path if os.path.getsize(path) < 6_000_000 and path.lower().endswith((".png", ".jpg", ".jpeg")) else None
    try:
        with Image.open(path) as im:
            im.draft("RGB", (max_px, max_px))
            im = im.convert("RGB")
            im.thumbnail((max_px, max_px))
            out = os.path.join(tmp, f"photo_{abs(hash(path)) % 10**10}.jpg")
            im.save(out, "JPEG", quality=85)
            return out
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 從紀錄整理出來的數字
# ---------------------------------------------------------------------------
_PAIR = re.compile(r"([A-Za-z][A-Za-z0-9]*)\s*_\s*([\d]+(?:\.\d+)?)")
_MATS = set(V.TOP_ALIASES) | set(K.MATERIAL_COLORS) | {"nbs2", "tase2", "ws2", "mose2", "cri3", "fgt", "pt", "ta2"}


def afm_values(rec, sample_dir=""):
    """[(材料, 厚度 nm, 來源)]：步驟參數（hBN 厚度）+ AFM 資料夾照片檔名（「hBN_48.5, Ta_14.8」）。"""
    out, seen = [], set()
    for st in rec.get("steps", []):
        if st.get("kind") != "afm":
            continue
        nos = [f.split(" ", 1)[0] for f in st.get("folders") or []]
        src = (" + ".join(nos) + " AFM") if nos else K.step_name(st)
        vals = []
        if (st.get("params") or {}).get("hbn_nm") is not None:
            vals.append(("hBN", float(st["params"]["hbn_nm"])))
        if sample_dir:
            for fname in st.get("folders") or []:
                for p in F.scan_folder(os.path.join(sample_dir, fname))["images"]:
                    for m, v in _PAIR.findall(os.path.splitext(os.path.basename(p))[0]):
                        if m.lower() not in _MATS:                 # 只認材料名稱（Z Height_2 這種不算）
                            continue
                        vals.append((V.TOP_ALIASES.get(m.lower(), m), float(v)))
        for m, v in vals:
            key = (m.lower(), round(v, 3))
            if key not in seen:
                seen.add(key)
                out.append((m, v, src))
    return out


def result_headline(rec):
    """最重要的一句結果：R_1700 (SC)；沒有電阻 → Tc 4.2 K；都沒有 → 空白。"""
    res = rec.get("results") or {}
    if res.get("r_ohm") is not None:
        return f"R_{res['r_ohm']:g}" + (" (SC)" if res.get("sc_contact") else "")
    if res.get("tc_k") is not None:
        return f"Tc {res['tc_k']:g} K"
    return ""


def _results_rows(rec, lang):
    res = rec.get("results") or {}
    en = lang == "en"
    rows = []
    if res.get("r_ohm") is not None:
        rows.append(("Low-T R" if en else "低溫電阻", f"{res['r_ohm']:g} Ω"))
    if res.get("sc_contact") is not None:
        v = ("Yes" if en else "是") if res["sc_contact"] else ("No" if en else "否")
        rows.append(("SC contact" if en else "超導 contact", v + (f"（on {res['sc_on']}）" if res.get("sc_on") else "")))
    if res.get("tc_k") is not None:
        rows.append(("Tc", f"{res['tc_k']:g} K"))
    return rows


def _metals(rec):
    out = []
    for st in rec.get("steps", []):
        if st.get("kind") == "contact":
            for sub in st.get("substeps") or []:
                ly = (sub.get("params") or {}).get("layers")
                if sub.get("kind") == "deposit" and ly:
                    out.append(K.format_layers(ly) + (f" ({sub['params']['method']})" if sub["params"].get("method") else ""))
    return " → ".join(out)


def _state(rec, lang):
    st = (rec.get("status") or {}).get("state", "active")
    if lang == "both":
        return f"{K.state_label(st)} {K.state_label(st, 'en')}"
    return K.state_label(st, _l(lang))


def _material(rec):
    m = K.stack_from_type(rec.get("type", ""))[1][0]
    return "" if m == "sample" else m


def folder_no(st):
    nums = [f.split(" ", 1)[0] for f in st.get("folders") or [] if re.match(r"\d", f)]
    if not nums:
        return ""
    return nums[0] if len(nums) == 1 else f"{nums[0]}–{nums[-1]}"


def rounds(steps):
    """依「輪」分組：電極做過之後又轉移 / 蓋 hBN = 新的一輪。"""
    out, cur, seen_contact = [], [], False
    for i, st in enumerate(steps):
        if st.get("kind") in ("transfer", "cover") and seen_contact and cur:
            out.append(cur)
            cur, seen_contact = [], False
        cur.append(i)
        if st.get("kind") == "contact":
            seen_contact = True
    if cur:
        out.append(cur)
    return out


# ---------------------------------------------------------------------------
# 版面元件
# ---------------------------------------------------------------------------
class Builder:
    def __init__(self, lang="zh", title=""):
        self.lang = lang
        self.deck = Deck(title=title)
        self.page = 0
        self.footer = ""
        self.tmp = ""

    def content(self, title, outline=""):
        s = self.deck.slide(outline or title)
        self.page += 1
        s.text(0.6, 0.36, 12.1, 0.72, title, size=26, bold=True, color=DK, anchor="m", autofit=False, inset=0)
        s.text(0.6, 7.05, 8, 0.28, self.footer, size=8, color=MUT, autofit=False, inset=0)
        s.text(11.73, 7.05, 1.0, 0.28, str(self.page + 1), size=8, color=MUT, align="r", autofit=False, inset=0)
        return s

    def card(self, s, x, y, w, h, fill=LT, line=None):
        s.rect(x, y, w, h, fill=fill, line=line, radius=0.04)

    def kv(self, s, x, y, w, rows, key_w=1.55, gap=0.42, size=10.5):
        for i, (k, v) in enumerate(rows):
            s.text(x, y + i * gap, key_w, gap, k, size=size - 1, color=MUT, autofit=False, anchor="m", inset=0)
            s.text(x + key_w, y + i * gap, w - key_w, gap, v, size=size, bold=True, color=TXT, autofit=False, anchor="m",
                   inset=0)
        return y + len(rows) * gap

    def photo(self, s, x, y, w, h, path, title, sub=""):
        """照片卡：有照片 → 照片 + 底下說明；沒有照片 → 虛線框（和模板一樣）。"""
        img = shrink(path, self.tmp) if path else None
        if img:
            self.card(s, x, y, w, h)
            try:
                s.image(img, x + 0.1, y + 0.1, w - 0.2, h - (0.62 if sub else 0.42))
            except ValueError:
                img = None
        if not img:
            s.rect(x, y, w, h, fill=LT, line="A9A3D9", radius=0.03, dash=True)
            s.text(x, y + h / 2 - 0.62, w, 0.42, "▣", size=20, color=MUT, align="c", autofit=False, inset=0)
        ty = y + h - (0.52 if sub else 0.32) if img else y + h / 2 - 0.08
        s.text(x + 0.1, ty, w - 0.2, 0.26, title, size=9.5, bold=True, color=DK, align="c", autofit=False, inset=0)
        if sub:
            s.text(x + 0.1, ty + 0.25, w - 0.2, 0.24, sub, size=7.5, color=MUT, align="c", autofit=False, inset=0)

    def num_dot(self, s, x, y, n, fill=CORAL, d=0.42, size=11):
        s.text(x, y, d, d, str(n), size=size, bold=True, color="FFFFFF", fill=fill, ellipse=True, align="c", anchor="m",
               inset=0, autofit=False)

    def bullets(self, s, x, y, w, h, items, size=11, hint=""):
        if items:
            s.text(x, y, w, h, [f"•  {t}" for t in items], size=size, color=TXT, spacing=5)
        else:
            s.text(x, y, w, h, hint, size=size - 1, color=MUT)


# ---------------------------------------------------------------------------
# 各頁
# ---------------------------------------------------------------------------
def slide_cover(b, items, deck_title, deck_sub, reporter):
    lang = b.lang
    s = b.deck.slide(deck_title)
    s.bg = DK
    multi = len(items) > 1
    tw = 12.0 if multi else 6.7
    s.text(0.6, 1.6, tw, 1.75, deck_title, size=32, bold=True, color="FFFFFF", anchor="b", autofit=False, inset=0)
    s.text(0.6, 3.45, tw, 0.9, deck_sub, size=13, color="B8B3F0", autofit=False, inset=0)
    if multi:
        x, y = 0.6, 4.45
        for it in items[:12]:
            rec = it["rec"]
            stt = (rec.get("status") or {}).get("state", "active")
            col = K.STATES.get(stt, K.STATES["active"])[2].lstrip("#")
            txt = f"{rec.get('label')} · {_state(rec, lang)}"
            w = 0.5 + 0.11 * len(txt)
            if x + w > 12.7:
                x, y = 0.6, y + 0.45
            s.text(x, y, w, 0.34, txt, size=10, bold=True, color="FFFFFF", fill=col, radius=0.5, align="c", anchor="m",
                   inset=0.02, autofit=False)
            x += w + 0.12
    else:
        it = items[0]
        s.rect(7.55, 1.35, 5.2, 4.8, fill="FFFFFF", radius=0.04)
        img, mats = V.render_clean(os.path.join(b.tmp, "cover.png"), it["rec"], it["outlines"], None, V.PPT_COLORS,
                                   size=(4.6, 2.9))
        s.image(img, 7.85, 1.6, 4.6, 3.1)
        x = 7.85
        for m in (mats + ["SiO2", "Si"])[:7]:
            s.rect(x, 4.92, 0.16, 0.16, fill=V.color_of(m, V.PPT_COLORS).lstrip("#"), radius=0.1)
            s.text(x + 0.2, 4.84, 0.8, 0.3, m, size=8.5, color=TXT, autofit=False, inset=0, anchor="m")
            x += 0.42 + 0.075 * len(m)
        s.text(7.85, 5.35, 4.6, 0.3, tr("cs_caption", lang), size=8.5, color=MUT, autofit=False, inset=0)
    s.text(0.6, 6.4, 8, 0.36, f"{tr('reporter', lang)}　{reporter or '（姓名）'}　|　{'Date' if lang == 'en' else '日期'}"
           f"　{time.strftime('%Y/%m/%d')}", size=10, color="B8B3F0", autofit=False, inset=0)


def slide_summary(b, it):
    rec, lang, tpl = it["rec"], b.lang, it["tpl"]
    steps = rec.get("steps", [])
    dates = sorted(d for x in steps for d in (x.get("date"), x.get("date_end")) if d)
    measured = (rec.get("status") or {}).get("state") == "measured"
    head = tpl["headline"]
    if not head:
        head = f"{len(steps)} steps" if lang == "en" else f"{len(steps)} 個步驟"
        if dates and rec.get("start") and lang != "en":
            from datetime import date as _d
            try:
                days = (_d.fromisoformat(dates[-1]) - _d.fromisoformat(rec["start"])).days
                head += f"，{days} 天" + ("完成量測" if measured else "")
            except ValueError:
                pass
    s = b.content(f"{tr('overview', lang)}：{head}")
    final, src = None, ""
    for st in reversed(steps):                          # 最後一個有照片的步驟的最後一張
        if st.get("kind") in ("analysis", "design", "measurement"):
            continue
        ph = folder_photos(it["dir"], rec, st.get("folders")) if it["dir"] else []
        if ph:
            final, src = ph[-1], (st.get("folders") or [""])[-1]
            break
    b.photo(s, 0.6, 1.33, 6.07, 4.42, final, tr("final_om", lang),
            ((f"自動帶入：{src} 的最後一張" if lang != "en" else f"from {src}") if final else
             ("資料夾裡還沒有照片" if lang != "en" else "no photo yet")))
    b.card(s, 7.05, 1.33, 5.7, 2.92)
    afm = afm_values(rec, it["dir"])
    last = steps[-1] if steps else None
    rows = [(tr("label", lang), str(rec.get("label"))), (tr("type", lang), rec.get("type") or "—"),
            (tr("start", lang), (rec.get("start") or "—").replace("-", "/")),
            ((tr("done", lang), dates[-1].replace("-", "/")) if measured and dates else
             (tr("last", lang), f"{step_label(last, lang)}　{_date(last.get('date'))}" if last else "—")),
            (tr("state", lang), result_headline(rec) or _state(rec, lang)),
            (tr("thick", lang), "、".join(f"{m} {v:g} nm" for m, v, _ in afm[:3]) or "—")]
    b.kv(s, 7.35, 1.48, 5.2, rows, key_w=1.45, gap=0.43)
    n_photo = 0
    if it["dir"]:
        for st in steps:
            n_photo += len(folder_photos(it["dir"], rec, st.get("folders")))
    stats = [(len(steps), tr("n_steps", lang), tr("rec_steps", lang), PUR),
             (n_photo, tr("n_photos", lang), tr("rec_photos", lang), TEAL),
             (sum(1 for x in steps if x.get("kind") == "contact"), tr("n_contact", lang), tr("rec_contact", lang), GOLD)]
    for i, (n, lab, sub, col) in enumerate(stats):
        x = 7.05 + i * 1.93
        b.card(s, x, 4.43, 1.84, 1.32, fill="FFFFFF", line=LINE)
        s.text(x + 0.15, 4.5, 1.6, 0.55, str(n), size=26, bold=True, color=col, autofit=False, inset=0, anchor="m")
        s.text(x + 0.15, 5.05, 1.6, 0.3, lab, size=10, bold=True, color=TXT, autofit=False, inset=0)
        s.text(x + 0.15, 5.35, 1.6, 0.28, sub, size=7.5, color=MUT, autofit=False, inset=0)
    story = tpl["story"]
    if not story:
        stt = rec.get("status") or {}
        parts = [f"{(rec.get('start') or '').replace('-', '/')} 開始" if rec.get("start") and lang != "en" else ""]
        if last:
            dt = _date(last.get("date"))
            parts.append(f"最近一步：{step_label(last, lang)}" + (f"（{dt}）" if dt else "") if lang != "en" else
                         f"latest: {step_label(last, lang)}")
        res = _results_rows(rec, lang)
        if res:
            parts.append("、".join(f"{k} {v}" for k, v in res))
        elif stt.get("next"):
            parts.append(f"下一步：{stt['next']}" if lang != "en" else f"next: {stt['next']}")
        story = "；".join(p for p in parts if p) + ("。" if lang != "en" else "")
    s.text(0.6, 5.95, 12.1, 0.7, story, size=12, color=TXT, autofit=False, inset=0)


def slide_flow(b, it):
    rec, lang = it["rec"], b.lang
    steps = rec.get("steps", [])
    if not steps:
        return
    s = b.content(f"{tr('flow', lang)}：{len(steps)} " + ("stages" if lang == "en" else "個階段一覽"))
    groups = rounds(steps)
    per = 10
    rows = sum((len(g) + per - 1) // per for g in groups)
    if rows > 3:
        per = 12
        rows = sum((len(g) + per - 1) // per for g in groups)
    sp = 12.1 / per
    d = min(0.73, sp * 0.6)
    row_h = min(1.45, (5.05 - (0.34 * len(groups) if len(groups) > 1 else 0)) / max(1, rows))
    y = 1.2
    for gi, g in enumerate(groups):
        if len(groups) > 1:
            s.text(0.6, y, 8, 0.3, f"Round {gi + 1}" if lang == "en" else f"第{'一二三四五六七八'[min(gi, 7)]}輪", size=11,
                   bold=True, color=TXT, autofit=False, inset=0)
            y += 0.34
        for r0 in range(0, len(g), per):
            cy = y + 0.05
            for j, idx in enumerate(g[r0:r0 + per]):
                st = steps[idx]
                cx = 0.6 + j * sp + (sp - d) / 2
                if j:
                    s.line(cx - (sp - d) + 0.04, cy + d / 2, cx - 0.04, cy + d / 2, color="C9C4E8", width=1.0, dash=True)
                col = CAT.get(K.category(st["kind"]), MUT)
                s.text(cx, cy, d, d, folder_no(st).split("–")[0] or str(idx + 1), size=11 if d > 0.6 else 9, bold=True,
                       color="FFFFFF", fill=col, ellipse=True, align="c", anchor="m", inset=0, autofit=False)
                s.text(0.6 + j * sp, cy + d + 0.06, sp, 0.3, step_label(st, "en" if lang == "en" else "zh"),
                       size=9.5 if per == 10 else 8.5, bold=True, color=TXT, align="c", autofit=False, inset=0)
                dt = (st.get("date") or "")[5:].replace("-", "/") or "—"
                s.text(0.6 + j * sp, cy + d + 0.36, sp, 0.26, dt, size=8, color=MUT, align="c", autofit=False, inset=0)
            y += row_h
    x = 0.6
    for c, (zh, en, _) in K.CATEGORIES.items():
        s.rect(x, 6.55, 0.14, 0.14, fill=CAT[c], ellipse=True)
        s.text(x + 0.2, 6.47, 2.3, 0.3, en if lang == "en" else zh, size=8.5, color=TXT, autofit=False, inset=0,
               anchor="m")
        x += 2.42


def _note(it, st):
    note = (it["tpl"]["step_notes"].get(st["id"]) or "").strip()
    if st.get("notes"):
        note = (note + "\n" + st["notes"]).strip() if note else st["notes"]
    return note


def _param_rows(st, lang):
    ll = _l(lang)
    rows = []
    if st.get("date"):
        rows.append((tr("date", lang), _date(st.get("date"), st.get("date_end"))))
    rows += K.params_text(st["kind"], st.get("params"), ll)
    for sub in st.get("substeps") or []:
        pr = K.params_text(sub["kind"], sub.get("params"), ll)
        if not pr:
            continue
        if sub["kind"] == "deposit":
            rows += pr
        else:
            rows.append((K.label(sub["kind"], ll), "　".join(f"{a} {v}" for a, v in pr)))
    return rows


def _stage_images(b, it, idx, stages):
    paths = [os.path.join(b.tmp, f"stage_{abs(hash(str(it['rec'].get('label')))) % 10**8}_{idx}_{k}.png")
             for k in range(len(stages))]
    V.render_stages(paths, stages, V.PPT_COLORS, size=(2.6, 1.75))
    return paths


CIRCLED = "①②③④⑤⑥⑦⑧"
SPIN = ("旋塗光阻", "Spin-coat resist")


def slide_step(b, it, idx):
    rec, lang = it["rec"], b.lang
    st = rec["steps"][idx]
    kind = st["kind"]
    stages = V.stage_sections(rec, idx, it["outlines"], _l(lang))
    etchy = any(x["kind"] in ("rie", "icp", "ion_mill") for x in st.get("substeps") or [])
    no = folder_no(st)
    prefix = f"{tr('step', lang)} {no}　" if no else f"{idx + 1}. "
    note = _note(it, st)
    photos = step_photos(it["dir"], rec, st, 4)
    if kind in K.GROUP_KINDS and etchy and stages:
        # 模板第 5 頁：開窗 → RIE → 離子研磨 → 鍍膜（+ lift-off）
        keep = [x for x in stages if x["label"] not in SPIN + ("Lift-off",)]
        lift = next(x for x in stages if x["label"] == "Lift-off")
        dep_i = next((i for i, x in enumerate(keep) if x["label"].startswith(("鍍 ", "Deposit"))), None)
        if dep_i is not None:
            metal = keep[dep_i]["label"].replace("鍍 ", "").replace("Deposit ", "")
            keep[dep_i] = dict(keep[dep_i], sec=lift["sec"], arrows=[],
                               label=metal + (" + lift-off" if lang == "en" else " 鍍膜 + lift-off"), short=metal)
        keep[0] = dict(keep[0], label="Open window (litho)" if lang == "en" else "開窗（微影）",
                       short="Open window" if lang == "en" else "開窗")
        title = prefix + f"{step_label(st, lang)}：" + " → ".join(x.get("short") or x["label"] for x in keep)
        s = b.content(title, step_label(st, lang))
        imgs = _stage_images(b, it, idx, keep)
        n = len(keep)
        w = (12.13 - 0.17 * (n - 1)) / n
        bottom = bool(note or photos)
        ph = 4.15 if bottom else 5.3
        for k, (x_, img) in enumerate(zip(keep, imgs)):
            x = 0.6 + k * (w + 0.17)
            b.card(s, x, 1.3, w, ph)
            b.num_dot(s, x + 0.15, 1.45, k + 1)
            s.text(x + 0.65, 1.45, w - 0.75, 0.42, x_["label"], size=10.5, bold=True, color=TXT, anchor="m",
                   autofit=False, inset=0)
            s.image(img, x + 0.15, 2.0, w - 0.3, 1.9 if bottom else 2.6)
            s.text(x + 0.15, 4.0 if bottom else 4.75, w - 0.3, 1.2, x_.get("text") or "", size=9, color=TXT,
                   autofit=False, inset=0)
        if bottom:
            y0 = 5.62
            pw = 0
            if photos:
                n_ph = min(len(photos), 3 if note else 6)
                pw = 1.75 * n_ph + 0.12 * (n_ph - 1)
                for k, p in enumerate(photos[:n_ph]):
                    b.photo(s, 12.73 - pw + k * 1.87, y0, 1.75, 1.3, p, os.path.basename(p)[:20])
            if note:
                wn = 12.13 - pw - (0.17 if pw else 0)
                b.card(s, 0.6, y0, wn, 1.3)
                s.text(0.85, y0 + 0.14, 0.8, 0.35, tr("key", lang), size=10.5, bold=True, color=DK, autofit=False,
                       inset=0)
                s.text(1.6, y0 + 0.14, wn - 1.2, 1.05, note, size=10.5, color=TXT, autofit=False, inset=0)
        return
    # 模板第 4 頁：上 = 分段插圖、下 = OM 照片、右 = 參數與備註
    if kind in K.GROUP_KINDS and stages:
        metals = "/".join(m for m, _ in V._metal_layers(st, []))
        title = prefix + step_label(st, lang) + ((f"：{metals} deposition" if lang == "en" else f"：{metals} 鍍膜")
                                                 if metals else "")
    else:
        title = prefix + step_label(st, lang)
    s = b.content(title, step_label(st, lang))
    left_w = 8.2
    if stages:
        if len(stages) > 4:
            stages = [x for x in stages if x["label"] not in SPIN][:4]
        imgs = _stage_images(b, it, idx, stages)
        n = len(stages)
        w = (left_w - 0.12 * (n - 1)) / n
        for k, (x_, img) in enumerate(zip(stages, imgs)):
            x = 0.6 + k * (w + 0.12)
            b.card(s, x, 1.33, w, 2.27)
            s.image(img, x + 0.1, 1.42, w - 0.2, 1.65)
            s.text(x + 0.12, 3.15, w - 0.2, 0.36, f"{CIRCLED[k]} {x_['label']}", size=9.5, bold=True, color=TXT,
                   autofit=False, inset=0, anchor="m")
        py, phh = 3.78, 3.22
    else:
        py, phh = 1.33, 5.67
    cards = []
    if kind in K.GROUP_KINDS or kind == "litho_group":     # 微影組：顯影後 / 鍍完 各一張
        for sub in st.get("substeps") or []:
            if sub["kind"] in ("lithography", "liftoff") and sub.get("folders"):
                ph = folder_photos(it["dir"], rec, sub["folders"]) if it["dir"] else []
                if lang == "en":
                    cap = "After development" if sub["kind"] == "lithography" else "After lift-off"
                else:
                    cap = "顯影後 OM" if sub["kind"] == "lithography" else "Lift-off 後 OM"
                cards.append((ph[-1] if ph else None, sub["folders"][0], cap + ("" if ph else "（沒有照片）")))
    if not cards:
        n_ph = 2 if stages else 4
        cards = [(p, os.path.basename(os.path.dirname(p)), os.path.basename(p)) for p in photos[:n_ph]]
    if not cards:
        cards = [(None, tr("nophoto", lang), "")]
    n = len(cards)
    cols = n if stages or n <= 2 else 2
    rws = (n + cols - 1) // cols
    cw, ch = (left_w - 0.15 * (cols - 1)) / cols, (phh - 0.15 * (rws - 1)) / rws
    for k, (p, t1, t2) in enumerate(cards):
        r, c = divmod(k, cols)
        b.photo(s, 0.6 + c * (cw + 0.15), py + r * (ch + 0.15), cw, ch, p, t1, t2)
    b.card(s, 9.0, 1.33, 3.75, 5.67, fill="FFFFFF", line=LINE)
    s.text(9.25, 1.5, 3.3, 0.35, tr("params", lang), size=12, bold=True, color=CORAL, autofit=False, inset=0)
    rows = _param_rows(st, lang) or [("—", "")]
    y = b.kv(s, 9.25, 1.95, 3.3, rows[:9], key_w=1.05, gap=0.4, size=10)
    s.text(9.25, y + 0.2, 3.3, 0.35, tr("notes", lang), size=11, bold=True, color=DK, autofit=False, inset=0)
    s.text(9.25, y + 0.58, 3.3, max(0.6, 6.85 - y - 0.6), note or ("—" if lang == "en" else "（可以在匯出視窗寫）"),
           size=10, color=TXT if note else MUT)


def slide_afm(b, it):
    rec, lang = it["rec"], b.lang
    vals = afm_values(rec, it["dir"])
    if not vals:
        return
    s = b.content(f"{tr('afm', lang)}：" + "、".join(f"{m} {v:g} nm" for m, v, _ in vals[:2]))
    x0, y0, w, h = 1.15, 1.95, 6.4, 3.95
    s.text(0.6, 1.35, 7.25, 0.35, "Thickness (nm)" if lang == "en" else "各層厚度（nm）", size=11, color=TXT, align="c",
           autofit=False, inset=0)
    top = max(v for _, v, _ in vals)
    step = next((st for st in (1, 2, 5, 10, 20, 25, 50, 100, 200, 500) if top * 1.2 / st <= 8), 1000)
    ymax = step * (int(top * 1.2 / step) + 1)
    for k in range(int(ymax / step) + 1):
        yy = y0 + h - h * k * step / ymax
        s.line(x0, yy, x0 + w, yy, color="EEEDF7", width=0.75)
        s.text(x0 - 0.5, yy - 0.12, 0.42, 0.24, f"{k * step:g}", size=7.5, color=MUT, align="r", autofit=False, inset=0)
    s.line(x0, y0 + h, x0 + w, y0 + h, color=MUT, width=1)
    n = min(len(vals), 8)
    bw = w / n
    for k, (m, v, src) in enumerate(vals[:n]):
        bh = h * v / ymax
        col = BLUE if "hbn" in m.lower() else TEAL if "tas2" in m.lower() or k == 1 else PUR
        s.rect(x0 + k * bw + bw * 0.2, y0 + h - bh, bw * 0.6, bh, fill=col)
        s.text(x0 + k * bw, y0 + h - bh - 0.3, bw, 0.28, f"{v:g} nm", size=9, color=TXT, align="c", autofit=False,
               inset=0)
        s.text(x0 + k * bw, y0 + h + 0.08, bw, 0.5, f"{m}\n（{src}）", size=8.5, color=TXT, align="c", autofit=False,
               inset=0)
    afm = next((st for st in rec.get("steps", []) if st.get("kind") == "afm" and st.get("folders")), None)
    img, cap = None, "AFM"
    if afm and it["dir"]:
        ph = folder_photos(it["dir"], rec, afm["folders"])
        pref = [p for p in ph if re.search(r"height|_z", os.path.basename(p), re.I)]
        img = (pref or ph or [None])[0]
        cap = f"{afm['folders'][0]} " + ("height map" if lang == "en" else "高度圖")
    b.photo(s, 7.55, 1.33, 5.2, 2.75, img, cap)
    b.card(s, 7.55, 4.25, 5.2, 1.95)
    s.text(7.8, 4.4, 4.7, 0.3, tr("how", lang), size=10.5, bold=True, color=DK, autofit=False, inset=0)
    s.text(7.8, 4.75, 4.7, 1.35, ("Read from AFM image file names (e.g. 'hBN_48.5, Ta_14.8') and the step parameters."
                                  if lang == "en" else
                                  "從 AFM 資料夾的照片檔名（例如「hBN_48.5, Ta_14.8」）和步驟裡填的 hBN 厚度自動讀出；"
                                  "也可以用 Magic Tool 的 AFM 台階分析直接算。"), size=9.5, color=TXT, autofit=False,
           inset=0)


def slide_measure(b, it):
    rec, lang = it["rec"], b.lang
    meas = [st for st in rec.get("steps", []) if st.get("kind") in ("measurement", "analysis")]
    res = _results_rows(rec, lang)
    if not meas and not res:
        return
    head = result_headline(rec)
    s = b.content(tr("measure", lang) + (f"：{head}" if head else ""))
    img, data, ana = None, [], ""
    if it["dir"]:
        for st in meas:
            ph = folder_photos(it["dir"], rec, st.get("folders"))
            pref = [p for p in ph if re.search(r"r[-_ ]?t|tc", os.path.basename(p), re.I)]
            img = img or (pref or ph or [None])[0]
            for fname in st.get("folders") or []:
                info = F.scan_folder(os.path.join(it["dir"], fname))
                data += [os.path.basename(p) for p in info["data"] if p.lower().endswith((".db", ".dat", ".csv"))]
                if st.get("kind") == "analysis":
                    ana = fname
    ph_t, ph_s = tr("rt_ph", lang).split("\n")[0], tr("rt_ph", lang).split("\n")[-1]
    b.photo(s, 0.6, 1.33, 7.3, 5.67, img, "R–T" if img else ph_t, "" if img else ph_s)
    b.card(s, 8.25, 1.33, 4.5, 2.25, fill=PUR)
    s.text(8.5, 1.45, 4.1, 0.9, head or _state(rec, lang), size=26, bold=True, color="FFFFFF", autofit=False, inset=0,
           anchor="m")
    src = (rec.get("results") or {}).get("source")
    s.text(8.5, 2.4, 4.1, 1.1, ["　".join(f"{k} {v}" for k, v in res) or ("no results yet" if lang == "en" else "還沒有填結果"),
                                (f"來源：{src}" if src else ("" if lang == "en" else
                                                            "Tc、低溫電阻可以從量測頁「📌 寫到樣品」帶入"))],
           size=9.5, color="DCD8FA", autofit=False, inset=0)
    b.card(s, 8.25, 3.75, 4.5, 3.25)
    mdate = next((st.get("date") for st in meas if st.get("date")), "")
    rows = [(tr("data", lang), "\n".join(data[:2]) or "—"), (tr("analysis", lang), ana or "—"),
            (tr("mdate", lang), mdate.replace("-", "/") or "—"),
            (tr("cond", lang), (rec.get("results") or {}).get("note") or ("—" if lang == "en" else "（溫度範圍、電流）"))]
    b.kv(s, 8.5, 3.95, 4.1, rows, key_w=1.0, gap=0.7, size=10)


def slide_discussion(b, it):
    rec, lang, tpl = it["rec"], b.lang, it["tpl"]
    s = b.content(tr("discuss", lang))
    res = tpl["results"] or [f"{k} {v}" for k, v in _results_rows(rec, lang)]
    st = rec.get("status") or {}
    nxt = list(tpl["next"])
    if not nxt:
        if st.get("next"):
            nxt = [st["next"] + (f"（{st['next_date'].replace('-', '/')}）" if st.get("next_date") else "")]
        elif st.get("state") == "hold" and st.get("reason"):
            nxt = [("On hold: " if lang == "en" else "擱置：") + st["reason"]]
    cols = [("res", TEAL, "✓", res), ("prob", CORAL, "!", tpl["problems"]), ("next", PUR, "»", nxt)]
    for i, (key, col, glyph, items) in enumerate(cols):
        x = 0.6 + i * 4.12
        b.card(s, x, 1.37, 3.89, 4.95)
        s.text(x + 0.3, 1.62, 0.58, 0.58, glyph, size=16, bold=True, color="FFFFFF", fill=col, ellipse=True, align="c",
               anchor="m", inset=0, autofit=False, font="Segoe UI Symbol" if glyph == "✓" else None)
        s.text(x + 1.05, 1.62, 2.7, 0.58, tr(key, lang), size=14, bold=True, color=DK, anchor="m", autofit=False, inset=0)
        b.bullets(s, x + 0.3, 2.45, 3.35, 3.7, items, size=11, hint=tr("fill_hint", lang))
    s.text(0.6, 6.45, 12, 0.3, tr("discuss_foot", lang), size=8, color=MUT, autofit=False, inset=0)


def _interpret(text, lang):
    kind, p = SH.classify(text)
    if kind in ("empty", "skip"):
        return ("skip" if lang == "en" else "跳過"), "other"
    if kind == "stop":
        return ("stopped here" if lang == "en" else "停在這裡"), "other"
    ll = _l(lang)
    pr = K.params_text(kind, p, ll)
    return K.label(kind, ll) + ("：" + "，".join(f"{a} {v}" for a, v in pr) if pr else ""), K.category(kind)


def _soft(hexcol, t=0.82):
    h = hexcol.lstrip("#")
    r, g, bb = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return "%02X%02X%02X" % tuple(int(c + (255 - c) * t) for c in (r, g, bb))


def slides_appendix(b, it):
    rec, lang = it["rec"], b.lang
    raw = (rec.get("sheet") or {}).get("process") or []
    if not raw:
        return
    rows, cats = [], []
    for i, t in enumerate(raw, start=1):
        meaning, cat = _interpret(t, lang)
        rows.append([str(i), t, meaning, K.CATEGORIES[cat][1 if lang == "en" else 0]])
        cats.append(cat)
    per = 13
    for k in range(0, len(rows), per):
        s = b.content(f"{tr('appendix', lang)}（Label {rec.get('label')}）" +
                      (f"（{k // per + 1}）" if len(rows) > per else ""))
        fills = {(ri, 3): _soft(CAT[c]) for ri, c in enumerate(cats[k:k + per], start=1)}
        s.table(0.6, 1.3, 12.13, [["#", tr("raw", lang), tr("meaning", lang), tr("cat", lang)]] + rows[k:k + per],
                col_w=[0.4, 3.6, 5.6, 1.8], size=9.5, header_fill=DK, stripe="FAFAFE", row_h=0.4, line="ECEAF6",
                fills=fills)


def slides_timeline(b, it):
    rec, lang = it["rec"], b.lang
    rows, kinds = [], []
    for i, st in enumerate(rec.get("steps", []), start=1):
        rows.append([folder_no(st) or str(i), step_label(st, lang), _date(st.get("date"), st.get("date_end")),
                     K.summary(st, _l(lang)) or "—"])
        kinds.append(st["kind"])
    for k in range(0, max(1, len(rows)), 13):
        s = b.content(f"{tr('timeline', lang)}（{rec.get('label')}）" + (f"（{k // 13 + 1}）" if len(rows) > 13 else ""))
        fills = {(ri, 1): _soft(CAT[K.category(kd)]) for ri, kd in enumerate(kinds[k:k + 13], start=1)}
        s.table(0.6, 1.3, 12.13, [["#", tr("step", lang), tr("date", lang), tr("content", lang)]] + rows[k:k + 13],
                col_w=[0.6, 2.4, 2.2, 6.9], size=10, header_fill=DK, stripe="FAFAFE", row_h=0.4, line="ECEAF6",
                fills=fills)


def slides_compare(b, items):
    lang = b.lang
    head = [tr("sample", lang), tr("type", lang), tr("start", lang), tr("state", lang), tr("n_steps", lang),
            tr("metal", lang), "R", "SC", "Tc"]
    rows = []
    for it in items:
        rec = it["rec"]
        res = rec.get("results") or {}
        rows.append([rec.get("label"), rec.get("type") or "", (rec.get("start") or "").replace("-", "/"),
                     _state(rec, lang), str(len(rec.get("steps", []))), _metals(rec),
                     f"{res['r_ohm']:g} Ω" if res.get("r_ohm") is not None else "",
                     (("Yes" if lang == "en" else "是") if res.get("sc_contact") else "") +
                     (f" {res['sc_on']}" if res.get("sc_on") else ""),
                     f"{res['tc_k']:g} K" if res.get("tc_k") is not None else ""])
    for k in range(0, len(rows), 12):
        s = b.content(tr("compare", lang) + (f"（{k // 12 + 1}）" if len(rows) > 12 else ""))
        s.table(0.6, 1.3, 12.13, [head] + rows[k:k + 12], col_w=[0.9, 1.4, 1.1, 1.2, 0.8, 3.2, 1.0, 1.0, 0.8],
                size=10, header_fill=DK, stripe="FAFAFE", row_h=0.42, line="ECEAF6")
    for k in range(0, len(items), 6):
        chunk = items[k:k + 6]
        s = b.content(f"{tr('compare', lang)}：" + ("cross-sections" if lang == "en" else "元件剖面"))
        cols = 3 if len(chunk) > 4 else 2
        rws = (len(chunk) + cols - 1) // cols
        cw, ch = (12.13 - 0.2 * (cols - 1)) / cols, (5.55 - 0.2 * (rws - 1)) / rws
        for n, it in enumerate(chunk):
            r, c = divmod(n, cols)
            x, y = 0.6 + c * (cw + 0.2), 1.33 + r * (ch + 0.2)
            b.card(s, x, y, cw, ch)
            img, _ = V.render_clean(os.path.join(b.tmp, f"cmp_{k + n}.png"), it["rec"], it["outlines"], None,
                                    V.PPT_COLORS, size=(4.4, 2.4))
            s.text(x + 0.2, y + 0.12, cw - 0.4, 0.32, f"{it['rec'].get('label')}　{it['rec'].get('type') or ''}",
                   size=11, bold=True, color=DK, autofit=False, inset=0)
            s.image(img, x + 0.2, y + 0.5, cw - 0.4, ch - 0.65)


def section_divider(b, it):
    rec = it["rec"]
    s = b.deck.slide(str(rec.get("label")))
    b.page += 1
    s.bg = DK
    s.text(0.6, 2.6, 12, 1.1, f"{tr('sample', b.lang)} {rec.get('label')}", size=36, bold=True, color="FFFFFF",
           anchor="b", autofit=False, inset=0)
    s.text(0.6, 3.75, 12, 0.6, " · ".join(x for x in (rec.get("type"), _state(rec, b.lang)) if x), size=15,
           color="B8B3F0", autofit=False, inset=0)


# ---------------------------------------------------------------------------
# 匯出
# ---------------------------------------------------------------------------
def export(items, path, lang="zh", sections=None, deck_title="", deck_sub="", log=None):
    """items = [{"rec", "dir", "outlines"}]。回傳 (路徑, 幾頁)。"""
    sections = set(sections if sections is not None else DEFAULT_ON)
    multi = len(items) > 1
    for it in items:
        it["tpl"] = template(it["rec"])
        if "skip_steps" not in (it["rec"].get("ppt") or {}):
            it["tpl"]["skip_steps"] = default_skip(it["rec"], it.get("dir"))
        it.setdefault("outlines", [])
        it.setdefault("dir", "")
    labels = "、".join(str(it["rec"].get("label")) for it in items)
    r0 = items[0]["rec"]
    if not deck_title:
        if multi:
            deck_title = f"{L['compare'][1] if lang == 'en' else L['compare'][0]}：{labels}"
        else:
            mat = _material(r0)
            deck_title = items[0]["tpl"]["title"] or (f"{mat} {r0.get('label')} " if mat else f"{r0.get('label')} ") + \
                (L["report"][1] if lang == "en" else L["report"][0])
    if not deck_sub:
        if not multi and items[0]["tpl"]["subtitle"]:
            deck_sub = items[0]["tpl"]["subtitle"]
        elif multi:
            deck_sub = f"{len(items)} " + ("samples" if lang == "en" else "顆樣品")
        else:
            dates = sorted(d for x in r0.get("steps", []) for d in (x.get("date"), x.get("date_end")) if d)
            head = result_headline(r0)
            span = _date(r0.get("start") or (dates[0] if dates else ""), dates[-1] if dates else "")
            deck_sub = " · ".join(x for x in (r0.get("type"), span,
                                              f"{'Status' if lang == 'en' else '狀態'} {head or _state(r0, lang)}") if x)
    reporter = next((it["tpl"]["reporter"] for it in items if it["tpl"]["reporter"]), "") or r0.get("user", "")
    b = Builder(lang, deck_title)
    b.tmp = tempfile.mkdtemp(prefix="magic_ppt_")
    try:
        if "cover" in sections:
            slide_cover(b, items, deck_title, deck_sub, reporter)
        if multi and "compare" in sections:
            slides_compare(b, items)
        for it in items:
            inc = {k: it["tpl"]["include"].get(k, k in sections) for k, _, _ in SECTIONS}
            mat = _material(it["rec"])
            b.footer = f"{mat + ' ' if mat else ''}{it['rec'].get('label')}　·　" + \
                ("fabrication record" if lang == "en" else "樣品製程紀錄")
            if multi:
                section_divider(b, it)
            if inc["summary"]:
                slide_summary(b, it)
            if inc["flow"]:
                slide_flow(b, it)
            if inc["timeline"]:
                slides_timeline(b, it)
            if inc["steps"]:
                for i, st in enumerate(it["rec"].get("steps", [])):
                    if st["id"] not in it["tpl"]["skip_steps"]:
                        slide_step(b, it, i)
                        if log:
                            log(f"{it['rec'].get('label')}：{step_label(st, lang)}")
            if inc["afm"]:
                slide_afm(b, it)
            if inc["measure"]:
                slide_measure(b, it)
            if inc["discussion"]:
                slide_discussion(b, it)
            if inc["appendix"]:
                slides_appendix(b, it)
        b.deck.save(path)
    finally:
        shutil.rmtree(b.tmp, ignore_errors=True)
    return path, len(b.deck.slides)
