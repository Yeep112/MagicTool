"""最小的 PowerPoint（.pptx）產生器：不需要 python-pptx，只用標準函式庫（zipfile + XML 文字）。

支援：文字框（多段、粗體、顏色、大小、對齊）、矩形 / 圓角矩形、圖片（PNG / JPEG，自動等比例縮放置中）、
表格、每頁的標題名稱（大綱裡看得到）。單位一律是英吋。
"""
from __future__ import annotations

import os
import struct
import time
import zipfile
from xml.sax.saxutils import escape

EMU = 914400
LATIN = "Calibri"
EA = "Microsoft JhengHei"


def emu(x):
    return int(round(x * EMU))


def _esc(s):
    return escape(str(s), {'"': "&quot;"})


def image_size(path):
    """PNG / JPEG 的像素大小（不需要 PIL）。"""
    with open(path, "rb") as f:
        head = f.read(26)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            return struct.unpack(">II", head[16:24])
        f.seek(0)
        data = f.read()
    if data[:2] != b"\xff\xd8":
        raise ValueError(f"不是 PNG / JPEG：{path}")
    i = 2
    while i < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return w, h
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seg = struct.unpack(">H", data[i + 2:i + 4])[0]
        i += 2 + seg
    raise ValueError(f"讀不到 JPEG 大小：{path}")


def _rpr(size=None, bold=False, color=None, italic=False, lang="zh-TW"):
    a = f'<a:rPr lang="{lang}" altLang="en-US" dirty="0"' + (f' sz="{int(size * 100)}"' if size else "") + \
        (' b="1"' if bold else ' b="0"') + (' i="1"' if italic else "") + ">"
    if color:
        a += f'<a:solidFill><a:srgbClr val="{color}"/></a:solidFill>'
    a += f'<a:latin typeface="{LATIN}"/><a:ea typeface="{EA}"/><a:cs typeface="{LATIN}"/></a:rPr>'
    return a


def _paras(paras, size, color, bold, align, spacing=None):
    """paras = ["文字", …] 或 [[("文字", {bold, color, size}), …], …]"""
    out = []
    al = {"l": "l", "c": "ctr", "r": "r", "left": "l", "center": "ctr", "right": "r"}.get(align, "l")
    for p in paras:
        runs = p if isinstance(p, (list, tuple)) else [(p, {})]
        sp = f'<a:spcBef><a:spcPts val="{int(spacing * 100)}"/></a:spcBef>' if spacing else ""
        xml = f'<a:p><a:pPr algn="{al}">{sp}<a:buNone/></a:pPr>'
        for text, o in runs:
            o = o or {}
            xml += (f'<a:r>{_rpr(o.get("size", size), o.get("bold", bold), o.get("color", color), o.get("italic", False))}'
                    f'<a:t>{_esc(text)}</a:t></a:r>')
        xml += f'<a:endParaRPr lang="zh-TW" sz="{int(size * 100)}" dirty="0"/></a:p>'
        out.append(xml)
    return "".join(out) or f'<a:p><a:endParaRPr lang="zh-TW" sz="{int(size * 100)}"/></a:p>'


class Slide:
    def __init__(self, deck, title=""):
        self.deck = deck
        self.title = title
        self.shapes = []
        self.rels = []           # (rId, target)
        self._id = 2
        self.bg = None

    def _nid(self):
        self._id += 1
        return self._id

    def rect(self, x, y, w, h, fill="FFFFFF", line=None, radius=0.0, name="Shape", line_w=0.75):
        geom = "roundRect" if radius else "rect"
        adj = f'<a:avLst><a:gd name="adj" fmla="val {int(radius * 100000)}"/></a:avLst>' if radius else "<a:avLst/>"
        ln = (f'<a:ln w="{int(line_w * 12700)}"><a:solidFill><a:srgbClr val="{line}"/></a:solidFill></a:ln>' if line
              else "<a:ln><a:noFill/></a:ln>")
        fl = f'<a:solidFill><a:srgbClr val="{fill}"/></a:solidFill>' if fill else "<a:noFill/>"
        i = self._nid()
        self.shapes.append(
            f'<p:sp><p:nvSpPr><p:cNvPr id="{i}" name="{_esc(name)} {i}"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
            f'<p:spPr><a:xfrm><a:off x="{emu(x)}" y="{emu(y)}"/><a:ext cx="{emu(w)}" cy="{emu(h)}"/></a:xfrm>'
            f'<a:prstGeom prst="{geom}">{adj}</a:prstGeom>{fl}{ln}</p:spPr>'
            f'<p:txBody><a:bodyPr rtlCol="0" anchor="ctr"/><a:lstStyle/><a:p><a:endParaRPr lang="zh-TW"/></a:p></p:txBody>'
            f'</p:sp>')

    def text(self, x, y, w, h, paras, size=14, color="1F2937", bold=False, align="l", anchor="t", fill=None,
             line=None, radius=0.0, inset=0.05, name="TextBox", spacing=None, autofit=True):
        if isinstance(paras, str):
            paras = paras.split("\n")
        geom = "roundRect" if radius else "rect"
        adj = f'<a:avLst><a:gd name="adj" fmla="val {int(radius * 100000)}"/></a:avLst>' if radius else "<a:avLst/>"
        fl = f'<a:solidFill><a:srgbClr val="{fill}"/></a:solidFill>' if fill else "<a:noFill/>"
        ln = (f'<a:ln w="9525"><a:solidFill><a:srgbClr val="{line}"/></a:solidFill></a:ln>' if line else
              "<a:ln><a:noFill/></a:ln>")
        anc = {"t": "t", "m": "ctr", "b": "b", "ctr": "ctr"}.get(anchor, "t")
        ins = emu(inset)
        fit = "<a:normAutofit/>" if autofit else ""
        i = self._nid()
        self.shapes.append(
            f'<p:sp><p:nvSpPr><p:cNvPr id="{i}" name="{_esc(name)} {i}"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>'
            f'<p:spPr><a:xfrm><a:off x="{emu(x)}" y="{emu(y)}"/><a:ext cx="{emu(w)}" cy="{emu(h)}"/></a:xfrm>'
            f'<a:prstGeom prst="{geom}">{adj}</a:prstGeom>{fl}{ln}</p:spPr>'
            f'<p:txBody><a:bodyPr wrap="square" lIns="{ins}" tIns="{ins}" rIns="{ins}" bIns="{ins}" rtlCol="0" '
            f'anchor="{anc}">{fit}</a:bodyPr><a:lstStyle/>{_paras(paras, size, color, bold, align, spacing)}</p:txBody></p:sp>')

    def image(self, path, x, y, w, h, fit=True, name="Picture", border=None):
        """等比例放進 (x, y, w, h) 的框裡置中；回傳實際的 (x, y, w, h)。"""
        pw, ph = image_size(path)
        if fit and pw and ph:
            r = min(w / pw, h / ph)
            nw, nh = pw * r, ph * r
            x, y, w, h = x + (w - nw) / 2, y + (h - nh) / 2, nw, nh
        rid = self.deck._media(self, path)
        i = self._nid()
        ln = (f'<a:ln w="6350"><a:solidFill><a:srgbClr val="{border}"/></a:solidFill></a:ln>' if border else "")
        self.shapes.append(
            f'<p:pic><p:nvPicPr><p:cNvPr id="{i}" name="{_esc(name)} {i}" descr="{_esc(os.path.basename(path))}"/>'
            f'<p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr/></p:nvPicPr>'
            f'<p:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>'
            f'<p:spPr><a:xfrm><a:off x="{emu(x)}" y="{emu(y)}"/><a:ext cx="{emu(w)}" cy="{emu(h)}"/></a:xfrm>'
            f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>{ln}</p:spPr></p:pic>')
        return x, y, w, h

    def table(self, x, y, w, rows, col_w=None, size=11, header_fill="DB2777", header_color="FFFFFF",
              stripe="F8FAFC", row_h=0.36, line="E5E7EB", fills=None):
        """rows = [[格子文字, …], …]（第一列是標題）；col_w = 每欄寬度比例；fills = {(列, 欄): 顏色}。"""
        n = max(len(r) for r in rows)
        col_w = col_w or [1] * n
        tot = sum(col_w)
        widths = [w * c / tot for c in col_w]
        fills = fills or {}
        grid = "".join(f'<a:gridCol w="{emu(c)}"/>' for c in widths)
        trs = []
        for ri, r in enumerate(rows):
            tcs = []
            for ci in range(n):
                txt = str(r[ci]) if ci < len(r) and r[ci] is not None else ""
                hdr = ri == 0
                fill = header_fill if hdr else fills.get((ri, ci)) or (stripe if ri % 2 == 0 else "FFFFFF")
                col = header_color if hdr else "1F2937"
                bd = "".join(f'<a:{s} w="6350"><a:solidFill><a:srgbClr val="{line}"/></a:solidFill></a:{s}>'
                             for s in ("lnL", "lnR", "lnT", "lnB"))
                tcs.append(f'<a:tc><a:txBody><a:bodyPr/><a:lstStyle/>{_paras(txt.split(chr(10)), size, col, hdr, "l")}'
                           f'</a:txBody><a:tcPr marL="68580" marR="68580" marT="34290" marB="34290" anchor="ctr">{bd}'
                           f'<a:solidFill><a:srgbClr val="{fill}"/></a:solidFill></a:tcPr></a:tc>')
            trs.append(f'<a:tr h="{emu(row_h)}">{"".join(tcs)}</a:tr>')
        i = self._nid()
        self.shapes.append(
            f'<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="{i}" name="Table {i}"/><p:cNvGraphicFramePr>'
            f'<a:graphicFrameLocks noGrp="1"/></p:cNvGraphicFramePr><p:nvPr/></p:nvGraphicFramePr>'
            f'<p:xfrm><a:off x="{emu(x)}" y="{emu(y)}"/><a:ext cx="{emu(w)}" cy="{emu(row_h * len(rows))}"/></p:xfrm>'
            f'<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table"><a:tbl>'
            f'<a:tblPr firstRow="1" bandRow="1"/><a:tblGrid>{grid}</a:tblGrid>{"".join(trs)}</a:tbl></a:graphicData>'
            f'</a:graphic></p:graphicFrame>')

    def line(self, x1, y1, x2, y2, color="E5E7EB", width=1.0):
        i = self._nid()
        x, y = min(x1, x2), min(y1, y2)
        w, h = abs(x2 - x1), abs(y2 - y1)
        self.shapes.append(
            f'<p:cxnSp><p:nvCxnSpPr><p:cNvPr id="{i}" name="Line {i}"/><p:cNvCxnSpPr/><p:nvPr/></p:nvCxnSpPr>'
            f'<p:spPr><a:xfrm><a:off x="{emu(x)}" y="{emu(y)}"/><a:ext cx="{emu(w)}" cy="{emu(h)}"/></a:xfrm>'
            f'<a:prstGeom prst="line"><a:avLst/></a:prstGeom><a:ln w="{int(width * 12700)}"><a:solidFill>'
            f'<a:srgbClr val="{color}"/></a:solidFill></a:ln></p:spPr></p:cxnSp>')

    def xml(self):
        bg = (f'<p:bg><p:bgPr><a:solidFill><a:srgbClr val="{self.bg}"/></a:solidFill><a:effectLst/></p:bgPr></p:bg>'
              if self.bg else "")
        return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<p:sld {NS}><p:cSld name="{_esc(self.title)}">'
                f'{bg}<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
                f'<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/>'
                f'<a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>{"".join(self.shapes)}</p:spTree></p:cSld>'
                f'<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>')


NS = ('xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
      'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"')
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"


class Deck:
    def __init__(self, width=13.333, height=7.5, title="", author="Magic Tool"):
        self.w, self.h = width, height
        self.slides = []
        self.media = []          # (name, path)
        self._media_idx = {}
        self.title, self.author = title, author

    def slide(self, title=""):
        s = Slide(self, title)
        self.slides.append(s)
        return s

    def _media(self, slide, path):
        key = os.path.abspath(path)
        if key not in self._media_idx:
            with open(path, "rb") as f:
                ext = ".png" if f.read(4) == b"\x89PNG" else ".jpeg"
            name = f"image{len(self.media) + 1}{ext}"
            self.media.append((name, path))
            self._media_idx[key] = name
        name = self._media_idx[key]
        for rid, tgt in slide.rels:
            if tgt == f"../media/{name}":
                return rid
        rid = f"rId{len(slide.rels) + 2}"
        slide.rels.append((rid, f"../media/{name}"))
        return rid

    # ---- 固定的部分
    def _content_types(self):
        ov = ['<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.'
              'presentationml.presentation.main+xml"/>',
              '<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-'
              'officedocument.presentationml.slideMaster+xml"/>',
              '<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-'
              'officedocument.presentationml.slideLayout+xml"/>',
              '<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.'
              'theme+xml"/>',
              '<Override PartName="/ppt/presProps.xml" ContentType="application/vnd.openxmlformats-officedocument.'
              'presentationml.presProps+xml"/>',
              '<Override PartName="/ppt/viewProps.xml" ContentType="application/vnd.openxmlformats-officedocument.'
              'presentationml.viewProps+xml"/>',
              '<Override PartName="/ppt/tableStyles.xml" ContentType="application/vnd.openxmlformats-officedocument.'
              'presentationml.tableStyles+xml"/>',
              '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-'
              'properties+xml"/>',
              '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.'
              'extended-properties+xml"/>']
        for i in range(len(self.slides)):
            ov.append(f'<Override PartName="/ppt/slides/slide{i + 1}.xml" ContentType="application/vnd.openxmlformats-'
                      f'officedocument.presentationml.slide+xml"/>')
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                '<Default Extension="xml" ContentType="application/xml"/>'
                '<Default Extension="png" ContentType="image/png"/>'
                '<Default Extension="jpeg" ContentType="image/jpeg"/>' + "".join(ov) + "</Types>")

    def _rels(self, items):
        body = "".join(f'<Relationship Id="{i}" Type="{t}" Target="{g}"/>' for i, t, g in items)
        return f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="{PKG}">{body}</Relationships>'

    def _presentation(self):
        sids = "".join(f'<p:sldId id="{256 + i}" r:id="rId{i + 2}"/>' for i in range(len(self.slides)))
        return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<p:presentation {NS} saveSubsetFonts="1">'
                f'<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
                f'<p:sldIdLst>{sids}</p:sldIdLst><p:sldSz cx="{emu(self.w)}" cy="{emu(self.h)}"/>'
                f'<p:notesSz cx="6858000" cy="9144000"/><p:defaultTextStyle><a:defPPr><a:defRPr lang="zh-TW"/></a:defPPr>'
                f'</p:defaultTextStyle></p:presentation>')

    def _master(self):
        tx = ('<a:lvl1pPr><a:defRPr sz="1800"><a:latin typeface="+mn-lt"/><a:ea typeface="+mn-ea"/></a:defRPr>'
              '</a:lvl1pPr>')
        return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<p:sldMaster {NS}><p:cSld><p:bg><p:bgRef '
                f'idx="1001"><a:schemeClr val="bg1"/></p:bgRef></p:bg><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/>'
                f'<p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
                f'<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr></p:spTree></p:cSld>'
                f'<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" '
                f'accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
                f'<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>'
                f'<p:txStyles><p:titleStyle>{tx}</p:titleStyle><p:bodyStyle>{tx}</p:bodyStyle><p:otherStyle>{tx}'
                f'</p:otherStyle></p:txStyles></p:sldMaster>')

    def _layout(self):
        return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<p:sldLayout {NS} preserve="1">'
                f'<p:cSld name="Blank"><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/>'
                f'</p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/>'
                f'<a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr></p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/>'
                f'</p:clrMapOvr></p:sldLayout>')

    @staticmethod
    def _theme():
        clr = {"dk1": "1F2937", "lt1": "FFFFFF", "dk2": "1E293B", "lt2": "F1F5F9", "accent1": "DB2777",
               "accent2": "0D9488", "accent3": "D97706", "accent4": "E4572E", "accent5": "7C3AED", "accent6": "2563EB",
               "hlink": "2563EB", "folHlink": "7C3AED"}
        cs = "".join(f'<a:{k}><a:srgbClr val="{v}"/></a:{k}>' for k, v in clr.items())
        font = f'<a:latin typeface="{LATIN}"/><a:ea typeface="{EA}"/><a:cs typeface=""/>'
        fill3 = '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>' * 3
        ln3 = '<a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>' * 3
        eff3 = '<a:effectStyle><a:effectLst/></a:effectStyle>' * 3
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                '<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Magic Tool">'
                f'<a:themeElements><a:clrScheme name="Magic Tool">{cs}</a:clrScheme>'
                f'<a:fontScheme name="Magic Tool"><a:majorFont>{font}</a:majorFont><a:minorFont>{font}</a:minorFont>'
                f'</a:fontScheme><a:fmtScheme name="Magic Tool"><a:fillStyleLst>{fill3}</a:fillStyleLst>'
                f'<a:lnStyleLst>{ln3}</a:lnStyleLst><a:effectStyleLst>{eff3}</a:effectStyleLst>'
                f'<a:bgFillStyleLst>{fill3}</a:bgFillStyleLst></a:fmtScheme></a:themeElements>'
                '<a:objectDefaults/><a:extraClrSchemeLst/></a:theme>')

    def save(self, path):
        tmp = path + ".tmp"
        P = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", self._content_types())
            z.writestr("_rels/.rels", self._rels([
                ("rId1", P + "officeDocument", "ppt/presentation.xml"),
                ("rId2", "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties",
                 "docProps/core.xml"),
                ("rId3", P + "extended-properties", "docProps/app.xml")]))
            z.writestr("docProps/core.xml",
                       '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<cp:coreProperties '
                       'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                       'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
                       'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
                       f'<dc:title>{_esc(self.title)}</dc:title><dc:creator>{_esc(self.author)}</dc:creator>'
                       f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>'
                       f'<dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified></cp:coreProperties>')
            z.writestr("docProps/app.xml",
                       '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Properties '
                       'xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
                       f'<Application>Magic Tool</Application><Slides>{len(self.slides)}</Slides></Properties>')
            z.writestr("ppt/presentation.xml", self._presentation())
            rels = [("rId1", P + "slideMaster", "slideMasters/slideMaster1.xml")]
            rels += [(f"rId{i + 2}", P + "slide", f"slides/slide{i + 1}.xml") for i in range(len(self.slides))]
            k = len(self.slides) + 2
            rels += [(f"rId{k}", P + "theme", "theme/theme1.xml"), (f"rId{k + 1}", P + "presProps", "presProps.xml"),
                     (f"rId{k + 2}", P + "viewProps", "viewProps.xml"),
                     (f"rId{k + 3}", P + "tableStyles", "tableStyles.xml")]
            z.writestr("ppt/_rels/presentation.xml.rels", self._rels(rels))
            z.writestr("ppt/presProps.xml", f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                                            f'<p:presentationPr {NS}/>')
            z.writestr("ppt/viewProps.xml", f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                                            f'<p:viewPr {NS}><p:normalViewPr><p:restoredLeft sz="15620"/>'
                                            f'<p:restoredTop sz="94660"/></p:normalViewPr>'
                                            f'<p:gridSpacing cx="76200" cy="76200"/></p:viewPr>')
            z.writestr("ppt/tableStyles.xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                                              '<a:tblStyleLst xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/'
                                              'main" def="{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}"/>')
            z.writestr("ppt/slideMasters/slideMaster1.xml", self._master())
            z.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels", self._rels([
                ("rId1", P + "slideLayout", "../slideLayouts/slideLayout1.xml"),
                ("rId2", P + "theme", "../theme/theme1.xml")]))
            z.writestr("ppt/slideLayouts/slideLayout1.xml", self._layout())
            z.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels", self._rels([
                ("rId1", P + "slideMaster", "../slideMasters/slideMaster1.xml")]))
            z.writestr("ppt/theme/theme1.xml", self._theme())
            for i, s in enumerate(self.slides, start=1):
                z.writestr(f"ppt/slides/slide{i}.xml", s.xml())
                z.writestr(f"ppt/slides/_rels/slide{i}.xml.rels", self._rels(
                    [("rId1", P + "slideLayout", "../slideLayouts/slideLayout1.xml")] +
                    [(rid, P + "image", tgt) for rid, tgt in s.rels]))
            for name, src in self.media:
                z.write(src, f"ppt/media/{name}")
        os.replace(tmp, path)
        return path
