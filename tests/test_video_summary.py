"""Video summary mode: no-key script + MP4 render (python -m pytest -q tests/test_video_summary.py)."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.deck import load_deck, render_slides  # noqa: E402
from core.narrate import longest_run  # noqa: E402
from core.video_summary import builtin_summary, build_summary, ffmpeg_bin, find_stat, make_video_summary, script_text  # noqa: E402

SAMPLE = str(ROOT / "samples" / "sample_deck.pptx")


def test_builtin_script_shape_and_length():
    slides = load_deck(SAMPLE)
    segs = builtin_summary(slides, "sample_deck.pptx")
    assert segs[0].kind == "intro" and segs[-1].kind == "outro"
    assert all(s.slide is not None for s in segs[1:-1]) and len(segs) >= 4
    words = len(script_text(segs).split())
    assert 120 <= words <= 320, words            # roughly 60-120 s of speech
    for s in segs[1:-1]:                          # not a verbatim read of the slide body
        src = slides[s.slide].full_text().replace(slides[s.slide].title, "", 1)
        assert longest_run(s.extra["caption"], src)[0] <= 8


def test_stat_and_no_key_fallback():
    slides = load_deck(SAMPLE)
    assert any(find_stat(s)[0] for s in slides)
    segs, src = build_summary(slides, cfg=None)
    assert src.startswith("built-in")


def test_render_mp4_end_to_end(tmp_path):
    os.environ.pop("LLM_API_KEY", None)
    slides = load_deck(SAMPLE)
    render_slides(SAMPLE, slides)
    out = tmp_path / "s.mp4"
    calls = []
    r = make_video_summary(slides[:3], str(out), k=2, progress=lambda f, m: calls.append(f))
    assert out.exists() and out.stat().st_size > 50_000
    probe = subprocess.run([ffmpeg_bin(), "-i", str(out)], capture_output=True, text=True).stderr
    assert "Video: h264" in probe and "Audio: aac" in probe
    assert calls and calls[-1] == 1.0 and r["seconds"] > 10


def test_fx_envelope_and_robot():
    import numpy as np
    from core.video_fx import draw_robot, envelope
    from core.video_summary import STYLES
    assert len(STYLES) == 4 and STYLES[0] == "Animated Explainer" and STYLES[2].startswith("AI") and "NOVA" not in STYLES[0]
    r = draw_robot(300, 1.0, 0.8, False, 1.0, 0.0)
    assert r.ndim == 3 and r.shape[2] == 4 and r.shape[0] >= 250 and r[..., 3].max() == 255
    a = draw_robot(300, 1.0, 0.0, True, 0.0, 0.0)
    assert np.asarray(a).tobytes() != np.asarray(r).tobytes()   # mouth/eyes/arm change with inputs
    tmp = ROOT / "data" / "test_out" / "env.wav"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([ffmpeg_bin(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=300:d=2",
                    "-af", "volume='if(lt(t,1),0,1)':eval=frame", str(tmp)], check=True)
    e = envelope(str(tmp), 20, 40)
    assert len(e) == 40 and 0 <= e.min() and e.max() <= 1.0 and e[30] > e[5]


def _probe(path):
    out = subprocess.run([ffmpeg_bin(), "-i", path], capture_output=True, text=True).stderr
    return out


def test_render_each_cinematic_style():
    from core.video_summary import STYLES
    slides = load_deck(SAMPLE)
    for st_ in STYLES[1:3]:
        out = ROOT / "data" / "test_out" / f"t_style_{st_[:4]}.mp4"
        r = make_video_summary(slides, str(out), deck_name="sample_deck.pptx", k=2, style=st_)
        info = _probe(str(out))
        assert "h264" in info and "aac" in info and r["style"] == st_
        assert 30 <= r["seconds"] <= 140


def test_stat_only_from_visible_slide_text():
    from core.deck import Slide
    s = Slide(1, "Competitive landscape", ["Leaders hold most of the installed base"],
              tables=[[["Vendor", "Share"], ["A", "31%"], ["B", "18%"]]],
              charts=[{"series": [{"name": "Growth", "values": [26]}], "categories": ["2026"]}], alt_texts=["26% growth"])
    st_, _ = find_stat(s)
    assert st_ in ("31%", "18%") and "26" not in st_
    assert find_stat(s, "Vendor B sits at 18% today.")[0] == "18%"          # tied to the narration wins
    assert find_stat(Slide(2, "Our plan", ["Grow fast", "Hire well"],
                           charts=[{"series": [{"values": [26]}]}]))[0] == ""   # nothing printed -> no callout


def test_photo_presenter_render(tmp_path):
    import shutil
    from core.photo_avatar import PhotoAvatar
    photo = tmp_path / "face.jpg"
    shutil.copy(ROOT / "samples" / "test_face_synthetic.jpg", photo)
    av = PhotoAvatar(str(photo), 340)
    assert av.detected and av.frame(1.0, 0.7, 0.0).shape[2] == 4
    from PIL import Image
    Image.new("RGB", (300, 200), (90, 90, 90)).save(tmp_path / "noface.png")   # no face -> centre-crop fallback
    assert not PhotoAvatar(str(tmp_path / "noface.png"), 200).detected
    out = ROOT / "data" / "test_out" / "t_photo.mp4"
    r = make_video_summary(load_deck(SAMPLE), str(out), deck_name="sample_deck.pptx", k=2, style="AI Presenter (robot)",
                           photo=str(photo), presenter_name="Test Host")
    assert "h264" in _probe(str(out)) and r["seconds"] > 20


def _all_text(sl):
    import json
    return json.dumps([sl.title, sl.bullets, getattr(sl, "tables", None), getattr(sl, "charts", None)], ensure_ascii=False, default=str)


def test_explainer_plans_use_only_deck_values():
    from core.deck import load_deck
    from core.explainer import plan_scene
    sl = load_deck("samples/test_explainer_deck.pptx")
    kinds = [plan_scene(s, "", "Brazil Market Entry Review")["kind"] for s in sl]
    assert kinds[1:] == ["country", "compare", "line", "versus", "cards"]
    for s in sl:
        pl = plan_scene(s, "", "Brazil Market Entry Review")
        src = _all_text(s)
        for st_ in pl.get("stats", []):
            assert st_["value"].rstrip("+") in src
        for ser in pl.get("series", []):
            for t in ser["text"]:
                assert t in src


def test_find_countries_prefers_deck_subject():
    from core.deck import load_deck
    from core.explainer import find_countries, plan_scene
    assert find_countries("Entering India's market") == ["India"]
    s = load_deck("samples/sample_deck.pptx")[1]
    pl = plan_scene(s, "", "Entering India's diagnostic imaging market")
    assert pl["kind"] == "country" and pl["countries"][0] == "India"


def test_walking_robot_shape():
    from core.video_fx import draw_robot
    a = draw_robot(200, 0.0, 0.3, 0.0, 1.0, 0.0, legs=1.0, stride=1.0, aim=1.57)
    b = draw_robot(200, 0.0, 0.3, 0.0, 0.0, 0.0)
    assert a.ndim == 3 and a.shape[2] == 4 and a.shape[1] > b.shape[1] and a[..., 3].max() > 0


def test_explainer_render_short(tmp_path):
    import subprocess
    from core.deck import load_deck
    from core.video_summary import make_video_summary
    out = str(tmp_path / "ex.mp4")
    sl = load_deck("samples/test_explainer_deck.pptx")
    make_video_summary(sl, out, deck_name="t", style="Animated Explainer", k=2)
    pr = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name", "-of", "csv=p=0", out], capture_output=True, text=True).stdout
    assert "h264" in pr and "aac" in pr


def test_stats_paired_with_own_line():
    from core.deck import load_deck
    from core.explainer import kpis
    for path in ("samples/sample_deck.pptx", "samples/test_explainer_deck.pptx"):
        for sl in load_deck(path):
            for st_ in kpis(sl, 3):
                assert st_["value"].lstrip("~").rstrip("+") in st_["label"]
                assert st_["label"] in [sl.title] + list(sl.bullets)


def test_country_primary_first_and_sfx(tmp_path):
    import wave
    from core.deck import load_deck
    from core.explainer import plan_scene
    from core.video_summary import make_sfx
    pl = plan_scene(load_deck("samples/sample_deck.pptx")[1], "", "Entering India's diagnostic imaging market")
    assert pl["countries"][0] == "India"
    p = make_sfx([(0.0, "whoosh"), (0.5, "tick"), (1.0, "pop")], 2.0, str(tmp_path / "s.wav"))
    with wave.open(p) as w:
        assert w.getnframes() > 44100 * 2
