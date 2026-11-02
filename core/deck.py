"""Deck loading: .pptx (python-pptx) and .pdf (PyMuPDF), plus slide-image rendering.

Rendering: LibreOffice headless -> PDF -> pdftoppm PNGs. If that fails, each slide gets a
generated text card so the viewer never breaks.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import textwrap
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional

DATA = Path(__file__).resolve().parent.parent / "data"
RENDER_DIR = DATA / "renders"


@dataclass
class Slide:
    number: int
    title: str = ""
    bullets: List[str] = field(default_factory=list)          # body paragraphs (with level prefix removed)
    levels: List[int] = field(default_factory=list)
    tables: List[List[List[str]]] = field(default_factory=list)  # list of tables -> rows -> cells
    charts: List[dict] = field(default_factory=list)          # {type,title,categories,series:[{name,values}]}
    notes: str = ""
    images: int = 0
    alt_texts: List[str] = field(default_factory=list)
    hidden: bool = False
    image_path: Optional[str] = None

    def body_text(self) -> str:
        return "\n".join(self.bullets)

    def full_text(self, with_notes: bool = False) -> str:
        parts = [self.title, self.body_text()]
        for t in self.tables:
            parts.append("\n".join(" | ".join(r) for r in t))
        for c in self.charts:
            parts.append(describe_chart_raw(c))
        parts += self.alt_texts
        if with_notes and self.notes:
            parts.append(self.notes)
        return "\n".join(p for p in parts if p)

    def to_dict(self):
        return asdict(self)


def describe_chart_raw(c: dict) -> str:
    lines = [f"Chart: {c.get('title') or c.get('type', '')}", "Categories: " + ", ".join(map(str, c.get("categories", [])))]
    for s in c.get("series", []):
        lines.append(f"{s['name']}: " + ", ".join("" if v is None else f"{v:g}" for v in s["values"]))
    return "\n".join(lines)


# ---------------------------------------------------------------- pptx
def _iter_shapes(shapes):
    from pptx.enum.shapes import MSO_SHAPE_TYPE
    for sh in shapes:
        if sh.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from _iter_shapes(sh.shapes)
        else:
            yield sh


def parse_pptx(path: str) -> List[Slide]:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE, PP_PLACEHOLDER
    prs = Presentation(path)
    slides: List[Slide] = []
    for i, s in enumerate(prs.slides, 1):
        sl = Slide(number=i, hidden=s._element.get("show") == "0")
        title_shape = s.shapes.title
        if title_shape is not None and title_shape.has_text_frame:
            sl.title = " ".join(title_shape.text_frame.text.split())
        shapes = sorted(_iter_shapes(s.shapes), key=lambda x: ((x.top or 0) // 20000, x.left or 0))
        for sh in shapes:
            if title_shape is not None and sh.shape_id == title_shape.shape_id:
                continue
            if sh.is_placeholder:
                try:
                    pht = sh.placeholder_format.type
                    if pht in (PP_PLACEHOLDER.SLIDE_NUMBER, PP_PLACEHOLDER.FOOTER, PP_PLACEHOLDER.DATE):
                        continue
                    if not sl.title and pht in (PP_PLACEHOLDER.CENTER_TITLE, PP_PLACEHOLDER.TITLE) and sh.has_text_frame:
                        sl.title = " ".join(sh.text_frame.text.split()); continue
                except Exception:
                    pass
            if getattr(sh, "has_table", False) and sh.has_table:
                sl.tables.append([[" ".join(c.text.split()) for c in r.cells] for r in sh.table.rows])
                continue
            if getattr(sh, "has_chart", False) and sh.has_chart:
                sl.charts.append(_chart(sh.chart)); continue
            if sh.shape_type == MSO_SHAPE_TYPE.PICTURE:
                sl.images += 1
                descr = sh._element.xpath("./p:nvPicPr/p:cNvPr/@descr")
                if descr and descr[0].strip():
                    sl.alt_texts.append("Image: " + descr[0].strip())
                continue
            if sh.has_text_frame:
                for p in sh.text_frame.paragraphs:
                    t = " ".join("".join(r.text for r in p.runs).split()) or " ".join(p.text.split())
                    if t:
                        sl.bullets.append(t); sl.levels.append(p.level)
        if not sl.title and sl.bullets:
            sl.title = sl.bullets.pop(0); sl.levels.pop(0)
        if s.has_notes_slide:
            sl.notes = (s.notes_slide.notes_text_frame.text or "").strip()
        slides.append(sl)
    return slides


def _chart(ch) -> dict:
    out = {"type": str(ch.chart_type).split(".")[-1].split(" ")[0], "title": "", "categories": [], "series": []}
    try:
        if ch.has_title:
            out["title"] = ch.chart_title.text_frame.text
    except Exception:
        pass
    try:
        plot = ch.plots[0]
        out["categories"] = [str(c) for c in plot.categories]
        for s in plot.series:
            out["series"].append({"name": s.name, "values": [None if v is None else float(v) for v in s.values]})
    except Exception:
        pass
    return out


# ---------------------------------------------------------------- pdf
def parse_pdf(path: str) -> List[Slide]:
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz
    doc = fitz.open(path)
    slides = []
    for i, page in enumerate(doc, 1):
        lines = []                                   # (text, font size)
        for b in page.get_text("dict")["blocks"]:
            for l in b.get("lines", []):
                t = " ".join("".join(sp["text"] for sp in l["spans"]).split())
                if t:
                    lines.append((t, max(sp["size"] for sp in l["spans"])))
        if not lines:
            slides.append(Slide(number=i)); continue
        top = max(sz for _, sz in lines)
        title_idx = [k for k, (_, sz) in enumerate(lines) if sz >= top - 0.5]
        # title = consecutive run of largest-font lines (multi-line titles)
        run = [title_idx[0]]
        for k in title_idx[1:]:
            if k == run[-1] + 1:
                run.append(k)
        title = " ".join(lines[k][0] for k in run)
        body = [t for k, (t, _) in enumerate(lines) if k not in run]
        slides.append(Slide(number=i, title=title, bullets=body, levels=[0] * len(body)))
    return slides


def load_deck(path: str) -> List[Slide]:
    ext = Path(path).suffix.lower()
    if ext == ".pptx":
        return parse_pptx(path)
    if ext == ".pdf":
        return parse_pdf(path)
    raise ValueError("Upload a .pptx or .pdf deck (older .ppt: save as .pptx first).")


# ---------------------------------------------------------------- rendering
def file_hash(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def soffice_bin() -> Optional[str]:
    return shutil.which("soffice") or shutil.which("libreoffice")


def render_slides(path: str, slides: List[Slide], dpi: int = 110) -> dict:
    """Fill slide.image_path. Returns {'method':..., 'error':...}."""
    key = file_hash(path)
    out = RENDER_DIR / key
    out.mkdir(parents=True, exist_ok=True)
    pngs = sorted(out.glob("slide-*.png"))
    info = {"method": "cache", "error": ""}
    if not pngs:
        info = {"method": "", "error": ""}
        try:
            pdf = path
            if Path(path).suffix.lower() != ".pdf":
                sbin = soffice_bin()
                if not sbin:
                    raise RuntimeError("LibreOffice not installed (apt install libreoffice-impress)")
                with tempfile.TemporaryDirectory() as td:
                    prof = Path(td) / "profile"
                    src = Path(td) / ("deck" + Path(path).suffix.lower())
                    shutil.copy(path, src)
                    cmd = [sbin, f"-env:UserInstallation=file://{prof}", "--headless", "--convert-to", "pdf",
                           "--outdir", td, str(src)]
                    subprocess.run(cmd, capture_output=True, timeout=240)
                    made = Path(td) / "deck.pdf"
                    if not made.exists():
                        raise RuntimeError("LibreOffice conversion produced no PDF")
                    pdf = str(out / "deck.pdf")
                    shutil.copy(made, pdf)
            if not shutil.which("pdftoppm"):
                raise RuntimeError("pdftoppm not installed (apt install poppler-utils)")
            subprocess.run(["pdftoppm", "-r", str(dpi), "-png", pdf, str(out / "slide")],
                           capture_output=True, timeout=300, check=True)
            pngs = sorted(out.glob("slide-*.png"))
            info["method"] = "libreoffice+pdftoppm" if pdf != path else "pdftoppm"
        except Exception as e:  # noqa
            info["error"] = str(e)
    visible = [s for s in slides if not s.hidden]
    if pngs and len(pngs) in (len(slides), len(visible)):
        targets = slides if len(pngs) == len(slides) else visible
        for s, p in zip(targets, pngs):
            s.image_path = str(p)
    elif pngs:
        info["error"] = (info["error"] + f" page count mismatch ({len(pngs)} images vs {len(slides)} slides)").strip()
        for s, p in zip(slides, pngs):
            s.image_path = str(p)
    for s in slides:
        if not s.image_path:
            s.image_path = text_card(s, out)
            info["method"] = info["method"] or "text-card fallback"
    return info


def _font(size: int, bold=False):
    from PIL import ImageFont
    for f in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
              "/Library/Fonts/Arial.ttf", "C:/Windows/Fonts/arial.ttf"]:
        if os.path.exists(f):
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def text_card(s: Slide, out: Path) -> str:
    from PIL import Image, ImageDraw
    W, H = 1280, 720
    img = Image.new("RGB", (W, H), (248, 246, 241))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 90], fill=(31, 56, 100))
    d.text((40, 24), (s.title or f"Slide {s.number}")[:70], font=_font(36, True), fill="white")
    y = 120
    lines = list(s.bullets)
    for t in s.tables:
        lines += [" | ".join(r) for r in t[:8]]
    for c in s.charts:
        lines.append(f"[chart] {c.get('title') or c.get('type')}")
    for line in lines[:14]:
        for w in textwrap.wrap("• " + line, 70)[:3]:
            d.text((50, y), w, font=_font(24), fill=(40, 40, 40)); y += 34
        if y > H - 60:
            break
    d.text((W - 160, H - 40), f"Slide {s.number}", font=_font(20), fill=(120, 120, 120))
    p = out / f"card-{s.number:03d}.png"
    img.save(p)
    return str(p)
