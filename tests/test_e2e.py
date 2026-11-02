"""End-to-end check of the core pipeline (no UI). Run: python tests/test_e2e.py  (mock LLM on :8765 for AI parts)."""
import io
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.deck import load_deck, render_slides
from core.explain import basic_script
from core.export import narrated_video, player_html, pptx_with_notes, talk_track_docx, talk_track_txt
from core.llm import LLMConfig, answer_question, generate_script, translate
from core.overlap import overlap
from core.session import PacedSession
from core.stt import parse_command, transcribe
from core.tts import synthesize

SAMPLE = str(ROOT / "samples" / "sample_deck.pptx")
MOCK = LLMConfig("test", "http://127.0.0.1:8765/v1", "mock")
R = {}


def body(s):
    return s.full_text().replace(s.title, "", 1)


def test_all():
    slides = load_deck(SAMPLE)
    info = render_slides(SAMPLE, slides)
    R["parse"] = [{"n": s.number, "title": s.title, "bullets": len(s.bullets), "tables": len(s.tables), "charts": len(s.charts),
                   "notes": bool(s.notes)} for s in slides]
    R["render"] = {**info, "images": [Path(s.image_path).name for s in slides]}
    assert len(slides) == 6 and all(Path(s.image_path).exists() for s in slides)

    # overlap: raw bullets read out vs notes vs no-key template vs (mock) AI with regeneration
    ov = []
    for i, s in enumerate(slides):
        raw = ". ".join(s.bullets)
        tmpl = basic_script(slides, i, use_notes=False)
        g = generate_script(MOCK, slides, i)
        ov.append({"slide": s.number, "reading_bullets": overlap(raw, body(s))["copy_ratio"] if s.bullets else None,
                   "notes_as_is": overlap(s.notes, body(s))["copy_ratio"] if s.notes else None,
                   "template_no_key": overlap(tmpl, body(s))["copy_ratio"],
                   "ai_mock_final": g["overlap"]["copy_ratio"], "ai_longest_run": g["overlap"]["longest_run"], "ai_attempts": g["attempts"]})
    R["overlap"] = ov
    assert all(o["ai_mock_final"] <= 0.15 for o in ov)

    # TTS in many languages
    texts = {"English (US)": basic_script(slides, 3), "English (India)": slides[0].notes,
             "Hindi": "भारत में डायग्नोस्टिक इमेजिंग की मांग, मशीनों की संख्या से कहीं ज़्यादा तेज़ी से बढ़ रही है। यही हमारा मौका है।",
             "Spanish (Spain)": "La demanda de diagnóstico por imagen en la India crece mucho más rápido que la capacidad. Ahí está nuestra oportunidad.",
             "Arabic": "الطلب على التصوير التشخيصي في الهند ينمو أسرع بكثير من عدد الأجهزة. وهنا تكمن فرصتنا.",
             "Japanese": "インドの画像診断の需要は、装置の数よりもずっと速いペースで伸びています。そこに私たちのチャンスがあります。",
             "French": "La demande dépasse largement la capacité installée. C'est là que se trouve notre opportunité.",
             "Chinese (Mandarin, Simplified)": "印度影像诊断的需求增长远快于设备数量。这正是我们的机会。",
             "Tamil": "தேவை மிக வேகமாக வளர்கிறது. இதுவே நமக்கான வாய்ப்பு."}
    R["tts"] = []
    for lang, txt in texts.items():
        r = synthesize(txt, lang)
        R["tts"].append({"lang": lang, "voice": r["voice"], "engine": r["engine"], "seconds": r["seconds"], "gen_ms": r["ms"],
                         "warning": r["warning"]})
        assert r["seconds"] > 1 and r["engine"].startswith("Edge")

    # STT + command detection on generated audio
    R["stt"] = []
    for lang, said in [("English (US)", "Next slide, please."), ("Hindi", "अगली स्लाइड"), ("Spanish (Spain)", "Siguiente, por favor."),
                       ("Arabic", "الشريحة التالية"), ("Japanese", "次のスライドへ"), ("English (US)", "Go back to slide two."),
                       ("English (US)", "What is the break-even timeline for this plan?")]:
        a = synthesize(said, lang)
        t = transcribe(a["path"], lang, size="base", short_command=True)
        R["stt"].append({"lang": lang, "said": said, "heard": t["text"], "ms": t["ms"], "command": parse_command(t["text"], lang)})
    assert [x["command"][0] for x in R["stt"]] == ["next", "next", "next", "next", "next", "goto", None]

    # presenter-paced flow driven by voice commands
    ps = PacedSession(total=len(slides))
    ps.start(0); ps.narration_finished()
    for heard in ["Next slide please.", "Agli Slide", "repeat", "go to slide 5", "previous", "next", "next", "next"]:
        cmd, arg = parse_command(heard, "Hindi" if heard == "Agli Slide" else "English (US)")
        if ps.command(cmd, arg):
            ps.narration_finished()
    R["paced_log"] = ps.log
    assert ps.state == "DONE" and ps.index == 5

    # cue audio appended (Hindi)
    cue = synthesize(texts["Hindi"] + "\n\nकृपया अगली स्लाइड पर जाइए।", "Hindi")
    R["cue_hi_seconds"] = cue["seconds"]

    # co-presenter Q&A (mock LLM) and no-key fallback
    R["qa"] = []
    for q, cur in [("How big will the market be by 2030?", 0), ("Who leads the market today?", 1),
                   ("How much money are you asking for?", 2), ("What happens in phase 2?", 0)]:
        t0 = time.time()
        a = answer_question(MOCK, slides, q, cur)
        nk = answer_question(None, slides, q, cur)
        tt = synthesize(a["answer"], "English (US)")
        R["qa"].append({"q": q, "current": cur + 1, "context": a["context_slides"], "cited": a["slides"], "jump": a["jump_to"],
                        "nokey_slide": nk["slides"], "llm_ms": a["ms"], "tts_ms": tt["ms"], "total_ms": int((time.time() - t0) * 1000)})

    # translation
    R["translate_mock"] = translate("The market doubles by 2030.", "Hindi", "hi", MOCK, "hi-IN")
    try:
        R["translate_free"] = translate("The market doubles by 2030.", "Hindi", "hi", None, "hi-IN")
    except Exception as e:
        R["translate_free"] = f"unavailable: {e}"

    # exports
    scripts = [generate_script(MOCK, slides, i)["script"] for i in range(len(slides))]
    out = ROOT / "data" / "test_out"; out.mkdir(exist_ok=True)
    (out / "talk_track.txt").write_text(talk_track_txt(slides, scripts))
    (out / "talk_track.docx").write_bytes(talk_track_docx(slides, scripts))
    (out / "deck_with_notes.pptx").write_bytes(pptx_with_notes(SAMPLE, scripts))
    back = load_deck(str(out / "deck_with_notes.pptx"))
    assert back[3].notes == scripts[3].strip()
    auds = [synthesize(basic_script(slides, i), "English (US)")["path"] for i in range(len(slides))]
    (out / "player.html").write_text(player_html(slides, auds, scripts))
    narrated_video(slides, auds, str(out / "narrated.mp4"))
    from core.tts import duration_s
    R["exports"] = {"files": sorted(p.name for p in out.iterdir()), "video_seconds": duration_s(str(out / "narrated.mp4"))}

    # PDF deck
    pdf = next((ROOT / "data" / "renders").glob("*/deck.pdf"))
    ps_ = load_deck(str(pdf))
    R["pdf"] = [(s.number, s.title) for s in ps_]
    assert len(ps_) == 6


if __name__ == "__main__":
    test_all()
    print(json.dumps(R, ensure_ascii=False, indent=1))
