"""Render .pptx slides to PNG with python-pptx + Pillow, without LibreOffice.

Used on hosts without LibreOffice (e.g. Streamlit Community Cloud), so the walkthrough always shows
the real slide: background, master/layout artwork, shapes, pictures, text, tables and charts.
Best effort: theme colours are resolved from the deck theme when possible, gradients use their first
stop, and SmartArt, effects and exotic geometry are simplified to rectangles/ellipses.
"""
from __future__ import annotations

import io
import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

W_OUT = 1600
FONT_DIRS = ["/usr/share/fonts/truetype/liberation", "/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/truetype/noto"]
_FONT_CACHE: dict = {}

DEFAULT_THEME = {"dk1": "000000", "lt1": "FFFFFF", "dk2": "44546A", "lt2": "E7E6E6", "accent1": "4472C4",
                 "accent2": "ED7D31", "accent3": "A5A5A5", "accent4": "FFC000", "accent5": "5B9BD5",
                 "accent6": "70AD47", "hlink": "0563C1", "folHlink": "954F72"}
THEME_ALIAS = {"bg1": "lt1", "tx1": "dk1", "bg2": "lt2", "tx2": "dk2",
               "BACKGROUND_1": "lt1", "TEXT_1": "dk1", "BACKGROUND_2": "lt2", "TEXT_2": "dk2",
               "DARK_1": "dk1", "LIGHT_1": "lt1", "DARK_2": "dk2", "LIGHT_2": "lt2",
               "ACCENT_1": "accent1", "ACCENT_2": "accent2", "ACCENT_3": "accent3", "ACCENT_4": "accent4",
               "ACCENT_5": "accent5", "ACCENT_6": "accent6", "HYPERLINK": "hlink", "FOLLOWED_HYPERLINK": "folHlink"}
NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main",
      "p": "http://schemas.openxmlformats.org/presentationml/2006/main"}


def font(size: int, bold=False, italic=False):
    size = max(6, int(size))
    k = (size, bold, italic)
    if k in _FONT_CACHE:
        return _FONT_CACHE[k]
    names = ["LiberationSans-" + ("BoldItalic" if bold and italic else "Bold" if bold else "Italic" if italic else "Regular") + ".ttf",
             "DejaVuSans" + ("-BoldOblique" if bold and italic else "-Bold" if bold else "-Oblique" if italic else "") + ".ttf"]
    f = None
    for d in FONT_DIRS:
        for n in names:
            p = os.path.join(d, n)
            if os.path.exists(p):
                f = ImageFont.truetype(p, size); break
        if f:
            break
    f = f or ImageFont.load_default()
    _FONT_CACHE[k] = f
    return f


def _hex(h: str) -> Tuple[int, int, int]:
    h = (h or "000000")[-6:]
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _theme(prs) -> dict:
    th = dict(DEFAULT_THEME)
    try:
        master = prs.slide_masters[0]
        for rel in master.part.rels.values():
            if rel.reltype.endswith("/theme"):
                from lxml import etree
                root = etree.fromstring(rel.target_part.blob)
                cs = root.find(".//a:clrScheme", NS)
                for el in cs:
                    tag = etree.QName(el).localname
                    v = el.find("a:srgbClr", NS)
                    s = el.find("a:sysClr", NS)
                    if v is not None:
                        th[tag] = v.get("val")
                    elif s is not None:
                        th[tag] = s.get("lastClr") or ("000000" if "dk" in tag else "FFFFFF")
                break
    except Exception:
        pass
    return th


def _lum(c, f):
    return tuple(max(0, min(255, int(v * f))) for v in c)


def _color_from_xml(el, theme) -> Optional[Tuple[int, int, int]]:
    """el: an a:solidFill (or similar) element. Handles srgbClr / schemeClr / sysClr + lumMod/lumOff."""
    if el is None:
        return None
    for child in el:
        tag = child.tag.split("}")[-1]
        c = None
        if tag == "srgbClr":
            c = _hex(child.get("val"))
        elif tag == "schemeClr":
            v = child.get("val"); v = THEME_ALIAS.get(v, v)
            c = _hex(theme.get(v, "000000"))
        elif tag == "sysClr":
            c = _hex(child.get("lastClr") or "000000")
        elif tag == "prstClr":
            c = {"black": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0), "blue": (0, 0, 255)}.get(child.get("val"), (0, 0, 0))
        if c is not None:
            mod = child.find("a:lumMod", NS); off = child.find("a:lumOff", NS)
            if mod is not None or off is not None:
                m = int(mod.get("val")) / 100000 if mod is not None else 1
                o = int(off.get("val")) / 100000 if off is not None else 0
                c = tuple(max(0, min(255, int(v * m + 255 * o))) for v in c)
            return c
    return None


def _fill_of(el, theme):
    """Fill colour of an spPr/bg element: solidFill or first gradient stop. None = no fill."""
    if el is None:
        return None
    if el.find("a:noFill", NS) is not None:
        return None
    sf = el.find("a:solidFill", NS)
    if sf is not None:
        return _color_from_xml(sf, theme)
    gs = el.find("a:gradFill/a:gsLst/a:gs", NS)
    if gs is not None:
        return _color_from_xml(gs, theme)
    return None


def _bg(obj, theme):
    try:
        cs = obj._element.find("p:cSld", NS)
        bg = cs.find("p:bg", NS) if cs is not None else None
        if bg is None:
            return None, None
        pr = bg.find("p:bgPr", NS)
        if pr is not None:
            blip = pr.find("a:blipFill/a:blip", NS)
            if blip is not None:
                rid = blip.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed")
                try:
                    return None, obj.part.related_part(rid).blob
                except Exception:
                    pass
            return _fill_of(pr, theme), None
        ref = bg.find("p:bgRef", NS)
        if ref is not None:
            return _color_from_xml(ref, theme), None
    except Exception:
        pass
    return None, None


def _master_sizes(master) -> dict:
    """{'title': pt, 'body': [pt per level], 'other': pt} from the master's txStyles."""
    out = {"title": 44.0, "body": [28.0, 24.0, 20.0, 18.0, 18.0], "other": 18.0, "title_algn": "l"}
    try:
        tx = master._element.find("p:txStyles", NS)
        t = tx.find("p:titleStyle/a:lvl1pPr", NS)
        r = t.find("a:defRPr", NS)
        if r is not None and r.get("sz"):
            out["title"] = int(r.get("sz")) / 100
        out["title_algn"] = {"ctr": "c", "r": "r"}.get(t.get("algn"), "l")
        for k in range(5):
            e = tx.find(f"p:bodyStyle/a:lvl{k + 1}pPr/a:defRPr", NS)
            if e is not None and e.get("sz"):
                out["body"][k] = int(e.get("sz")) / 100
        e = tx.find("p:otherStyle/a:lvl1pPr/a:defRPr", NS)
        if e is not None and e.get("sz"):
            out["other"] = int(e.get("sz")) / 100
    except Exception:
        pass
    return out


def _layout_ph_size(sh):
    """Font size set on the matching layout placeholder (lstStyle lvl1 or first run), if any."""
    try:
        lp = sh._base_placeholder if hasattr(sh, "_base_placeholder") else None
        if lp is None:
            return None
        for el in lp._element.iter("{%s}defRPr" % NS["a"], "{%s}rPr" % NS["a"], "{%s}endParaRPr" % NS["a"]):
            if el.get("sz"):
                return int(el.get("sz")) / 100
    except Exception:
        pass
    return None


class Ctx:
    def __init__(self, img, sc, theme, dark, sizes=None):
        self.img, self.sc, self.theme, self.dark = img, sc, theme, dark
        self.sizes = sizes or _master_sizes(None)
        self.d = ImageDraw.Draw(img, "RGBA")


def _box(sh, sc, off=(0, 0, 1.0, 1.0)):
    ox, oy, fx, fy = off
    x = ((sh.left or 0) * fx + ox) * sc; y = ((sh.top or 0) * fy + oy) * sc
    w = (sh.width or 0) * fx * sc; h = (sh.height or 0) * fy * sc
    return [x, y, x + max(1, w), y + max(1, h)]


def _text_color(run_or_para_font, ctx, default):
    try:
        c = run_or_para_font.color
        if c and c.type is not None:
            if c.rgb is not None and str(c.type).endswith("RGB (1)") or getattr(c, "_color", None).__class__.__name__ == "_SRgbColor":
                return _hex(str(c.rgb))
            tc = str(c.theme_color).split(".")[-1].split(" ")[0]
            k = THEME_ALIAS.get(tc, tc.lower())
            if k in ctx.theme:
                return _hex(ctx.theme[k])
    except Exception:
        pass
    return default


def _wrap(d, text, f, width):
    out = []
    for para in text.split("\n"):
        words, cur = para.split(" "), ""
        for w in words:
            t = (cur + " " + w).strip()
            if d.textlength(t, font=f) <= width or not cur:
                cur = t
            else:
                out.append(cur); cur = w
        out.append(cur)
    return out


def _draw_text(ctx, sh, box, is_title=False):
    tf = sh.text_frame
    d, sc = ctx.d, ctx.sc
    x0, y0, x1, y1 = box
    ins_l = (tf.margin_left if tf.margin_left is not None else 91440) * sc
    ins_r = (tf.margin_right if tf.margin_right is not None else 91440) * sc
    ins_t = (tf.margin_top if tf.margin_top is not None else 45720) * sc
    width = max(10, x1 - x0 - ins_l - ins_r)
    default_col = (255, 255, 255) if ctx.dark else (20, 20, 20)
    scale = 1.0
    na = tf._txBody.find("a:bodyPr/a:normAutofit", NS)
    if na is not None and na.get("fontScale"):
        scale = int(na.get("fontScale")) / 100000
    ph = sh.is_placeholder
    ph_sz = _layout_ph_size(sh) if ph else None
    def layout(fit):
        lines = []                                    # (text, font, color, align, indent)
        for p in tf.paragraphs:
            txt = "".join(r.text for r in p.runs) or p.text
            r0 = p.runs[0] if p.runs else None
            sz = None
            for src in ([r0.font] if r0 else []) + [p.font]:
                if src is not None and src.size:
                    sz = src.size.pt; break
            if not sz:
                sz = ph_sz or (ctx.sizes["title"] if is_title else ctx.sizes["body"][min(p.level, 4)] if ph else ctx.sizes["other"])

            bold = bool((r0 and r0.font.bold) or p.font.bold)
            ital = bool((r0 and r0.font.italic) or p.font.italic)
            f = font(sz * 12700 * sc * scale * fit, bold, ital)
            col = _text_color(r0.font if r0 else p.font, ctx, default_col)
            bullet = ""
            if not is_title and sh.is_placeholder and txt.strip():
                try:
                    if sh.placeholder_format.type is not None and "BODY" in str(sh.placeholder_format.type) or "OBJECT" in str(sh.placeholder_format.type):
                        bullet = "• "
                except Exception:
                    pass
            if p._pPr is not None and p._pPr.find("a:buNone", NS) is not None:
                bullet = ""
            if p._pPr is not None and p._pPr.find("a:buChar", NS) is not None:
                bullet = p._pPr.find("a:buChar", NS).get("char", "•") + " "
            indent = p.level * 0.4 * 914400 * sc
            al = str(p.alignment or "")
            align = "c" if "CENTER" in al else "r" if "RIGHT" in al else "l"
            if not al and is_title:
                align = "c" if "CENTER" in str(getattr(sh.placeholder_format, "type", "")) else ctx.sizes["title_algn"]
            if not txt.strip():
                lines.append(("", f, col, align, indent)); continue
            for k, ln in enumerate(_wrap(d, bullet + txt, f, width - indent)):
                lines.append((ln, f, col, align, indent + (0 if k == 0 else d.textlength(bullet, font=f))))

        return lines

    shrink = ph or na is not None or tf._txBody.find("a:bodyPr/a:spAutoFit", NS) is None
    avail = (y1 - y0) - ins_t * 2
    fit = 1.0
    lines = layout(fit)
    while shrink and fit > 0.45 and sum(f.size * 1.2 for _, f, _, _, _ in lines) > avail:
        fit *= 0.9
        lines = layout(fit)
    heights = [(f.size * 1.2) for _, f, _, _, _ in lines]
    total = sum(heights)
    anchor = str(tf.vertical_anchor or "")
    y = y0 + ins_t
    if "MIDDLE" in anchor or (is_title and not anchor):
        y = y0 + max(0, (y1 - y0 - total) / 2)
    elif "BOTTOM" in anchor:
        y = y1 - total - ins_t
    for (ln, f, col, align, ind), h in zip(lines, heights):
        if ln:
            tw = d.textlength(ln, font=f)
            if align == "c":
                x = x0 + (x1 - x0 - tw) / 2
            elif align == "r":
                x = x1 - ins_r - tw
            else:
                x = x0 + ins_l + ind
            d.text((x, y), ln, font=f, fill=col)
        y += h


def _draw_table(ctx, sh, box):
    d = ctx.d
    tb = sh.table
    x0, y0, x1, y1 = box
    cols = [c.width * ctx.sc for c in tb.columns]
    rows = [r.height * ctx.sc for r in tb.rows]
    y = y0
    for ri, r in enumerate(tb.rows):
        x = x0
        for ci, c in enumerate(r.cells):
            w = cols[ci] if ci < len(cols) else 50
            fill = None
            try:
                fill = _fill_of(c._tc.tcPr, ctx.theme) if c._tc.tcPr is not None else None
            except Exception:
                pass
            if fill is None:
                fill = _hex(ctx.theme.get("accent1")) if ri == 0 else ((233, 237, 244) if ri % 2 else (207, 213, 234))
            d.rectangle([x, y, x + w, y + rows[ri]], fill=fill, outline=(255, 255, 255), width=max(1, int(2 * ctx.sc * 9525)))
            txt = " ".join(c.text.split())
            sz = 14
            try:
                for p in c.text_frame.paragraphs:
                    for rr in p.runs:
                        if rr.font.size:
                            sz = rr.font.size.pt; break
            except Exception:
                pass
            f = font(sz * 12700 * ctx.sc, ri == 0)
            col = (255, 255, 255) if ri == 0 and sum(fill) < 450 else (20, 20, 20)
            ty = y + 4
            for ln in _wrap(d, txt, f, w - 10)[:3]:
                d.text((x + 6, ty), ln, font=f, fill=col); ty += f.size * 1.15
            x += w
        y += rows[ri]


def _draw_chart(ctx, sh, box):
    from .deck import _chart
    d = ctx.d
    c = _chart(sh.chart)
    x0, y0, x1, y1 = box
    f = font(max(12, (y1 - y0) / 22))
    if c.get("title"):
        tw = d.textlength(c["title"], font=font(f.size + 4, True))
        d.text((x0 + (x1 - x0 - tw) / 2, y0 + 4), c["title"], font=font(f.size + 4, True), fill=(40, 40, 40) if not ctx.dark else (240, 240, 240))
        y0 += f.size * 2
    series = c.get("series") or []
    cats = c.get("categories") or []
    vals = [v for s in series for v in s["values"] if v is not None]
    if not series or not vals:
        d.rectangle(box, outline=(150, 150, 150)); return
    pal = [_hex(ctx.theme.get(f"accent{i}")) for i in range(1, 7)]
    typ = c.get("type", "").upper()
    if "PIE" in typ or "DOUGHNUT" in typ:
        s = series[0]["values"]; tot = sum(v or 0 for v in s) or 1
        r = min(x1 - x0, y1 - y0) / 2 - 10; cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        a = -90
        for i, v in enumerate(s):
            e = a + 360 * (v or 0) / tot
            d.pieslice([cx - r, cy - r, cx + r, cy + r], a, e, fill=pal[i % 6], outline=(255, 255, 255))
            a = e
        return
    lo, hi = min(0, min(vals)), max(vals) or 1
    px0, py0, px1, py1 = x0 + 50, y0 + 10, x1 - 10, y1 - f.size * 2
    ax = (90, 90, 90)
    d.line([(px0, py1), (px1, py1)], fill=ax, width=2); d.line([(px0, py0), (px0, py1)], fill=ax, width=1)
    for k in range(5):
        v = lo + (hi - lo) * k / 4; yy = py1 - (py1 - py0) * k / 4
        d.text((x0, yy - f.size / 2), f"{v:g}" if abs(v) < 1000 else f"{v:,.0f}", font=f, fill=ax)
    n = max(1, len(cats) or len(series[0]["values"]))
    gw = (px1 - px0) / n
    yv = lambda v: py1 - (py1 - py0) * ((v or 0) - lo) / ((hi - lo) or 1)
    if "LINE" in typ:
        for si, s in enumerate(series):
            pts = [(px0 + gw * (i + 0.5), yv(v)) for i, v in enumerate(s["values"]) if v is not None]
            if len(pts) > 1:
                d.line(pts, fill=pal[si % 6], width=4)
            for p in pts:
                d.ellipse([p[0] - 5, p[1] - 5, p[0] + 5, p[1] + 5], fill=pal[si % 6])
    else:
        ns = len(series); bw = gw * 0.7 / ns
        for si, s in enumerate(series):
            for i, v in enumerate(s["values"]):
                if v is None:
                    continue
                bx = px0 + gw * i + gw * 0.15 + bw * si
                d.rectangle([bx, min(yv(v), yv(0)), bx + bw - 2, max(yv(v), yv(0))], fill=pal[si % 6])
    for i, cat in enumerate(cats[:n]):
        t = str(cat)[:14]; tw = d.textlength(t, font=f)
        d.text((px0 + gw * (i + 0.5) - tw / 2, py1 + 4), t, font=f, fill=ax)


def _draw_shape(ctx, sh, off, is_title=False):
    from pptx.enum.shapes import MSO_SHAPE_TYPE
    box = _box(sh, ctx.sc, off)
    st = sh.shape_type
    if st == MSO_SHAPE_TYPE.GROUP:
        try:
            xfrm = sh._element.find("p:grpSpPr/a:xfrm", NS)
            o, e = xfrm.find("a:off", NS), xfrm.find("a:ext", NS)
            co, ce = xfrm.find("a:chOff", NS), xfrm.find("a:chExt", NS)
            fx = int(e.get("cx")) / max(1, int(ce.get("cx"))) * off[2]
            fy = int(e.get("cy")) / max(1, int(ce.get("cy"))) * off[3]
            ox = off[0] + int(o.get("x")) * off[2] - int(co.get("x")) * fx
            oy = off[1] + int(o.get("y")) * off[3] - int(co.get("y")) * fy
            sub = (ox, oy, fx, fy)
        except Exception:
            sub = off
        for c in sh.shapes:
            _safe(_draw_shape, ctx, c, sub)
        return
    if st == MSO_SHAPE_TYPE.PICTURE or (getattr(sh, "image", None) is not None and st != MSO_SHAPE_TYPE.GROUP and hasattr(sh, "_pic")):
        im = Image.open(io.BytesIO(sh.image.blob)).convert("RGBA")
        w, h = int(box[2] - box[0]), int(box[3] - box[1])
        if w > 0 and h > 0:
            ctx.img.paste(im.resize((w, h), Image.LANCZOS), (int(box[0]), int(box[1])), im.resize((w, h), Image.LANCZOS))
        return
    if getattr(sh, "has_table", False) and sh.has_table:
        _draw_table(ctx, sh, box); return
    if getattr(sh, "has_chart", False) and sh.has_chart:
        _draw_chart(ctx, sh, box); return
    sppr = sh._element.find("p:spPr", NS)
    fill = _fill_of(sppr, ctx.theme)
    if fill is None and sppr is not None and sppr.find("a:noFill", NS) is None:
        sref = sh._element.find("p:style/a:fillRef", NS)
        if sref is not None and sref.get("idx") not in (None, "0"):
            fill = _color_from_xml(sref, ctx.theme)
    line = None
    ln = sppr.find("a:ln", NS) if sppr is not None else None
    if ln is not None and ln.find("a:noFill", NS) is None:
        line = _color_from_xml(ln.find("a:solidFill", NS), ctx.theme) if ln.find("a:solidFill", NS) is not None else None
    elif ln is None:
        lref = sh._element.find("p:style/a:lnRef", NS)
        if lref is not None and lref.get("idx") not in (None, "0"):
            line = _color_from_xml(lref, ctx.theme)
    geom = sppr.find("a:prstGeom", NS) if sppr is not None else None
    g = geom.get("prst") if geom is not None else "rect"
    if st == MSO_SHAPE_TYPE.LINE or g in ("line", "straightConnector1") or sh._element.tag.endswith("cxnSp"):
        col = line or (120, 120, 120)
        flip = sh._element.find("p:spPr/a:xfrm", NS)
        fv = flip is not None and flip.get("flipV") == "1"
        pts = [(box[0], box[3]), (box[2], box[1])] if fv else [(box[0], box[1]), (box[2], box[3])]
        ctx.d.line(pts, fill=col, width=max(1, int(ctx.sc * 19050)))
        return
    if fill is not None or line is not None:
        kw = {"fill": fill, "outline": line, "width": max(1, int(ctx.sc * 12700))}
        if g in ("ellipse", "flowChartConnector"):
            ctx.d.ellipse(box, **kw)
        elif g in ("roundRect", "snip1Rect", "round2SameRect", "flowChartAlternateProcess"):
            ctx.d.rounded_rectangle(box, radius=min(box[2] - box[0], box[3] - box[1]) * 0.15, **kw)
        elif g in ("triangle", "isoTriangle"):
            ctx.d.polygon([((box[0] + box[2]) / 2, box[1]), (box[2], box[3]), (box[0], box[3])], fill=fill, outline=line)
        elif g in ("rightArrow", "chevron", "homePlate"):
            x0, y0, x1, y1 = box; m = (y0 + y1) / 2; t = (x1 - x0) * 0.25
            ctx.d.polygon([(x0, y0), (x1 - t, y0), (x1, m), (x1 - t, y1), (x0, y1)] + ([(x0 + t, m)] if g == "chevron" else []), fill=fill, outline=line)
        else:
            ctx.d.rectangle(box, **kw)
    if getattr(sh, "has_text_frame", False) and sh.has_text_frame and sh.text_frame.text.strip():
        old = ctx.dark
        if fill is not None:
            ctx.dark = sum(fill) < 380
        _draw_text(ctx, sh, box, is_title)
        ctx.dark = old


def _safe(fn, *a, **k):
    try:
        fn(*a, **k)
    except Exception:
        pass


def _deco_shapes(obj):
    """Non-placeholder artwork on a layout/master (logos, bands); placeholders there are prompts, skip."""
    for sh in obj.shapes:
        if not sh.is_placeholder:
            yield sh


def render_pptx(path: str, out_dir: Path, width: int = W_OUT, prefix: str = "slide") -> List[str]:
    """Render every slide of `path` to out_dir/{prefix}-NN.png. Returns paths (one per slide)."""
    from pptx import Presentation
    prs = Presentation(path)
    theme = _theme(prs)
    SW, SH = prs.slide_width or 12192000, prs.slide_height or 6858000
    sc = width / SW
    H = int(SH * sc)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    n = len(prs.slides)
    for i, s in enumerate(prs.slides, 1):
        layout = s.slide_layout; master = layout.slide_master
        bgc, bgimg = None, None
        follow = s._element.find("p:cSld/p:bg", NS) is None
        for obj in (s, layout, master):
            bgc, bgimg = _bg(obj, theme)
            if bgc is not None or bgimg is not None:
                break
        img = Image.new("RGB", (width, H), bgc or (255, 255, 255))
        if bgimg:
            try:
                img.paste(Image.open(io.BytesIO(bgimg)).convert("RGB").resize((width, H)))
            except Exception:
                pass
        dark = sum(bgc or (255, 255, 255)) < 380
        ctx = Ctx(img, sc, theme, dark, _master_sizes(master))
        show_master = s._element.get("showMasterSp") != "0" and layout._element.get("showMasterSp") != "0"
        if show_master:
            for sh in _deco_shapes(master):
                _safe(_draw_shape, ctx, sh, (0, 0, 1.0, 1.0))
        for sh in _deco_shapes(layout):
            _safe(_draw_shape, ctx, sh, (0, 0, 1.0, 1.0))
        title_id = s.shapes.title.shape_id if s.shapes.title is not None else None
        for sh in s.shapes:
            _safe(_draw_shape, ctx, sh, (0, 0, 1.0, 1.0), sh.shape_id == title_id)
        p = out_dir / f"{prefix}-{i:0{len(str(n))}d}.png"
        img.save(p, optimize=True)
        paths.append(str(p))
    return paths
