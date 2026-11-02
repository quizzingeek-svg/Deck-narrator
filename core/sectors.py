"""Sector themes for the Animated Explainer: auto-detection, accent palettes (Deloitte black/#86BC25-led),
icon libraries, parallax backdrops and sound motifs. Pure PIL vector art (drawn supersampled by the caller).
Illustrations are decorative only; they never carry data."""
from __future__ import annotations

import math
import re
from typing import Dict, List

from PIL import Image, ImageDraw

G = (134, 188, 37)
G2 = (88, 130, 30)
LG = (196, 255, 96)
W_ = (238, 242, 234)
GR = (126, 134, 124)
DG = (54, 60, 52)
INK = (12, 16, 10)
SKIN = (232, 196, 160)

# name -> detection regex, secondary accent (always paired with Deloitte green), icon set, backdrop motif, transition, sfx motif
SECTORS: Dict[str, dict] = {
    "Defense & Security": dict(rx=r"defen[cs]e|military|army|navy|air force|missile|radar|drone|uav|warfare|munition|armou?r|combat|sovereign|nato|deterren",
                               accent=(150, 170, 120), icons=["radar", "jet", "ship", "drone", "shield"], motif="radar", sfx="ping"),
    "Security & Justice": dict(rx=r"justice|court|police|policing|crime|prison|judicial|law enforcement|cctv|surveillance|offender|legal aid",
                               accent=(170, 175, 190), icons=["courthouse", "scales", "badge", "cctv", "shield"], motif="columns", sfx="chime"),
    "Health / LSHC": dict(rx=r"health|hospital|clinic|patient|pharma|life science|medtech|diagnos|imaging|mri|\bct\b|scan|drug|therap|care\b|medical",
                          accent=(120, 210, 200), icons=["hospital", "scanner", "dna", "pulse", "pill"], motif="pulse", sfx="beat"),
    "Financial Services": dict(rx=r"bank|banking|insur|asset manag|wealth|lending|loan|credit|deposit|fintech|payment|capital market|basel|aum|nim\b",
                               accent=(220, 200, 110), icons=["bank", "coins", "candles", "card", "money"], motif="candles", sfx="coin"),
    "TMT": dict(rx=r"telecom|5g|broadband|software|saas|cloud|data cent|semiconductor|media|streaming|digital|\bai\b|platform|network|satellite|device|app\b",
                accent=(110, 190, 240), icons=["laptop", "phone", "network", "satellite", "cloud"], motif="nodes", sfx="blip"),
    "Energy / ER&I": dict(rx=r"energy|power|renewable|solar|wind|turbine|grid|utility|utilities|oil|gas|pipeline|hydrogen|mining|chemical|decarbon|emission",
                          accent=(240, 200, 90), icons=["turbine", "solar", "pylon", "pipeline", "factory"], motif="hills", sfx="hum"),
    "Consumer": dict(rx=r"retail|consumer|shopper|store|e-?commerce|fmcg|cpg|brand|basket|grocery|apparel|restaurant|hospitality|travel|automotive",
                     accent=(240, 150, 120), icons=["store", "cart", "box", "bag", "truck"], motif="shelves", sfx="pop"),
    "Government & Public Services": dict(rx=r"government|ministry|public sector|public service|citizen|municipal|state-owned|policy|welfare|tax|civic|infrastructure|council",
                                         accent=(160, 190, 230), icons=["civic", "people", "bridge", "building", "target"], motif="civic", sfx="chime"),
    "General": dict(rx=r"$^", accent=(200, 210, 195), icons=["growth", "building", "people", "target", "globe"], motif="skyline", sfx="pop"),
}
SECTOR_NAMES = ["Auto-detect"] + list(SECTORS)


def detect_sector(text: str) -> str:
    """Pick the sector whose keywords appear most in the deck text (General if nothing stands out)."""
    low = (text or "").lower()
    best, score = "General", 0
    for name, cfg in SECTORS.items():
        n = len(re.findall(cfg["rx"], low))
        if n > score:
            best, score = name, n
    return best if score >= 2 else "General"


def resolve(choice: str, text: str) -> str:
    return choice if choice in SECTORS else detect_sector(text)


# ------------------------------------------------------------------ shading helpers (flat cartoon with outline + light/shade)
def _sh(c, k):
    return tuple(max(0, min(255, int(v * k))) for v in c[:3])


def blk(d, box, fill, u, r=0):
    """Outlined block with a top highlight and a right-side shade (gives depth)."""
    x0, y0, x1, y1 = box
    ow = max(1, int(2.2 * u))
    rr = int(r * u)
    d.rounded_rectangle([x0 - ow, y0 - ow, x1 + ow, y1 + ow], radius=rr + ow, fill=INK)
    d.rounded_rectangle([x0, y0, x1, y1], radius=rr, fill=fill)
    sw = (x1 - x0) * 0.22
    if sw > 2:
        d.rectangle([x1 - sw, y0 + rr, x1 - max(0, rr * 0.3), y1 - rr * 0.3], fill=_sh(fill, 0.8))
    hh = (y1 - y0) * 0.14
    if hh > 2:
        d.rectangle([x0 + rr * 0.6 + ow, y0 + ow, x1 - sw - ow, y0 + ow + hh * 0.5], fill=_sh(fill, 1.15))


def ell(d, box, fill, u):
    ow = max(1, int(2.2 * u))
    x0, y0, x1, y1 = box
    d.ellipse([x0 - ow, y0 - ow, x1 + ow, y1 + ow], fill=INK)
    d.ellipse(box, fill=fill)
    d.chord([x0, y0, x1, y1], 300, 60, fill=_sh(fill, 0.82))
    w, h = x1 - x0, y1 - y0
    d.ellipse([x0 + w * .2, y0 + h * .15, x0 + w * .38, y0 + h * .3], fill=_sh(fill, 1.2))


def poly(d, pts, fill, u):
    ow = max(1, int(2.2 * u))
    d.polygon(pts, fill=fill, outline=INK, width=ow)


def ln(d, pts, fill, u, w=3):
    d.line(pts, fill=INK, width=max(2, int((w + 2.4) * u)), joint="curve")
    d.line(pts, fill=fill, width=max(1, int(w * u)), joint="curve")


def ground(d, cx, b, u, w=50):
    d.ellipse([cx - w * u, b - 5 * u, cx + w * u, b + 5 * u], fill=(0, 0, 0, 120))


# ------------------------------------------------------------------ sector icons: draw(d, cx, b, u, t); b = ground line, ~100u tall
def _radar(d, cx, b, u, t):
    ground(d, cx, b, u)
    blk(d, [cx - 10 * u, b - 34 * u, cx + 10 * u, b], GR, u, 2)
    c = (cx, b - 62 * u)
    R = 34 * u
    ell(d, [c[0] - R, c[1] - R, c[0] + R, c[1] + R], (20, 40, 16), u)
    for k in (0.66, 0.33):
        d.ellipse([c[0] - R * k, c[1] - R * k, c[0] + R * k, c[1] + R * k], outline=G2, width=max(1, int(u)))
    a = (t * 140) % 360
    for j in range(10):
        d.pieslice([c[0] - R, c[1] - R, c[0] + R, c[1] + R], a - 6 * (j + 1), a - 6 * j, fill=G + (int(170 - j * 16),))
    bl = math.radians(a - 50)
    d.ellipse([c[0] + R * .55 * math.cos(bl) - 3 * u, c[1] + R * .55 * math.sin(bl) - 3 * u, c[0] + R * .55 * math.cos(bl) + 3 * u,
               c[1] + R * .55 * math.sin(bl) + 3 * u], fill=LG)


def _jet(d, cx, b, u, t):
    y = b - 50 * u + 3 * u * math.sin(t * 3)
    for k in range(4):
        d.line([(cx - (52 + k * 10) * u, y + (k - 1.5) * 2 * u), (cx - (38 + k * 10) * u, y + (k - 1.5) * 2 * u)], fill=(200, 210, 200, 140), width=max(1, int(2 * u)))
    poly(d, [(cx - 40 * u, y), (cx + 44 * u, y - 4 * u), (cx + 52 * u, y), (cx + 44 * u, y + 4 * u)], GR, u)
    poly(d, [(cx - 6 * u, y), (cx + 16 * u, y), (cx - 18 * u, y + 28 * u), (cx - 26 * u, y + 28 * u)], DG, u)
    poly(d, [(cx - 6 * u, y), (cx + 16 * u, y), (cx - 18 * u, y - 26 * u), (cx - 26 * u, y - 26 * u)], (100, 108, 98), u)
    poly(d, [(cx - 40 * u, y), (cx - 30 * u, y), (cx - 42 * u, y - 14 * u)], DG, u)
    d.ellipse([cx + 26 * u, y - 4 * u, cx + 38 * u, y + 1 * u], fill=G)


def _ship(d, cx, b, u, t):
    bob = 2 * u * math.sin(t * 2.5)
    poly(d, [(cx - 48 * u, b - 24 * u + bob), (cx + 50 * u, b - 24 * u + bob), (cx + 36 * u, b - 4 * u + bob), (cx - 40 * u, b - 4 * u + bob)], GR, u)
    blk(d, [cx - 20 * u, b - 44 * u + bob, cx + 12 * u, b - 24 * u + bob], DG, u, 2)
    blk(d, [cx - 10 * u, b - 58 * u + bob, cx + 2 * u, b - 44 * u + bob], (100, 108, 98), u, 1)
    ln(d, [(cx - 4 * u, b - 58 * u + bob), (cx - 4 * u, b - 72 * u + bob)], GR, u, 2)
    d.rectangle([cx - 26 * u, b - 30 * u + bob, cx + 30 * u, b - 27 * u + bob], fill=G)
    for k in range(3):
        x = cx - 50 * u + ((t * 30 + k * 34) % 100) * u
        d.arc([x - 8 * u, b - 6 * u, x + 8 * u, b + 4 * u], 200, 340, fill=(90, 140, 170), width=max(1, int(2 * u)))


def _drone(d, cx, b, u, t):
    y = b - 56 * u + 4 * u * math.sin(t * 2)
    ground(d, cx, b, u, 30)
    for sx in (-1, 1):
        ln(d, [(cx, y), (cx + sx * 34 * u, y - 8 * u)], GR, u, 3)
        px = cx + sx * 34 * u
        w = 16 * u * abs(math.cos(t * 30 + sx))
        d.ellipse([px - w - 2 * u, y - 12 * u, px + w + 2 * u, y - 6 * u], fill=(200, 210, 200, 150))
    blk(d, [cx - 18 * u, y - 8 * u, cx + 18 * u, y + 8 * u], DG, u, 5)
    ell(d, [cx - 6 * u, y + 6 * u, cx + 6 * u, y + 16 * u], (30, 30, 30), u)
    d.ellipse([cx - 2 * u, y - 2 * u, cx + 2 * u, y + 2 * u], fill=LG if int(t * 3) % 2 else G2)


def _shield(d, cx, b, u, t):
    ground(d, cx, b, u, 34)
    top = b - 92 * u
    pts = [(cx, top), (cx + 36 * u, top + 12 * u), (cx + 32 * u, top + 52 * u), (cx, top + 86 * u), (cx - 32 * u, top + 52 * u), (cx - 36 * u, top + 12 * u)]
    poly(d, pts, G, u)
    poly(d, [(cx, top + 10 * u), (cx + 26 * u, top + 19 * u), (cx + 23 * u, top + 50 * u), (cx, top + 74 * u)], G2, u)
    ln(d, [(cx - 14 * u, top + 44 * u), (cx - 3 * u, top + 56 * u), (cx + 16 * u, top + 30 * u)], W_, u, 5)


def _courthouse(d, cx, b, u, t):
    ground(d, cx, b, u)
    blk(d, [cx - 46 * u, b - 10 * u, cx + 46 * u, b], GR, u)
    for i in range(5):
        x = cx - 36 * u + i * 18 * u
        blk(d, [x - 4 * u, b - 56 * u, x + 4 * u, b - 10 * u], W_, u)
    blk(d, [cx - 46 * u, b - 64 * u, cx + 46 * u, b - 56 * u], W_, u)
    poly(d, [(cx - 50 * u, b - 64 * u), (cx, b - 90 * u), (cx + 50 * u, b - 64 * u)], G, u)


def _scales(d, cx, b, u, t):
    ground(d, cx, b, u, 30)
    tilt = 6 * u * math.sin(t * 1.6)
    blk(d, [cx - 3 * u, b - 80 * u, cx + 3 * u, b - 6 * u], GR, u)
    blk(d, [cx - 20 * u, b - 8 * u, cx + 20 * u, b], DG, u, 2)
    ln(d, [(cx - 36 * u, b - 74 * u + tilt), (cx + 36 * u, b - 74 * u - tilt)], W_, u, 3)
    for sx, dy in ((-1, tilt), (1, -tilt)):
        px, py = cx + sx * 36 * u, b - 74 * u + dy
        d.line([(px, py), (px - 12 * u, py + 26 * u)], fill=GR, width=max(1, int(u)))
        d.line([(px, py), (px + 12 * u, py + 26 * u)], fill=GR, width=max(1, int(u)))
        d.chord([px - 16 * u, py + 18 * u, px + 16 * u, py + 36 * u], 0, 180, fill=G, outline=INK, width=max(1, int(2 * u)))
    ell(d, [cx - 6 * u, b - 88 * u, cx + 6 * u, b - 76 * u], G, u)


def _badge(d, cx, b, u, t):
    ground(d, cx, b, u, 30)
    c = (cx, b - 46 * u)
    pts = [(c[0] + 38 * u * math.cos(math.radians(a)) * (1 if k % 2 == 0 else .72), c[1] + 38 * u * math.sin(math.radians(a)) * (1 if k % 2 == 0 else .72))
           for k, a in enumerate(range(-90, 270, 36))]
    poly(d, pts, (220, 190, 90), u)
    ell(d, [c[0] - 18 * u, c[1] - 18 * u, c[0] + 18 * u, c[1] + 18 * u], G, u)
    d.polygon([(c[0], c[1] - 9 * u), (c[0] + 3 * u, c[1] - 2 * u), (c[0] + 9 * u, c[1] - 2 * u), (c[0] + 4 * u, c[1] + 3 * u),
               (c[0] + 6 * u, c[1] + 10 * u), (c[0], c[1] + 6 * u), (c[0] - 6 * u, c[1] + 10 * u), (c[0] - 4 * u, c[1] + 3 * u),
               (c[0] - 9 * u, c[1] - 2 * u), (c[0] - 3 * u, c[1] - 2 * u)], fill=W_)


def _cctv(d, cx, b, u, t):
    ground(d, cx, b, u, 26)
    blk(d, [cx - 30 * u, b - 90 * u, cx - 24 * u, b], GR, u)
    ang = 8 * math.sin(t * 1.2)
    c = (cx + 6 * u, b - 70 * u + ang * u * .4)
    poly(d, [(c[0] - 28 * u, c[1] - 9 * u), (c[0] + 22 * u, c[1] - 12 * u + ang * u * .3), (c[0] + 22 * u, c[1] + 8 * u + ang * u * .3), (c[0] - 28 * u, c[1] + 9 * u)], W_, u)
    ell(d, [c[0] + 16 * u, c[1] - 7 * u, c[0] + 28 * u, c[1] + 5 * u], DG, u)
    d.ellipse([c[0] + 20 * u, c[1] - 3 * u, c[0] + 24 * u, c[1] + 1 * u], fill=(255, 60, 60) if int(t * 2) % 2 else (120, 30, 30))
    d.polygon([(c[0] + 28 * u, c[1]), (c[0] + 60 * u, c[1] + 50 * u), (c[0] + 10 * u, c[1] + 56 * u)], fill=G + (45,))


def _scanner(d, cx, b, u, t):
    ground(d, cx, b, u)
    blk(d, [cx - 46 * u, b - 22 * u, cx + 46 * u, b - 14 * u], W_, u, 2)
    blk(d, [cx - 30 * u, b - 14 * u, cx - 24 * u, b], GR, u)
    blk(d, [cx + 24 * u, b - 14 * u, cx + 30 * u, b], GR, u)
    c = (cx + 10 * u, b - 48 * u)
    R = 36 * u
    ell(d, [c[0] - R, c[1] - R, c[0] + R, c[1] + R], W_, u)
    d.ellipse([c[0] - R * .55, c[1] - R * .55, c[0] + R * .55, c[1] + R * .55], fill=(20, 26, 20), outline=INK, width=max(1, int(2 * u)))
    a = (t * 200) % 360
    d.arc([c[0] - R * .8, c[1] - R * .8, c[0] + R * .8, c[1] + R * .8], a, a + 70, fill=G, width=max(2, int(4 * u)))
    blk(d, [cx - 40 * u, b - 30 * u, cx + 10 * u, b - 22 * u], G, u, 3)


def _dna(d, cx, b, u, t):
    ground(d, cx, b, u, 26)
    for i in range(14):
        y = b - 8 * u - i * 6.2 * u
        ph = t * 3 + i * 0.55
        x1, x2 = cx + 18 * u * math.sin(ph), cx - 18 * u * math.sin(ph)
        d.line([(x1, y), (x2, y)], fill=(90, 110, 85), width=max(1, int(2 * u)))
        front = math.cos(ph) > 0
        for x, col in ((x1, G if front else G2), (x2, W_ if not front else GR)):
            r = 4.5 * u
            d.ellipse([x - r, y - r, x + r, y + r], fill=col, outline=INK, width=max(1, int(1.2 * u)))


def _pulse(d, cx, b, u, t):
    blk(d, [cx - 48 * u, b - 76 * u, cx + 48 * u, b], (24, 32, 22), u, 6)
    pts = []
    for i in range(49):
        x = -42 + i * 1.75
        ph = (i / 48 * 2 + t * 0.9) % 1
        y = 0
        if 0.42 < ph < 0.46: y = -10
        elif 0.46 < ph < 0.5: y = 26
        elif 0.5 < ph < 0.54: y = -12
        pts.append((cx + x * u, b - 38 * u - y * u))
    d.line(pts, fill=LG, width=max(2, int(3 * u)))
    blk(d, [cx + 24 * u, b - 70 * u, cx + 42 * u, b - 60 * u], G, u, 2)
    d.rectangle([cx + 30 * u, b - 68 * u, cx + 36 * u, b - 62 * u], fill=W_)


def _pill(d, cx, b, u, t):
    ground(d, cx, b, u, 36)
    rot = math.sin(t * 2) * 6
    c = (cx, b - 44 * u)
    blk(d, [c[0] - 40 * u, c[1] - 14 * u + rot * u * .2, c[0], c[1] + 14 * u], W_, u, 14)
    blk(d, [c[0], c[1] - 14 * u, c[0] + 40 * u, c[1] + 14 * u - rot * u * .2], G, u, 14)
    for k, (x, y) in enumerate(((-30, -40), (24, -44), (36, -24))):
        s = 4 * u * (1 + .3 * math.sin(t * 4 + k))
        d.ellipse([c[0] + x * u - s, c[1] + y * u - s, c[0] + x * u + s, c[1] + y * u + s], fill=LG)


def _bank(d, cx, b, u, t):
    ground(d, cx, b, u)
    blk(d, [cx - 46 * u, b - 10 * u, cx + 46 * u, b], GR, u)
    for i in range(4):
        x = cx - 30 * u + i * 20 * u
        blk(d, [x - 5 * u, b - 52 * u, x + 5 * u, b - 10 * u], W_, u)
    blk(d, [cx - 46 * u, b - 60 * u, cx + 46 * u, b - 52 * u], W_, u)
    poly(d, [(cx - 50 * u, b - 60 * u), (cx, b - 86 * u), (cx + 50 * u, b - 60 * u)], (220, 200, 110), u)
    d.text((cx, b - 69 * u), "$", fill=INK, anchor="mm", font=_f(int(16 * u)))


def _coins(d, cx, b, u, t):
    ground(d, cx, b, u, 44)
    for s_, (x, n) in enumerate(((-26, 4), (0, 7), (26, 5))):
        for i in range(n):
            y = b - 6 * u - i * 7 * u
            ell(d, [cx + (x - 13) * u, y - 5 * u, cx + (x + 13) * u, y + 5 * u], (226, 196, 90) if i % 2 else (240, 212, 110), u)
    y = b - 80 * u - 6 * u * abs(math.sin(t * 3))
    w = 13 * u * abs(math.cos(t * 4))
    ell(d, [cx - w - 1, y - 13 * u, cx + w + 1, y + 13 * u], (240, 212, 110), u)


def _candles(d, cx, b, u, t):
    blk(d, [cx - 48 * u, b - 84 * u, cx + 48 * u, b], (24, 32, 22), u, 6)
    data = [(30, 44, 22, 50), (44, 40, 36, 52), (40, 52, 34, 58), (52, 60, 46, 66), (60, 56, 50, 64), (56, 70, 52, 76)]
    n = min(len(data), int(t * 3) + 1)
    for i, (o, c, lo, hi) in enumerate(data[:n]):
        x = cx - 36 * u + i * 14 * u
        up = c >= o
        col = G if up else (200, 90, 80)
        d.line([(x, b - lo * u), (x, b - hi * u)], fill=W_, width=max(1, int(1.5 * u)))
        y0 = b - max(o, c) * u
        d.rectangle([x - 4 * u, y0, x + 4 * u, max(y0, b - min(o, c) * u - 1)], fill=col, outline=INK)


def _card(d, cx, b, u, t):
    ground(d, cx, b, u, 40)
    tilt = 4 * math.sin(t * 1.5)
    blk(d, [cx - 42 * u, b - 70 * u + tilt * u, cx + 42 * u, b - 18 * u + tilt * u], G2, u, 7)
    d.rectangle([cx - 42 * u, b - 60 * u + tilt * u, cx + 42 * u, b - 52 * u + tilt * u], fill=INK)
    blk(d, [cx - 32 * u, b - 46 * u + tilt * u, cx - 18 * u, b - 36 * u + tilt * u], (230, 200, 110), u, 2)
    for i in range(4):
        d.rectangle([cx - 30 * u + i * 16 * u, b - 28 * u + tilt * u, cx - 20 * u + i * 16 * u, b - 25 * u + tilt * u], fill=W_)


def _laptop(d, cx, b, u, t):
    ground(d, cx, b, u)
    blk(d, [cx - 38 * u, b - 74 * u, cx + 38 * u, b - 18 * u], DG, u, 4)
    d.rectangle([cx - 32 * u, b - 68 * u, cx + 32 * u, b - 24 * u], fill=(16, 30, 40))
    for i in range(4):
        w = (20 + 30 * ((i * 37 + int(t * 6)) % 7) / 7) * u
        d.rectangle([cx - 28 * u, b - 62 * u + i * 9 * u, cx - 28 * u + w, b - 58 * u + i * 9 * u], fill=G if i % 2 == 0 else (110, 190, 240))
    poly(d, [(cx - 46 * u, b - 18 * u), (cx + 46 * u, b - 18 * u), (cx + 50 * u, b - 8 * u), (cx - 50 * u, b - 8 * u)], GR, u)


def _phone(d, cx, b, u, t):
    ground(d, cx, b, u, 26)
    blk(d, [cx - 20 * u, b - 90 * u, cx + 20 * u, b - 6 * u], DG, u, 7)
    d.rectangle([cx - 16 * u, b - 82 * u, cx + 16 * u, b - 16 * u], fill=(16, 30, 40))
    for i in range(3):
        r = (8 + i * 8) * u * (0.8 + 0.2 * math.sin(t * 4 - i))
        d.arc([cx + 24 * u - r, b - 84 * u - r, cx + 24 * u + r, b - 84 * u + r], 200, 340, fill=G, width=max(1, int(2.5 * u)))
    for i in range(3):
        blk(d, [cx - 12 * u, b - 74 * u + i * 18 * u, cx + 12 * u, b - 62 * u + i * 18 * u], G if i == int(t * 2) % 3 else GR, u, 3)


def _network(d, cx, b, u, t):
    pts = [(0, -80), (-34, -58), (34, -58), (-40, -22), (0, -40), (40, -22), (-16, -6), (20, -6)]
    edges = [(0, 1), (0, 2), (1, 4), (2, 4), (1, 3), (2, 5), (3, 6), (4, 6), (4, 7), (5, 7)]
    P = [(cx + x * u, b + y * u) for x, y in pts]
    for k, (i, j) in enumerate(edges):
        d.line([P[i], P[j]], fill=(70, 100, 60), width=max(1, int(2 * u)))
        p = (t * 0.9 + k * 0.13) % 1
        x, y = P[i][0] + (P[j][0] - P[i][0]) * p, P[i][1] + (P[j][1] - P[i][1]) * p
        d.ellipse([x - 2.5 * u, y - 2.5 * u, x + 2.5 * u, y + 2.5 * u], fill=LG)
    for k, p in enumerate(P):
        r = (8 if k == 4 else 6) * u
        ell(d, [p[0] - r, p[1] - r, p[0] + r, p[1] + r], G if k == 4 else (110, 190, 240), u)


def _satellite(d, cx, b, u, t):
    y = b - 54 * u + 3 * u * math.sin(t * 1.5)
    for sx in (-1, 1):
        x0 = cx + sx * 14 * u
        x1 = cx + sx * 46 * u
        blk(d, [min(x0, x1), y - 10 * u, max(x0, x1), y + 10 * u], (50, 80, 140), u, 1)
        for k in range(1, 4):
            xx = x0 + (x1 - x0) * k / 4
            d.line([(xx, y - 10 * u), (xx, y + 10 * u)], fill=(140, 170, 220), width=1)
    blk(d, [cx - 12 * u, y - 14 * u, cx + 12 * u, y + 14 * u], W_, u, 3)
    ln(d, [(cx, y + 14 * u), (cx, y + 24 * u)], GR, u, 2)
    for i in range(3):
        r = ((t * 30 + i * 12) % 36) * u
        d.arc([cx - r, y + 24 * u - r * .5, cx + r, y + 24 * u + r * .5], 20, 160, fill=G + (int(255 * (1 - r / (36 * u))),), width=max(1, int(2 * u)))


def _cloud(d, cx, b, u, t):
    ground(d, cx, b, u, 36)
    y = b - 54 * u + 2 * u * math.sin(t * 2)
    for (x, yy, r) in ((-22, 4, 18), (0, -8, 24), (24, 4, 18)):
        ell(d, [cx + (x - r) * u, y + (yy - r) * u, cx + (x + r) * u, y + (yy + r) * u], W_, u)
    d.rectangle([cx - 38 * u, y + 4 * u, cx + 40 * u, y + 22 * u], fill=W_)
    d.line([(cx - 40 * u, y + 23 * u), (cx + 42 * u, y + 23 * u)], fill=INK, width=max(1, int(2.2 * u)))
    for i, x in enumerate((-16, 0, 16)):
        p = (t * 1.2 + i * .33) % 1
        d.polygon([(cx + x * u, y + (26 + 16 * p) * u), (cx + (x - 4) * u, y + (20 + 16 * p) * u), (cx + (x + 4) * u, y + (20 + 16 * p) * u)], fill=G)


def _turbine(d, cx, b, u, t):
    ground(d, cx, b, u, 26)
    poly(d, [(cx - 4 * u, b), (cx + 4 * u, b), (cx + 2 * u, b - 66 * u), (cx - 2 * u, b - 66 * u)], W_, u)
    c = (cx, b - 68 * u)
    for k in range(3):
        a = t * 3 + k * 2 * math.pi / 3
        ex, ey = c[0] + 36 * u * math.cos(a), c[1] + 36 * u * math.sin(a)
        nx, ny = -math.sin(a) * 4 * u, math.cos(a) * 4 * u
        poly(d, [c, (c[0] + nx * 1.5 + (ex - c[0]) * .3, c[1] + ny * 1.5 + (ey - c[1]) * .3), (ex, ey)], W_, u)
    ell(d, [c[0] - 5 * u, c[1] - 5 * u, c[0] + 5 * u, c[1] + 5 * u], G, u)


def _solar(d, cx, b, u, t):
    ground(d, cx, b, u)
    r = 12 * u
    sx, sy = cx + 30 * u, b - 82 * u
    for k in range(8):
        a = k * math.pi / 4 + t * .5
        d.line([(sx + r * 1.3 * math.cos(a), sy + r * 1.3 * math.sin(a)), (sx + r * 1.8 * math.cos(a), sy + r * 1.8 * math.sin(a))], fill=(240, 200, 90), width=max(1, int(2 * u)))
    ell(d, [sx - r, sy - r, sx + r, sy + r], (240, 200, 90), u)
    poly(d, [(cx - 46 * u, b - 18 * u), (cx + 30 * u, b - 18 * u), (cx + 40 * u, b - 46 * u), (cx - 36 * u, b - 46 * u)], (40, 70, 130), u)
    for k in range(1, 4):
        x0 = cx - 46 * u + k * 19 * u
        d.line([(x0, b - 18 * u), (x0 + 10 * u, b - 46 * u)], fill=(140, 170, 220), width=1)
    d.line([(cx - 41 * u, b - 32 * u), (cx + 35 * u, b - 32 * u)], fill=(140, 170, 220), width=1)
    blk(d, [cx - 4 * u, b - 18 * u, cx + 4 * u, b], GR, u)
    sh = ((t * .7) % 1.4) * 90 * u
    d.line([(cx - 46 * u + sh, b - 18 * u), (cx - 36 * u + sh, b - 46 * u)], fill=(255, 255, 255, 90), width=max(2, int(4 * u)))


def _pylon(d, cx, b, u, t):
    ground(d, cx, b, u, 30)
    for sx in (-1, 1):
        ln(d, [(cx + sx * 22 * u, b), (cx + sx * 4 * u, b - 88 * u)], GR, u, 2.5)
    for y, w in ((-30, 30), (-56, 34), (-76, 22)):
        ln(d, [(cx - w * u, b + y * u), (cx + w * u, b + y * u)], GR, u, 2.5)
    for k in range(4):
        y0 = b - (8 + k * 20) * u
        d.line([(cx - 18 * u + k * 4 * u, y0), (cx + 14 * u - k * 4 * u, y0 - 18 * u)], fill=GR, width=max(1, int(1.2 * u)))
    for y, w in ((-30, 30), (-56, 34)):
        p = (t * 1.5) % 1
        d.ellipse([cx + w * u * (2 * p - 1) - 3 * u, b + y * u - 3 * u, cx + w * u * (2 * p - 1) + 3 * u, b + y * u + 3 * u], fill=(240, 200, 90))


def _pipeline(d, cx, b, u, t):
    ground(d, cx, b, u)
    blk(d, [cx - 50 * u, b - 34 * u, cx + 50 * u, b - 18 * u], GR, u, 6)
    for x in (-30, 0, 30):
        blk(d, [cx + (x - 3) * u, b - 18 * u, cx + (x + 3) * u, b], DG, u)
        blk(d, [cx + (x - 7) * u, b - 37 * u, cx + (x + 7) * u, b - 15 * u], (100, 108, 98), u, 2)
    p = (t * .8) % 1
    d.rectangle([cx - 50 * u + p * 90 * u, b - 30 * u, cx - 42 * u + p * 90 * u, b - 22 * u], fill=(240, 200, 90))
    blk(d, [cx + 30 * u, b - 70 * u, cx + 42 * u, b - 34 * u], W_, u, 2)
    ell(d, [cx + 26 * u, b - 76 * u, cx + 46 * u, b - 64 * u], G, u)


def _store(d, cx, b, u, t):
    ground(d, cx, b, u)
    blk(d, [cx - 42 * u, b - 56 * u, cx + 42 * u, b], W_, u, 2)
    for i in range(6):
        col = G if i % 2 == 0 else W_
        x = cx - 46 * u + i * 15.4 * u
        d.pieslice([x, b - 74 * u, x + 15.4 * u, b - 56 * u], 0, 180, fill=col, outline=INK)
        d.rectangle([x, b - 74 * u, x + 15.4 * u, b - 65 * u], fill=col, outline=INK)
    blk(d, [cx - 30 * u, b - 46 * u, cx - 4 * u, b - 22 * u], (110, 190, 240), u, 2)
    blk(d, [cx + 6 * u, b - 46 * u, cx + 28 * u, b], DG, u, 2)


def _cart(d, cx, b, u, t):
    ground(d, cx, b, u, 40)
    dx = 4 * u * math.sin(t * 3)
    ln(d, [(cx - 50 * u + dx, b - 72 * u), (cx - 38 * u + dx, b - 72 * u), (cx - 26 * u + dx, b - 22 * u), (cx + 34 * u + dx, b - 22 * u)], GR, u, 3)
    poly(d, [(cx - 34 * u + dx, b - 60 * u), (cx + 44 * u + dx, b - 60 * u), (cx + 36 * u + dx, b - 30 * u), (cx - 27 * u + dx, b - 30 * u)], W_, u)
    for k, col in enumerate((G, (240, 150, 120), (240, 200, 90))):
        blk(d, [cx + (-22 + k * 20) * u + dx, b - (78 - k * 4) * u, cx + (-8 + k * 20) * u + dx, b - 60 * u], col, u, 2)
    for x in (-18, 26):
        ell(d, [cx + (x - 6) * u + dx, b - 16 * u, cx + (x + 6) * u + dx, b - 4 * u], DG, u)


def _box(d, cx, b, u, t):
    ground(d, cx, b, u, 40)
    hop = 6 * u * abs(math.sin(t * 2.5))
    poly(d, [(cx - 36 * u, b - 50 * u - hop), (cx, b - 64 * u - hop), (cx + 36 * u, b - 50 * u - hop), (cx, b - 36 * u - hop)], (226, 190, 130), u)
    poly(d, [(cx - 36 * u, b - 50 * u - hop), (cx, b - 36 * u - hop), (cx, b - hop), (cx - 36 * u, b - 14 * u - hop)], (200, 160, 100), u)
    poly(d, [(cx + 36 * u, b - 50 * u - hop), (cx, b - 36 * u - hop), (cx, b - hop), (cx + 36 * u, b - 14 * u - hop)], (170, 130, 80), u)
    d.line([(cx - 18 * u, b - 57 * u - hop), (cx + 18 * u, b - 43 * u - hop)], fill=G, width=max(2, int(5 * u)))


def _bag(d, cx, b, u, t):
    ground(d, cx, b, u, 34)
    d.arc([cx - 14 * u, b - 90 * u, cx + 14 * u, b - 58 * u], 180, 360, fill=GR, width=max(2, int(5 * u)))
    poly(d, [(cx - 32 * u, b - 74 * u), (cx + 32 * u, b - 74 * u), (cx + 38 * u, b), (cx - 38 * u, b)], G, u)
    poly(d, [(cx + 14 * u, b - 74 * u), (cx + 32 * u, b - 74 * u), (cx + 38 * u, b), (cx + 18 * u, b)], G2, u)
    d.text((cx - 4 * u, b - 38 * u), "%", fill=W_, anchor="mm", font=_f(int(24 * u)))


def _civic(d, cx, b, u, t):
    ground(d, cx, b, u)
    blk(d, [cx - 46 * u, b - 40 * u, cx + 46 * u, b], W_, u)
    for i in range(6):
        x = cx - 38 * u + i * 15 * u
        d.rectangle([x, b - 32 * u, x + 6 * u, b - 8 * u], fill=GR)
    blk(d, [cx - 20 * u, b - 56 * u, cx + 20 * u, b - 40 * u], W_, u)
    d.chord([cx - 22 * u, b - 80 * u, cx + 22 * u, b - 36 * u], 180, 360, fill=G, outline=INK, width=max(1, int(2.2 * u)))
    ln(d, [(cx, b - 80 * u), (cx, b - 96 * u)], GR, u, 1.5)
    w = 12 * u * (0.8 + 0.2 * math.sin(t * 5))
    d.polygon([(cx, b - 96 * u), (cx + w, b - 92 * u), (cx, b - 88 * u)], fill=G)


def _bridge(d, cx, b, u, t):
    d.rectangle([cx - 50 * u, b - 6 * u, cx + 50 * u, b], fill=(40, 80, 110))
    blk(d, [cx - 50 * u, b - 30 * u, cx + 50 * u, b - 24 * u], GR, u)
    for x in (-24, 24):
        blk(d, [cx + (x - 3) * u, b - 70 * u, cx + (x + 3) * u, b - 6 * u], W_, u)
    d.arc([cx - 24 * u, b - 76 * u, cx + 24 * u, b - 24 * u], 180, 360, fill=G, width=max(2, int(3 * u)))
    for x in range(-18, 20, 6):
        d.line([(cx + x * u, b - 30 * u), (cx + x * u, b - 30 * u - (26 - abs(x) * 1.0) * u)], fill=G2, width=1)
    p = (t * .5) % 1
    blk(d, [cx + (-50 + p * 90) * u, b - 36 * u, cx + (-40 + p * 90) * u, b - 30 * u], (240, 150, 120), u, 2)


ICONS = {"radar": _radar, "jet": _jet, "ship": _ship, "drone": _drone, "shield": _shield, "courthouse": _courthouse,
         "scales": _scales, "badge": _badge, "cctv": _cctv, "scanner": _scanner, "dna": _dna, "pulse": _pulse, "pill": _pill,
         "bank": _bank, "coins": _coins, "candles": _candles, "card": _card, "laptop": _laptop, "phone": _phone,
         "network": _network, "satellite": _satellite, "cloud": _cloud, "turbine": _turbine, "solar": _solar, "pylon": _pylon,
         "pipeline": _pipeline, "store": _store, "cart": _cart, "box": _box, "bag": _bag, "civic": _civic, "bridge": _bridge}

# keyword -> icon, checked per sentence inside a sector (falls back to rotating through the sector set)
ICON_HINTS = [("radar", r"radar|surveil|detect|sensor|isr"), ("jet", r"air|jet|aircraft|fighter|aviation"), ("ship", r"naval|navy|ship|maritime|sea"),
              ("drone", r"drone|uav|unmanned|autonom"), ("shield", r"secur|protect|defen|resilien|cyber|risk"),
              ("scales", r"justice|fair|law|legal|court"), ("cctv", r"cctv|camera|monitor"), ("badge", r"police|officer|enforce"),
              ("scanner", r"scan|mri|\bct\b|imaging|diagnos"), ("dna", r"genom|dna|biotech|research|trial|life science"),
              ("pulse", r"patient|outcome|care|clinical|beds?\b"), ("pill", r"drug|pharma|therap|medicine"),
              ("candles", r"market|stock|trading|price|return|yield"), ("coins", r"revenue|profit|cost|saving|fee|usd|\$|₹|eur"),
              ("card", r"payment|card|digital bank|wallet"), ("bank", r"bank|deposit|loan|lending|branch"),
              ("satellite", r"satellite|space|coverage"), ("network", r"network|5g|connect|data|ai\b|platform"), ("phone", r"mobile|app|phone|user"),
              ("cloud", r"cloud|saas|software"), ("turbine", r"wind|turbine"), ("solar", r"solar|renewable|clean"), ("pylon", r"grid|power|transmission|electric"),
              ("pipeline", r"oil|gas|pipeline|hydrogen"), ("cart", r"basket|cart|shopper|purchase"), ("store", r"store|retail|outlet"),
              ("box", r"deliver|parcel|supply|logistic"), ("civic", r"government|ministry|public|policy"), ("bridge", r"infrastructure|road|bridge|transport")]


def icon_for_sentence(sector: str, sentence: str, i: int) -> str:
    pool = SECTORS.get(sector, SECTORS["General"])["icons"]
    low = sentence.lower()
    for k, rx in ICON_HINTS:
        if k in ICONS and re.search(rx, low) and (k in pool or sector == "General"):
            return k
    for k, rx in ICON_HINTS:
        if re.search(rx, low) and k in ICONS:
            return k
    return pool[i % len(pool)]


class _Safe:
    """Proxy that normalises box coords so tiny icon scales never raise."""
    def __init__(self, d): self._d = d
    def __getattr__(self, k): return getattr(self._d, k)
    def _fix(self, xy):
        try:
            x0, y0, x1, y1 = [float(v) for v in xy]
        except Exception:
            return xy
        return [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]
    def rectangle(self, xy, *a, **k): return self._d.rectangle(self._fix(xy), *a, **k)
    def rounded_rectangle(self, xy, *a, **k): return self._d.rounded_rectangle(self._fix(xy), *a, **k)
    def ellipse(self, xy, *a, **k): return self._d.ellipse(self._fix(xy), *a, **k)
    def pieslice(self, xy, *a, **k): return self._d.pieslice(self._fix(xy), *a, **k)
    def arc(self, xy, *a, **k): return self._d.arc(self._fix(xy), *a, **k)
    def chord(self, xy, *a, **k): return self._d.chord(self._fix(xy), *a, **k)


def draw_icon(d, kind, cx, b, u, t):
    from .flat_art import draw_art
    if kind in ICONS:
        ICONS[kind](_Safe(d), cx, b, u, t)
    else:
        draw_art(d, kind, cx, b - 50 * u, 100 * u, t)


def render_icon(kind: str, size: int, t: float, ss: int = 2) -> Image.Image:
    """Anti-aliased RGBA icon (supersampled) roughly size x size, ground at the bottom."""
    S = size * ss
    im = Image.new("RGBA", (int(S * 1.3), S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im, "RGBA")
    draw_icon(d, kind, im.width / 2, S * 0.95, S / 100 * 0.9, t)
    return im.resize((im.width // ss, size), Image.LANCZOS)


# ------------------------------------------------------------------ parallax backdrops (built once, scrolled per frame)
def backdrop_layers(sector: str, W: int, H: int, seed: int = 5):
    """Returns (far, near) RGBA layers 1.5x wide for parallax; drawn supersampled for clean edges."""
    import random
    rnd = random.Random(seed)
    motif = SECTORS.get(sector, SECTORS["General"])["motif"]
    acc = SECTORS.get(sector, SECTORS["General"])["accent"]
    ss = 2
    LW, LH = int(W * 1.5) * ss, H * ss
    far = Image.new("RGBA", (LW, LH), (0, 0, 0, 0))
    near = Image.new("RGBA", (LW, LH), (0, 0, 0, 0))
    fd, nd = ImageDraw.Draw(far, "RGBA"), ImageDraw.Draw(near, "RGBA")
    hz = LH * 0.8
    fc = (32, 44, 28, 255)
    nc = (18, 24, 17, 255)
    if motif in ("skyline", "civic", "columns", "shelves"):
        x = 0
        while x < LW:
            w = rnd.randint(40, 110) * ss
            h = rnd.randint(60, 220) * ss * H / 540
            fd.rectangle([x, hz - h, x + w, hz], fill=fc)
            for wy in range(int(hz - h + 12 * ss), int(hz - 10 * ss), int(18 * ss)):
                for wx in range(x + 8 * ss, x + w - 8 * ss, 16 * ss):
                    if rnd.random() < 0.25:
                        fd.rectangle([wx, wy, wx + 5 * ss, wy + 6 * ss], fill=(60, 80, 40, 255))
            if motif == "civic" and rnd.random() < .2:
                fd.chord([x, hz - h - w * .5, x + w, hz - h + w * .5], 180, 360, fill=fc)
            x += w + rnd.randint(4, 30) * ss
    elif motif == "hills":
        pts = [(0, LH)] + [(x, hz - (60 + 40 * math.sin(x / (180 * ss)) + 25 * math.sin(x / (70 * ss))) * ss * H / 540) for x in range(0, LW + 20, 20)] + [(LW, LH)]
        fd.polygon(pts, fill=fc)
        for x in range(60 * ss, LW, 260 * ss):
            y = hz - 120 * ss * H / 540
            fd.line([(x, y), (x, y + 110 * ss)], fill=(44, 56, 40, 255), width=3 * ss)
    elif motif == "radar":
        for r in range(1, 6):
            R = r * 110 * ss
            fd.ellipse([LW * .3 - R, hz - R, LW * .3 + R, hz + R], outline=(40, 70, 28, 255), width=2 * ss)
        for x in range(0, LW, 60 * ss):
            fd.line([(x, 0), (x, LH)], fill=(28, 40, 24, 255), width=ss)
        for y in range(0, LH, 60 * ss):
            fd.line([(0, y), (LW, y)], fill=(28, 40, 24, 255), width=ss)
        pts = [(0, LH)] + [(x, hz - (30 + 20 * math.sin(x / (120 * ss))) * ss) for x in range(0, LW + 20, 20)] + [(LW, LH)]
        fd.polygon(pts, fill=fc)
    elif motif == "pulse":
        y0 = hz - 140 * ss * H / 540
        pts = []
        for x in range(0, LW, 6):
            ph = (x / (300 * ss)) % 1
            y = 0
            if 0.4 < ph < 0.43: y = -40
            elif 0.43 < ph < 0.47: y = 70
            elif 0.47 < ph < 0.5: y = -30
            pts.append((x, y0 - y * ss * H / 540))
        fd.line(pts, fill=(40, 70, 30, 255), width=3 * ss)
        x = 0
        while x < LW:
            w, h = rnd.randint(60, 120) * ss, rnd.randint(50, 120) * ss
            fd.rectangle([x, hz - h, x + w, hz], fill=fc)
            if rnd.random() < .4:
                fd.rectangle([x + w / 2 - 6 * ss, hz - h + 10 * ss, x + w / 2 + 6 * ss, hz - h + 34 * ss], fill=(44, 70, 30, 255))
                fd.rectangle([x + w / 2 - 12 * ss, hz - h + 16 * ss, x + w / 2 + 12 * ss, hz - h + 28 * ss], fill=(44, 70, 30, 255))
            x += w + rnd.randint(30, 90) * ss
    elif motif == "candles":
        y = hz - 160 * ss
        for x in range(30 * ss, LW, 34 * ss):
            y += rnd.randint(-20, 22) * ss
            h = rnd.randint(14, 50) * ss
            fd.line([(x + 6 * ss, y - h * .4), (x + 6 * ss, y + h * 1.4)], fill=(34, 48, 28, 255), width=ss)
            fd.rectangle([x, y, x + 12 * ss, y + h], fill=(36, 52, 28, 255))
        x = 0
        while x < LW:
            w, h = rnd.randint(50, 100) * ss, rnd.randint(70, 200) * ss
            nd.rectangle([x, hz - h, x + w, hz], fill=nc)
            x += w + rnd.randint(10, 40) * ss
    elif motif == "nodes":
        P = [(rnd.randint(0, LW), rnd.randint(int(LH * .1), int(hz))) for _ in range(40)]
        for i, p in enumerate(P):
            for q in P[i + 1:i + 3]:
                fd.line([p, q], fill=(30, 46, 40, 255), width=ss)
            fd.ellipse([p[0] - 4 * ss, p[1] - 4 * ss, p[0] + 4 * ss, p[1] + 4 * ss], fill=(40, 70, 70, 255))
    # near layer: soft foreground strip with a few sector-tinted props
    nd.rectangle([0, hz, LW, LH], fill=(14, 19, 13, 255))
    nd.line([(0, hz), (LW, hz)], fill=G2 + (255,), width=2 * ss)
    for x in range(0, LW, 140 * ss):
        nd.line([(x, hz + 8 * ss), (x + 60 * ss, hz + 8 * ss)], fill=acc + (70,), width=2 * ss)
    far = far.resize((LW // ss, H), Image.LANCZOS)
    near = near.resize((LW // ss, H), Image.LANCZOS)
    return far, near


_FC = {}


def _f(sz):
    from .video_summary import font
    sz = max(8, int(sz))
    if sz not in _FC:
        _FC[sz] = font(sz, True)
    return _FC[sz]


# ------------------------------------------------------------------ rigged cartoon character (sector outfit)
OUTFITS = {
    "Defense & Security": dict(shirt=(96, 112, 70), pants=(60, 70, 46), hat="helmet"),
    "Security & Justice": dict(shirt=(40, 50, 70), pants=(28, 32, 44), hat="cap"),
    "Health / LSHC": dict(shirt=(240, 244, 240), pants=(90, 160, 160), hat=None, steth=True),
    "Financial Services": dict(shirt=(44, 48, 56), pants=(36, 38, 44), hat=None, tie=G),
    "TMT": dict(shirt=(60, 70, 80), pants=(40, 60, 100), hat=None, hood=True),
    "Energy / ER&I": dict(shirt=(240, 150, 40), pants=(50, 60, 90), hat="hardhat"),
    "Consumer": dict(shirt=(240, 244, 240), pants=(60, 60, 70), hat=None, apron=G),
    "Government & Public Services": dict(shirt=(50, 70, 100), pants=(40, 44, 56), hat=None, tie=(200, 60, 60)),
    "General": dict(shirt=G, pants=(50, 56, 50), hat=None),
}


def _limb(d, a, b_, c, col, w, u):
    d.line([a, b_, c], fill=INK, width=int(w + 3 * u), joint="curve")
    d.line([a, b_, c], fill=col, width=int(w), joint="curve")


def rig(d, x, base, h, t, sector="General", mood="neutral", pose="idle", walk=0.0, face=1):
    """Cartoon presenter. pose: idle|point|wave|shrug; walk: 0..1 walking intensity (legs swing, body bobs);
    face: 1 looks right, -1 left. Blinks every ~3 s. Draw on a supersampled RGBA layer for smooth edges."""
    o = OUTFITS.get(sector, OUTFITS["General"])
    u = h / 100
    ph = t * 9
    bob = (abs(math.sin(ph)) * 3 * walk + 1.2 * math.sin(t * 3) * (1 - walk)) * u
    hip = (x, base - 44 * u - bob)
    ow = max(1, int(2.2 * u))
    d.ellipse([x - 22 * u, base - 4 * u, x + 22 * u, base + 4 * u], fill=(0, 0, 0, 110))
    # legs
    for sgn in (-1, 1):
        sw = math.sin(ph + (0 if sgn > 0 else math.pi)) * 20 * u * walk
        knee = (hip[0] + sgn * 4 * u + sw * .5, hip[1] + 22 * u)
        foot = (hip[0] + sgn * 5 * u + sw, base - 3 * u - max(0, math.cos(ph + (0 if sgn > 0 else math.pi))) * 5 * u * walk)
        _limb(d, (hip[0] + sgn * 5 * u, hip[1]), knee, foot, o["pants"], 9 * u, u)
        d.ellipse([foot[0] - 6 * u + face * 3 * u, foot[1] - 4 * u, foot[0] + 6 * u + face * 3 * u, foot[1] + 4 * u], fill=INK)
    # torso
    top = hip[1] - 40 * u
    blk(d, [x - 15 * u, top, x + 15 * u, hip[1] + 4 * u], o["shirt"], u, 8)
    if o.get("apron"):
        d.rounded_rectangle([x - 11 * u, top + 12 * u, x + 11 * u, hip[1] + 4 * u], radius=int(3 * u), fill=o["apron"])
    if o.get("tie"):
        d.polygon([(x, top + 2 * u), (x + 3 * u, top + 8 * u), (x + 1.5 * u, top + 24 * u), (x - 1.5 * u, top + 24 * u), (x - 3 * u, top + 8 * u)], fill=o["tie"])
        d.polygon([(x - 7 * u, top), (x, top + 8 * u), (x - 2 * u, top)], fill=W_)
        d.polygon([(x + 7 * u, top), (x, top + 8 * u), (x + 2 * u, top)], fill=W_)
    if o.get("steth"):
        d.arc([x - 9 * u, top - 2 * u, x + 9 * u, top + 22 * u], 0, 180, fill=DG, width=max(1, int(2 * u)))
        d.ellipse([x + 5 * u, top + 18 * u, x + 11 * u, top + 24 * u], fill=GR)
    if sector == "Energy / ER&I":
        d.line([(x - 15 * u, top + 20 * u), (x + 15 * u, top + 20 * u)], fill=(240, 240, 120), width=max(1, int(3 * u)))
    # arms
    sh_y = top + 7 * u
    for sgn in (-1, 1):
        s0 = (x + sgn * 14 * u, sh_y)
        front = sgn == face
        if pose == "point" and front:
            el, hd = (s0[0] + sgn * 16 * u, s0[1] - 6 * u), (s0[0] + sgn * 32 * u, s0[1] - 16 * u + 2 * u * math.sin(t * 5))
        elif pose == "wave" and front:
            a = math.sin(t * 10) * 0.5
            el = (s0[0] + sgn * 12 * u, s0[1] - 10 * u)
            hd = (el[0] + sgn * 10 * u * math.cos(a) , el[1] - 16 * u)
        elif pose == "shrug":
            el, hd = (s0[0] + sgn * 12 * u, s0[1] + 10 * u), (s0[0] + sgn * 20 * u, s0[1] - 2 * u)
        else:
            sw = -math.sin(ph + (0 if sgn > 0 else math.pi)) * 9 * u * walk
            el, hd = (s0[0] + sgn * 5 * u + sw * .5, s0[1] + 16 * u), (s0[0] + sgn * 8 * u + sw, s0[1] + 29 * u)
        _limb(d, s0, el, hd, o["shirt"], 8 * u, u)
        r = 4.5 * u
        d.ellipse([hd[0] - r - ow, hd[1] - r - ow, hd[0] + r + ow, hd[1] + r + ow], fill=INK)
        d.ellipse([hd[0] - r, hd[1] - r, hd[0] + r, hd[1] + r], fill=SKIN)
    # head
    hx, hy = x + face * 1.5 * u, top - 17 * u
    R = 15 * u
    d.ellipse([hx - R - ow, hy - R - ow, hx + R + ow, hy + R + ow], fill=INK)
    d.ellipse([hx - R, hy - R, hx + R, hy + R], fill=SKIN)
    d.chord([hx - R, hy - R, hx + R, hy + R], 300, 60, fill=(214, 176, 140))
    hat = o.get("hat")
    if hat == "helmet":
        d.chord([hx - R - 3 * u, hy - R - 4 * u, hx + R + 3 * u, hy + R * 0.6], 180, 360, fill=o["shirt"], outline=INK, width=ow)
    elif hat == "hardhat":
        d.chord([hx - R - 1 * u, hy - R - 4 * u, hx + R + 1 * u, hy + R * 0.5], 180, 360, fill=(250, 210, 60), outline=INK, width=ow)
        d.line([(hx - R - 5 * u, hy - 1 * u), (hx + R + 5 * u, hy - 1 * u)], fill=(250, 210, 60), width=max(2, int(3 * u)))
    elif hat == "cap":
        d.chord([hx - R, hy - R - 3 * u, hx + R, hy + R * 0.4], 180, 360, fill=o["shirt"], outline=INK, width=ow)
        d.line([(hx, hy - 3 * u), (hx + face * (R + 7 * u), hy - 3 * u)], fill=INK, width=max(2, int(3 * u)))
    elif o.get("hood"):
        d.arc([hx - R - 3 * u, hy - R - 3 * u, hx + R + 3 * u, hy + R + 3 * u], 150, 390, fill=o["shirt"], width=max(2, int(4 * u)))
        d.chord([hx - R, hy - R - 1 * u, hx + R, hy + R * 0.1], 180, 360, fill=(40, 30, 26))
    else:
        d.chord([hx - R, hy - R - 1 * u, hx + R, hy + R * 0.1], 180, 360, fill=(40, 30, 26))
    ex0 = hx + face * 4 * u
    ey = hy + 2 * u
    blink = (t % 3.1) < 0.12
    for sgn in (-1, 1):
        ex = ex0 + sgn * 5.5 * u
        if blink:
            d.line([(ex - 3 * u, ey), (ex + 3 * u, ey)], fill=INK, width=max(1, int(1.6 * u)))
        elif mood == "happy":
            d.arc([ex - 3.5 * u, ey - 2 * u, ex + 3.5 * u, ey + 4 * u], 200, 340, fill=INK, width=max(1, int(1.8 * u)))
        else:
            r = (3.4 if mood == "wow" else 2.6) * u
            d.ellipse([ex - r, ey - r, ex + r, ey + r], fill=W_)
            d.ellipse([ex - r * .6 + face * .6 * u, ey - r * .6, ex + r * .6 + face * .6 * u, ey + r * .6], fill=INK)
        if mood == "worried":
            d.line([(ex - 3 * u, ey - 6 * u + sgn * 1.5 * u), (ex + 3 * u, ey - 6 * u - sgn * 1.5 * u)], fill=INK, width=max(1, int(1.6 * u)))
        elif mood == "wow":
            d.arc([ex - 3 * u, ey - 9 * u, ex + 3 * u, ey - 4 * u], 200, 340, fill=INK, width=max(1, int(1.4 * u)))
    my = hy + 8.5 * u
    talk = abs(math.sin(t * 11)) if pose in ("point", "idle") and walk < .3 else 0
    if mood == "happy":
        d.chord([ex0 - 6 * u, my - 4 * u, ex0 + 6 * u, my + 4 * u + talk * 2 * u], 0, 180, fill=INK)
    elif mood == "worried":
        d.arc([ex0 - 5 * u, my, ex0 + 5 * u, my + 6 * u], 200, 340, fill=INK, width=max(1, int(1.8 * u)))
    elif mood == "wow":
        d.ellipse([ex0 - 3 * u, my - 2 * u, ex0 + 3 * u, my + 5 * u], fill=INK)
    else:
        d.ellipse([ex0 - 4 * u, my - 1 * u, ex0 + 4 * u, my + 1.5 * u + talk * 3 * u], fill=INK)


def transition(d, kind, W, H, p, acc):
    """Sector-flavoured scene-entry wipe; p 0->1 (cover recedes). Draw last, on top of the frame."""
    if p >= 1:
        return
    q = 1 - p
    col = (10, 12, 10, 255)
    if kind == "radar":      # clock sweep reveal
        R = math.hypot(W, H)
        a = -90 + 360 * p
        d.pieslice([W / 2 - R, H / 2 - R, W / 2 + R, H / 2 + R], a, 270, fill=col)
        d.line([(W / 2, H / 2), (W / 2 + R * math.cos(math.radians(a)), H / 2 + R * math.sin(math.radians(a)))], fill=G + (255,), width=max(2, H // 180))
    elif kind == "candles":  # bars drop away in a staggered sequence
        n = 10
        for i in range(n):
            qq = min(1, max(0, (p * 1.6 - i * 0.06)))
            y = H * qq ** 2
            d.rectangle([i * W / n, y, (i + 1) * W / n + 1, H], fill=col)
            d.rectangle([i * W / n, y, (i + 1) * W / n + 1, y + H * 0.008], fill=(G if i % 3 else acc) + (255,))
    elif kind == "pulse":    # heartbeat line sweeps across, revealing
        x = W * p
        d.rectangle([x, 0, W, H], fill=col)
        y = H / 2
        d.line([(x - W * .1, y), (x - W * .05, y), (x - W * .04, y - H * .1), (x - W * .03, y + H * .12), (x - W * .02, y), (x + 4, y)], fill=G + (255,), width=max(2, H // 200))
    elif kind == "nodes":    # pixel tiles dissolve
        n = 12
        cw, ch = W / n, H / (n * H / W)
        for i in range(n):
            for j in range(int(H / ch) + 1):
                if ((i * 7 + j * 13) % 17) / 17 > p:
                    d.rectangle([i * cw, j * ch, (i + 1) * cw, (j + 1) * ch], fill=col)
    else:                    # diagonal panel with an accent edge
        x = -W * 0.3 + (W * 1.6) * p
        d.polygon([(x, 0), (W * 1.4, 0), (W * 1.4, H), (x - W * 0.3, H)], fill=col)
        d.line([(x, 0), (x - W * 0.3, H)], fill=G + (255,), width=max(3, H // 120))
    _ = q
