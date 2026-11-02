"""Flat 2D cartoon vector art for the Animated Explainer (Infographics-Show-like, in Deloitte black/#86BC25).
All shapes are procedural PIL polygons/ellipses. No external assets, no keys."""
from __future__ import annotations

import math
import re

from PIL import ImageDraw

G = (134, 188, 37)
G2 = (88, 130, 30)
LG = (196, 255, 96)
W_ = (240, 244, 236)
GR = (120, 128, 118)
DG = (52, 58, 50)
SKIN = (232, 196, 160)
INK = (16, 20, 14)

KEYWORDS = [
    ("hospital", r"health|hospital|clinic|diagnos|medical|patient|scan|mri|\bct\b|imaging|doctor|bed"),
    ("money", r"usd|\$|₹|revenue|cost|price|profit|margin|invest|fund|capex|budget|sales|billion|million|\bm\b|crore|payback|break-even"),
    ("factory", r"factory|manufactur|plant|production|oem|supply|industr|vendor"),
    ("truck", r"logistic|truck|deliver|freight|road|transport|shipping|distribution|hub"),
    ("globe", r"country|global|world|region|international|export|india|brazil|mexico|nation|market entry"),
    ("growth", r"grow|cagr|increase|rise|expand|scale|up\b|share|lead"),
    ("people", r"people|population|customer|user|staff|team|hire|citizen|talent|partner"),
    ("building", r"city|cities|tier|office|chain|store|branch|hq|open"),
    ("target", r"goal|target|aim|ask|decision|sign off|phase|pilot|plan|next"),
]
MOODS = [("worried", r"risk|lack|gap|shortage|decline|fall|drop|only|problem|challenge|slow|threat"),
         ("happy", r"grow|lead|win|opportun|rise|gain|strong|best|up\b|expand|record")]


def art_for(text: str) -> str:
    low = text.lower()
    for k, rx in KEYWORDS:
        if re.search(rx, low):
            return k
    return "building"


def mood_for(text: str) -> str:
    low = text.lower()
    for k, rx in MOODS:
        if re.search(rx, low):
            return k
    return "neutral"


def back_out(p: float, s: float = 1.9) -> float:
    """Playful overshoot easing (0..1 -> slightly past 1 -> 1)."""
    p = max(0.0, min(1.0, p)) - 1
    return 1 + p * p * ((s + 1) * p + s)


def squash(p: float):
    """(sx, sy) for a landing squash-and-stretch as p goes 0..1."""
    if p >= 1:
        return 1.0, 1.0
    k = math.sin(p * math.pi) * 0.18 * (1 - p)
    return 1 + k, 1 - k


def _r(d, box, fill, r=0):
    d.rounded_rectangle(box, radius=r, fill=fill) if r else d.rectangle(box, fill=fill)


def draw_art(d: ImageDraw.ImageDraw, kind: str, cx: float, cy: float, size: float, t: float = 0.0, mood: str = "neutral"):
    """Draw a flat illustration centred at (cx, cy) about `size` px tall. (sx, sy) squash is applied by the caller via size."""
    u = size / 100.0
    b = cy + 50 * u                                   # ground line
    d.ellipse([cx - 46 * u, b - 5 * u, cx + 46 * u, b + 5 * u], fill=(22, 30, 18))
    if kind == "hospital":
        _r(d, [cx - 38 * u, b - 70 * u, cx + 38 * u, b], W_, int(4 * u))
        _r(d, [cx - 38 * u, b - 76 * u, cx + 38 * u, b - 66 * u], G, int(3 * u))
        d.rectangle([cx - 6 * u, b - 62 * u, cx + 6 * u, b - 38 * u], fill=G)
        d.rectangle([cx - 12 * u, b - 56 * u, cx + 12 * u, b - 44 * u], fill=G)
        for i in (-1, 1):
            d.rectangle([cx + i * 26 * u - 7 * u, b - 30 * u, cx + i * 26 * u + 7 * u, b - 18 * u], fill=GR)
        d.rectangle([cx - 8 * u, b - 22 * u, cx + 8 * u, b], fill=G2)
    elif kind == "money":
        for i in range(4):
            y = b - 10 * u - i * 9 * u
            _r(d, [cx - 40 * u + i * 2 * u, y - 8 * u, cx + 20 * u + i * 2 * u, y], G if i % 2 == 0 else G2, int(2 * u))
        r = 20 * u + 2 * u * math.sin(t * 5)
        d.ellipse([cx + 8 * u, b - 70 * u, cx + 8 * u + 2 * r, b - 70 * u + 2 * r], fill=LG)
        d.text((cx + 8 * u + r, b - 70 * u + r), "$", fill=INK, anchor="mm", font=_f(int(26 * u)))
    elif kind == "factory":
        d.polygon([(cx - 44 * u, b), (cx - 44 * u, b - 40 * u), (cx - 24 * u, b - 52 * u), (cx - 24 * u, b - 40 * u),
                   (cx - 4 * u, b - 52 * u), (cx - 4 * u, b - 40 * u), (cx + 16 * u, b - 52 * u), (cx + 16 * u, b)], fill=GR)
        d.rectangle([cx + 16 * u, b - 80 * u, cx + 30 * u, b], fill=DG)
        for k in range(3):
            ph = (t * 0.7 + k / 3) % 1
            r = (5 + 8 * ph) * u
            d.ellipse([cx + 23 * u - r + 6 * u * ph, b - 88 * u - 30 * u * ph - r, cx + 23 * u + r + 6 * u * ph, b - 88 * u - 30 * u * ph + r],
                      fill=(200, 210, 195))
        for i in range(3):
            d.rectangle([cx - 38 * u + i * 18 * u, b - 28 * u, cx - 28 * u + i * 18 * u, b - 18 * u], fill=LG)
    elif kind == "truck":
        dx = 3 * u * math.sin(t * 8)
        _r(d, [cx - 46 * u + dx, b - 46 * u, cx + 14 * u + dx, b - 10 * u], W_, int(3 * u))
        d.text((cx - 16 * u + dx, b - 28 * u), "→", fill=G, anchor="mm", font=_f(int(22 * u)))
        _r(d, [cx + 16 * u + dx, b - 34 * u, cx + 42 * u + dx, b - 10 * u], G, int(4 * u))
        d.rectangle([cx + 26 * u + dx, b - 30 * u, cx + 38 * u + dx, b - 22 * u], fill=(30, 50, 20))
        for x in (-32, 0, 30):
            d.ellipse([cx + (x - 8) * u + dx, b - 18 * u, cx + (x + 8) * u + dx, b - 2 * u], fill=INK, outline=GR, width=max(1, int(3 * u)))
    elif kind == "globe":
        R = 40 * u
        c = (cx, b - 46 * u)
        d.ellipse([c[0] - R, c[1] - R, c[0] + R, c[1] + R], fill=(40, 70, 90))
        sh = (t * 12) % 40 - 20
        for (x, y, w, h) in ((-20, -18, 22, 16), (6, -6, 26, 22), (-14, 10, 14, 16)):
            xx = x + sh
            if -R / u < xx < R / u - w:
                d.ellipse([c[0] + xx * u, c[1] + y * u, c[0] + (xx + w) * u, c[1] + (y + h) * u], fill=G)
        d.arc([c[0] - R, c[1] - R, c[0] + R, c[1] + R], 0, 360, fill=W_, width=max(1, int(2 * u)))
    elif kind == "growth":
        hs = [18, 30, 44, 60]
        for i, h in enumerate(hs):
            p = min(1.0, max(0.0, t * 1.5 - i * 0.15))
            d.rectangle([cx - 42 * u + i * 22 * u, b - h * u * p, cx - 26 * u + i * 22 * u, b], fill=G if i < 3 else LG)
        d.line([(cx - 40 * u, b - 30 * u), (cx - 10 * u, b - 46 * u), (cx + 10 * u, b - 40 * u), (cx + 40 * u, b - 76 * u)], fill=W_, width=max(2, int(4 * u)))
        d.polygon([(cx + 44 * u, b - 82 * u), (cx + 30 * u, b - 76 * u), (cx + 42 * u, b - 66 * u)], fill=W_)
    elif kind == "people":
        for i, x in enumerate((-30, 30, 0)):
            sc = 0.8 if i < 2 else 1.0
            person(d, cx + x * u, b, 62 * u * sc, mood if i == 2 else "neutral", t + i, shirt=G if i == 2 else GR)
        return
    elif kind == "target":
        c = (cx, b - 46 * u)
        for k, col in enumerate((W_, G, W_, G)):
            R = (40 - k * 10) * u
            d.ellipse([c[0] - R, c[1] - R, c[0] + R, c[1] + R], fill=col)
        d.line([(c[0] + 44 * u, c[1] - 30 * u), c], fill=LG, width=max(2, int(4 * u)))
        d.polygon([(c[0] + 44 * u, c[1] - 30 * u), (c[0] + 56 * u, c[1] - 32 * u), (c[0] + 46 * u, c[1] - 42 * u)], fill=LG)
    else:   # building / skyline
        for (x, w, h, col) in ((-44, 24, 50, GR), (-18, 30, 82, W_), (14, 26, 62, G), (-8, 12, 28, G2)):
            d.rectangle([cx + x * u, b - h * u, cx + (x + w) * u, b], fill=col)
        for r in range(5):
            for c_ in range(2):
                on = (r + c_ + int(t * 2)) % 3 != 0
                d.rectangle([cx + (-13 + c_ * 12) * u, b - (74 - r * 13) * u, cx + (-7 + c_ * 12) * u, b - (68 - r * 13) * u], fill=G if on else (60, 66, 58))


def person(d, x, base, h, mood="neutral", t=0.0, shirt=G):
    """A simple flat person (pill body, round head, expressive face). mood: neutral|happy|worried|wow."""
    u = h / 100
    bob = 1.5 * u * math.sin(t * 4)
    hy = base - 78 * u + bob
    _r(d, [x - 18 * u, base - 52 * u + bob, x + 18 * u, base], shirt, int(14 * u))
    arm = -1 if mood == "happy" else 1
    for sgn in (-1, 1):
        sx, sy = x + sgn * 18 * u, base - 44 * u + bob
        ex, ey = sx + sgn * 12 * u, sy + arm * 22 * u + (3 * u * math.sin(t * 8) if mood == "happy" else 0)
        d.line([(sx, sy), (ex, ey)], fill=shirt, width=max(2, int(8 * u)))
        d.ellipse([ex - 5 * u, ey - 5 * u, ex + 5 * u, ey + 5 * u], fill=SKIN)
    R = 20 * u
    d.ellipse([x - R, hy - R, x + R, hy + R], fill=SKIN)
    d.chord([x - R, hy - R - 2 * u, x + R, hy + R * 0.2], 180, 360, fill=(40, 34, 30))
    ey = hy + 2 * u
    for sgn in (-1, 1):
        ex = x + sgn * 7 * u
        if mood == "happy":
            d.arc([ex - 4 * u, ey - 3 * u, ex + 4 * u, ey + 4 * u], 200, 340, fill=INK, width=max(1, int(2 * u)))
        else:
            r = (4 if mood == "wow" else 3) * u
            d.ellipse([ex - r, ey - r, ex + r, ey + r], fill=INK)
        if mood == "worried":
            d.line([(ex - 4 * u, ey - 7 * u + sgn * 2 * u), (ex + 4 * u, ey - 7 * u - sgn * 2 * u)], fill=INK, width=max(1, int(2 * u)))
    my = hy + 11 * u
    if mood == "happy":
        d.chord([x - 8 * u, my - 5 * u, x + 8 * u, my + 6 * u], 0, 180, fill=INK)
    elif mood == "worried":
        d.arc([x - 6 * u, my, x + 6 * u, my + 7 * u], 200, 340, fill=INK, width=max(1, int(2 * u)))
    elif mood == "wow":
        d.ellipse([x - 4 * u, my - 3 * u, x + 4 * u, my + 5 * u], fill=INK)
    else:
        d.line([(x - 5 * u, my + 1 * u), (x + 5 * u, my + 1 * u)], fill=INK, width=max(1, int(2 * u)))


_FC = {}


def _f(sz):
    from .video_summary import font
    sz = max(8, int(sz))
    if sz not in _FC:
        _FC[sz] = font(sz, True)
    return _FC[sz]
