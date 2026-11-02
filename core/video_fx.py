"""Cinematic renderers for the video summary.

* HoloRenderer(presenter=False): "Holographic (cinematic)". It has parallax depth layers (a perspective floor grid,
  circuit traces, data streams and a particle field), a perspective-tilted holographic slide panel with light sweeps,
  bloom, animated HUD rings, a typewriter caption with a glowing cursor, glitch transitions, a camera drift, an intro
  sting and a CRT-off outro.
* HoloRenderer(presenter=True): "AI Presenter". The same studio, plus NOVA, an original hover-robot drawn procedurally
  (vector shapes, supersampled). Its mouth light-bar, chest core and head bob follow the voiceover loudness, and it
  blinks and gestures toward a large holographic screen that plays the slides.

Pure PIL + numpy, so there are no models, GPUs or API keys, and it runs on Streamlit Community Cloud.
"""
from __future__ import annotations

import math
import os
import random
import re
import subprocess
from typing import List

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .video_summary import GREEN, Segment, _count_up, _ease, _rgba_over, _wrap, ffmpeg_bin, font

EYE = (196, 255, 96)
BODY = (44, 48, 54)
BODY_HI = (78, 84, 92)
DARK = (16, 18, 20)
RIM = (134, 188, 37)
AUDIO_DELAY = 0.25          # matches adelay=250 in render_video


# --------------------------------------------------------------------------- audio envelope
def envelope(path: str, fps: int, n: int) -> np.ndarray:
    """Per-frame loudness 0..1 (fast attack, slower release) for lip-sync."""
    try:
        raw = subprocess.run([ffmpeg_bin(), "-loglevel", "error", "-i", path, "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                             capture_output=True, timeout=60, check=True).stdout
        x = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
    except Exception:
        return np.zeros(n, np.float32)
    hop = 16000 // fps
    pad = np.zeros(int(AUDIO_DELAY * 16000), np.float32)
    x = np.concatenate([pad, x])
    m = len(x) // hop
    rms = np.sqrt((x[: m * hop].reshape(m, hop) ** 2).mean(1)) if m else np.zeros(0)
    ref = np.percentile(rms, 95) if len(rms) else 1
    v = np.clip((rms - 0.012) / max(ref, 1e-4), 0, 1)
    out = np.zeros(n, np.float32)
    prev = 0.0
    for i in range(n):
        cur = v[i] if i < len(v) else 0.0
        prev = cur if cur > prev else prev * 0.55 + cur * 0.45
        out[i] = prev
    return out


# --------------------------------------------------------------------------- geometry / fx helpers
def _coeffs(dst, src):
    A, B = [], []
    for (x, y), (u, v) in zip(dst, src):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y]); B.append(u)
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y]); B.append(v)
    return np.linalg.solve(np.array(A, float), np.array(B, float))


def _quad(cx, cy, pw, ph, yaw, pitch=0.0, scale=1.0):
    D = pw * 2.4
    out = []
    for x, y in [(-pw / 2, -ph / 2), (pw / 2, -ph / 2), (pw / 2, ph / 2), (-pw / 2, ph / 2)]:
        x, y = x * scale, y * scale
        X, Z = x * math.cos(yaw), x * math.sin(yaw)
        Y, Z = y * math.cos(pitch), Z + y * math.sin(pitch)
        s = D / (D + Z)
        out.append((cx + X * s, cy + Y * s))
    return out


def bloom(img: np.ndarray, strength=0.6, thresh=125) -> np.ndarray:
    H, W = img.shape[:2]
    sm = Image.fromarray(img).resize((W // 4, H // 4), Image.BILINEAR)
    a = np.asarray(sm).astype(np.int16) - thresh
    a = np.clip(a * 2, 0, 255).astype(np.uint8)
    b = Image.fromarray(a).filter(ImageFilter.GaussianBlur(3)).resize((W, H), Image.BILINEAR)
    return np.clip(img.astype(np.int16) + (np.asarray(b).astype(np.int16) * strength).astype(np.int16), 0, 255).astype(np.uint8)


def glitch(img: np.ndarray, k: float, seed: int) -> np.ndarray:
    if k <= 0.01:
        return img
    rng = np.random.default_rng(seed)
    H, W = img.shape[:2]
    out = img.copy()
    for _ in range(int(2 + 9 * k)):
        y = int(rng.integers(0, H - 4)); h = int(rng.integers(2, max(3, int(H * 0.06 * k) + 3)))
        out[y:y + h] = np.roll(out[y:y + h], int(rng.integers(-1, 2) * W * 0.06 * k * rng.random()), axis=1)
    d = max(1, int(W * 0.008 * k))
    out[..., 0] = np.roll(out[..., 0], d, axis=1)
    out[..., 2] = np.roll(out[..., 2], -d, axis=1)
    for _ in range(int(4 * k)):
        x, y = int(rng.integers(0, W - 40)), int(rng.integers(0, H - 10))
        out[y:y + int(rng.integers(3, 12)), x:x + int(rng.integers(20, 120))] = GREEN if rng.random() < .5 else (230, 255, 200)
    return (out * (1 - 0.35 * k * rng.random())).astype(np.uint8)


def _glitch_layer(arr: np.ndarray, k: float, seed: int) -> np.ndarray:
    if k <= 0.01:
        return arr
    rng = np.random.default_rng(seed)
    out = arr.copy()
    h = arr.shape[0]
    for _ in range(int(3 + 6 * k)):
        y = int(rng.integers(0, max(1, h - 2))); hh = int(rng.integers(1, max(2, h // 5)))
        out[y:y + hh] = np.roll(out[y:y + hh], int((rng.random() - .5) * 60 * k), axis=1)
    out[..., 0] = np.roll(out[..., 0], int(6 * k) + 1, axis=1)
    out[..., 2] = np.roll(out[..., 2], -int(6 * k) - 1, axis=1)
    return out


# --------------------------------------------------------------------------- robot (procedural, original design)
def draw_robot(height_px: int, t: float, amp: float, blink: float, point: float, wave: float, ss: int = 2) -> np.ndarray:
    """NOVA: a friendly hover robot. Returns an RGBA array about 0.76*height wide."""
    u = height_px / 100 * ss
    Wb, Hb = int(78 * u), int(100 * u)
    im = Image.new("RGBA", (Wb, Hb), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx = Wb / 2
    bob = math.sin(t * 1.7) * 1.1
    hb = bob + amp * 0.9 + math.sin(t * 3.3) * 0.3
    hx = math.sin(t * 0.8) * 0.7

    def P(x, y, dy=bob, dx=0.0):
        return (cx + (x + dx) * u, (y + dy) * u)

    def R(x0, y0, x1, y1, dy=bob, dx=0.0):
        a, b = P(x0, y0, dy, dx), P(x1, y1, dy, dx)
        return [a[0], a[1], b[0], b[1]]
    lw = max(1, int(0.7 * u))
    # thruster + hover base
    fl = 0.75 + 0.25 * math.sin(t * 23)
    d.ellipse(R(-10, 91, 10, 95.5), fill=EYE[:3] + (int(150 * fl),))
    d.ellipse(R(-6, 92, 6, 94.5), fill=(235, 255, 210, 255))
    d.polygon([P(-15, 72), P(15, 72), P(11, 81), P(-11, 81)], fill=DARK)
    d.ellipse(R(-14, 79, 14, 90), fill=BODY, outline=RIM, width=lw)
    d.ellipse(R(-9, 82.5, 9, 86.5), outline=EYE, width=lw)

    # arms (back side first)
    def limb(side, a1, a2, glow=False):
        sx, sy = P(22 * side, 45)
        L1, L2 = 15 * u, 14 * u
        ex, ey = sx + L1 * math.sin(a1) * side, sy + L1 * math.cos(a1)
        hx_, hy_ = ex + L2 * math.sin(a2) * side, ey + L2 * math.cos(a2)
        d.line([(sx, sy), (ex, ey)], fill=BODY, width=int(6.5 * u))
        d.line([(ex, ey), (hx_, hy_)], fill=BODY_HI, width=int(5 * u))
        for (x, y, r) in [(sx, sy, 4.6), (ex, ey, 3.4)]:
            d.ellipse([x - r * u, y - r * u, x + r * u, y + r * u], fill=DARK, outline=RIM, width=lw)
        r = 3.8 * u
        d.ellipse([hx_ - r, hy_ - r, hx_ + r, hy_ + r], fill=DARK, outline=RIM, width=lw)
        r2 = (1.5 + (1.2 if glow else 0)) * u
        d.ellipse([hx_ - r2, hy_ - r2, hx_ + r2, hy_ + r2], fill=EYE)
    # torso
    d.rounded_rectangle(R(-21, 39, 21, 73), radius=int(9 * u), fill=BODY, outline=RIM, width=lw)
    d.rounded_rectangle(R(-17, 41.5, 4, 46), radius=int(2 * u), fill=BODY_HI)
    d.line([P(-19, 66), P(19, 66)], fill=DARK, width=lw)
    for k in range(3):
        d.line([P(10, 59 + k * 2.2), P(16, 59 + k * 2.2)], fill=RIM, width=lw)
    core = 2.4 + amp * 2.4
    d.ellipse(R(-7, 47, 7, 61), fill=DARK, outline=RIM, width=lw)
    d.ellipse(R(-core, 54 - core, core, 54 + core), fill=EYE)
    d.ellipse(R(-5.2, 48.8, 5.2, 59.2), outline=EYE[:3] + (int(120 + 135 * amp),), width=lw)
    # arms in front
    talk = min(1.0, amp * 1.5)
    limb(+1, 0.28 + 1.75 * point + 0.06 * math.sin(t * 2.1), 0.65 + 1.55 * point + 0.12 * talk * math.sin(t * 4.3), glow=point > .5)
    limb(-1, 0.22 + 2.25 * wave + 0.05 * talk * math.sin(t * 3.1),
         0.75 + 2.4 * wave + 0.35 * wave * math.sin(t * 10) + 0.25 * talk * math.sin(t * 4.7 + 1))
    # neck + head
    d.rectangle(R(-5, 33, 5, 40.5), fill=DARK)
    d.ellipse(R(-23, 17.5, -15, 26.5, hb, hx), fill=DARK, outline=RIM, width=lw)
    d.ellipse(R(15, 17.5, 23, 26.5, hb, hx), fill=DARK, outline=RIM, width=lw)
    d.ellipse(R(-20.5, 20.5, -17.5, 23.5, hb, hx), fill=EYE)
    d.ellipse(R(17.5, 20.5, 20.5, 23.5, hb, hx), fill=EYE)
    d.rounded_rectangle(R(-18, 8, 18, 35.5, hb, hx), radius=int(11 * u), fill=BODY, outline=RIM, width=lw)
    d.ellipse(R(-12, 9.6, 6, 13.2, hb, hx), fill=BODY_HI)
    d.rounded_rectangle(R(-14.5, 14, 14.5, 31, hb, hx), radius=int(6 * u), fill=(5, 9, 5), outline=(70, 105, 28), width=lw)
    lx = math.sin(t * 0.7) * 0.9 + 0.6 * point
    eh = max(0.5, 5.6 * (1 - blink))
    for ex in (-6.5, 6.5):
        d.rounded_rectangle(R(ex - 3.3 + lx, 20.5 - eh / 2, ex + 3.3 + lx, 20.5 + eh / 2, hb, hx), radius=int(1.6 * u), fill=EYE)
    for i in range(9):
        shape = 1 - abs(i - 4) / 5
        h = 0.45 + amp * 3.0 * shape * (0.65 + 0.35 * math.sin(t * 23 + i * 1.7))
        x = -8 + i * 2
        d.rounded_rectangle(R(x - 0.55, 27 - h / 2, x + 0.55, 27 + h / 2, hb, hx), radius=int(0.5 * u), fill=EYE)
    d.line([P(0, 8.5, hb, hx), P(0, 3.6, hb, hx)], fill=DARK, width=int(1.1 * u))
    pr = 1.6 + 0.5 * math.sin(t * 4)
    d.ellipse(R(-pr, 2.6 - pr, pr, 2.6 + pr, hb, hx), fill=EYE)
    im = im.resize((Wb // ss, Hb // ss), Image.LANCZOS)
    return np.asarray(im)


# --------------------------------------------------------------------------- renderer
class HoloRenderer:
    def __init__(self, W, H, fps, deck_title: str, lang_label: str = "", presenter: bool = False, seed: int = 7,
                 photo: str | None = None, presenter_name: str = ""):
        self.W, self.H, self.fps = W, H, fps
        self.k = W / 1280
        self.title, self.lang, self.presenter = deck_title, lang_label, presenter
        self.avatar = None
        if presenter and photo:
            from .photo_avatar import PhotoAvatar
            self.avatar = PhotoAvatar(photo, int(H * 0.64))
        nm = (presenter_name or "").strip()[:28]
        self.tag = f"{nm.upper()} // AI PRESENTER" if nm else ("AI PRESENTER" if self.avatar else "NOVA // AI PRESENTER")
        self.T = 0.0
        self.m = int(0.05 * W)
        rnd = random.Random(seed)
        self.rnd = rnd
        self.far = self._far(rnd)
        self.mid = self._circuits(rnd)
        self.streams = self._streams(rnd)
        n = 260
        r = np.random.default_rng(seed)
        self.px, self.py, self.pz = r.random(n) * W, r.random(n) * H, 0.25 + 0.75 * r.random(n) ** 2
        self.blinks = sorted(rnd.uniform(0, 600) for _ in range(260))
        self.f_hud = font(self.s(15), "mono")

    def s(self, v):
        return max(1, int(v * self.k))

    # ---------------- static layers
    def _far(self, rnd):
        W, H, m = self.W + 2 * self.m, self.H + 2 * self.m, self.m
        im = Image.new("RGB", (W, H), (0, 0, 0))
        d = ImageDraw.Draw(im)
        hz = int(H * 0.62)
        vx = W // 2
        for i in range(-24, 25):
            d.line([(vx + i * W * 0.012, hz), (vx + i * W * 0.11, H)], fill=(18, 34, 6), width=1)
        y, step = hz, 3.0
        while y < H:
            d.line([(0, int(y)), (W, int(y))], fill=(18, 34, 6), width=1)
            step *= 1.28; y += step
        d.line([(0, hz), (W, hz)], fill=(40, 70, 14), width=1)
        for _ in range(140):
            x, yy = rnd.uniform(0, W), rnd.uniform(0, hz)
            c = rnd.randint(25, 70)
            d.point((x, yy), fill=(c, c + 15, c // 2))
        a = np.asarray(im).astype(np.float32)
        yy, xx = np.mgrid[0:H, 0:W]
        haze = np.exp(-(((xx - W / 2) / (W * .45)) ** 2 + ((yy - hz) / (H * .35)) ** 2))
        a += haze[..., None] * np.array([10, 22, 3])
        v = 1 - 0.6 * (((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2) / 2
        return (a * v[..., None]).clip(0, 255).astype(np.uint8)

    def _circuits(self, rnd):
        W, H = self.W + 2 * self.m, self.H + 2 * self.m
        im = Image.new("RGB", (W, H), (0, 0, 0))
        d = ImageDraw.Draw(im)
        g = max(6, W // 90)
        for _ in range(46):
            x = rnd.choice([rnd.uniform(0, W * .18), rnd.uniform(W * .82, W)])
            y = rnd.uniform(0, H * .6)
            x, y = round(x / g) * g, round(y / g) * g
            pts = [(x, y)]
            for _ in range(rnd.randint(3, 6)):
                if rnd.random() < .5:
                    x += rnd.choice([-1, 1]) * g * rnd.randint(2, 7)
                else:
                    y += rnd.choice([-1, 1]) * g * rnd.randint(2, 6)
                pts.append((x, y))
            c = rnd.randint(28, 55)
            d.line(pts, fill=(c // 2, c, c // 5), width=1)
            for p in (pts[0], pts[-1]):
                d.ellipse([p[0] - 2, p[1] - 2, p[0] + 2, p[1] + 2], outline=(c, c * 2, c // 3))
        return np.asarray(im)

    def _streams(self, rnd):
        f = font(self.s(13), "mono")
        cw = self.s(12)
        out = []
        xs = [rnd.uniform(0.01, 0.12) for _ in range(4)] + [rnd.uniform(0.88, 0.98) for _ in range(4)]
        for x in xs:
            hh = self.H * 2
            im = Image.new("RGB", (cw, hh), (0, 0, 0))
            d = ImageDraw.Draw(im)
            y = 0
            while y < hh:
                c = int(25 + 70 * ((y / hh * 3) % 1))
                d.text((0, y), rnd.choice("0123456789ABCDEF<>/#"), font=f, fill=(c // 3, c, c // 6))
                y += self.s(15)
            out.append((int(x * self.W), np.asarray(im), rnd.uniform(40, 110) * self.k))
        return out

    # ---------------- per-frame building blocks
    def cam(self, t):
        return math.sin(t * 0.31) * self.m * 0.8, math.sin(t * 0.23 + 1) * self.m * 0.5

    def background(self, t):
        cx, cy = self.cam(t)
        m, W, H = self.m, self.W, self.H
        ox, oy = int(m + cx * 0.3), int(m + cy * 0.3)
        img = self.far[oy:oy + H, ox:ox + W].copy()
        ox, oy = int(m + cx * 0.7), int(m + cy * 0.7)
        np.maximum(img, self.mid[oy:oy + H, ox:ox + W], out=img)
        for x, strip, sp in self.streams:
            off = int(t * sp) % H
            seg = strip[H - off: 2 * H - off]
            w = seg.shape[1]
            x0 = int(x + cx * 0.5)
            if 0 <= x0 and x0 + w <= W:
                np.maximum(img[:, x0:x0 + w], seg, out=img[:, x0:x0 + w])
        return img

    def particles(self, img, t, near: bool):
        W, H = self.W, self.H
        cx, cy = self.cam(t)
        sel = self.pz > 0.75 if near else self.pz <= 0.75
        z = self.pz[sel]
        x = ((self.px[sel] + cx * z * 1.4 + np.sin(t * 0.5 + self.py[sel]) * 6 * z) % W).astype(int)
        y = ((self.py[sel] - t * 18 * self.k * z + cy * z) % H).astype(int)
        tw = 0.6 + 0.4 * np.sin(t * 3 + self.px[sel])
        col = (np.array(EYE)[None, :] * (z * tw)[:, None]).astype(np.uint8)
        img[y, x] = np.maximum(img[y, x], col)
        if near:
            for dx, dy in ((1, 0), (0, 1), (1, 1)):
                yy, xx = np.minimum(y + dy, H - 1), np.minimum(x + dx, W - 1)
                img[yy, xx] = np.maximum(img[yy, xx], col)

    def rings(self, d: ImageDraw.ImageDraw, c, R, t, alpha=1.0, n=3):
        x, y = c
        for k in range(n):
            r = R * (1 - 0.17 * k)
            a0 = (t * (40 + 25 * k) * (-1) ** k) % 360
            col = tuple(int(v * alpha * (0.95 - 0.25 * k)) for v in GREEN)
            segs = [(0, 70), (95, 150), (180, 260), (290, 330)] if k % 2 == 0 else [(0, 200)]
            for s0, s1 in segs:
                d.arc([x - r, y - r, x + r, y + r], a0 + s0, a0 + s1, fill=col, width=max(1, self.s(3 - k)))
        for i in range(24):
            a = math.radians(i * 15 + t * 20)
            r1, r2 = R * 1.08, R * (1.13 if i % 3 == 0 else 1.10)
            col = tuple(int(v * alpha * .6) for v in GREEN)
            d.line([(x + r1 * math.cos(a), y + r1 * math.sin(a)), (x + r2 * math.cos(a), y + r2 * math.sin(a))], fill=col)

    def holo_panel(self, img, src: Image.Image, cx, cy, pw, ph, yaw, t, appear=1.0, pitch=-0.05):
        quad = _quad(cx, cy, pw, ph, yaw + 0.035 * math.sin(t * 0.5), pitch + 0.02 * math.sin(t * 0.37), 0.9 + 0.1 * appear)
        xs, ys = [p[0] for p in quad], [p[1] for p in quad]
        x0, y0, x1, y1 = int(min(xs)), int(min(ys)), int(math.ceil(max(xs))), int(math.ceil(max(ys)))
        bw, bh = x1 - x0, y1 - y0
        co = _coeffs([(x - x0, y - y0) for x, y in quad], [(0, 0), (src.width, 0), (src.width, src.height), (0, src.height)])
        warped = np.asarray(src.transform((bw, bh), Image.PERSPECTIVE, tuple(co), Image.BILINEAR)).copy()
        a = warped[..., 3].astype(np.float32) / 255
        # light sweep
        pos = ((t * 0.32) % 1.6 - 0.3) * (bw + bh)
        xx = np.arange(bw, dtype=np.float32)[None, :]
        yy = np.arange(bh, dtype=np.float32)[:, None]
        band = np.exp(-(((xx + 0.5 * yy) - pos) / (0.05 * bw + 1)) ** 2) * 110
        rgb = warped[..., :3].astype(np.float32) + band[..., None] * np.array([0.8, 1.0, 0.6])
        warped[..., :3] = rgb.clip(0, 255).astype(np.uint8)
        warped[..., 3] = (a * 255 * appear * (0.9 + 0.1 * math.sin(t * 13))).astype(np.uint8)
        _rgba_over(img, warped, x0, y0)
        return quad

    def frame_hud(self, d: ImageDraw.ImageDraw, label, idx, total, t):
        W, H, s = self.W, self.H, self.s
        d.ellipse([s(28), s(24), s(40), s(36)], fill=GREEN if int(t * 2) % 2 == 0 else (60, 90, 20))
        d.text((s(50), s(21)), f"NEURAL BRIEFING  //  {self.title[:44].upper()}", font=self.f_hud, fill=(190, 200, 190))
        d.text((W - s(28), s(21)), f"{label} {idx:02d}/{total:02d}", font=self.f_hud, fill=GREEN, anchor="ra")
        d.line([(s(28), s(46)), (W - s(28), s(46))], fill=(50, 80, 18))
        pw_ = (W - s(56)) * min(1.0, (idx - 1 + min(1.0, t / 8)) / max(1, total))
        d.line([(s(28), H - s(26)), (W - s(28), H - s(26))], fill=(30, 50, 10), width=s(3))
        d.line([(s(28), H - s(26)), (s(28) + pw_, H - s(26))], fill=GREEN, width=s(3))
        if self.lang:
            d.text((W - s(28), H - s(48)), f"VOICE // {self.lang.upper()}", font=self.f_hud, fill=(110, 120, 110), anchor="ra")

    def text_layer(self, text, fnt, color=(255, 255, 255), width=None, lines=1, spacing=1.25, anchor_center=False):
        width = width or self.W
        ls = _wrap(text, fnt, width, lines) or [""]
        lh = int(fnt.size * spacing)
        im = Image.new("RGBA", (width, lh * len(ls) + self.s(8)), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        for i, ln in enumerate(ls):
            if anchor_center:
                d.text((width // 2, i * lh), ln, font=fnt, fill=color + (255,), anchor="ma")
            else:
                d.text((0, i * lh), ln, font=fnt, fill=color + (255,))
        return np.asarray(im), ls, lh

    def typewriter(self, img, layer, lines, lh, fnt, x, y, p, t):
        total = sum(len(l) for l in lines) or 1
        n = int(total * max(0.0, min(1.0, p)))
        out = np.zeros_like(layer)
        cur = None
        for i, ln in enumerate(lines):
            if n <= 0:
                break
            k = min(len(ln), n)
            w = int(fnt.getlength(ln[:k])) + 2
            out[i * lh:(i + 1) * lh, :w] = layer[i * lh:(i + 1) * lh, :w]
            cur = (x + w + 2, y + i * lh)
            n -= len(ln)
        _rgba_over(img, out, x, y)
        if cur and (p < 1 or int(t * 2.5) % 2 == 0):
            cx, cy = cur
            img[cy + 2:cy + int(lh * 0.8), cx:cx + max(2, self.s(9))] = EYE

    # ---------------- segments
    def frames(self, seg: Segment, slides, idx: int, total: int):
        n = max(1, int(round(seg.seconds * self.fps)))
        env = envelope(seg.audio, self.fps, n) if (self.presenter and seg.audio) else np.zeros(n, np.float32)
        gen = self._point(seg, slides[seg.slide], idx, total, n, env) if seg.kind == "point" else self._card(seg, idx, total, n, env)
        for f, img in enumerate(gen):
            yield img
        self.T += n / self.fps

    def _slide_src(self, slide, pw, ph):
        if slide is not None and slide.image_path and os.path.exists(slide.image_path):
            src = Image.open(slide.image_path).convert("RGB").resize((int(pw), int(ph)), Image.LANCZOS)
        else:
            src = Image.new("RGB", (int(pw), int(ph)), (10, 20, 6))
        a = np.asarray(src).astype(np.float32)
        a = a * 0.62 + np.array([6, 22, 2])
        a[::3] *= 0.8
        a = a.clip(0, 255).astype(np.uint8)
        alpha = np.full(a.shape[:2], 238, np.uint8)
        e = max(2, int(pw * 0.006))
        rgba = np.dstack([a, alpha])
        rgba[:e, :, :3] = GREEN; rgba[-e:, :, :3] = GREEN; rgba[:, :e, :3] = GREEN; rgba[:, -e:, :3] = GREEN
        rgba[:e, :, 3] = rgba[-e:, :, 3] = rgba[:, :e, 3] = rgba[:, -e:, 3] = 255
        return Image.fromarray(rgba, "RGBA")

    def _robot(self, img, t, amp, f, n, appear=1.0, point=0.0, wave=0.0):
        W, H = self.W, self.H
        tt = self.T + t
        blink = 0.0
        for b in self.blinks:
            if abs(tt - b) < 0.09:
                blink = 1 - abs(tt - b) / 0.09
        rh = int(H * 0.64)
        cx, cy = self.cam(tt)
        rob = self.avatar.frame(tt, float(amp), blink) if self.avatar else draw_robot(rh, tt, float(amp), blink, point, wave)
        rx = int(W * 0.17 - rob.shape[1] / 2 + cx * 1.1)
        ry = int(H * 0.95 - rob.shape[0] + cy * 1.1)
        # floor shadow + glow pool
        pil = Image.fromarray(img)
        d = ImageDraw.Draw(pil)
        fx, fy = rx + rob.shape[1] // 2, int(H * 0.955 + cy * 1.1)
        for k in range(5, 0, -1):
            c = int(14 * (6 - k) * appear)
            d.ellipse([fx - k * rh * .045, fy - k * rh * .009, fx + k * rh * .045, fy + k * rh * .009], fill=(c // 3, c, c // 6))
        img[:] = np.asarray(pil)
        if appear < 1:
            rob = rob.copy()
            cut = int(rob.shape[0] * (1 - appear))
            rob[:cut, :, 3] = 0
            if 0 < cut < rob.shape[0]:
                rob[cut:cut + 3, :, :3] = EYE
            rob[..., 3] = (rob[..., 3] * (0.4 + 0.6 * appear)).astype(np.uint8)
        _rgba_over(img, rob, rx, ry)
        tag = self.tag
        ImageDraw.Draw(pil2 := Image.fromarray(img)).text((fx, fy + self.s(6)), tag, font=self.f_hud, fill=(150, 190, 90), anchor="ma")
        img[:] = np.asarray(pil2)

    def _point(self, seg: Segment, slide, idx, total, n, env):
        W, H, s, fps = self.W, self.H, self.s, self.fps
        P = self.presenter
        pw = W * (0.6 if P else 0.54)
        ph = pw * 9 / 16
        src = self._slide_src(slide, pw, ph)
        f_title = font(s(40 if not P else 34), True)
        tl, _, _ = self.text_layer(seg.headline, f_title, width=int(W * (0.9 if not P else 0.62)))
        f_cap = font(s(21 if not P else 20))
        cap_w = int(W * 0.27) if not P else int(W * 0.6)
        cap, cl, clh = self.text_layer(seg.extra.get("caption") or seg.narration, f_cap, (225, 232, 225), cap_w,
                                       lines=9 if not P else 3, spacing=1.4)
        f_stat = font(s(58 if not P else 40), True)
        f_lab = font(s(15), "mono")
        stat_cache = {}
        lab = None
        if seg.stat:
            lab, _, _ = self.text_layer((seg.stat_label or "KEY FIGURE").upper(), f_lab, (160, 175, 160), int(W * .2))
        T_in, T_out = int(0.4 * fps), int(0.3 * fps)
        for f in range(n):
            t = f / fps
            tt = self.T + t
            cxm, cym = self.cam(tt)
            img = self.background(tt)
            self.particles(img, tt, near=False)
            appear = _ease(t / 0.7)
            if P:
                pcx, pcy, yaw = W * 0.62 + cxm, H * 0.45 + cym, -0.2
            else:
                pcx, pcy, yaw = W * 0.37 + cxm, H * 0.55 + cym, 0.24
            pil = Image.fromarray(img)
            d = ImageDraw.Draw(pil)
            self.rings(d, (pcx, pcy), ph * 0.78, tt, alpha=0.35)
            img = np.asarray(pil).copy()
            quad = self.holo_panel(img, src, pcx, pcy, pw, ph, yaw, tt, appear)
            pil = Image.fromarray(img)
            d = ImageDraw.Draw(pil)
            # projector beam + corner brackets
            base = (pcx, H * 0.93 + cym)
            for q in (quad[2], quad[3]):
                d.line([base, q], fill=(40, 70, 14), width=1)
            d.ellipse([base[0] - s(30), base[1] - s(5), base[0] + s(30), base[1] + s(5)], outline=GREEN)
            L = s(22)
            for (x, y), (sx, sy) in zip(quad, [(1, 1), (-1, 1), (-1, -1), (1, -1)]):
                x, y = x - sx * s(8), y - sy * s(8)
                d.line([(x, y), (x + sx * L, y)], fill=EYE, width=s(3)); d.line([(x, y), (x, y + sy * L)], fill=EYE, width=s(3))
            self.frame_hud(d, "NODE", idx, total, t)
            img = np.asarray(pil).copy()
            # headline: glitch-in
            pt = _ease((t - 0.1) / 0.5)
            if pt > 0:
                tx, ty = (int(W * 0.05 + cxm * 0.4), int(H * 0.11 + cym * 0.4)) if not P else (int(W * 0.33 + cxm), int(H * 0.085 + cym))
                _rgba_over(img, _glitch_layer(tl, 1 - pt, f), tx, ty, min(1.0, pt * 1.3))
            # stat + caption
            if P:
                capx, capy = int(W * 0.33), int(H * 0.8)
                if seg.stat:
                    ps = _ease((t - 0.8) / 0.5)
                    if ps > 0:
                        txt = _count_up(seg.stat, (t - 0.9) / 1.3)
                        if txt not in stat_cache:
                            stat_cache[txt] = self.text_layer(txt, f_stat, EYE, s(260))[0]
                        sx_, sy_ = int(quad[1][0] - s(150)), int(quad[1][1] + s(14))
                        img[sy_ - s(4):sy_ + s(56), sx_ - s(12):sx_ + s(150)] = (img[sy_ - s(4):sy_ + s(56), sx_ - s(12):sx_ + s(150)] * 0.25).astype(np.uint8)
                        _rgba_over(img, stat_cache[txt], sx_, sy_, ps)
                img[capy - s(10):capy + 3 * clh + s(6), capx - s(16):W - s(28)] = (img[capy - s(10):capy + 3 * clh + s(6), capx - s(16):W - s(28)] * 0.35).astype(np.uint8)
                img[capy - s(10):capy + 3 * clh + s(6), capx - s(16):capx - s(12)] = GREEN
            else:
                capx = int(W * 0.69 + cxm * 0.6)
                capy = int(H * 0.2 + cym * 0.6)
                if seg.stat:
                    ps = _ease((t - 0.7) / 0.5)
                    if ps > 0:
                        pil = Image.fromarray(img); d = ImageDraw.Draw(pil)
                        rc = (capx + s(46), capy + s(52))
                        self.rings(d, rc, s(44) * ps, tt * 1.8, alpha=ps, n=2)
                        img = np.asarray(pil).copy()
                        txt = _count_up(seg.stat, (t - 0.8) / 1.3)
                        if txt not in stat_cache:
                            stat_cache[txt] = self.text_layer(txt, f_stat, (255, 255, 255), int(W * .3))[0]
                        _rgba_over(img, stat_cache[txt], capx + s(104), capy + s(14), ps)
                        _rgba_over(img, lab, capx + s(106), capy + s(84), ps)
                    capy += s(130)
            self.typewriter(img, cap, cl, clh, f_cap, capx, capy, (t - 0.9) / max(1.0, seg.seconds * 0.8 - 0.9), tt)
            if P:
                pnt = _ease((t - 0.5) / 0.6) * (1 - _ease((t - 3.2) / 0.8))
                if seg.seconds > 10:
                    mid = seg.seconds * 0.55
                    pnt = max(pnt, _ease((t - mid) / 0.6) * (1 - _ease((t - mid - 2.2) / 0.7)))
                self._robot(img, t, env[f], f, n, point=pnt)
            self.particles(img, tt, near=True)
            img = bloom(img)
            if f < T_in:
                img = glitch(img, 1 - f / T_in, idx * 1000 + f)
            elif f >= n - T_out:
                img = glitch(img, (f - (n - T_out)) / T_out, idx * 1000 + f)
            yield img

    def _card(self, seg: Segment, idx, total, n, env):
        W, H, s, fps = self.W, self.H, self.s, self.fps
        P = self.presenter
        intro = seg.kind == "intro"
        ccx = W * (0.6 if P else 0.5)
        f_big = font(s(56 if not P else 46), True)
        big, bl, blh = self.text_layer(seg.headline if intro else "KEY TAKEAWAYS", f_big, (255, 255, 255),
                                       int(W * (0.8 if not P else 0.62)), lines=2, anchor_center=True)
        f_sub = font(s(19), "mono")
        sub, _, _ = self.text_layer("AI VIDEO BRIEFING  //  AUTO-GENERATED" if intro else "END OF BRIEFING  //  THANK YOU",
                                    f_sub, GREEN, int(W * .9), anchor_center=True)
        f_pt = font(s(23))
        pts = [self.text_layer(p, f_pt, (230, 235, 230), int(W * .5))[0] for p in seg.extra.get("points", [])[:4]]
        for f in range(n):
            t = f / fps
            tt = self.T + t
            cxm, cym = self.cam(tt)
            img = self.background(tt)
            if intro:   # sting: dark -> line flash -> rings -> title
                img = (img * _ease(t / 1.2)).astype(np.uint8)
            self.particles(img, tt, near=False)
            pil = Image.fromarray(img); d = ImageDraw.Draw(pil)
            cy = H * (0.42 if pts else 0.47) + cym
            cx = ccx + cxm
            ra = _ease((t - 0.3) / 0.9) if intro else 1.0
            self.rings(d, (cx, cy), H * 0.36 * (0.6 + 0.4 * ra), tt * (3 - 2 * ra if intro else 1), alpha=0.85 * ra)
            if intro and t < 1.4:
                lw = W * _ease(t / 0.5) * 0.9
                y = H * 0.47 + cym
                d.line([(cx - lw / 2, y), (cx + lw / 2, y)], fill=(230, 255, 200), width=s(3))
            self.frame_hud(d, "INIT" if intro else "END", idx, total, t)
            img = np.asarray(pil).copy()
            if intro and 0.35 < t < 0.6:
                img = np.clip(img.astype(np.int16) + int(160 * (1 - abs(t - 0.45) / 0.15)), 0, 255).astype(np.uint8)
            pb = _ease((t - (1.0 if intro else 0.2)) / 0.6)
            by = int(cy - blh * len(bl) / 2 - (s(60) if pts else 0))
            if pb > 0:
                lay = _glitch_layer(big, (1 - pb) + (0.5 if (intro and 2.6 < t < 2.75) else 0), f)
                _rgba_over(img, lay, int(cx - big.shape[1] / 2), by, min(1.0, pb * 1.5))
                # flare sweep across the title
                fx = int(cx - W * .45 + ((t - 1.6) / 1.2) * W * .9)
                if 0 < fx < W - s(30):
                    sl = img[by:by + big.shape[0], fx:fx + s(26)].astype(np.int16) + 120
                    img[by:by + big.shape[0], fx:fx + s(26)] = np.clip(sl, 0, 255).astype(np.uint8)
            ps = _ease((t - (1.7 if intro else 0.6)) / 0.5)
            _rgba_over(img, sub, int(cx - sub.shape[1] / 2), by + blh * len(bl) + s(12), ps)
            for k, layer in enumerate(pts):
                pk = _ease((t - 1.2 - 0.6 * k) / 0.5)
                if pk > 0:
                    x = int(cx - W * .22 - 40 * (1 - pk) * self.k)
                    y = int(by + blh * len(bl) + s(56) + k * s(46))
                    img[y + s(8):y + s(18), x - s(22):x - s(12)] = GREEN
                    _rgba_over(img, _glitch_layer(layer, 1 - pk, k + f), x, y, pk)
            if P:
                appear = _ease((t - 0.6) / 1.0) if intro else 1.0
                wave = (_ease((t - 1.4) / 0.4) * (1 - _ease((t - 3.6) / 0.5))) if intro else (_ease((t - seg.seconds + 3) / 0.5))
                self._robot(img, t, env[f], f, n, appear=appear, wave=wave)
            self.particles(img, tt, near=True)
            img = bloom(img)
            if not intro and t > seg.seconds - 1.0:      # CRT power-off
                q = _ease((t - (seg.seconds - 1.0)) / 0.8)
                hh = max(2, int(H * (1 - q)))
                sm = Image.fromarray(img).resize((W, hh), Image.BILINEAR)
                out = np.zeros_like(img)
                y0 = (H - hh) // 2
                out[y0:y0 + hh] = (np.asarray(sm) * (1 - 0.5 * q) + 120 * q).clip(0, 255).astype(np.uint8)
                if q > 0.85:
                    w = int(W * (1 - (q - .85) / .15))
                    out[:] = 0; out[H // 2 - 1:H // 2 + 1, (W - w) // 2:(W + w) // 2] = (230, 255, 200)
                img = out
            elif not intro:
                if f < int(0.4 * fps):
                    img = glitch(img, 1 - f / (0.4 * fps), f)
            elif f >= n - int(0.3 * fps):
                img = glitch(img, (f - (n - 0.3 * fps)) / (0.3 * fps), f)
            yield img
