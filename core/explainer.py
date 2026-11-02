"""Animated Explainer style (the default video summary look): each slide is rebuilt as an
animated motion-graphic scene (counters, bar/line/donut charts, grouped comparison columns, a country map, or icon cards).

Rules:
* Only data that is in the deck is shown. Scene data comes from the slide's chart series, table cells, title and
  bullets; nothing is estimated or filled in. plan_scene() is pure and unit-tested.
* Everything is procedural (PIL + numpy) and needs no key. The map uses the bundled Natural Earth 1:110m countries
  (public domain) in assets/ne_110m_countries.json.
"""
from __future__ import annotations

import json
import math
import os
import re
from functools import lru_cache
from typing import List, Optional

import numpy as np
from PIL import Image, ImageDraw

from .sectors import SECTORS, draw_icon as sector_icon, icon_for_sentence, backdrop_layers, rig, transition, render_icon
from .flat_art import art_for, back_out, draw_art, mood_for, person, squash
from .video_fx import EYE, HoloRenderer, _glitch_layer, bloom, envelope, glitch
from .video_summary import GREEN, STAT_RE, Segment, _count_up, _ease, _rgba_over, _wrap, font

ASSET = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "ne_110m_countries.json")
GREEN2 = (70, 110, 28)
PALE = (205, 225, 190)
SHADES = [(134, 188, 37), (196, 255, 96), (88, 130, 30), (160, 210, 120), (60, 92, 22), (225, 245, 200), (110, 160, 50), (40, 70, 15)]
COMPARE_RE = re.compile(r"(?i)\b(vs\.?|versus|compared (to|with)|comparison|head[- ]to[- ]head)\b")


# --------------------------------------------------------------------------- data helpers (pure)
def num(cell) -> Optional[float]:
    """Value of a cell that is a single number ('USD 1.6B', '28%', '1,200'); None for text or mixed cells."""
    s = str(cell or "").strip()
    m = re.fullmatch(r"(?i)(?:[a-z]{0,3}\s?)?[$€£₹~≈]?\s?(-?\d[\d,]*(?:\.\d+)?)\s?(%|x|bn|mn|b|m|k|t|cr|crore|lakh|million|billion)?\+?", s)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def visible_lines(slide) -> List[str]:
    return [slide.title or ""] + list(slide.bullets) + [" | ".join(str(c) for c in r) for t in slide.tables for r in t]


def kpis(slide, k: int = 3) -> List[dict]:
    """Numbers printed on the slide (title/bullets) paired with the exact line they came from.
    One number per line (the first qualifying one), so a value is never shown next to someone else's sentence.
    Years and tiny bare numbers are skipped."""
    out, seen = [], set()
    for line in [slide.title or ""] + list(slide.bullets):
        for m in STAT_RE.finditer(line):
            tok = m.group(1).strip()
            st, end = m.start(1), m.end()
            if line[end:end + 1] == "+":
                tok, end = tok + "+", end + 1
            if st > 0 and line[st - 1] == "~":
                tok = "~" + tok
            if re.fullmatch(r"(19|20)\d\d", tok) or not re.search(r"\d", tok) or tok in seen:
                continue
            if not re.search(r"[%$€£₹]|\d{2,}|\d\.\d|bn|B\b|M\b|K\b|T\b|x\b|million|billion|crore|lakh", tok):
                continue          # skip tiny bare numbers like '3' or '2'
            out.append({"value": tok, "label": re.sub(r"\s+", " ", line).strip()})
            seen.add(tok)
            break
    return out[:k]


@lru_cache(maxsize=1)
def geo():
    with open(ASSET) as f:
        return json.load(f)["countries"]


_SHORT = {"US": "United States of America", "USA": "United States of America", "U.S.": "United States of America",
          "UK": "United Kingdom", "UAE": "United Arab Emirates", "KSA": "Saudi Arabia"}


def find_countries(text: str, limit: int = 3) -> List[str]:
    """Country names (Natural Earth NAME) mentioned in text, in order of first mention."""
    found = {}
    for c in geo():
        for a in set(c["aliases"] + [c["name"]]):
            if len(a) < 4:
                continue
            m = re.search(r"(?<![\w])" + re.escape(a) + r"(?:'s)?(?![\w])", text)
            if m:
                found[c["name"]] = min(found.get(c["name"], 1e9), m.start())
    for k, v in _SHORT.items():
        m = re.search(r"(?<![\w.])" + re.escape(k) + r"(?![\w])", text)
        if m:
            found[v] = min(found.get(v, 1e9), m.start())
    return [n for n, _ in sorted(found.items(), key=lambda x: x[1])][:limit]


def _mention_times(labels: List[str], narration: str) -> List[float]:
    """Fraction (0..1) of the narration where each label is first mentioned, or -1."""
    low, n = narration.lower(), max(1, len(narration))
    out = []
    for lb in labels:
        words = [w for w in re.findall(r"[\w%.$]+", lb.lower()) if len(w) >= 3 and not w.isdigit()] or [lb.lower()]
        pos = [low.find(w) for w in words[:3] if low.find(w) >= 0]
        out.append(min(pos) / n if pos else -1.0)
    return out


def plan_scene(slide, narration: str = "", deck_title: str = "") -> dict:
    """Pick the scene for a slide from its content. Values are copied from the deck, never invented.
    deck_title only adds context countries (e.g. 'Entering India's ...') to a slide that already names a country."""
    title = slide.title or ""
    text = "\n".join(visible_lines(slide))
    # 1) chart data
    for ch in slide.charts:
        cats = [str(c) for c in (ch.get("categories") or [])]
        series = [s for s in ch.get("series", []) if sum(isinstance(v, (int, float)) for v in s.get("values", [])) >= 2]
        if not series:
            continue
        typ = str(ch.get("type", "")).upper()
        if len(series) >= 2 and len(cats) <= 6:
            k = min(len(cats), *(len(s["values"]) for s in series[:2]))
            return {"kind": "compare", "labels": cats[:k] or [f"#{i + 1}" for i in range(k)],
                    "series": [{"name": s.get("name") or f"Series {j + 1}", "values": [float(v or 0) for v in s["values"][:k]]}
                               for j, s in enumerate(series[:2])], "source": "chart"}
        s0 = series[0]
        vals = [float(v) if isinstance(v, (int, float)) else None for v in s0["values"]]
        labels = (cats + [""] * len(vals))[:len(vals)]
        pairs = [(lb, v) for lb, v in zip(labels, vals) if v is not None][:10]
        kind = "donut" if ("PIE" in typ or "DOUGHNUT" in typ) else "line" if "LINE" in typ else "bar"
        return {"kind": kind, "labels": [p[0] for p in pairs], "values": [p[1] for p in pairs],
                "name": s0.get("name") or ch.get("title") or "", "source": "chart"}
    # 2) tables
    for t in slide.tables:
        if len(t) < 2:
            continue
        head, rows = [str(c) for c in t[0]], [[str(c) for c in r] for r in t[1:]]
        ncol = max(len(r) for r in t)
        numcols = [j for j in range(1, ncol) if sum(num(r[j]) is not None for r in rows if j < len(r)) >= max(2, len(rows) - 1)]
        if len(numcols) >= 2 and len(rows) <= 6:
            js = numcols[:2]
            keep = [r for r in rows if all(j < len(r) and num(r[j]) is not None for j in js)]
            if len(keep) >= 2:
                return {"kind": "compare", "labels": [r[0] for r in keep],
                        "series": [{"name": head[j] if j < len(head) else f"Col {j}", "values": [num(r[j]) for r in keep],
                                    "text": [r[j] for r in keep]} for j in js], "source": "table"}
        if numcols:
            j = numcols[0]
            keep = [r for r in rows if j < len(r) and num(r[j]) is not None][:10]
            return {"kind": "bar", "labels": [r[0] for r in keep], "values": [num(r[j]) for r in keep],
                    "text": [r[j] for r in keep], "name": head[j] if j < len(head) else "", "source": "table"}
        cards = [": ".join(c for c in r[:2] if c) for r in rows][:4]
        return {"kind": "cards", "items": cards, "source": "table"}
    # 3) a titled comparison ("Brazil vs Mexico") with two printed numbers
    ks0 = kpis(slide, 3)
    if len(ks0) >= 2 and COMPARE_RE.search(title or ""):
        return {"kind": "versus", "stats": ks0[:2], "source": "text"}
    # 4) countries
    cs = find_countries(text)
    if cs:
        cs = ([c for c in find_countries(deck_title) if c not in cs] + cs)[:3]  # deck subject first; slide mentions (e.g. a US benchmark) after
        return {"kind": "country", "countries": cs, "stats": kpis(slide, 3),
                "facts": [b for b in slide.bullets if not any(x["value"] in b for x in kpis(slide, 3))][:2], "source": "text"}
    ks = kpis(slide, 3)
    # 4) comparison of two printed numbers
    if len(ks) >= 2 and COMPARE_RE.search(text):
        return {"kind": "versus", "stats": ks[:2], "source": "text"}
    # 5) KPI counters
    if ks:
        return {"kind": "kpi", "stats": ks, "source": "text"}
    # 6) icon cards
    items = [b for b in slide.bullets if b.strip()][:4] or ([title] if title else [])
    return {"kind": "cards", "items": items, "source": "text"}


ICON_WORDS = [("money", r"usd|\$|₹|revenue|cost|price|profit|margin|invest|fund|capex|budget|sales|market"),
              ("people", r"people|patient|customer|user|staff|team|hire|population|citizen|talent"),
              ("growth", r"grow|cagr|increase|rise|up\b|expand|scale|%"),
              ("health", r"health|hospital|clinic|diagnos|medical|care|scan|mri|ct\b|ultrasound"),
              ("globe", r"country|global|india|region|city|cities|nation|world|export|international"),
              ("gear", r"service|operation|network|install|process|supply|platform|tech"),
              ("target", r"goal|target|plan|phase|strategy|aim|focus|priority"),
              ("time", r"year|month|fy\d|timeline|week|day|by 20")]


def icon_for(text: str) -> str:
    t = text.lower()
    for name, rx in ICON_WORDS:
        if re.search(rx, t):
            return name
    return "check"


def draw_icon(d: ImageDraw.ImageDraw, kind: str, cx: float, cy: float, r: float, col=EYE, w: int = 2):
    """Small line icons drawn procedurally."""
    def L(*pts):
        d.line([(cx + x * r, cy + y * r) for x, y in pts], fill=col, width=w, joint="curve")
    if kind == "money":
        d.ellipse([cx - r * .8, cy - r * .8, cx + r * .8, cy + r * .8], outline=col, width=w)
        L((0, -.55), (0, .55)); L((.3, -.32), (-.25, -.32), (-.3, -.05), (.3, .05), (.25, .32), (-.3, .32))
    elif kind == "people":
        for dx, s in ((-.38, .7), (.38, .7), (0, 1)):
            d.ellipse([cx + (dx - .18 * s) * r, cy - .62 * s * r, cx + (dx + .18 * s) * r, cy - .26 * s * r], outline=col, width=w)
            d.arc([cx + (dx - .38 * s) * r, cy - .12 * r, cx + (dx + .38 * s) * r, cy + .7 * r], 180, 360, fill=col, width=w)
    elif kind == "growth":
        L((-.8, .6), (-.3, .1), (.05, .35), (.75, -.45)); L((.35, -.45), (.75, -.45), (.75, -.05))
    elif kind == "health":
        d.rounded_rectangle([cx - .75 * r, cy - .75 * r, cx + .75 * r, cy + .75 * r], radius=int(r * .2), outline=col, width=w)
        L((0, -.42), (0, .42)); L((-.42, 0), (.42, 0))
    elif kind == "globe":
        d.ellipse([cx - .8 * r, cy - .8 * r, cx + .8 * r, cy + .8 * r], outline=col, width=w)
        d.ellipse([cx - .35 * r, cy - .8 * r, cx + .35 * r, cy + .8 * r], outline=col, width=w)
        L((-.8, 0), (.8, 0))
    elif kind == "gear":
        for k in range(8):
            a = k * math.pi / 4
            L((.55 * math.cos(a), .55 * math.sin(a)), (.85 * math.cos(a), .85 * math.sin(a)))
        d.ellipse([cx - .55 * r, cy - .55 * r, cx + .55 * r, cy + .55 * r], outline=col, width=w)
        d.ellipse([cx - .2 * r, cy - .2 * r, cx + .2 * r, cy + .2 * r], outline=col, width=w)
    elif kind == "target":
        for q in (.8, .5, .2):
            d.ellipse([cx - q * r, cy - q * r, cx + q * r, cy + q * r], outline=col, width=w)
    elif kind == "time":
        d.ellipse([cx - .8 * r, cy - .8 * r, cx + .8 * r, cy + .8 * r], outline=col, width=w)
        L((0, -.5), (0, 0), (.38, .2))
    else:
        L((-.5, 0), (-.12, .4), (.6, -.45))


def _fmt(v: float) -> str:
    return f"{v:,.0f}" if abs(v) >= 100 or float(v).is_integer() else f"{v:,.1f}" if abs(v) >= 10 else f"{v:g}"


# --------------------------------------------------------------------------- renderer
class FadeDraw(ImageDraw.ImageDraw):
    """PIL ignores the alpha of text drawn onto an RGB frame, so fades popped in. This blends translucent text
    toward the dark backdrop instead (and skips fully transparent text)."""
    BG = (16, 20, 15)

    def __init__(self, im):
        super().__init__(im, "RGBA")

    def text(self, xy, text, fill=None, *a, **k):
        if isinstance(fill, tuple) and len(fill) == 4 and fill[3] < 255:
            al = fill[3] / 255
            if al <= 0.02:
                return
            fill = tuple(int(c * al + b * (1 - al)) for c, b in zip(fill[:3], self.BG))
        return super().text(xy, text, fill, *a, **k)


class ExplainerRenderer(HoloRenderer):
    """Character-free animated explainer. A light beam/cursor points at the item being narrated."""

    def __init__(self, W, H, fps, deck_title: str, lang_label: str = "", hook: Optional[dict] = None, seed: int = 11,
                 sector: str = "General"):
        super().__init__(W, H, fps, deck_title, lang_label, presenter=False, seed=seed)
        self.hook = hook or {}
        self.sector = sector if sector in SECTORS else "General"
        self.sec = SECTORS[self.sector]
        self.ss = 2 if H <= 720 else 1.5      # supersampling factor for character/illustration layers
        self._layers = None
        self.events: List[tuple] = []          # (time_s, kind) for the optional sound design
        self.f_lab = font(self.s(17))
        self.f_val = font(self.s(20), True)
        self.f_big = font(self.s(54), True)
        self.f_head = font(self.s(34), True)
        self.f_cap = font(self.s(20))
        self.f_capb = font(self.s(21), True)
        self._bg = None
        self.f_card = font(self.s(19))
        self._beam = None

    # ---------------- segments
    def frames(self, seg: Segment, slides, idx: int, total: int):
        n = max(1, int(round(seg.seconds * self.fps)))
        env = envelope(seg.audio, self.fps, n) if seg.audio else np.zeros(n, np.float32)
        self.events.append((self.T, "whoosh"))
        self.events.append((self.T + 0.05, self.sec["sfx"]))
        if seg.kind == "point":
            gen = self._scene(seg, slides[seg.slide], idx, total, n, env)
        elif seg.kind == "intro":
            gen = self._intro(seg, idx, total, n, env)
        else:
            gen = self._outro(seg, idx, total, n, env)
        for img in gen:
            yield img
        self.T += n / self.fps

    def _intro(self, seg: Segment, idx, total, n, env):
        """Cold open (first ~5 s): the deck's most striking real number slams in over sector art, then the title."""
        W, H, s, fps = self.W, self.H, self.s, self.fps
        hv, hl = self.hook.get("value"), self.hook.get("label", "")
        words = (seg.headline or self.title or "").split()[:14]
        fT = font(s(46), True)
        lines, cur = [], []
        for w in words:
            if cur and fT.getlength(" ".join(cur + [w])) > W * 0.66:
                lines.append(cur); cur = []
            cur.append(w)
        if cur:
            lines.append(cur)
        lines = lines[:2]
        f_hl = font(s(22))
        hlines = _wrap(hl, f_hl, int(W * 0.74), 2) if hv else []
        fbig = font(s(120), True)
        icons = self.sec["icons"][:3]
        T_TITLE = 3.4 if hv else 0.4          # number owns the first ~3.4 s, then the title takes over
        icon_imgs = {}
        tag = (self.sector if self.sector != "General" else "BRIEFING").upper()
        for f in range(n):
            t = f / fps
            tt = self.T + t
            img = self.background(tt, -W * 0.1 * _ease(t / 4))
            pil = Image.fromarray(img)
            d = FadeDraw(pil)
            self.frame_hud(d, "OPEN", idx, total, t)
            mv = _ease((t - T_TITLE) / 0.6)    # 0 = hook centre stage, 1 = hook docked above title
            if hv:
                q = _ease((t - 0.15) / 0.9)
                if q > 0 and not self._hook_ev:
                    self.events.append((tt + 0.1, "tick")); self.events.append((tt + 0.95, "slam")); self._hook_ev = True
                sxq, syq = squash(min(1, max(0, (t - 1.0) / 0.3)))
                yb = H * (0.34 - 0.19 * mv)
                fb = fbig if mv < 0.5 else font(s(70), True)
                val = _count_up(hv, q) if q < 1 else hv
                d.text((W * (0.5 - 0.08 * mv), yb + s(30) * (1 - back_out(min(1, q * 1.2)))), val, font=fb, fill=EYE + (int(255 * min(1, q * 2)),), anchor="mm")
                if 0.95 < t < 1.4:      # impact ring
                    r = s(60) + s(500) * (t - 0.95)
                    d.ellipse([W / 2 - r, yb - r * 0.5, W / 2 + r, yb + r * 0.5], outline=GREEN + (int(220 * (1.4 - t) / 0.45),), width=s(4))
                la = _ease((t - 1.1) / 0.4) * (1 - mv)
                if la > 0:
                    for j, ln_ in enumerate(hlines):
                        d.text((W / 2, H * 0.47 + j * s(30)), ln_, font=f_hl, fill=(230, 236, 226, int(255 * la)), anchor="ma")
                    d.text((W / 2, H * 0.19), "COLD OPEN  //  " + tag, font=self.f_hud, fill=GREEN + (int(255 * la),), anchor="ma")
                # sector icons pop around the number
                for k, kind in enumerate(icons):
                    pk = (t - 1.25 - 0.18 * k) / 0.45
                    if pk > 0 and mv < 1:
                        sz = int(H * 0.27)
                        key = (kind, int(t * 8) % 8)
                        if key not in icon_imgs:
                            icon_imgs[key] = render_icon(kind, sz, t, 2)
                        ic = icon_imgs[key]
                        sc = back_out(min(1, pk)) * (1 - mv)
                        if sc > 0.05:
                            ic2 = ic.resize((max(1, int(ic.width * sc)), max(1, int(ic.height * sc))))
                            cx = W * (0.18 + 0.32 * k)
                            pil.paste(ic2, (int(cx - ic2.width / 2), int(H * 0.79 - ic2.height)), ic2)
            # title kinetic type
            top = H * (0.42 if hv else 0.36)
            lh = s(58)
            k = 0
            for li, ln_ in enumerate(lines):
                widths = [fT.getlength(w + " ") for w in ln_]
                x = W * 0.42 - sum(widths) / 2
                for w, wd in zip(ln_, widths):
                    qq = _ease((t - T_TITLE - 0.1 * k) / 0.4)
                    if qq > 0:
                        y = top + li * lh + s(30) * (1 - qq)
                        col = (255, 255, 255, int(255 * qq)) if not any(c.isdigit() for c in w) else EYE + (int(255 * qq),)
                        d.text((x, y), w, font=fT, fill=col)
                    x += wd
                    k += 1
            t_line = T_TITLE + 0.3 + 0.1 * k
            lw = W * 0.5 * _ease((t - t_line) / 0.5)
            yl = top + lh * len(lines) + s(14)
            if lw > 1:
                d.line([(W * 0.42 - lw / 2, yl), (W * 0.42 + lw / 2, yl)], fill=GREEN, width=s(3))
            sub = tag + " EXPLAINER  //  " + (self.lang or "").upper()
            if t > t_line:
                d.text((W * 0.42, yl + s(22)), sub, font=self.f_hud, fill=GREEN + (int(255 * _ease((t - t_line) / 0.5)),), anchor="ma")
            if t > T_TITLE:
                lay_w = int(H * 0.5)
                X = W * (0.86 - 0.0)
                lay = Image.new("RGBA", (int(lay_w * self.ss), int(lay_w * self.ss)), (0, 0, 0, 0))
                rig(ImageDraw.Draw(lay, "RGBA"), lay.width / 2, lay.height * 0.95, lay.height * 0.8, t, self.sector, "happy", "wave",
                    0, face=-1)
                lay = lay.resize((lay_w, lay_w), Image.LANCZOS)
                dy = int(H * 0.3 * (1 - back_out(min(1, (t - T_TITLE) / 0.6))))
                pil.paste(lay, (int(X - lay_w / 2), int(H * 0.8 - lay_w + dy)), lay)
            if t < 0.15:
                d.rectangle([0, 0, W, H], fill=(0, 0, 0, int(255 * (1 - t / 0.15))))
            yield np.asarray(pil)
        self._hook_ev = False

    def _outro(self, seg: Segment, idx, total, n, env):
        """Sector-themed end card: 'the bottom line' with the key slides as icon cards and the presenter waving off."""
        W, H, s, fps = self.W, self.H, self.s, self.fps
        pts = [p for p in seg.extra.get("points", []) if p][:4]
        f_t = font(s(44), True)
        f_p = font(s(20), True)
        tag = (self.sector if self.sector != "General" else "BRIEFING").upper()
        cw = W * 0.165
        gap = W * 0.02
        tw = len(pts) * cw + (len(pts) - 1) * gap if pts else 0
        icons = {}
        for f in range(n):
            t = f / fps
            tt = self.T + t
            img = self.background(tt, W * 0.1 * _ease(t / 3))
            pil = Image.fromarray(img)
            d = FadeDraw(pil)
            self.frame_hud(d, "END", idx, total, t)
            q = _ease(t / 0.5)
            d.text((W * 0.06, H * 0.1 + s(20) * (1 - q)), "THE BOTTOM LINE", font=f_t, fill=(255, 255, 255, int(255 * q)))
            d.line([(W * 0.06, H * 0.1 + s(56)), (W * 0.06 + s(200) * q, H * 0.1 + s(56))], fill=GREEN, width=s(4))
            x = W * 0.06
            for k, ptxt in enumerate(pts):
                pk = (t - 0.5 - 0.35 * k) / 0.5
                if pk > 0:
                    if k == 0 or pk < 0.05:
                        pass
                    sc = back_out(min(1, pk))
                    y = H * 0.3 + s(40) * (1 - sc)
                    h = H * 0.42
                    d.rounded_rectangle([x + s(4), y + s(6), x + cw + s(4), y + h + s(6)], radius=s(14), fill=(0, 0, 0, 120))
                    d.rounded_rectangle([x, y, x + cw, y + h], radius=s(14), fill=(24, 30, 22, int(250 * min(1, pk * 2))), outline=GREEN, width=s(2))
                    d.text((x + s(14), y + s(10)), f"{k + 1:02d}", font=self.f_val, fill=GREEN)
                    kind = icon_for_sentence(self.sector, ptxt, k)
                    key = (kind, int(t * 6) % 6)
                    if key not in icons:
                        icons[key] = render_icon(kind, int(h * 0.42), t, 2)
                    ic = icons[key]
                    pil.paste(ic, (int(x + cw / 2 - ic.width / 2), int(y + h * 0.1)), ic)
                    for j, ln_ in enumerate(_wrap(ptxt, f_p, int(cw - s(24)), 4)):
                        d.text((x + s(12), y + h * 0.56 + j * s(24)), ln_, font=f_p, fill=(236, 240, 232))
                    if 0 < pk < 0.15 and not getattr(self, "_oev", set()).__contains__(k):
                        self._oev = getattr(self, "_oev", set()) | {k}; self.events.append((tt, "pop"))
                x += cw + gap
            # presenter waves goodbye on the right
            lay_w = int(H * 0.5)
            lay = Image.new("RGBA", (int(lay_w * self.ss), int(lay_w * self.ss)), (0, 0, 0, 0))
            rig(ImageDraw.Draw(lay, "RGBA"), lay.width / 2, lay.height * 0.95, lay.height * 0.8, t, self.sector, "happy",
                "wave" if t > 1.0 else "idle", 0, face=-1)
            lay = lay.resize((lay_w, lay_w), Image.LANCZOS)
            dx = int(W * 0.25 * (1 - _ease((t - 0.3) / 0.8)))
            pil.paste(lay, (int(W * 0.89 - lay_w / 2 + dx), int(H * 0.8 - lay_w)), lay)
            ft = _ease((t - 0.8) / 0.5)
            d.text((W * 0.06, H * 0.79 + s(8)), f"{tag}  //  {self.title[:60].upper()}", font=self.f_hud, fill=GREEN + (int(255 * ft),))
            d.text((W * 0.06, H * 0.83 + s(8)), "Figures shown are from the deck. Generated by Deck Narrator.", font=self.f_cap,
                   fill=(170, 180, 166, int(255 * ft)))
            fo = _ease((t - (n / fps - 0.6)) / 0.6)
            if fo > 0:
                d.rectangle([0, 0, W, H], fill=(0, 0, 0, int(255 * fo)))
            transition(d, self.sec["motif"], W, H, _ease(t / 0.5), self.sec["accent"])
            yield np.asarray(pil)

    _hook_ev = False

    def background(self, t, ox=0.0):
        """Flat near-black backdrop with two sector-themed parallax layers (far skyline/motif, near floor strip)."""
        W, H = self.W, self.H
        if self._layers is None:
            y = np.linspace(0, 1, H)[:, None, None]
            base = np.array([12, 14, 12], np.float32) + np.array([4, 10, 2], np.float32) * y
            far, near = backdrop_layers(self.sector, W, H)
            fa = np.asarray(far, np.float32)
            wide = np.repeat(base, far.width, axis=1)
            a = fa[..., 3:4] / 255 * 0.85
            wide = wide * (1 - a) + fa[..., :3] * a
            na = np.asarray(near, np.float32)
            y0 = int(H * 0.79)
            self._layers = (wide.astype(np.uint8), na[y0:, :, :3], na[y0:, :, 3:4] / 255, y0, far.width)
        wide, nrgb, na, y0, LW = self._layers
        span = LW - W
        fx = int((span * 0.5 + ox * 0.15 + t * self.s(6)) % span)
        img = wide[:, fx:fx + W].copy()
        nx = int((span * 0.5 + ox * 0.45 + t * self.s(14)) % span)
        seg = img[y0:].astype(np.float32)
        img[y0:] = (seg * (1 - na[:, nx:nx + W]) + nrgb[:, nx:nx + W] * na[:, nx:nx + W]).astype(np.uint8)
        return img

    def particles(self, img, t, near=False):   # flat style: no particle field
        return None

    @staticmethod
    def sentences(text):
        out = [x.strip() for x in re.split(r"(?<=[.!?।])\s+", text or "") if x.strip()]
        return out or [text or ""]

    def _beats(self, narration, D):
        ss = self.sentences(narration)
        t0, t1 = 0.3, max(0.8, D - 0.8)
        tot = sum(len(x) for x in ss) or 1
        out, acc = [], t0
        for x in ss:
            dur = (t1 - t0) * len(x) / tot
            out.append((acc, acc + dur, x))
            acc += dur
        return out

    def _beat_panel(self, pil, beats, t, ox, D):
        """Per-sentence beat: a sector icon bounces onto a little stage and the presenter walks in and points at it.
        Drawn on a supersampled layer (anti-aliased), then composited."""
        W, H = self.W, self.H
        cur = 0
        for i, (a, _, _) in enumerate(beats):
            if t >= a:
                cur = i
        a, _, sent = beats[cur]
        x0, y0, x1, y1 = int(W * 0.655), int(H * 0.17), int(W * 0.995), int(H * 0.79)
        ss = self.ss
        lw, lh = int((x1 - x0) * ss), int((y1 - y0) * ss)
        lay = Image.new("RGBA", (lw, lh), (0, 0, 0, 0))
        d = ImageDraw.Draw(lay, "RGBA")
        L = lambda X, Y: ((X - x0 + ox) * ss, (Y - y0) * ss)
        size = H * 0.3
        gx, gy = L(W * 0.79, H * 0.66)
        # stage
        d.ellipse([gx - size * 0.62 * ss, gy - size * 0.07 * ss, gx + size * 0.62 * ss, gy + size * 0.07 * ss], fill=(30, 44, 22, 255), outline=GREEN + (255,), width=max(1, int(2 * ss)))
        p = (t - a) / 0.5
        if p > 0:
            sc = back_out(min(1, p))
            sx, sy = squash(min(1, max(0, (t - a - 0.3) / 0.35)))
            u = size / 100 * ss * sc
            kind = icon_for_sentence(self.sector, sent, cur)
            if u > 0.05:
                sector_icon(d, kind, gx, gy - size * 0.04 * ss, u * sy, t)
        # presenter: walks in during the first beat, then idles / points / reacts
        walk_in = _ease((t - 0.2) / 1.2)
        px = W * (1.08 - 0.17 * walk_in)
        walking = 1.0 if 0.2 < t < 1.4 else 0.0
        leaving = t > D - 0.9
        if leaving:
            px += W * 0.2 * _ease((t - (D - 0.9)) / 0.8); walking = 1.0
        pm = mood_for(sent)
        pm = "wow" if pm == "neutral" and re.search(r"\d", sent) and (t - a) < 1.2 else pm
        pose = "point" if not walking and (t - a) % 4 < 2.2 else "idle"
        if pm == "worried" and not walking:
            pose = "shrug"
        X, Y = L(px, H * 0.74)
        rig(d, X, Y, H * 0.36 * ss, t, self.sector, pm, pose, walking, face=-1)
        lay = lay.resize((x1 - x0, y1 - y0), Image.LANCZOS)
        pil.paste(lay, (x0, y0), lay)

    def _caption(self, d, beats, t, ox):
        W, H, s = self.W, self.H, self.s
        cur = None
        for i, (a, _, _) in enumerate(beats):
            if t >= a:
                cur = i
        if cur is None:
            return
        a, _, sent = beats[cur]
        q = _ease((t - a) / 0.3)
        lines = _wrap(sent, self.f_capb, int(W * 0.86), 2)
        y = H * 0.83 + s(10) * (1 - q)
        for j, ln in enumerate(lines):
            d.text((W * 0.06 + ox, y + j * s(28)), ln, font=self.f_capb, fill=(240, 244, 236, int(255 * q)))

    def _sweep(self, img, t, start):
        """A soft diagonal light sweep passing once across the frame."""
        W, H = self.W, self.H
        p = (t - start) / 1.1
        if 0 < p < 1:
            x = int(-W * 0.2 + p * W * 1.4)
            xs = np.arange(W)[None, :] - (x - (np.arange(H)[:, None] * 0.35))
            m = np.clip(1 - np.abs(xs) / (W * 0.05), 0, 1) * 38 * math.sin(p * math.pi)
            img[:] = np.clip(img.astype(np.float32) + m[..., None], 0, 255).astype(np.uint8)

    def _draw_beam(self, d, target, t, H):
        """Smoothly follow the narrated item with a light cone + chevron cursor."""
        if target is None:
            self._beam = None
            return
        if self._beam is None:
            self._beam = list(target)
        else:
            self._beam[0] += (target[0] - self._beam[0]) * 0.25
            self._beam[1] += (target[1] - self._beam[1]) * 0.25
        x, y = self._beam
        s = self.s
        top = H * 0.2
        if y - top > s(30):
            for k in range(6, 0, -1):
                w = s(4) * k
                d.polygon([(x - w * 0.3, top), (x + w * 0.3, top), (x + w, y - s(16)), (x - w, y - s(16))], fill=(196, 255, 96, 7))
        bob = s(5) * math.sin(t * 6)
        cy = y - s(20) + bob
        d.polygon([(x - s(9), cy - s(9)), (x + s(9), cy - s(9)), (x, cy + s(3))], fill=EYE + (240,))
        r = s(10) + s(7) * ((t * 1.3) % 1)
        d.ellipse([x - r, y - r * 0.35 + s(16), x + r, y + r * 0.35 + s(16)], outline=(220, 255, 160, int(200 * (1 - (t * 1.3) % 1))), width=1)

    def _scene(self, seg: Segment, slide, idx, total, n, env):
        W, H, s, fps = self.W, self.H, self.s, self.fps
        plan = plan_scene(slide, seg.narration, self.title)
        seg.extra["scene"] = plan["kind"]
        D = n / fps
        cap, cl, clh = self.text_layer(seg.extra.get("caption") or seg.narration, self.f_cap, (225, 232, 225), int(W * 0.84), lines=2, spacing=1.35)
        head = (seg.headline or "")
        times = self._times(plan, seg.narration, D)
        for tr in times["reveal"]:
            self.events.append((self.T + tr, "tick"))
        geo_cache = {}
        self._beam = None
        beats = self._beats(seg.narration, D)
        for a, _, _ in beats[1:]:
            self.events.append((self.T + a, "pop"))
        panel = plan["kind"] != "country"
        for f in range(n):
            t = f / fps
            tt = self.T + t
            pin = 1 - _ease(t / 0.8)
            pout = _ease((t - (D - 0.7)) / 0.7)
            ox = W * 0.35 * pin - W * 0.35 * pout                    # camera pan between scenes
            img = self.background(tt, ox)
            pil = Image.fromarray(img)
            d = FadeDraw(pil)
            self.frame_hud(d, plan["kind"].upper()[:7], idx, total, t)
            d.text((W * 0.06 + ox, H * 0.1), head[:58] + ("…" if len(head) > 58 else ""), font=self.f_head, fill=(255, 255, 255))
            d.line([(W * 0.06 + ox, H * 0.1 + s(46)), (W * 0.06 + ox + s(120) * _ease(t / 0.8), H * 0.1 + s(46))], fill=GREEN, width=s(3))
            target, _ = getattr(self, "_draw_" + plan["kind"])(d, pil, plan, t, D, ox, times, geo_cache)
            self._draw_beam(d, target if 0.9 < t < D - 0.8 else None, tt, H)
            if panel:
                self._beat_panel(pil, beats, t, ox, D)
            self._caption(d, beats, t, ox)
            transition(d, self.sec["motif"], W, H, _ease(t / 0.5), self.sec["accent"])
            yield np.asarray(pil)

    # ---------------- timing of reveals / highlights (from where things are mentioned in the narration)
    def _times(self, plan, narration, D):
        labels = plan.get("labels") or [x["label"] or x["value"] for x in plan.get("stats", [])] or plan.get("items") or plan.get("countries") or []
        fr = _mention_times(labels, narration)
        start, end = 1.4, max(2.5, D * 0.78)
        k = max(1, len(labels))
        even = [start + (end - start) * i / k for i in range(k)]
        out = [start + (end - start) * x if x >= 0 else e for x, e in zip(fr, even)]
        return {"reveal": even, "mention": out, "mentioned": [x >= 0 for x in fr]}

    def _focus(self, times, t):
        """Index of the item being discussed at time t (most recent mention), or None before the first."""
        cur = None
        for i, (m, ok) in sorted(enumerate(zip(times["mention"], times["mentioned"])), key=lambda x: x[1][0]):
            if ok and t >= m:
                cur = i
        return cur

    # ---------------- scenes; each returns (pointing target or None, mood)
    def _area(self, ox):
        W, H = self.W, self.H
        return W * 0.07 + ox, H * 0.29, W * 0.64 + ox, H * 0.72

    def _draw_bar(self, d, pil, plan, t, D, ox, times, _):
        x0, y0, x1, y1 = self._area(ox)
        vals = [max(0.0, v) for v in plan["values"]]
        labels, texts = plan["labels"], plan.get("text") or [_fmt(v) for v in plan["values"]]
        n = len(vals)
        vmax = max(vals) or 1
        gap = (x1 - x0) / n
        bw = gap * 0.58
        foc = self._focus(times, t)
        if foc is None and t > D * 0.45:
            foc = int(np.argmax(vals))
        if plan.get("name"):
            d.text((x0, y0 - self.s(34)), str(plan["name"])[:50].upper(), font=self.f_hud, fill=GREEN)
        for g in range(5):
            yy = y1 - (y1 - y0) * g / 4
            d.line([(x0, yy), (x1, yy)], fill=(30, 50, 14, 160), width=1)
        target = None
        for i, v in enumerate(vals):
            p = _ease((t - 0.7 - 0.13 * i) / 0.9)
            h = (y1 - y0) * (v / vmax) * p
            bx = x0 + gap * i + (gap - bw) / 2
            hi = i == foc
            col = EYE if hi else GREEN
            if hi:
                d.rectangle([bx - 4, y1 - h - 4, bx + bw + 4, y1], fill=(196, 255, 96, 50))
            d.rectangle([bx, y1 - h, bx + bw, y1], fill=col + (235,))
            d.rectangle([bx, y1 - h, bx + bw, y1 - h + max(2, self.s(4))], fill=(240, 255, 220))
            if p > 0.05:
                txt = _count_up(texts[i], p) if p < 1 else texts[i]
                d.text((bx + bw / 2, y1 - h - self.s(8)), txt, font=self.f_val if hi else self.f_lab, fill=(255, 255, 255) if hi else PALE, anchor="md")
            lab = _wrap(str(labels[i]), self.f_lab, int(gap * 0.98), 2)
            for j, ln in enumerate(lab):
                d.text((bx + bw / 2, y1 + self.s(8) + j * self.s(19)), ln, font=self.f_lab, fill=(255, 255, 255) if hi else (170, 185, 165), anchor="ma")
            if hi:
                target = (bx + bw / 2, y1 - h - self.s(30))
        d.line([(x0, y1), (x1, y1)], fill=GREEN, width=self.s(2))
        return target, "happy" if foc is not None and t > D * 0.6 else ""

    def _draw_line(self, d, pil, plan, t, D, ox, times, _):
        x0, y0, x1, y1 = self._area(ox)
        vals, labels = plan["values"], plan["labels"]
        n = len(vals)
        lo, hi_ = min(0.0, min(vals)), max(vals) or 1
        pts = [(x0 + (x1 - x0) * (i / max(1, n - 1)), y1 - (y1 - y0) * (v - lo) / (hi_ - lo or 1)) for i, v in enumerate(vals)]
        p = _ease((t - 0.7) / 2.2) * (n - 1)
        foc = self._focus(times, t)
        if foc is None and t > D * 0.45:
            foc = n - 1
        for g in range(5):
            yy = y1 - (y1 - y0) * g / 4
            d.line([(x0, yy), (x1, yy)], fill=(30, 50, 14, 160), width=1)
        k = int(p)
        path = pts[:k + 1]
        if k < n - 1:
            fr = p - k
            path.append((pts[k][0] + (pts[k + 1][0] - pts[k][0]) * fr, pts[k][1] + (pts[k + 1][1] - pts[k][1]) * fr))
        if len(path) >= 2:
            d.polygon(path + [(path[-1][0], y1), (path[0][0], y1)], fill=(134, 188, 37, 45))
            d.line(path, fill=EYE, width=self.s(4), joint="curve")
        target = None
        for i, (x, y) in enumerate(pts):
            if i <= p + 1e-6:
                r = self.s(9 if i == foc else 6)
                d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255) if i == foc else EYE)
                d.text((x, y - self.s(14)), _fmt(vals[i]), font=self.f_val if i == foc else self.f_lab, fill=(255, 255, 255), anchor="md")
            d.text((x, y1 + self.s(8)), str(labels[i])[:10], font=self.f_lab, fill=(170, 185, 165), anchor="ma")
            if i == foc and i <= p:
                target = (x, y - self.s(30))
        d.line([(x0, y1), (x1, y1)], fill=GREEN, width=self.s(2))
        if plan.get("name"):
            d.text((x0, y0 - self.s(34)), str(plan["name"])[:50].upper(), font=self.f_hud, fill=GREEN)
        return target, ""

    def _draw_donut(self, d, pil, plan, t, D, ox, times, _):
        W, H = self.W, self.H
        vals = [max(0.0, v) for v in plan["values"]]
        tot = sum(vals) or 1
        cx, cy, R = W * 0.2 + ox, H * 0.52, H * 0.2
        p = _ease((t - 0.7) / 1.6)
        foc = self._focus(times, t)
        a = -90.0
        target = None
        for i, v in enumerate(vals):
            sweep = 360 * v / tot
            e = min(a + sweep, -90 + 360 * p)
            if e > a:
                rr = R + (self.s(12) if i == foc else 0)
                d.pieslice([cx - rr, cy - rr, cx + rr, cy + rr], a, e, fill=SHADES[i % len(SHADES)] + (240,))
            if i == foc:
                mid = math.radians(a + sweep / 2)
                target = (cx + R * 1.05 * math.cos(mid), cy + R * 1.05 * math.sin(mid))
            a += sweep
        d.ellipse([cx - R * .58, cy - R * .58, cx + R * .58, cy + R * .58], fill=(4, 8, 4))
        if plan.get("name"):
            d.text((cx, cy), str(plan["name"])[:16], font=self.f_lab, fill=PALE, anchor="mm")
        lx = W * 0.4 + ox
        for i, (lb, v) in enumerate(zip(plan["labels"], plan["values"])):
            q = _ease((t - 0.9 - 0.2 * i) / 0.4)
            if q <= 0:
                continue
            y = H * 0.3 + i * self.s(34)
            d.rectangle([lx, y, lx + self.s(16), y + self.s(16)], fill=SHADES[i % len(SHADES)])
            d.text((lx + self.s(26), y - self.s(2)), f"{str(lb)[:22]}  {_fmt(v)}", font=self.f_val if i == foc else self.f_lab,
                   fill=(255, 255, 255) if i == foc else PALE)
        return target, ""

    def _draw_compare(self, d, pil, plan, t, D, ox, times, _):
        x0, y0, x1, y1 = self._area(ox)
        labels, ser = plan["labels"], plan["series"]
        n = len(labels)
        vmax = max(max(s["values"]) for s in ser) or 1
        gap = (x1 - x0) / n
        bw = gap * 0.3
        cols = [GREEN, (200, 215, 190)]
        foc = self._focus(times, t)
        for j, s in enumerate(ser):
            lx = x0 + j * self.s(240)
            d.rectangle([lx, y0 - self.s(30), lx + self.s(14), y0 - self.s(16)], fill=cols[j])
            d.text((lx + self.s(22), y0 - self.s(33)), str(s["name"])[:24], font=self.f_lab, fill=PALE)
        target = None
        for i in range(n):
            for j, s in enumerate(ser):
                v = max(0.0, s["values"][i])
                p = _ease((t - 0.7 - 0.15 * i - 0.08 * j) / 0.9)
                h = (y1 - y0 - self.s(10)) * v / vmax * p
                bx = x0 + gap * i + gap * 0.18 + j * (bw + gap * 0.04)
                c = EYE if (i == foc and j == 0) else cols[j]
                d.rectangle([bx, y1 - h, bx + bw, y1], fill=c + (235,))
                if p > 0.05:
                    txt = (s.get("text") or [_fmt(x) for x in s["values"]])[i]
                    d.text((bx + bw / 2, y1 - h - self.s(6)), _count_up(txt, p) if p < 1 else txt, font=self.f_lab, fill=(255, 255, 255), anchor="md")
                if i == foc and j == 0:
                    target = (bx + bw, y1 - h - self.s(26))
            for k, ln in enumerate(_wrap(str(labels[i]), self.f_lab, int(gap * .95), 2)):
                d.text((x0 + gap * (i + .5), y1 + self.s(8) + k * self.s(19)), ln, font=self.f_lab,
                       fill=(255, 255, 255) if i == foc else (170, 185, 165), anchor="ma")
        d.line([(x0, y1), (x1, y1)], fill=GREEN, width=self.s(2))
        return target, ""

    def _counter_card(self, d, x, y, w, h, st, p, hi):
        d.rounded_rectangle([x, y, x + w, y + h], radius=self.s(14), fill=(8, 16, 6, 215), outline=EYE if hi else GREEN2, width=self.s(2))
        r = self.s(22)
        d.ellipse([x + self.s(18), y + self.s(18), x + self.s(18) + 2 * r, y + self.s(18) + 2 * r], outline=GREEN, width=self.s(2))
        draw_icon(d, icon_for(st["label"] + " " + st["value"]), x + self.s(18) + r, y + self.s(18) + r, r * .62, EYE, max(2, self.s(2)))
        d.text((x + self.s(18), y + self.s(78)), _count_up(st["value"], p) if p < 1 else st["value"], font=self.f_big, fill=(255, 255, 255))
        for k, ln in enumerate(_wrap(st["label"] or "", self.f_lab, int(w - self.s(30)), 3)):
            d.text((x + self.s(18), y + self.s(148) + k * self.s(21)), ln, font=self.f_lab, fill=PALE)

    def _draw_kpi(self, d, pil, plan, t, D, ox, times, _):
        W, H = self.W, self.H
        sts = plan["stats"]
        n = len(sts)
        x0, x1 = W * 0.06 + ox, W * 0.64 + ox
        w = min(W * 0.26, (x1 - x0 - self.s(24) * (n - 1)) / n)
        x0 = W * 0.35 + ox - (w * n + self.s(24) * (n - 1)) / 2
        foc = self._focus(times, t)
        target = None
        for i, st in enumerate(sts):
            q = _ease((t - times["reveal"][i]) / 0.45)
            if q <= 0:
                continue
            x = x0 + i * (w + self.s(24))
            y = H * 0.27 + self.s(30) * (1 - q)
            self._counter_card(d, x, y, w, self.s(230), st, _ease((t - times["reveal"][i]) / 1.4), i == foc)
            if i == foc or (foc is None and t - times["reveal"][i] < 1.6):
                target = (x + w / 2, y - self.s(4))
        return target, "happy" if t > times["reveal"][-1] + 1.4 else ""

    def _draw_versus(self, d, pil, plan, t, D, ox, times, _):
        W, H = self.W, self.H
        a, b = plan["stats"]
        w = W * 0.25
        for i, st in enumerate((a, b)):
            q = _ease((t - 0.7 - 0.5 * i) / 0.5)
            if q > 0:
                x = W * (0.07 if i == 0 else 0.39) + ox
                self._counter_card(d, x, H * 0.27 + self.s(30) * (1 - q), w, self.s(250), st, _ease((t - 0.7 - 0.5 * i) / 1.4), False)
        cx, cy = W * 0.355 + ox, H * 0.27 + self.s(125)
        r = self.s(30) * _ease((t - 1.2) / 0.4)
        if r > 1:
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(10, 20, 6), outline=EYE, width=self.s(2))
            d.text((cx, cy), "VS", font=self.f_val, fill=EYE, anchor="mm")
        foc = self._focus(times, t)
        tx = W * (0.07 if (foc or 0) == 0 else 0.39) + ox
        return ((tx + w / 2, H * 0.27 - self.s(4)) if t > 1.4 else None), ""

    def _draw_cards(self, d, pil, plan, t, D, ox, times, _):
        W, H = self.W, self.H
        items = plan["items"]
        n = len(items)
        cols = 1 if n == 1 else 2
        x0, y0 = W * 0.06 + ox, H * 0.27
        w = (W * 0.58 - self.s(20) * (cols - 1)) / cols
        h = self.s(116)
        target = None
        latest = None
        for i, it in enumerate(items):
            q = _ease((t - times["reveal"][i]) / 0.4)
            if q <= 0:
                continue
            latest = i
            r_, c_ = divmod(i, cols)
            x, y = x0 + c_ * (w + self.s(20)), y0 + r_ * (h + self.s(20))
            sc = 0.85 + 0.15 * q + 0.05 * math.sin(min(1.0, q) * math.pi)
            cxm, cym = x + w / 2, y + h / 2
            bx0, by0, bx1, by1 = cxm - w / 2 * sc, cym - h / 2 * sc, cxm + w / 2 * sc, cym + h / 2 * sc
            d.rounded_rectangle([bx0, by0, bx1, by1], radius=self.s(14), fill=(8, 16, 6, int(215 * q)), outline=GREEN, width=self.s(2))
            ir = self.s(22)
            d.ellipse([bx0 + self.s(16), by0 + self.s(16), bx0 + self.s(16) + 2 * ir, by0 + self.s(16) + 2 * ir], outline=GREEN, width=self.s(2))
            draw_icon(d, icon_for(it), bx0 + self.s(16) + ir, by0 + self.s(16) + ir, ir * .62, EYE, max(2, self.s(2)))
            for k, ln in enumerate(_wrap(it, self.f_card, int(w - self.s(90)), 4)):
                d.text((bx0 + self.s(76), by0 + self.s(14) + k * self.s(24)), ln, font=self.f_card, fill=(235, 240, 230, int(255 * q)))
        if latest is not None and t - times["reveal"][latest] < 1.8:
            r_, c_ = divmod(latest, cols)
            target = (x0 + c_ * (w + self.s(20)) + self.s(38), y0 + r_ * (h + self.s(20)) - self.s(2))
        return target, ""

    def _draw_country(self, d, pil, plan, t, D, ox, times, cache):
        W, H, s = self.W, self.H, self.s
        mx0, my0, mx1, my1 = W * 0.06 + ox, H * 0.22, W * 0.56 + ox, H * 0.78
        primary = plan["countries"][0]
        names = set(plan["countries"])
        if "bbox" not in cache:
            pts = np.concatenate([np.array(r) for c in geo() if c["name"] == primary for r in c["rings"]])
            if primary in ("Russia", "United States of America", "Fiji"):
                pts = pts[(pts[:, 0] > -170) & (pts[:, 0] < 179)]
            lo, la = pts[:, 0], pts[:, 1]
            cxl, cyl = (lo.min() + lo.max()) / 2, (la.min() + la.max()) / 2
            span = max(lo.max() - lo.min(), (la.max() - la.min()) * 1.4, 30) * 1.6
            cache["bbox"] = (cxl, cyl, span)
        cxl, cyl, span = cache["bbox"]
        z = _ease((t - 0.6) / 1.6)
        span_t = 360 * (1 - z) + span * z
        ccx, ccy = 0 * (1 - z) + cxl * z, 10 * (1 - z) + cyl * z
        pw, ph = mx1 - mx0, my1 - my0
        k = pw / span_t
        d.rounded_rectangle([mx0 - s(6), my0 - s(6), mx1 + s(6), my1 + s(6)], radius=s(10), fill=(4, 10, 4, 200), outline=GREEN2, width=s(2))
        for g in range(-180, 181, 30):
            x = mx0 + pw / 2 + (g - ccx) * k
            if mx0 < x < mx1:
                d.line([(x, my0), (x, my1)], fill=(25, 45, 12, 150))
        for g in range(-60, 91, 30):
            y = my0 + ph / 2 - (g - ccy) * k
            if my0 < y < my1:
                d.line([(mx0, y), (mx1, y)], fill=(25, 45, 12, 150))
        lay = Image.new("RGBA", (int(pw), int(ph)), (0, 0, 0, 0))
        ld = ImageDraw.Draw(lay)
        pulse = 0.6 + 0.4 * math.sin(t * 4)
        hl_pts = []
        for c in geo():
            hl = c["name"] == primary
            sec = (not hl) and c["name"] in names
            for r in c["rings"]:
                a = np.array(r)
                xy = np.stack([pw / 2 + (a[:, 0] - ccx) * k, ph / 2 - (a[:, 1] - ccy) * k], 1)
                if xy[:, 0].max() < 0 or xy[:, 0].min() > pw or xy[:, 1].max() < 0 or xy[:, 1].min() > ph or len(xy) < 3:
                    continue
                pl = [tuple(p) for p in xy]
                if hl:
                    hl_pts.append(xy)
                    ld.polygon(pl, fill=(134, 188, 37, int(120 + 110 * pulse * z)), outline=(220, 255, 160, 255))
                elif sec:
                    ld.polygon(pl, fill=(60, 90, 28, 200), outline=(110, 150, 60, 255))
                else:
                    ld.polygon(pl, fill=(20, 32, 16, 230), outline=(60, 92, 30, 255))
        pil.alpha_composite(lay, (int(mx0), int(my0))) if pil.mode == "RGBA" else pil.paste(lay, (int(mx0), int(my0)), lay)
        target = None
        if hl_pts and z > 0.6:
            a = np.concatenate(hl_pts)
            target = (mx0 + float(np.clip(a[:, 0].mean(), 0, pw)), my0 + float(np.clip(a[:, 1].mean(), 0, ph)))
            ext = max(np.ptp(a[:, 0]), np.ptp(a[:, 1])) / 2
            R0 = float(np.clip(ext * 1.1, s(22), min(pw, ph) * 0.45)) * (0.6 + 0.4 * _ease((t - 1.4) / 0.6))
            d.ellipse([target[0] - R0, target[1] - R0, target[0] + R0, target[1] + R0], outline=EYE + (230,), width=s(2))
            r = R0 + s(14) * ((t * 1.2) % 1)
            d.ellipse([target[0] - r, target[1] - r, target[0] + r, target[1] + r], outline=(220, 255, 160, int(200 * (1 - (t * 1.2) % 1))), width=s(1) + 1)
            target = (target[0], target[1] - R0)
        # profile card (no flags): primary country + numbers printed on the slide, each next to its own source line
        q = _ease((t - 1.6) / 0.5)
        if q > 0:
            cx0, cy0, cx1 = W * 0.6 + ox + s(20) * (1 - q), H * 0.22, W * 0.94 + ox
            cw = int(cx1 - cx0 - s(32))
            fN = font(s(24), True)
            nl = _wrap(primary, fN, cw, 2)
            others = [c for c in plan["countries"][1:]]
            ol = _wrap("Also mentioned: " + ", ".join(others), self.f_lab, cw, 2) if others else []
            blocks = []
            for st in plan["stats"]:
                blocks.append(("stat", st, _wrap(st["label"], self.f_lab, cw, 3)))
            for fct in plan["facts"]:
                blocks.append(("fact", fct, _wrap("• " + fct, self.f_lab, cw, 2)))
            ch = s(40) + len(nl) * s(30) + len(ol) * s(20) + s(10) + sum((s(38) if k == "stat" else 0) + len(ls) * s(20) + s(10) for k, _, ls in blocks)
            ch = min(ch, H * 0.78 - cy0)
            d.rounded_rectangle([cx0, cy0, cx1, cy0 + ch], radius=s(12), fill=(8, 16, 6, int(225 * q)), outline=GREEN, width=s(2))
            d.text((cx0 + s(16), cy0 + s(12)), "COUNTRY PROFILE", font=self.f_hud, fill=GREEN)
            y = cy0 + s(32)
            for ln in nl:
                d.text((cx0 + s(16), y), ln, font=fN, fill=(255, 255, 255)); y += s(30)
            for ln in ol:
                d.text((cx0 + s(16), y), ln, font=self.f_lab, fill=(140, 165, 120)); y += s(20)
            y += s(10)
            bottom = cy0 + ch - s(8)
            for i, (kind, it, ls) in enumerate(blocks):
                p = _ease((t - 2.0 - 0.5 * i) / 1.2)
                need = (s(38) if kind == "stat" else 0) + len(ls) * s(20)
                if p <= 0 or y + need > bottom:
                    break
                if kind == "stat":
                    d.text((cx0 + s(16), y), _count_up(it["value"], p) if p < 1 else it["value"], font=font(s(30), True), fill=EYE)
                    y += s(38)
                for ln in ls:
                    d.text((cx0 + s(16), y), ln, font=self.f_lab, fill=PALE if kind == "stat" else (190, 205, 185)); y += s(20)
                y += s(10)
        return target, ""
