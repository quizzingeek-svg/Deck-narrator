"""Streamlit AppTest smoke tests. Needs the mock LLM running on :8765 for the AI parts
(python scripts/mock_llm.py 8765). Run: python -m pytest -q tests/test_ui.py"""
import os
import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
APP = str(ROOT / "app.py")


def _btn(at, label):
    return next(b for b in at.button if b.label == label)


def _loaded(at):
    at.run(timeout=120)
    _btn(at, "Load sample deck").click().run(timeout=180)
    assert not at.exception, at.exception
    return at


def test_no_key_presenter_paced():
    os.environ.pop("LLM_API_KEY", None)
    at = _loaded(AppTest.from_file(APP, default_timeout=180))
    assert any("6 slides" in c.value for c in at.caption)
    at.radio(key="top_mode").set_value("🎤 Live co-presenter").run(timeout=180)
    at.radio(key="mode").set_value("Presenter-paced (I narrate, then wait for 'next')").run(timeout=180)   # radio[0] = voice gender
    _btn(at, "▶ Start / resume").click().run(timeout=180)
    assert at.session_state.paced.state == "WAITING" and at.session_state.cur == 0
    assert at.session_state.now_playing["slide"] == 0
    _btn(at, "Next ▶").click().run(timeout=180)
    assert at.session_state.cur == 1 and at.session_state.paced.state == "WAITING"
    _btn(at, "◀ Prev").click().run(timeout=180)
    assert at.session_state.cur == 0
    assert not at.exception
    # talk-track tab: AI option disabled without key, warning text present
    assert at.radio(key="src").value.startswith("Smart narration")


def test_with_mock_llm_track_and_qa():
    os.environ.update(LLM_API_KEY="test", LLM_BASE_URL="http://127.0.0.1:8765/v1", LLM_MODEL="mock")
    try:
        at = _loaded(AppTest.from_file(APP, default_timeout=240))
        _btn(at, "✨ Build talk track for all slides").click().run(timeout=240)
        assert not at.exception, at.exception
        meta = at.session_state.meta
        assert all(m["source"].startswith("AI explanation") for m in meta)
        assert all(m["overlap"]["copy_ratio"] <= 0.15 for m in meta)
        at.text_input(key="qa_text").set_value("How big will the market be by 2030?")
        _btn(at, "Ask").click().run(timeout=240)
        log = at.session_state.qa_log
        assert log and 3 in log[0]["slides"] and log[0]["jump"] == 3 and at.session_state.cur == 2
        assert log[0]["audio"]
    finally:
        for k in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"):
            os.environ.pop(k, None)


def test_video_summary_mode_no_key():
    os.environ.pop("LLM_API_KEY", None)
    at = _loaded(AppTest.from_file(APP, default_timeout=600))
    at.radio(key="top_mode").set_value("🎞️ Video summary").run(timeout=300)
    at.slider(key="vs_k").set_value(3).run(timeout=300)
    _btn(at, "🎞️ Generate video summary").click().run(timeout=600)
    assert not at.exception, at.exception
    r = at.session_state.vsum
    assert os.path.exists(r["path"]) and r["source"].startswith("built-in")
    assert any(b.label.startswith("⬇️ Download video summary") for b in at.get("download_button"))


def test_video_summary_presenter_style():
    os.environ.pop("LLM_API_KEY", None)
    at = _loaded(AppTest.from_file(APP, default_timeout=600))
    at.radio(key="top_mode").set_value("🎞️ Video summary").run(timeout=300)
    at.selectbox(key="vs_style").set_value("AI Presenter (robot)").run(timeout=300)
    at.radio(key="vs_pres").set_value("🧑 Use my photo").run(timeout=300)
    assert not at.exception and any("session only" in c.value for c in at.caption)
    at.text_input(key="vs_name").set_value("Test Host").run(timeout=300)
    at.slider(key="vs_k").set_value(3).run(timeout=300)
    _btn(at, "🎞️ Generate video summary").click().run(timeout=600)
    assert not at.exception, at.exception
    assert at.session_state.vsum["style"] == "AI Presenter (robot)"
