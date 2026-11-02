"""Futuristic video summary: deck -> 60-120 s MP4 with a key-point voiceover and HUD-style visuals.

No API key needed. The script comes from the built-in narrator (core/narrate.py); an optional LLM
(Gemini via LLM_API_KEY) writes it instead when available, using the same fallback and cooldown
(core/llm.chat). The voice comes from core/tts.synthesize (edge-tts, falling back to gTTS). Frames are drawn
with PIL and numpy and piped straight into ffmpeg. There is no moviepy and no GPU, so it runs on Streamlit Community Cloud.
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .deck import Slide
from .narrate import FIRST, LAST, MID, _rng, _sentences, classify, narrate

GREEN = (134, 188, 37)          # Deloitte green dot #86BC25
WHITE = (255, 255, 255)
GREY = (150, 150, 150)
QUALITY = {"Fast (540p)": (960, 540, 20), "HD (720p)": (1280, 720, 24)}
TARGET_WORDS = (150, 260)       # ~60-120 s of speech


# --------------------------------------------------------------------------- ffmpeg / fonts
def ffmpeg_bin() -> str:
    b = shutil.which("ffmpeg")
    if b:
        return b
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:  # noqa
        raise RuntimeError("ffmpeg not found (add 'ffmpeg' to packages.txt or pip install imageio-ffmpeg)") from e


_FONTS = {
    True: ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
           "/Library/Fonts/Arial Bold.ttf", "C:/Windows/Fonts/arialbd.ttf"],
    False: ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
            "/Library/Fonts/Arial.ttf", "C:/Windows/Fonts/arial.ttf"],
    "mono": ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"],
}


def font(size: int, kind=False):
    for f in _FONTS[kind] + _FONTS[False]:
        if os.path.exists(f):
            return ImageFont.truetype(f, size)
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


# --------------------------------------------------------------------------- script
@dataclass
class Segment:
    kind: str                     # intro | point | outro
    headline: str
    narration: str
    slide: Optional[int] = None   # index into slides
    stat: str = ""                # e.g. "38%", "$4.2B"
    stat_label: str = ""
    audio: str = ""
    seconds: float = 0.0
    extra: dict = field(default_factory=dict)


STAT_RE = re.compile(r"(?<![\w.])((?:[$€£₹]\s?)?\d[\d,]*(?:\.\d+)?\s?(?:%|x|X|bn|BN|B|M|K|k|mn|tn|T|billion|million|trillion|crore|lakh)?)(?![\w])")


def _num_key(tok: str) -> str:
    """Comparable form of a number token: digits and decimal point only ('USD 1.6B' -> '1.6')."""
    return re.sub(r"[^\d.]", "", tok.replace(",", "")).strip(".")


def find_stat(s: Slide, narration: str = "") -> tuple[str, str]:
    """Headline number for the callout, or ("", "") when there is none worth showing.

    Only numbers printed in the slide's own title, bullets or tables count (no chart series values, alt text or
    notes), so the callout never shows a figure the viewer can't find on the slide. A number that is also said
    in the narration wins over a bigger one that isn't."""
    best, score_best, label = "", -1, ""
    lines = [s.title] + list(s.bullets) + [" | ".join(str(c) for c in r) for t in s.tables for r in t]
    said = {_num_key(m.group(1)) for m in STAT_RE.finditer(narration or "")} - {""}
    for line in lines:
        for m in STAT_RE.finditer(line or ""):
            tok = m.group(1).strip()
            digits = re.sub(r"\D", "", tok)
            if not digits or (re.fullmatch(r"(19|20)\d\d", tok)):   # skip bare years
                continue
            sc = len(digits) + (4 if re.search(r"[%$€£₹]|bn|B\b|M\b|billion|million|x\b", tok) else 0)
            if _num_key(tok) in said:
                sc += 20
            if sc > score_best:
                score_best, best = sc, tok
                rest = (line[:m.start()] + line[m.end():]).strip(" :-–|,.")
                label = re.sub(r"\s+", " ", rest)[:48]
    if best and _num_key(best) not in {_num_key(x.group(1)) for ln in lines for x in STAT_RE.finditer(ln or "")}:
        return "", ""
    return best, label


def _first_sentences(text: str, max_words: int) -> str:
    out, n = [], 0
    for sent in _sentences(text):
        w = len(sent.split())
        if out and n + w > max_words:
            break
        out.append(sent if sent[-1] in ".!?" else sent + ".")
        n += w
    s = " ".join(out)
    if len(s.split()) > max_words + 12:
        s = " ".join(s.split()[:max_words]) + "."
    return s


def pick_slides(slides: List[Slide], k: int = 6) -> List[int]:
    n = len(slides)
    cand = []
    for i, s in enumerate(slides):
        if s.hidden:
            continue
        kind = classify(s, i, n)
        if kind in ("title", "agenda") or (i == 0 and n > 2):
            continue
        weight = len(s.full_text().split()) + 25 * bool(find_stat(s)[0]) + 15 * bool(s.charts or s.tables)
        cand.append((weight, i))
    if not cand:
        cand = [(1, i) for i in range(n)]
    keep = sorted(i for _, i in sorted(cand, reverse=True)[:k])
    return keep


def _deck_title(slides: List[Slide], name: str = "") -> str:
    t = (slides[0].title if slides else "") or Path(name).stem.replace("_", " ").title() or "Deck summary"
    return t.strip()[:80]


_CONNECT = re.compile(r"(?i)^(" + "|".join(re.escape(x.rstrip(",")) for x in FIRST + MID + LAST + [
    "If we look closely at the data", "Reading the numbers", "Digging into the figures"]) + r")[,]?\s+|^(with|and|but|so|also),\s*")


def _tidy(text: str) -> str:
    """Strip narrator connectors ('What's more,') so each summary sentence stands alone."""
    out = []
    for sent in _sentences(text):
        for _ in range(2):
            sent = _CONNECT.sub("", sent).strip()
        if sent:
            sent = re.sub(r"\b(is|are|was) importantly\b", r"\1", sent)
            out.append(sent[:1].upper() + sent[1:])
    return " ".join(out)


def builtin_summary(slides: List[Slide], deck_name: str = "", k: int = 6) -> List[Segment]:
    """Key-point script with the no-key narrator engine: each picked slide's narration is trimmed to its core point."""
    idx = pick_slides(slides, k)
    title = _deck_title(slides, deck_name)
    per = max(18, min(40, (TARGET_WORDS[0] + 40) // max(1, len(idx))))
    rng = _rng(title, "video")
    segs = [Segment("intro", title, rng.choice([
        f"Here's your briefing on {title}, in about a minute and a half.",
        f"Welcome. This is a quick summary of {title}: the key points and the numbers behind them.",
        f"Let's run through {title}. Here's what you need to know."]))]
    for j, i in enumerate(idx):
        s = slides[i]
        full = narrate(slides, i, notes_mode="guide", deck_key=title)
        paras = [p for p in full.split("\n\n") if p.strip()]
        core = " ".join(paras[1:-1]) if len(paras) > 2 else " ".join(paras)   # drop opener + transition
        core = re.sub(r"(?i)^(first(ly)?|to start|let's start with|we kick off with)[, ]+", "", core.strip())
        line = _tidy(_first_sentences(core, per) or _first_sentences(full, per))
        stat, label = find_stat(s, full)
        lead = ["First,", "Next,", "Then,", "Also,", "Beyond that,", "Finally,"]
        lead_w = lead[0] if j == 0 else (lead[-1] if j == len(idx) - 1 else lead[1 + (j - 1) % 4])
        head = (s.title or f"Slide {s.number}").strip()
        spoken_head = re.sub(r"\s*:\s*", ": ", head).rstrip(".")
        segs.append(Segment("point", head, f"{lead_w} {spoken_head[:1].lower() + spoken_head[1:] if not head[:2].isupper() else spoken_head}. {line}",
                            slide=i, stat=stat, stat_label=label, extra={"caption": line}))
    pts = [re.split(r"\s*[:–-]\s+", slides[i].title)[0].strip().lower() for i in idx[:3] if slides[i].title]
    outro = "That's the summary. " + (f"The big themes: {', '.join(pts[:-1])} and {pts[-1]}. " if len(pts) > 1 else "") + \
        "Open the full deck for the detail."
    segs.append(Segment("outro", "Key takeaways", outro, extra={"points": [slides[i].title for i in idx[:4]]}))
    return segs


def ai_summary(cfg, slides: List[Slide], deck_name: str = "", k: int = 6) -> Optional[List[Segment]]:
    """One LLM call; returns None on any failure (caller uses builtin_summary). Respects the llm cooldown."""
    from .llm import ai_ok, chat, _parse_json
    if cfg is None or not getattr(cfg, "ready", False) or not ai_ok(cfg):
        return None
    idx = pick_slides(slides, k)
    deck = "\n\n".join(f"[{i}] {slides[i].full_text(with_notes=True)[:900]}" for i in idx)
    prompt = (f"Write a punchy 75-110 second video summary voiceover for this deck. Return JSON: "
              '{"intro": str, "points": [{"slide": int, "headline": str (max 7 words), "line": str (1-2 sentences, '
              '25-40 words, explain the so-what, do NOT copy slide text verbatim)}], "outro": str}. '
              f"Use the slide numbers in brackets, in order, at most {k} points.\n\n{deck}")
    try:
        raw = chat(cfg, [{"role": "user", "content": prompt}], temperature=0.5, max_tokens=1200, json_mode=True)
        d = _parse_json(raw)
        title = _deck_title(slides, deck_name)
        segs = [Segment("intro", title, str(d["intro"]).strip())]
        for p in d["points"][:k]:
            i = int(p["slide"])
            if not 0 <= i < len(slides):
                continue
            st_, lb = find_stat(slides[i], str(p.get("line", "")))
            segs.append(Segment("point", str(p.get("headline") or slides[i].title)[:70], str(p["line"]).strip(), slide=i,
                                stat=st_, stat_label=lb, extra={"caption": str(p["line"]).strip()}))
        segs.append(Segment("outro", "Key takeaways", str(d["outro"]).strip(),
                            extra={"points": [s.headline for s in segs if s.kind == "point"][:4]}))
        return segs if len(segs) >= 3 else None
    except Exception:
        return None


def build_summary(slides, deck_name="", cfg=None, k: int = 6) -> tuple[List[Segment], str]:
    segs = ai_summary(cfg, slides, deck_name, k)
    if segs:
        return segs, "AI summary"
    return builtin_summary(slides, deck_name, k), "built-in narrator (no AI)"


def script_text(segs: List[Segment]) -> str:
    return "\n\n".join(s.narration for s in segs)


# --------------------------------------------------------------------------- drawing helpers
def _glow_text(size_wh, xy, text, fnt, color=WHITE, glow=GREEN, radius=6, anchor="la") -> Image.Image:
    layer = Image.new("RGBA", size_wh, (0, 0, 0, 0))
    g = Image.new("RGBA", size_wh, (0, 0, 0, 0))
    ImageDraw.Draw(g).text(xy, text, font=fnt, fill=glow + (255,), anchor=anchor)
    g = g.filter(ImageFilter.GaussianBlur(radius))
    layer = Image.alpha_composite(layer, g)
    layer = Image.alpha_composite(layer, g)
    ImageDraw.Draw(layer).text(xy, text, font=fnt, fill=color + (255,), anchor=anchor)
    return layer


def _wrap(text: str, fnt, width: int, max_lines: int = 2) -> List[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if fnt.getlength(t) <= width:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
            if len(lines) == max_lines:
                break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    if len(lines) == max_lines and " ".join(lines) != text.strip():
        while lines[-1] and fnt.getlength(lines[-1] + "…") > width:
            lines[-1] = lines[-1][:-1]
        lines[-1] = lines[-1].rstrip() + "…"
    return lines


def _background(W, H) -> np.ndarray:
    """Black with a faint green perspective-free grid and vignette."""
    img = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(img)
    step = W // 24
    for x in range(0, W, step):
        d.line([(x, 0), (x, H)], fill=(10, 22, 4))
    for y in range(0, H, step):
        d.line([(0, y), (W, y)], fill=(10, 22, 4))
    a = np.asarray(img).astype(np.float32)
    yy, xx = np.mgrid[0:H, 0:W]
    v = 1 - 0.55 * (((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2) / 2
    a *= v[..., None]
    return a.clip(0, 255).astype(np.uint8)


def _scanlines(W, H) -> np.ndarray:
    m = np.ones((H, 1, 1), np.float32)
    m[::3] = 0.86
    return m


def _brackets(d: ImageDraw.ImageDraw, box, L=26, w=3, col=GREEN):
    x0, y0, x1, y1 = box
    for (x, y, dx, dy) in [(x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)]:
        d.line([(x, y), (x + dx * L, y)], fill=col, width=w)
        d.line([(x, y), (x, y + dy * L)], fill=col, width=w)


def _ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def _rgba_over(base: np.ndarray, layer: np.ndarray, x: int = 0, y: int = 0, alpha_mul: float = 1.0):
    """In-place alpha composite of an RGBA uint8 layer onto RGB base at (x, y)."""
    h, w = layer.shape[:2]
    H, W = base.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if x1 <= x0 or y1 <= y0 or alpha_mul <= 0:
        return
    L = layer[y0 - y:y1 - y, x0 - x:x1 - x]
    a = (L[..., 3:4].astype(np.float32) / 255.0) * alpha_mul
    roi = base[y0:y1, x0:x1].astype(np.float32)
    base[y0:y1, x0:x1] = (roi * (1 - a) + L[..., :3].astype(np.float32) * a).astype(np.uint8)


def _count_up(stat: str, p: float) -> str:
    m = re.search(r"\d[\d,]*(?:\.\d+)?", stat)
    if not m:
        return stat
    raw = m.group(0)
    val = float(raw.replace(",", ""))
    dec = len(raw.split(".")[1]) if "." in raw else 0
    cur = val * _ease(p)
    s = f"{cur:,.{dec}f}" if "," in raw else f"{cur:.{dec}f}"
    return stat[:m.start()] + s + stat[m.end():]


# --------------------------------------------------------------------------- renderer
class Renderer:
    def __init__(self, W, H, fps, deck_title: str, lang_label: str = ""):
        self.W, self.H, self.fps = W, H, fps
        self.k = W / 1280
        self.bg = _background(W, H)
        self.scan = _scanlines(W, H)
        self.title = deck_title
        self.lang = lang_label
        self.f_hud = font(int(15 * self.k), "mono")

    def s(self, v):
        return int(v * self.k)

    # static HUD chrome (top bar text, frame ticks) as RGBA
    def chrome(self, label: str, idx: int, total: int) -> np.ndarray:
        W, H, s = self.W, self.H, self.s
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.ellipse([s(28), s(26), s(40), s(38)], fill=GREEN + (255,))
        d.text((s(50), s(23)), f"DECK//SUMMARY  ·  {self.title[:48].upper()}", font=self.f_hud, fill=(200, 200, 200, 255))
        d.text((W - s(28), s(23)), f"{label}  {idx:02d}/{total:02d}", font=self.f_hud, fill=GREEN + (255,), anchor="ra")
        d.line([(s(28), s(50)), (W - s(28), s(50))], fill=GREEN + (90,), width=1)
        d.line([(s(28), H - s(30)), (W - s(28), H - s(30))], fill=GREEN + (60,), width=1)
        for i in range(0, 40):
            x = s(28) + i * (W - s(56)) // 40
            d.line([(x, H - s(30)), (x, H - s(30) - (s(8) if i % 5 == 0 else s(4)))], fill=GREEN + (110,), width=1)
        if self.lang:
            d.text((s(28), H - s(26)), f"VOICE: {self.lang.upper()}", font=self.f_hud, fill=(120, 120, 120, 255))
        return np.asarray(im)

    def frames(self, seg: Segment, slides: List[Slide], idx: int, total: int):
        dur = seg.seconds
        n = max(1, int(round(dur * self.fps)))
        if seg.kind == "point":
            yield from self._point(seg, slides[seg.slide], idx, total, n)
        else:
            yield from self._card(seg, idx, total, n)

    # ----- slide segment: Ken Burns image panel + HUD title + stat callout
    def _point(self, seg: Segment, slide: Slide, idx, total, n):
        W, H, s, fps = self.W, self.H, self.s, self.fps
        pw, ph = s(800), s(450)
        px, py = s(56), s(130)
        src = None
        if slide.image_path and os.path.exists(slide.image_path):
            src = Image.open(slide.image_path).convert("RGB")
            r = max(pw * 1.25 / src.width, ph * 1.25 / src.height)
            src = src.resize((int(src.width * r), int(src.height * r)), Image.LANCZOS)
        # Ken Burns direction alternates per segment
        z0, z1 = (1.0, 1.12) if idx % 2 else (1.12, 1.0)
        dx = 1 if idx % 3 else -1
        # static layers
        chrome = self.chrome("POINT", idx, total)
        frame = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        fd = ImageDraw.Draw(frame)
        fd.rectangle([px - 2, py - 2, px + pw + 1, py + ph + 1], outline=GREEN + (120,), width=1)
        _brackets(fd, (px - s(10), py - s(10), px + pw + s(9), py + ph + s(9)), L=s(26), w=max(2, s(3)), col=GREEN + (255,))
        frame = np.asarray(frame)
        f_title = font(s(38), True)
        tlines = _wrap(seg.headline, f_title, W - s(112), 1)
        title = np.asarray(_glow_text((W, s(70)), (s(56), s(8)), tlines[0] if tlines else "", f_title, radius=s(7)))
        # right column: stat callout + narration caption
        cx, cw = px + pw + s(36), W - (px + pw + s(36)) - s(40)
        f_stat = font(s(64), True)
        f_lab = font(s(19))
        f_cap = font(s(20))
        cap = _wrap(seg.extra.get("caption") or seg.narration, f_cap, cw, 9)
        cap_layer = Image.new("RGBA", (cw, s(330)), (0, 0, 0, 0))
        cd = ImageDraw.Draw(cap_layer)
        for k, line in enumerate(cap):
            cd.text((0, k * s(29)), line, font=f_cap, fill=(225, 225, 225, 255))
        cap_layer = np.asarray(cap_layer)
        lab = np.asarray(self._label(seg.stat_label or "KEY FIGURE", f_lab, cw)) if seg.stat else None
        stat_cache = {}
        T_in, T_out = int(0.5 * fps), int(0.45 * fps)
        for f in range(n):
            t = f / fps
            p = f / max(1, n - 1)
            img = self.bg.copy()
            # Ken Burns panel
            if src is not None:
                z = z0 + (z1 - z0) * _ease(p)
                base_w = min(src.width, src.height * pw / ph)
                cwin, chin = base_w / z, base_w / z * ph / pw
                ox = (src.width - cwin) / 2 + dx * (src.width - cwin) / 2 * (p - 0.5) * 1.6
                oy = (src.height - chin) / 2 + (src.height - chin) / 2 * (0.5 - p) * 1.2
                ox = min(max(0.0, ox), src.width - cwin); oy = min(max(0.0, oy), src.height - chin)
                crop = src.resize((pw, ph), Image.BILINEAR, box=(ox, oy, ox + cwin, oy + chin))
                panel = np.asarray(crop).astype(np.float32) * 0.92
                img[py:py + ph, px:px + pw] = panel.astype(np.uint8)
            # sweeping highlight line over panel
            sy = py + int((t * 0.35 % 1.0) * ph)
            img[sy:sy + 2, px:px + pw] = (img[sy:sy + 2, px:px + pw] * 0.4 + np.array(GREEN) * 0.6).astype(np.uint8)
            _rgba_over(img, frame)
            _rgba_over(img, chrome)
            # title: slide-in + wipe reveal
            pt = _ease((t - 0.15) / 0.6)
            if pt > 0:
                wv = int(W * pt)
                _rgba_over(img, title[:, :max(1, wv)], int(-30 * (1 - pt)), s(62))
            # stat callout: box grows, number counts up
            if seg.stat:
                ps = _ease((t - 0.6) / 0.5)
                if ps > 0:
                    bh = s(150)
                    by = py
                    bw = int(cw * ps)
                    img[by:by + bh, cx:cx + bw] = (img[by:by + bh, cx:cx + bw] * 0.3 + np.array((14, 26, 4)) * 0.7).astype(np.uint8)
                    img[by:by + bh, cx:cx + max(1, s(4))] = GREEN
                    txt = _count_up(seg.stat, (t - 0.7) / 1.3)
                    if txt not in stat_cache:
                        stat_cache[txt] = np.asarray(_glow_text((cw, s(90)), (s(18), s(6)), txt, f_stat, radius=s(8)))
                    _rgba_over(img, stat_cache[txt][:, :max(1, bw)], cx, by + s(10), ps)
                    _rgba_over(img, lab, cx + s(18), by + s(100), ps)
                cy = py + s(180)
            else:
                cy = py
            # caption fades in line by line
            pc = _ease((t - 0.9) / 1.2)
            if pc > 0:
                rows = max(1, int(cap_layer.shape[0] * min(1.0, pc * 1.4)))
                _rgba_over(img, cap_layer[:rows], cx, cy, pc)
            # scanlines + moving glow band
            img = self._post(img, t)
            # transitions: fade + green sweep line
            img = self._edge(img, f, n, T_in, T_out)
            yield img

    def _label(self, text, fnt, width):
        im = Image.new("RGBA", (width, int(fnt.size * 1.5)), (0, 0, 0, 0))
        lines = _wrap(text.upper(), fnt, width - 20, 1)
        ImageDraw.Draw(im).text((0, 0), lines[0] if lines else "", font=fnt, fill=(170, 170, 170, 255))
        return im

    # ----- intro / outro cards
    def _card(self, seg: Segment, idx, total, n):
        W, H, s, fps = self.W, self.H, self.s, self.fps
        chrome = self.chrome("INTRO" if seg.kind == "intro" else "OUTRO", idx, total)
        f_big = font(s(54), True)
        f_sub = font(s(22), "mono")
        f_pt = font(s(24))
        lines = _wrap(seg.headline, f_big, W - s(220), 2)
        big = Image.new("RGBA", (W, s(160)), (0, 0, 0, 0))
        for k, ln in enumerate(lines):
            big = Image.alpha_composite(big, _glow_text((W, s(160)), (W // 2, s(10) + k * s(70)), ln, f_big, radius=s(9), anchor="ma"))
        big = np.asarray(big)
        sub_txt = "VIDEO SUMMARY  //  AUTO-GENERATED BRIEFING" if seg.kind == "intro" else "END OF BRIEFING  //  THANK YOU"
        sub = Image.new("RGBA", (W, s(40)), (0, 0, 0, 0))
        ImageDraw.Draw(sub).text((W // 2, 0), sub_txt, font=f_sub, fill=GREEN + (255,), anchor="ma")
        sub = np.asarray(sub)
        pts = []
        for k, ptxt in enumerate(seg.extra.get("points", [])[:4]):
            im = Image.new("RGBA", (W, s(40)), (0, 0, 0, 0))
            d = ImageDraw.Draw(im)
            d.rectangle([W // 2 - s(330), s(12), W // 2 - s(320), s(22)], fill=GREEN + (255,))
            d.text((W // 2 - s(305), s(2)), _wrap(ptxt, f_pt, s(620), 1)[0] if ptxt else "", font=f_pt, fill=(230, 230, 230, 255))
            pts.append(np.asarray(im))
        y0 = s(200) if not pts else s(120)
        T_in, T_out = int(0.5 * fps), int(0.6 * fps)
        cx, cy = W // 2, y0 + s(80)
        for f in range(n):
            t = f / fps
            img = self.bg.copy()
            # rotating HUD ring
            ring = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            rd = ImageDraw.Draw(ring)
            R = s(240) if not pts else s(170)
            a0 = (t * 40) % 360
            for k in range(6):
                rd.arc([cx - R, cy - R, cx + R, cy + R], a0 + k * 60, a0 + k * 60 + 34, fill=GREEN + (150,), width=max(2, s(3)))
            R2 = R + s(18)
            rd.arc([cx - R2, cy - R2, cx + R2, cy + R2], -a0 * 1.5, -a0 * 1.5 + 200, fill=GREEN + (60,), width=1)
            _rgba_over(img, np.asarray(ring))
            _rgba_over(img, chrome)
            pb = _ease(t / 0.9)
            if pb > 0:
                wv = max(1, int(W * pb))
                _rgba_over(img, big[:, :wv], 0, y0)
            ps = _ease((t - 0.6) / 0.6)
            _rgba_over(img, sub, 0, y0 + s(20) + len(lines) * s(70), ps)
            for k, layer in enumerate(pts):
                pk = _ease((t - 1.2 - 0.5 * k) / 0.5)
                _rgba_over(img, layer, int(-40 * (1 - pk) * self.k), y0 + s(200) + k * s(52), pk)
            img = self._post(img, t)
            img = self._edge(img, f, n, T_in, T_out)
            yield img

    def _post(self, img: np.ndarray, t: float) -> np.ndarray:
        out = img.astype(np.float32) * self.scan
        band_y = int((t * 0.22 % 1.0) * (self.H + 120)) - 60
        y0, y1 = max(0, band_y), min(self.H, band_y + 60)
        if y1 > y0:
            out[y0:y1] *= 1.12
            out[y0:y1, :, 1] += 6
        return out.clip(0, 255).astype(np.uint8)

    def _edge(self, img, f, n, T_in, T_out):
        if f < T_in:
            a = _ease(f / T_in)
            img = (img.astype(np.float32) * a).astype(np.uint8)
            y = int(self.H * (1 - a))
            img[max(0, y - 2):y + 1] = GREEN
        elif f >= n - T_out:
            a = _ease((n - f) / T_out)
            img = (img.astype(np.float32) * a).astype(np.uint8)
            y = int(self.H * (1 - a))
            img[max(0, y - 2):y + 1] = GREEN
        return img


# --------------------------------------------------------------------------- pipeline
STYLES = ["Holographic (cinematic)", "AI Presenter (robot)", "Classic HUD"]


def render_video(slides: List[Slide], segs: List[Segment], out_path: str, quality: str = "Fast (540p)",
                 lang_label: str = "", deck_title: str = "", style: str = STYLES[0],
                 photo: Optional[str] = None, presenter_name: str = "", progress: Optional[Callable[[float, str], None]] = None) -> dict:
    """Segments must have .audio set. Writes an MP4 (H.264 + AAC). Returns stats."""
    W, H, fps = QUALITY[quality]
    ff = ffmpeg_bin()
    t0 = time.time()
    work = Path(tempfile.mkdtemp(prefix="vsum_"))
    try:
        from .tts import duration_s
        for sg in segs:
            sg.seconds = round((duration_s(sg.audio) if sg.audio else 3.0) + (1.0 if sg.kind != "point" else 0.8), 2)
        # audio track: each clip padded to its segment length, then concatenated
        audio = work / "track.m4a"
        args = [ff, "-y", "-loglevel", "error"]
        for sg in segs:
            args += ["-i", sg.audio]
        fc = "".join(f"[{i}:a]aresample=44100,aformat=channel_layouts=mono,adelay=250,apad,atrim=0:{sg.seconds}[a{i}];"
                     for i, sg in enumerate(segs))
        fc += "".join(f"[a{i}]" for i in range(len(segs))) + f"concat=n={len(segs)}:v=0:a=1[out]"
        subprocess.run(args + ["-filter_complex", fc, "-map", "[out]", "-c:a", "aac", "-b:a", "128k", str(audio)],
                       check=True, capture_output=True, timeout=300)
        total_frames = sum(int(round(sg.seconds * fps)) or 1 for sg in segs)
        proc = subprocess.Popen([ff, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                                 "-r", str(fps), "-i", "-", "-i", str(audio), "-c:v", "libx264", "-preset", "veryfast",
                                 "-crf", "23", "-pix_fmt", "yuv420p", "-c:a", "copy", "-shortest", "-movflags", "+faststart",
                                 out_path], stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        if style.startswith("Classic"):
            r = Renderer(W, H, fps, deck_title or _deck_title(slides), lang_label)
        else:
            from .video_fx import HoloRenderer
            r = HoloRenderer(W, H, fps, deck_title or _deck_title(slides), lang_label, presenter=style.startswith("AI"),
                             photo=photo, presenter_name=presenter_name)
        done = 0
        try:
            for k, sg in enumerate(segs):
                for frame in r.frames(sg, slides, k + 1, len(segs)):
                    proc.stdin.write(frame.tobytes())
                    done += 1
                    if progress and done % fps == 0:
                        progress(min(0.999, done / total_frames), f"Rendering frames {done}/{total_frames}")
            proc.stdin.close()
        except BrokenPipeError:
            pass
        err = proc.stderr.read().decode(errors="ignore")
        if proc.wait() != 0:
            raise RuntimeError(f"ffmpeg failed: {err[-400:]}")
        dur = sum(sg.seconds for sg in segs)
        return {"seconds": round(dur, 1), "frames": done, "render_s": round(time.time() - t0, 1), "size": f"{W}x{H}@{fps}", "style": style,
                "path": out_path}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def make_video_summary(slides: List[Slide], out_path: str, *, deck_name: str = "", cfg=None, lang: str = "English (US)",
                       voice: Optional[str] = None, rate: int = 0, pitch: int = 0, engine: Optional[str] = None,
                       keys: Optional[dict] = None, quality: str = "Fast (540p)", k: int = 6, translate_fn=None, style: str = STYLES[0],
                       photo: Optional[str] = None, presenter_name: str = "",
                       progress: Optional[Callable[[float, str], None]] = None) -> dict:
    """Full pipeline: script -> (translate) -> voice -> frames -> MP4. progress(fraction, text)."""
    from .tts import ENGINES, synthesize
    prog = progress or (lambda *_: None)
    t0 = time.time()
    prog(0.02, "Writing the summary script…")
    segs, source = build_summary(slides, deck_name, cfg, k)
    notes = []
    if translate_fn:
        for sg in segs:
            try:
                sg.narration = translate_fn(sg.narration)
            except Exception as e:  # noqa
                notes.append(f"translation failed for one segment ({str(e)[:80]}); kept original")
    from concurrent.futures import ThreadPoolExecutor
    prog(0.05, f"Recording voiceover ({len(segs)} parts)…")

    def _voice(sg):
        return synthesize(sg.narration, lang, voice, rate, pitch, 250, 500, engine or ENGINES[0], keys or {})
    with ThreadPoolExecutor(max_workers=4) as ex:
        for j, (sg, a) in enumerate(zip(segs, ex.map(_voice, segs))):
            sg.audio = a["path"]
            if a.get("warning"):
                notes.append(a["warning"])
            prog(0.05 + 0.2 * (j + 1) / len(segs), f"Voiceover {j + 1}/{len(segs)} ready")
    t_audio = time.time() - t0
    st = render_video(slides, segs, out_path, quality, lang, _deck_title(slides, deck_name), style=style, photo=photo, presenter_name=presenter_name,
                      progress=lambda f, m: prog(0.25 + 0.75 * f, m))
    prog(1.0, "Done")
    st.update(script=script_text(segs), source=source, notes=sorted(set(notes)), total_s=round(time.time() - t0, 1),
              audio_s=round(t_audio, 1), segments=[{"kind": s.kind, "headline": s.headline, "slide": s.slide, "stat": s.stat,
                                                    "seconds": s.seconds} for s in segs])
    return st
