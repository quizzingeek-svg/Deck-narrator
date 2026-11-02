"""Sector detection, themed assets and the HD render path of the Animated Explainer."""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.sectors import ICONS, OUTFITS, SECTORS, SECTOR_NAMES, backdrop_layers, detect_sector, render_icon, resolve  # noqa: E402
from core.video_summary import DEFAULT_QUALITY, MOTIFS, QUALITY, Segment, deck_text  # noqa: E402


def test_detect_sector_keywords():
    assert detect_sector("Defense budget, drone and radar programs for the navy and air force") == "Defense & Security"
    assert detect_sector("Hospital capacity, patient waiting lists and MRI diagnostic imaging") == "Health / LSHC"
    assert detect_sector("Bank net interest margin, deposit costs and credit card lending") == "Financial Services"
    assert detect_sector("Wind turbine and solar renewable power for the grid") == "Energy / ER&I"
    assert detect_sector("Police, courts and the criminal justice system") == "Security & Justice"
    assert detect_sector("Quarterly update on our plans") == "General"
    assert resolve("Auto-detect", "bank lending loan") == "Financial Services"
    assert resolve("TMT", "bank lending loan") == "TMT"
    assert SECTOR_NAMES[0] == "Auto-detect"


def test_sample_decks_detected():
    from core.deck import load_deck
    exp = {"test_defense_deck": "Defense & Security", "test_health_deck": "Health / LSHC", "test_fs_deck": "Financial Services"}
    for name, sec in exp.items():
        assert detect_sector(deck_text(load_deck(str(ROOT / "samples" / f"{name}.pptx")))) == sec


def test_sector_assets_complete():
    for name, cfg in SECTORS.items():
        assert name in OUTFITS
        assert all(k in ICONS or k in ("money", "growth", "building", "people", "target", "globe", "factory", "truck", "hospital") for k in cfg["icons"])
        assert cfg["sfx"] in MOTIFS or cfg["sfx"] == "pop"
    im = render_icon("radar", 120, 0.5)
    assert im.mode == "RGBA" and np.asarray(im)[..., 3].max() > 0
    far, near = backdrop_layers("Financial Services", 640, 360)
    assert far.size == near.size == (960, 360)


def test_quality_presets_hd_default():
    assert DEFAULT_QUALITY == "HD (720p)" and QUALITY[DEFAULT_QUALITY][:2] == (1280, 720)
    assert any(v[:2] == (1920, 1080) for v in QUALITY.values()) and any(v[:2] == (960, 540) for v in QUALITY.values())
    assert all(24 <= v[2] <= 30 or v[1] == 540 for v in QUALITY.values())


def test_hd_frames_cold_open_scene_outro():
    from core.deck import load_deck
    from core.explainer import ExplainerRenderer
    sl = load_deck(str(ROOT / "samples" / "test_defense_deck.pptx"))
    r = ExplainerRenderer(1280, 720, 24, "Defense test", "English", hook={"value": "14%", "label": "Defense spending up 14%"},
                          sector="Defense & Security")
    segs = [Segment("intro", "Defense test", "x"), Segment("point", sl[1].title, "Defense spending up 14% year on year.", slide=1),
            Segment("outro", "Key takeaways", "x", extra={"points": [s.title for s in sl[1:4]]})]
    for sg in segs:
        sg.seconds = 2.0
        frames = list(r.frames(sg, sl, 1, 3))
        assert len(frames) == 48 and frames[-1].shape == (720, 1280, 3)
        assert frames[30].std() > 5            # not blank
    kinds = {k for _, k in r.events}
    assert "ping" in kinds and "slam" in kinds   # sector motif + cold-open hit
