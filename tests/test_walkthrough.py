"""Narrated walkthrough: slides always render (without LibreOffice too), slide-then-narration order,
and spoken-only pronunciation fixes (R&D must not become "Randy").

Browser tests (Playwright + Chromium) start the real Streamlit app; they are skipped if Playwright
or its browser is unavailable. Run: python -m pytest -q tests/test_walkthrough.py
"""
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from PIL import Image, ImageStat

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import deck as deckmod                                   # noqa: E402
from core.deck import load_deck, render_slides                      # noqa: E402
from core.export import player_html                                 # noqa: E402
from core.speech_text import pronounce, speakable                   # noqa: E402

PPTX = ROOT / "samples" / "test_fs_deck.pptx"
PDF = ROOT / "samples" / "test_fs_deck.pdf"
SHOTS = ROOT / "data" / "test_out" / "walkthrough"


# ---------------------------------------------------------------- pronunciation
@pytest.mark.parametrize("src,want", [
    ("Our R&D spend grew", "R and D"),
    ("R & D budget", "R and D"),
    ("M&A pipeline", "M and A"),
    ("the P&L view", "P and L"),
    ("S&J practice", "S and J"),
    ("ER&I sector", "E R and I"),
    ("Q&A next", "Q and A"),
    ("B2B and D2C", "B to B and D to C"),
    ("CEO and CFO on ESG", "C E O and C F O on E S G"),
    ("LSHC and TMT", "L S H C and T M T"),
    ("R&amp;D", "R and D"),
])
def test_pronounce_expands_acronyms(src, want):
    out = pronounce(src)
    assert want in out, out
    assert "&" not in out and "Randy" not in out


def test_pronounce_keeps_words_and_other_languages():
    assert pronounce("it is fine") == "it is fine"           # 'IT' only when upper case
    assert pronounce("Tom & Jerry") == "Tom and Jerry"
    assert pronounce("R&D y M&A", "es") == "R and D y M and A"
    assert "&" in pronounce("Tom & Jerry", "fr")             # plain words: voice reads '&' natively
    assert "R and D" in speakable("Our R&D spend rose 5%", "en")
    assert "R and D" in speakable("हमारा R&D खर्च", "hi")


def test_tts_input_is_normalised_but_screen_text_is_not(monkeypatch, tmp_path):
    from core import tts
    seen = []
    monkeypatch.setattr(tts, "CACHE", tmp_path)
    monkeypatch.setattr(tts, "_edge_paced", lambda clean, *a, **k: (seen.append(clean), _tone(a[-1]))[1])
    script = "Our R&D and M&A teams report to the CEO."
    for prepared in (False, True):
        tts.synthesize(script, "English (US)", prepared=prepared)
    assert all("R and D" in s and "M and A" in s and "&" not in s for s in seen), seen
    assert script == "Our R&D and M&A teams report to the CEO."    # caller's (on-screen) text untouched


def _tone(out, secs=1.2):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration={secs}",
                    "-c:a", "libmp3lame", str(out)], check=True)
    return str(out)


# ---------------------------------------------------------------- slide images
def _nonblank(path):
    im = Image.open(path).convert("L")
    return ImageStat.Stat(im).stddev[0] > 8 and im.width >= 1000


def test_pptx_renders_without_libreoffice(monkeypatch, tmp_path):
    monkeypatch.setenv("DN_NO_LIBREOFFICE", "1")
    monkeypatch.setattr(deckmod, "RENDER_DIR", tmp_path)
    slides = load_deck(str(PPTX))
    info = render_slides(str(PPTX), slides)
    assert info["method"] == "built-in pptx renderer" and not info["error"], info
    assert all(s.image_path and Path(s.image_path).name.startswith("slide-") and _nonblank(s.image_path) for s in slides)


def test_pptx_renderer_handles_every_sample(tmp_path):
    from core.pptx_render import render_pptx
    for f in sorted((ROOT / "samples").glob("*.pptx")):
        paths = render_pptx(str(f), tmp_path / f.stem)
        assert len(paths) == len(load_deck(str(f))) and all(_nonblank(p) for p in paths), f


def test_pdf_renders_with_poppler_and_pymupdf(monkeypatch, tmp_path):
    monkeypatch.setattr(deckmod, "RENDER_DIR", tmp_path / "a")
    slides = load_deck(str(PDF))
    info = render_slides(str(PDF), slides)
    if shutil.which("pdftoppm"):
        assert info["method"] == "pdftoppm"
    assert all(_nonblank(s.image_path) for s in slides)
    # no poppler (pure-pip host): PyMuPDF takes over
    monkeypatch.setattr(deckmod, "RENDER_DIR", tmp_path / "b")
    real = shutil.which
    monkeypatch.setattr(deckmod.shutil, "which", lambda n: None if n == "pdftoppm" else real(n))
    slides = load_deck(str(PDF))
    info = render_slides(str(PDF), slides)
    assert info["method"] == "pymupdf" and all(_nonblank(s.image_path) for s in slides), info


def test_player_shows_slide_before_audio():
    html = player_html([], [], [], lead_ms=800, gap_ms=500)
    assert "const LEAD=800,GAP=500" in html and "slide_shown" in html and "img.onload" in html


# ---------------------------------------------------------------- browser (Playwright)
def _browser():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("playwright not installed")
    return sync_playwright


def _check_player(page_or_frame, n_slides, lead_ms, shot_prefix, page):
    """Wait for slide 1 shown -> audio -> slide 2 shown -> audio; check order, beat, image visible."""
    fr = page_or_frame
    fr.wait_for_function("() => window.__dn && window.__dn.log.some(e => e.type==='slide_shown')", timeout=60000)
    st = fr.evaluate("() => window.__dn.state")
    if st == "blocked":                               # browser autoplay policy: user presses play once
        fr.click("#big")
    fr.wait_for_function("() => window.__dn.log.some(e => e.type==='audio_start' && e.slide===0)", timeout=60000)
    vis = fr.evaluate("() => { const i=document.getElementById('img'); const r=i.getBoundingClientRect();"
                      " return {w:i.naturalWidth, h:r.height, op:getComputedStyle(i).opacity}; }")
    assert vis["w"] > 500 and vis["h"] > 200 and float(vis["op"]) > 0.9, vis
    page.screenshot(path=str(SHOTS / f"{shot_prefix}_slide1.png"))
    if n_slides > 1:
        fr.wait_for_function("() => window.__dn.log.some(e => e.type==='audio_start' && e.slide===1)", timeout=180000)
        page.screenshot(path=str(SHOTS / f"{shot_prefix}_slide2.png"))
    log = fr.evaluate("() => window.__dn.log")
    for k in range(min(2, n_slides)):
        shown = next(e["t"] for e in log if e["type"] == "slide_shown" and e["slide"] == k)
        audio = next(e["t"] for e in log if e["type"] == "audio_start" and e["slide"] == k)
        assert audio - shown >= lead_ms - 60, (k, audio - shown)           # slide visible first, then the beat
    if n_slides > 1:
        end0 = next(e["t"] for e in log if e["type"] == "audio_end" and e["slide"] == 0)
        shown1 = next(e["t"] for e in log if e["type"] == "slide_shown" and e["slide"] == 1)
        assert shown1 > end0                                                  # advances only after narration
    return log


def test_player_html_in_browser(tmp_path):
    sp = _browser()
    SHOTS.mkdir(parents=True, exist_ok=True)
    slides = load_deck(str(PPTX))[:2]
    from core.pptx_render import render_pptx
    for s, im in zip(slides, render_pptx(str(PPTX), tmp_path / "r")):
        s.image_path = im
    aud = [_tone(tmp_path / f"a{i}.mp3", 1.5) for i in range(2)]
    html = player_html(slides, aud, ["one", "two"], lead_ms=700, gap_ms=300)
    f = tmp_path / "p.html"; f.write_text(html)
    with sp() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:
            pytest.skip(f"chromium unavailable: {e}")
        page = b.new_page(viewport={"width": 1200, "height": 900})
        page.goto(f.as_uri())
        _check_player(page, 2, 700, "player", page)
        b.close()


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close(); return port


@pytest.mark.parametrize("deck", [PPTX, PDF], ids=["pptx", "pdf"])
def test_streamlit_walkthrough_in_browser(deck, tmp_path):
    sp = _browser()
    SHOTS.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    env = dict(os.environ, DN_NO_LIBREOFFICE="1", DN_RENDER_DIR=str(tmp_path / "renders"))   # simulate Streamlit Cloud
    env.pop("LLM_API_KEY", None)
    proc = subprocess.Popen([sys.executable, "-m", "streamlit", "run", str(ROOT / "app.py"), "--server.headless", "true",
                             "--server.port", str(port), "--browser.gatherUsageStats", "false"],
                            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        with sp() as p:
            try:
                b = p.chromium.launch()
            except Exception as e:
                pytest.skip(f"chromium unavailable: {e}")
            page = b.new_page(viewport={"width": 1400, "height": 1300})
            for _ in range(60):
                try:
                    page.goto(f"http://127.0.0.1:{port}", timeout=5000); break
                except Exception:
                    time.sleep(1)
            page.wait_for_selector("input[type=file]", state="attached", timeout=90000)
            page.locator("input[type=file]").first.set_input_files(str(deck))
            page.get_by_text("Prepare & play walkthrough").wait_for(timeout=180000)
            # slide 1 preview visible before anything is prepared
            prev = page.locator("[data-testid=stImage] img").first
            prev.wait_for(timeout=60000)
            assert page.evaluate("(e) => e.naturalWidth", prev.element_handle()) > 500
            cap = page.get_by_text("images:", exact=False).first.inner_text()
            assert ("built-in pptx renderer" in cap) if deck.suffix == ".pptx" else ("pdftoppm" in cap or "pymupdf" in cap), cap
            page.screenshot(path=str(SHOTS / f"app_{deck.suffix[1:]}_preview.png"))
            page.get_by_role("slider").first.focus()          # keep defaults; just make sure sliders exist
            page.get_by_text("Prepare & play walkthrough").click()
            fl = page.frame_locator("iframe").first
            fl.locator("#img").wait_for(timeout=300000)
            frame = next(f for f in page.frames if f != page.main_frame and f.evaluate("() => !!window.__dn") )
            page.locator("iframe").first.scroll_into_view_if_needed()
            _check_player(frame, 2, 700, f"app_{deck.suffix[1:]}", page)
            b.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:
            proc.kill()
