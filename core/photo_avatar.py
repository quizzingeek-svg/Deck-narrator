"""Photo presenter for the "AI Presenter" style.

Takes one face photo, finds the face (OpenCV Haar cascade, centre-crop fallback), and builds a stylised
holographic bust: a circular portrait with a green grade and scanlines inside a glowing HUD frame.
Per frame it adds a subtle head bob and breathing, blinks (eyelid fill over Haar-detected eyes), and an
audio-reactive glow ring + radial waveform. The mouth is NOT animated: simple 2D warping of a still photo
looked uncanny in tests, so speech is shown through the reactive glow instead.
The photo is only read from the path given; callers delete it after the render.
"""
from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

GREEN = (134, 188, 37)


def _cv2():
    try:
        import cv2
        return cv2
    except Exception:
        return None


def detect_face(rgb: np.ndarray):
    """Returns ((x, y, w, h) face box or None, list of eye boxes in image coords)."""
    cv2 = _cv2()
    if cv2 is None:
        return None, []
    g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    g = cv2.equalizeHist(g)
    casc = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    m = max(40, min(g.shape) // 8)
    faces = casc.detectMultiScale(g, 1.1, 5, minSize=(m, m))
    if len(faces) == 0:
        return None, []
    x, y, w, h = max(faces, key=lambda b: b[2] * b[3])
    eyes = []
    ec = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye.xml")
    roi = g[y:y + h // 2 + h // 10, x:x + w]
    for ex, ey, ew, eh in ec.detectMultiScale(roi, 1.1, 6, minSize=(w // 10, w // 10)):
        if ey + eh / 2 < h * 0.55:
            eyes.append((x + ex, y + ey, ew, eh))
    eyes = sorted(eyes, key=lambda b: -b[2])[:2]
    return (int(x), int(y), int(w), int(h)), eyes


class PhotoAvatar:
    def __init__(self, photo_path: str, height_px: int):
        src = Image.open(photo_path)
        src = src.convert("RGB")
        src.thumbnail((1400, 1400))
        rgb = np.asarray(src)
        face, eyes = detect_face(rgb)
        self.detected = face is not None
        H0, W0 = rgb.shape[:2]
        if face:
            x, y, w, h = face
            cx, cy, side = x + w / 2, y + h * 0.52, w * 1.9
        else:   # centre crop, biased up (faces sit in the top half of most portraits)
            side = min(W0, H0) * 0.8
            cx, cy = W0 / 2, H0 * 0.42
        side = min(side, W0, H0)
        x0 = int(min(max(0, cx - side / 2), W0 - side)); y0 = int(min(max(0, cy - side / 2), H0 - side))
        D = int(height_px * 0.6)          # portrait disc diameter
        self.D, self.size = D, (int(height_px * 0.86), height_px)
        crop = Image.fromarray(rgb).crop((x0, y0, x0 + int(side), y0 + int(side))).resize((D, D), Image.LANCZOS)
        k = D / side
        self.eyes = [((ex - x0) * k, (ey - y0) * k, ew * k, eh * k) for ex, ey, ew, eh in eyes]
        a = np.asarray(crop).astype(np.float32)
        lum = a.mean(axis=2, keepdims=True)
        grade = 0.55 * a + 0.45 * (lum * np.array([0.78, 1.08, 0.62]))   # keep identity, push towards green
        hi = np.clip((lum - 170) / 85, 0, 1)                            # dim pale studio backdrops
        grade *= 1 - 0.38 * hi
        grade[::3] *= 0.86                                              # scanlines
        self.base = np.clip(grade * 1.04 + 4, 0, 255).astype(np.uint8)
        yy, xx = np.mgrid[0:D, 0:D]
        r = np.hypot(xx - D / 2, yy - D / 2) / (D / 2)
        self.mask = (np.clip((1 - r) * D / 6, 0, 1) * 255).astype(np.uint8)     # soft circular edge
        # eyelid patches: skin colour sampled just above each eye
        self.lids = []
        for ex, ey, ew, eh in self.eyes:
            x1, x2 = int(ex + ew * 0.12), int(ex + ew * 0.88)
            y1, y2 = int(ey + eh * 0.3), int(ey + eh * 0.72)
            above = self.base[max(0, int(ey) - max(2, int(eh * 0.12))):max(1, int(ey)), x1:x2]
            if above.size and x2 > x1 and y2 > y1:
                col = above.reshape(-1, 3).mean(0)
                self.lids.append((x1, y1, x2, y2, col))

    def frame(self, t: float, amp: float, blink: float) -> np.ndarray:
        Wc, Hc = self.size
        D = self.D
        out = Image.new("RGBA", (Wc, Hc), (0, 0, 0, 0))
        d = ImageDraw.Draw(out)
        bob = math.sin(t * 1.6) * D * 0.008
        breathe = 1 + 0.006 * math.sin(t * 2 * math.pi / 3.6)
        cx, cy = Wc / 2, D / 2 * 1.37 + bob
        # pedestal / bust plinth
        py = cy + D / 2 + Hc * 0.03
        for k in range(6, 0, -1):
            c = int(18 * (7 - k) * (0.6 + 0.4 * amp))
            d.ellipse([cx - k * D * .07, py - k * D * .012, cx + k * D * .07, py + k * D * .012], fill=(c // 3, c, c // 6, 255))
        d.polygon([(cx - D * .3, Hc - 2), (cx + D * .3, Hc - 2), (cx + D * .17, py + D * .02), (cx - D * .17, py + D * .02)],
                  fill=(14, 22, 10, 230), outline=GREEN + (255,))
        # audio-reactive glow + radial waveform
        R = D / 2
        glow = Image.new("RGBA", (Wc, Hc), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gr = R * (1.06 + 0.05 * amp)
        gd.ellipse([cx - gr, cy - gr, cx + gr, cy + gr], outline=GREEN + (int(120 + 135 * amp),), width=max(3, int(D * (0.02 + 0.03 * amp))))
        glow = glow.filter(ImageFilter.GaussianBlur(D * 0.025))
        out.alpha_composite(glow)
        d = ImageDraw.Draw(out)
        nb = 72
        for i in range(nb):
            ang = i / nb * 2 * math.pi + t * 0.2
            wv = amp * (0.5 + 0.5 * math.sin(i * 1.7 + t * 9)) * (0.6 + 0.4 * math.sin(i * 0.43 - t * 5))
            r1, r2 = R * 1.12, R * (1.14 + 0.16 * max(0.04, wv))
            d.line([(cx + r1 * math.cos(ang), cy + r1 * math.sin(ang)), (cx + r2 * math.cos(ang), cy + r2 * math.sin(ang))],
                   fill=(190, 240, 110, 230), width=max(1, D // 160))
        # rotating HUD arcs
        rr = R * 1.33
        for k in range(3):
            st = (t * (30 + 18 * k) + k * 120) % 360
            d.arc([cx - rr, cy - rr, cx + rr, cy + rr], st, st + 70, fill=GREEN + (200,), width=max(2, D // 110))
        d.ellipse([cx - R * 1.02, cy - R * 1.02, cx + R * 1.02, cy + R * 1.02], outline=GREEN + (255,), width=max(2, D // 120))
        # portrait
        face = self.base
        if blink > 0 and self.lids:
            face = face.copy()
            for x1, y1, x2, y2, col in self.lids:
                h = y2 - y1
                cut = int(h * blink)
                if cut > 0:
                    w = x2 - x1
                    fx = np.sin(np.linspace(0, np.pi, w))[None, :, None] ** 0.6     # soft lid edges
                    k = blink * .9 * fx
                    face[y1:y1 + cut, x1:x2] = (face[y1:y1 + cut, x1:x2] * (1 - k) + col * k).astype(np.uint8)
        fs = int(D * breathe)
        img = Image.fromarray(np.dstack([face, self.mask]), "RGBA")
        if fs != D:
            img = img.resize((fs, fs), Image.BILINEAR)
        # light sweep across the hologram
        a = np.asarray(img).copy()
        sx = int(((t * 0.35) % 1.6 - 0.3) * fs)
        if 0 < sx < fs - 6:
            a[:, sx:sx + max(4, fs // 30), :3] = np.clip(a[:, sx:sx + max(4, fs // 30), :3].astype(np.int16) + 45, 0, 255)
        out.alpha_composite(Image.fromarray(a, "RGBA"), (int(cx - fs / 2), int(cy - fs / 2)))
        return np.asarray(out)
