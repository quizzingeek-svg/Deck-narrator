"""Deck Narrator Bot: narrate, explain and co-present PowerPoint / PDF decks in 60+ languages."""
from __future__ import annotations

import hashlib
import os
import tempfile
import time
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from core.deck import load_deck, render_slides
from core.explain import basic_script
from core.export import narrated_video, player_html, pptx_with_notes, talk_track_docx, talk_track_txt
from core.languages import LANGUAGES, default_voice, language_names, voices_for
from core.llm import LENGTHS, PRESETS, TONES, LLMConfig, ai_status, answer_question, reset_breaker, generate_script, test_connection, translate
from core.overlap import overlap
from core.session import PacedSession
from core.stt import parse_command, transcribe
from core.tts import ENGINES, edge_voice_list, synthesize
from core.video_summary import QUALITY, STYLES, make_video_summary

ROOT = Path(__file__).resolve().parent
UPLOADS = ROOT / "data" / "uploads"
UPLOADS.mkdir(parents=True, exist_ok=True)
SAMPLE = ROOT / "samples" / "sample_deck.pptx"
RTL = {"ar", "he", "fa", "ur"}

st.set_page_config(page_title="Deck Narrator Bot", page_icon="🎙️", layout="wide")
st.markdown("""<style>
:root{--dg:#86BC25}
.block-container{padding-top:1.2rem}
h1,h2,h3{color:#fff}
h1 span, h2 span{border-bottom:3px solid var(--dg)}
.script-box{background:#111;border:1px solid #2a2a2a;border-left:4px solid var(--dg);border-radius:10px;padding:14px 16px;font-size:1.02rem;line-height:1.55;max-height:420px;overflow:auto;white-space:pre-wrap;color:#fff}
.tag{display:inline-block;background:#1c2a0a;color:var(--dg);border:1px solid var(--dg);border-radius:6px;padding:1px 8px;font-size:.8rem;margin-right:6px}
.waiting{background:#0d1a00;border:1px solid var(--dg);border-radius:10px;padding:10px 14px;color:#fff}
.stButton>button[kind="primary"],.stDownloadButton>button[kind="primary"],button[data-testid="stBaseButton-primary"]{background:var(--dg)!important;color:#000!important;border:none!important;font-weight:700}
.stButton>button[kind="primary"]:hover,button[data-testid="stBaseButton-primary"]:hover{background:#9fd63a!important;color:#000!important}
button[data-testid="stBaseButton-secondary"]:hover{border-color:var(--dg)!important;color:var(--dg)!important}
.stTabs [data-baseweb="tab"][aria-selected="true"]{color:var(--dg)!important}
.stTabs [data-baseweb="tab-highlight"]{background:var(--dg)!important}
div[role="radiogroup"] label:has(input:checked){color:var(--dg)!important;font-weight:700}
section[data-testid="stSidebar"]{border-right:2px solid var(--dg)}
</style>""", unsafe_allow_html=True)

ss = st.session_state
for k, v in {"slides": None, "cur": 0, "scripts": [], "meta": [], "script_lang": [], "ta_ver": 0, "now_playing": None,
             "played_nonce": None, "paced": None, "qa_log": [], "seen_audio": set(), "tr_cache": {}, "deck_path": None,
             "deck_name": "", "render_info": {}, "msgs": []}.items():
    ss.setdefault(k, v)


# ------------------------------------------------------------------ sidebar
@st.cache_data(show_spinner=False, ttl=24 * 3600)
def _voices():
    return edge_voice_list()


with st.sidebar:
    st.header("🎙️ Deck Narrator")
    with st.expander("🧠 AI model (for explaining, Q&A, translation)", expanded=False):
        env = os.environ.get
        presets = list(PRESETS)
        # keys can come from env / .env (Docker): LLM_API_KEY (+LLM_PROVIDER/LLM_BASE_URL/LLM_MODEL) or a provider key
        env_provider, env_key = env("LLM_PROVIDER", ""), env("LLM_API_KEY", "")
        if not env_key:
            for name, var in (("Google Gemini (free tier)", "GEMINI_API_KEY"), ("Groq (free tier)", "GROQ_API_KEY"),
                              ("OpenAI", "OPENAI_API_KEY")):
                if env(var):
                    env_provider, env_key = env_provider or name, env(var)
                    break
        if env_provider not in presets:
            env_provider = "Custom OpenAI-compatible" if env("LLM_BASE_URL") else presets[0]
        preset = st.selectbox("Provider preset", presets, index=presets.index(env_provider))
        p = PRESETS[preset]
        from_env = preset == env_provider
        api_key = st.text_input("API key", type="password", value=env_key if from_env else "", help=p["key_hint"],
                                key=f"key_{preset}")
        base_url = st.text_input("Base URL", value=(env("LLM_BASE_URL") if from_env else "") or p["base_url"], key=f"bu_{preset}")
        model = st.text_input("Model", value=(env("LLM_MODEL") if from_env else "") or p["model"], key=f"mo_{preset}")
        st.caption(p["key_hint"])
        cfg = LLMConfig(api_key.strip(), base_url.strip(), model.strip())
        if st.button("Test connection", disabled=not cfg.ready):
            try:
                reset_breaker()
                st.success(test_connection(cfg))
            except Exception as e:
                st.error(f"Failed: {e}")
    _ai = ai_status(cfg) if cfg.ready else None
    if _ai:
        st.caption("ℹ️ Using built-in narrator")
    else:
        st.markdown("**AI:** " + ("✅ connected settings" if cfg.ready else "⚪ no key needed: free smart narration, translation, both modes work"))

    st.subheader("🗣️ Language & voice")
    langs = language_names()
    lang = st.selectbox("Narration language", langs, index=langs.index("English (US)"))
    L = LANGUAGES[lang]
    deck_lang = st.selectbox("Deck is written in", langs, index=langs.index("English (US)"),
                             help="Used to decide when the script must be translated.")
    notes_exact = st.toggle("📝 Read my speaker notes exactly", value=False, key="notes_exact",
                            help="Off (default): notes are paraphrased and used as guidance for a natural narration. "
                                 "On: slides with speaker notes are read word for word.")
    gender = st.radio("Voice", ["Female", "Male"], horizontal=True)
    vlist = voices_for(lang, _voices())
    dv = default_voice(lang, gender)
    voice = st.selectbox("Voice (curated natural default first)", vlist or [""], index=(vlist.index(dv) if dv in vlist else 0),
                         key=f"voice_{lang}_{gender}")
    if not L["female"] and not L["male"]:
        st.warning(f"No free neural voice for {lang}: gTTS fallback (robotic) unless you use a premium engine.")
    rate = st.slider("Speaking rate", -30, 30, 0, 5, format="%d%%")
    pitch = st.slider("Pitch (Hz)", -20, 20, 0, 2)
    c1, c2 = st.columns(2)
    sp_ms = c1.number_input("Pause: sentences (ms)", 0, 1500, 300, 50)
    pp_ms = c2.number_input("Pause: paragraphs (ms)", 0, 3000, 750, 50)
    with st.expander("🔊 Voice engine", expanded=False):
        env = os.environ.get
        engine = st.selectbox("Engine", ENGINES, index=0, help="Edge neural voices are free and natural; gTTS is only an automatic last-resort fallback.")
        keys = {}
        if engine.startswith("OpenAI"):
            keys["openai_tts_key"] = st.text_input("OpenAI key", type="password", value=env("OPENAI_API_KEY", ""))
            keys["openai_voice"] = st.selectbox("OpenAI voice", ["alloy", "nova", "shimmer", "echo", "onyx", "fable", "ash", "coral", "sage"])
            keys["openai_tts_model"] = st.text_input("TTS model", "gpt-4o-mini-tts")
        elif engine.startswith("ElevenLabs"):
            keys["eleven_key"] = st.text_input("ElevenLabs key", type="password", value=env("ELEVENLABS_API_KEY", ""))
            keys["eleven_voice_id"] = st.text_input("Voice ID", env("ELEVENLABS_VOICE_ID") or "21m00Tcm4TlvDq8ikWAM")
        elif engine.startswith("Azure"):
            keys["azure_key"] = st.text_input("Azure Speech key", type="password", value=env("AZURE_SPEECH_KEY", ""))
            keys["azure_region"] = st.text_input("Region", env("AZURE_SPEECH_REGION") or "eastus")
            st.caption("Azure uses the voice selected above with real SSML pauses.")
    with st.expander("🎤 Speech recognition", expanded=False):
        _sizes = ["base", "small", "tiny"]
        _def = os.environ.get("WHISPER_MODEL", "base")
        stt_size = st.selectbox("Local Whisper model (free)", _sizes, index=_sizes.index(_def) if _def in _sizes else 0,
                                help="base ≈ 0.4–1 s per short command on CPU; small is more accurate for Indic languages, slower.")
        stt_key = st.text_input("Optional API STT key (OpenAI-compatible /audio/transcriptions)", type="password",
                                value=os.environ.get("STT_API_KEY", ""))
        stt_base = st.text_input("STT base URL", "https://api.openai.com/v1")
        stt_model = st.text_input("STT model", "whisper-1")
        stt_api = {"key": stt_key, "base_url": stt_base, "model": stt_model} if stt_key else None

ISO, DECK_ISO = L["iso"], LANGUAGES[deck_lang]["iso"]


# ------------------------------------------------------------------ helpers
def load(path: str, name: str):
    with st.spinner("Reading slides and rendering images (LibreOffice)…"):
        slides = load_deck(path)
        info = render_slides(path, slides)
    ss.slides, ss.deck_path, ss.deck_name, ss.render_info = slides, path, name, info
    ss.scripts = [basic_script(slides, i, use_notes=True, notes_exact=notes_exact) for i in range(len(slides))]
    ss.meta = [{"source": "speaker notes" if (s.notes.strip() and notes_exact) else "smart narration (no AI)"} for s in slides]
    ss.script_lang = [deck_lang] * len(slides)
    ss.cur, ss.ta_ver, ss.paced, ss.qa_log, ss.now_playing, ss.tr_cache = 0, ss.ta_ver + 1, None, [], None, {}


def spoken_script(i: int) -> tuple[str, str]:
    """Script for slide i in the narration language. Returns (text, note)."""
    base = ss.scripts[i]
    src_iso = LANGUAGES[ss.script_lang[i]]["iso"]
    if src_iso == ISO:
        return base, ""
    k = (lang, hashlib.sha1(base.encode()).hexdigest())
    if k in ss.tr_cache:
        return ss.tr_cache[k]
    try:
        r = translate(base, lang, ISO, cfg if cfg.ready else None, L["locale"])
        ss.tr_cache[k] = (r["text"], f"translated via {r['engine']}")
    except Exception as e:
        ss.tr_cache[k] = (base, f"⚠️ {e} Narrating the original text.")
    return ss.tr_cache[k]


def audio_for(i: int, with_cue: bool = False) -> dict:
    text, note = spoken_script(i)
    v = voice
    if note.startswith("⚠️"):
        v = default_voice(ss.script_lang[i], gender)
    if with_cue and i < len(ss.slides) - 1:
        text = text.rstrip() + "\n\n" + L["cue"]
    r = synthesize(text, lang if not note.startswith("⚠️") else ss.script_lang[i], v, rate, pitch, sp_ms, pp_ms, engine, keys)
    r["note"] = note
    return r


def play(i: int, with_cue: bool = False):
    t = time.time()
    with st.spinner(f"Preparing voice for slide {i + 1}…"):
        r = audio_for(i, with_cue)
    r["prep_ms"] = int((time.time() - t) * 1000)
    ss.now_playing = {"slide": i, "nonce": time.time(), **r}


def goto(i: int, narrate: bool = False, cue: bool = False):
    ss.cur = max(0, min(i, len(ss.slides) - 1))
    if narrate:
        play(ss.cur, cue)


def render_player():
    np_ = ss.now_playing
    if not np_:
        return
    auto = np_["nonce"] != ss.played_nonce
    st.audio(np_["path"], format="audio/mp3", autoplay=auto)
    ss.played_nonce = np_["nonce"]
    bits = [f"slide {np_['slide'] + 1}", f"{np_['seconds']:.0f}s audio", np_["voice"], np_["engine"],
            "cached" if np_.get("cached") else f"generated in {np_.get('prep_ms', 0) / 1000:.1f}s"]
    st.caption(" · ".join(str(b) for b in bits if b))
    if np_.get("warning"):
        st.warning(np_["warning"])
    if np_.get("note"):
        st.caption(np_["note"])


def html_frame(html: str, height: int):
    if hasattr(st, "iframe"):
        st.iframe(html, height=max(1, height))
    else:
        components.html(html, height=height)


def keyboard_shortcuts():
    html_frame("""<script>
const doc = window.parent.document;
if (!doc.__narratorKeys) { doc.__narratorKeys = true;
 doc.addEventListener('keydown', e => {
  const t = e.target, tag = (t.tagName||'').toLowerCase();
  if (['input','textarea','select'].includes(tag) || t.isContentEditable) return;
  let label = null;
  if (['ArrowRight','PageDown','n','N'].includes(e.key)) label = 'Next ▶';
  else if (['ArrowLeft','PageUp','p','P'].includes(e.key)) label = '◀ Prev';
  else if (['r','R'].includes(e.key)) label = '🔁 Repeat';
  if (!label) return;
  const btn = [...doc.querySelectorAll('button')].find(b => b.innerText.trim() === label && b.offsetParent !== null);
  if (btn) { e.preventDefault(); btn.click(); }
 });
}</script>""", height=1)


def handle_voice(audio_file, key: str, short: bool = True):
    """Transcribe a new st.audio_input clip once. Returns transcription dict or None."""
    if audio_file is None:
        return None
    data = audio_file.getvalue()
    h = hashlib.sha1(data).hexdigest()
    if (key, h) in ss.seen_audio:
        return None
    ss.seen_audio.add((key, h))
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(data); path = f.name
    with st.spinner("Listening…"):
        return transcribe(path, lang, size=stt_size, api=stt_api, short_command=short)


def slide_image(i: int, width="stretch"):
    s = ss.slides[i]
    if s.image_path and os.path.exists(s.image_path):
        st.image(s.image_path, width=width)
    else:
        st.info(s.title)


def render_video_summary():
    st.write("Generates a short futuristic **MP4 recap** of the deck: key points, headline numbers, slide visuals with "
             "pan & zoom, HUD titles, and a voiceover in your narration language. No AI key needed.")
    style = st.selectbox("Visual style", STYLES, index=0, key="vs_style",
                         help="Holographic: cinematic 3D HUD with a tilted holo-panel. AI Presenter: NOVA, a robot host, "
                              "narrates beside a big holo-screen showing your slides. Classic: the simpler HUD look.")
    photo_up, pname = None, ""
    if style.startswith("AI"):
        pc = st.columns([1, 1.3, 1.2])
        who = pc[0].radio("Presenter", ["🤖 NOVA (robot)", "🧑 Use my photo"], key="vs_pres")
        if who.startswith("🧑"):
            photo_up = pc[1].file_uploader("Face photo (JPG/PNG)", type=["jpg", "jpeg", "png"], key="vs_photo",
                                           help="A clear, front-facing photo works best. The face is found and cropped automatically.")
            pc[1].caption("🔒 Your photo stays in this session only. It is used for this render and deleted right after; "
                          "it is never stored on the server or sent anywhere. Only upload a photo you have the right to use.")
        pname = pc[2].text_input("Presenter name (optional)", key="vs_name", max_chars=28,
                                 placeholder="NOVA" if not photo_up else "e.g. Mohit")
    c = st.columns([1.2, 1, 1.4])
    quality = c[0].selectbox("Quality", list(QUALITY), index=0, key="vs_quality",
                             help="Fast (540p) renders about 2x quicker, which is best on Streamlit Cloud. HD (720p) looks sharper.")
    k = c[1].slider("Key points", 3, 8, min(6, max(3, N - 1)), key="vs_k")
    c[2].caption(f"🌐 Voice: **{lang}** · {voice or 'auto'}<br>✍️ Script: "
                 + ("AI (falls back to the built-in narrator automatically)" if cfg.ready and ai_status(cfg) is None
                    else "built-in narrator (no AI)"), unsafe_allow_html=True)
    if st.button("🎞️ Generate video summary", type="primary", key="vs_go"):
        bar = st.progress(0.0, "Starting…")
        out = ROOT / "data" / "video_summary" / f"{hashlib.sha1((ss.deck_path + lang + str(time.time())).encode()).hexdigest()[:12]}.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        for old in sorted(out.parent.glob("*.mp4"))[:-4]:
            old.unlink(missing_ok=True)   # keep the folder small on Cloud
        tr = None
        if ISO != DECK_ISO:
            tr = lambda t: translate(t, lang, ISO, cfg if cfg.ready else None, L["locale"])["text"]
        photo_path = None
        if photo_up is not None:
            import tempfile
            fd, photo_path = tempfile.mkstemp(suffix=Path(photo_up.name).suffix.lower() or ".jpg")
            with os.fdopen(fd, "wb") as fh:
                fh.write(photo_up.getvalue())
        try:
            r = make_video_summary(slides, str(out), deck_name=ss.deck_name, cfg=cfg if cfg.ready else None, lang=lang,
                                   voice=voice or None, rate=rate, pitch=pitch, engine=engine, keys=keys, quality=quality, k=k, style=style,
                                   photo=photo_path, presenter_name=pname,
                                   translate_fn=tr, progress=lambda f, m: bar.progress(min(1.0, f), m))
            ss.vsum = r
        except Exception as e:
            st.error(f"Could not render the video: {e}")
        finally:
            if photo_path:
                Path(photo_path).unlink(missing_ok=True)   # privacy: the photo never outlives the render
    r = ss.get("vsum")
    if r and os.path.exists(r["path"]):
        st.video(r["path"])
        st.caption(f"⏱️ {r['seconds']:.0f}s video · {r['size']} · rendered in {r['total_s']:.0f}s · script: {r['source']}")
        for n_ in r.get("notes", []):
            st.caption(n_)
        st.download_button("⬇️ Download video summary (MP4)", Path(r["path"]).read_bytes(), file_name=f"{Path(ss.deck_name).stem}_summary.mp4",
                           mime="video/mp4", type="primary", key="vs_dl")
        with st.expander("📝 Voiceover script"):
            st.markdown(f"<div class='script-box'>{r['script'].replace('<', '&lt;')}</div>", unsafe_allow_html=True)


# ------------------------------------------------------------------ main
st.title("🎙️ Deck Narrator & Co-Presenter")
up_c1, up_c2 = st.columns([4, 1])
up = up_c1.file_uploader("Upload a deck (.pptx or .pdf)", type=["pptx", "pdf"], label_visibility="collapsed")
if up is not None:
    data = up.getvalue()
    h = hashlib.sha1(data).hexdigest()[:16]
    path = UPLOADS / f"{h}{Path(up.name).suffix.lower()}"
    if not path.exists():
        path.write_bytes(data)
    if ss.deck_path != str(path):
        try:
            load(str(path), up.name)
        except Exception as e:
            st.error(f"Could not read this deck: {e}")
if up_c2.button("Load sample deck", width="stretch") or (st.query_params.get("sample") == "1" and not ss.slides):
    load(str(SAMPLE), SAMPLE.name)

if not ss.slides:
    st.info("Upload a PowerPoint (.pptx) or PDF deck, or click **Load sample deck**. "
            "Narration uses free natural neural voices; explaining slides in your own words, live Q&A and translation need an AI key "
            "(Google Gemini has a free tier).")
    st.stop()

slides = ss.slides
N = len(slides)
ri = ss.render_info
st.caption(f"**{ss.deck_name}**: {N} slides · images: {ri.get('method')}" + (f" · ⚠️ {ri['error']}" if ri.get("error") else "")
           + f" · narration: {lang} · voice {voice}")

tab_present, tab_track, tab_live, tab_deck = st.tabs(["▶️ Present", "✍️ Talk track", "💬 Live Q&A", "📄 Deck data"])

# ================================================================== PRESENT
with tab_present:
    top = st.radio("Choose a mode", ["🎬 Narrated walkthrough", "🎤 Live co-presenter", "🎞️ Video summary"], horizontal=True,
                   key="top_mode",
                   help="Narrated walkthrough: slides appear one by one with narration auto-played. "
                        "Live co-presenter: you present; I narrate or prompt per slide when you ask. "
                        "Video summary: a 1-2 minute futuristic MP4 recap of the key points, voiced in your language.")
    st.caption(f"🌐 Narration language: **{lang}** (change it in the sidebar; scripts are translated and spoken with a {lang} voice).")
    if top.startswith("🎬"):
        mode = "Auto walkthrough"
    elif top.startswith("🎞️"):
        mode = "Video summary"
    else:
        sub = st.radio("Pacing", ["On demand (I narrate when you click)", "Presenter-paced (I narrate, then wait for 'next')"],
                       horizontal=True, key="mode",
                       help="Presenter-paced: narrates a slide, asks you to move on, and waits for Next / → key / saying 'next'. "
                            "For questions from the audience use the 💬 Live Q&A tab.")
        mode = "Presenter-paced" if sub.startswith("Presenter") else "Narrate (manual)"
    external = False if mode == "Video summary" else st.toggle("I'm driving PowerPoint / Teams separately (hide slides here)", value=False)
    if ss.scripts and all(m.get("source") in ("speaker notes", "basic template (no AI)", "smart narration (no AI)", "built-in narrator") for m in ss.meta) and not cfg.ready:
        st.caption("ℹ️ Free smart narration is on (no AI key needed): slide points are paraphrased, numbers interpreted, with a "
                   "takeaway and a link to the next slide. An optional AI key in the sidebar makes it even more natural.")

    if mode == "Video summary":
        render_video_summary()
    elif mode == "Auto walkthrough":
        st.write("Plays every slide with its narration and advances automatically. Space = pause, ←/→ = move.")
        gap = st.slider("Gap between slides (s)", 0.0, 3.0, 0.8, 0.1)
        if st.button("🎬 Prepare & play walkthrough", type="primary"):
            bar = st.progress(0.0, "Generating narration…")
            aud = []
            for i in range(N):
                aud.append(audio_for(i)["path"]); bar.progress((i + 1) / N, f"Slide {i + 1}/{N} ready")
            ss.walk = {"audio": aud, "scripts": [spoken_script(i)[0] for i in range(N)], "gap": gap}
        if ss.get("walk"):
            w = ss.walk
            html = player_html(slides, w["audio"], w["scripts"], gap_ms=int(w["gap"] * 1000), rtl=ISO in RTL)
            html_frame(html, 760)
            d1, d2 = st.columns(2)
            d1.download_button("⬇️ Standalone HTML player", html.encode(), file_name="narrated_deck.html", mime="text/html")
            if d2.button("🎞️ Export narrated MP4"):
                with st.spinner("Rendering video with ffmpeg…"):
                    out = str(ROOT / "data" / "narrated_deck.mp4")
                    narrated_video(slides, w["audio"], out)
                st.download_button("⬇️ Download MP4", Path(out).read_bytes(), file_name="narrated_deck.mp4", mime="video/mp4")
    else:
        paced = mode == "Presenter-paced"
        if paced and (ss.paced is None or ss.paced.total != N):
            ss.paced = PacedSession(total=N, index=ss.cur)
        left, right = st.columns([3, 2], gap="medium")
        with left:
            if external:
                st.markdown(f"<div class='waiting'><h3>Slide {ss.cur + 1} / {N}: {slides[ss.cur].title}</h3>"
                            "Keep this window open next to PowerPoint. Advance PowerPoint yourself when I ask, then press Next / say 'next' here.</div>",
                            unsafe_allow_html=True)
            else:
                slide_image(ss.cur)
            st.progress((ss.cur + 1) / N, text=f"Slide {ss.cur + 1} of {N}")
            b = st.columns([1, 1.3, 1, 1, 1.4])
            if b[0].button("◀ Prev", width="stretch", disabled=ss.cur == 0):
                if paced:
                    ss.paced.command("prev"); goto(ss.paced.index, True, True)
                else:
                    goto(ss.cur - 1)
                st.rerun()
            if paced:
                if b[1].button("▶ Start / resume" if ss.paced.state in ("IDLE", "DONE") else "🔁 Repeat", width="stretch", type="primary"):
                    if ss.paced.state in ("IDLE", "DONE"):
                        ss.paced.start(ss.cur)
                    else:
                        ss.paced.command("repeat")
                    play(ss.paced.index, True); ss.paced.narration_finished()
                    st.rerun()
            else:
                if b[1].button("🔊 Narrate slide", width="stretch", type="primary"):
                    play(ss.cur); st.rerun()
            if b[2].button("Next ▶", width="stretch", disabled=ss.cur >= N - 1 and not paced):
                if paced:
                    if ss.paced.state == "IDLE":
                        ss.paced.start(ss.cur)
                        ss.paced.state = "WAITING"
                    if ss.paced.command("next"):
                        goto(ss.paced.index, True, True); ss.paced.narration_finished()
                else:
                    goto(ss.cur + 1)
                st.rerun()
            if not paced and b[3].button("🔁 Repeat", width="stretch"):
                play(ss.cur); st.rerun()
            j = b[4].number_input("Jump to", 1, N, ss.cur + 1, label_visibility="collapsed", key=f"jump_{ss.cur}")
            if j - 1 != ss.cur:
                if paced:
                    ss.paced.command("goto", j); goto(ss.paced.index, True, True); ss.paced.narration_finished()
                else:
                    goto(j - 1)
                st.rerun()
            render_player()
            if paced:
                stt_note = "⌨️ → / PageDown / N = next · ← / P = previous · R = repeat (click the page once so it has focus)"
                if ss.paced.state == "WAITING":
                    st.markdown(f"<div class='waiting'>⏸️ <b>Waiting for you.</b> After the narration I'll say “{L['cue']}”. "
                                "Click <b>Next ▶</b>, press →, or say <b>“next”</b>.</div>", unsafe_allow_html=True)
                elif ss.paced.state == "DONE":
                    st.success("That was the last slide. 🎉 Switch to **💬 Live Q&A** for questions.")
                st.caption(stt_note)
                said = handle_voice(st.audio_input(f"🎤 Voice command (say 'next', 'previous', 'repeat', 'go to slide 3' – {lang})",
                                                   key=f"cmd_{ss.cur}"), "cmd")
                if said:
                    cmd, arg = parse_command(said["text"], lang)
                    st.caption(f"Heard: “{said['text']}” → {cmd or 'not a command'} ({said['ms']} ms, {said['engine']})")
                    if cmd:
                        if ss.paced.state == "IDLE":
                            ss.paced.start(ss.cur); ss.paced.state = "WAITING"
                        if ss.paced.command(cmd, arg):
                            goto(ss.paced.index, True, True); ss.paced.narration_finished()
                        st.rerun()
        with right:
            text, note = spoken_script(ss.cur)
            m = ss.meta[ss.cur]
            tags = f"<span class='tag'>{m.get('source')}</span>"
            if m.get("overlap") and m["overlap"].get("copy_ratio") is not None:
                tags += f"<span class='tag'>verbatim {m['overlap']['copy_ratio']:.0%}</span>"
            st.markdown(f"**Script, slide {ss.cur + 1}** {tags}", unsafe_allow_html=True)
            st.markdown(f"<div class='script-box' dir='{'rtl' if ISO in RTL else 'ltr'}'>{text}</div>", unsafe_allow_html=True)
            if note:
                st.caption(note)
            if paced:
                st.caption(f"Then I say: “{L['cue']}”")
            with st.expander("Speaker notes on this slide"):
                st.write(slides[ss.cur].notes or "_(none)_")
    keyboard_shortcuts()

# ================================================================== TALK TRACK
with tab_track:
    st.subheader("Build the talk track")
    opts = ["Explain with AI (rewrite notes into a natural explanation)", "Use speaker notes as-is",
            "Smart narration without AI (free: paraphrases slide + notes, adds insights)"]
    src = st.radio("Script source", opts, index=0 if cfg.ready else 2, key="src")
    if src == opts[0] and not cfg.ready:
        st.warning("Explaining slides (the 'so what', interpreting charts and tables, transitions) needs an AI model. "
                   "Add a key in the sidebar: Google Gemini's free tier works. Until then use notes or the basic outline.")
    c = st.columns(4)
    tone = c[0].selectbox("Tone", list(TONES), index=0)
    length = c[1].selectbox("Length per slide", list(LENGTHS), index=1)
    audience = c[2].text_input("Audience", "board members and senior leaders")
    write_in = c[3].selectbox("Write script in", [f"Narration language ({lang})", f"Deck language ({deck_lang})"])
    max_ratio = st.slider("Max verbatim overlap before regenerating (share of 4-word phrases copied from the slide)",
                          0.05, 0.5, 0.15, 0.05)
    out_lang = lang if write_in.startswith("Narration") else deck_lang

    def build(i: int):
        r = None
        if src == opts[0] and cfg.ready and ai_status(cfg) is None:
            try:
                r = generate_script(cfg, slides, i, language=out_lang, tone=tone, length=length, audience=audience,
                                notes_mode="rewrite", same_language_as_deck=LANGUAGES[out_lang]["iso"] == DECK_ISO,
                                max_ratio=max_ratio)
            except Exception:
                r = None   # key exhausted / invalid / offline -> built-in narrator for this slide
        if r:
            ss.scripts[i] = r["script"]; ss.script_lang[i] = out_lang
            ss.meta[i] = {"source": "AI explanation" + (" (regenerated)" if r["regenerated"] else ""), "overlap": r["overlap"],
                          "attempts": r["attempts"], "ms": r["ms"]}
        else:
            exact = src == opts[1] or notes_exact
            ss.scripts[i] = basic_script(slides, i, use_notes=True, notes_exact=exact)
            ss.script_lang[i] = deck_lang
            ss.meta[i] = {"source": "speaker notes" if (slides[i].notes.strip() and exact) else
                          ("built-in narrator" if src == opts[0] else "smart narration (no AI)")}
        ss.meta[i]["overlap"] = ss.meta[i].get("overlap") or (
            overlap(ss.scripts[i], slides[i].full_text().replace(slides[i].title, "", 1))
            if LANGUAGES[ss.script_lang[i]]["iso"] == DECK_ISO else None)

    if st.button("✨ Build talk track for all slides", type="primary", disabled=(src == opts[0] and not cfg.ready)):
        bar = st.progress(0.0)
        err = None
        for i in range(N):
            try:
                build(i)
            except Exception as e:
                err = e; break
            bar.progress((i + 1) / N, f"Slide {i + 1}/{N}")
        ss.ta_ver += 1
        if err:
            st.error(f"Stopped: {err}")

    rows = []
    for i, s in enumerate(slides):
        o = ss.meta[i].get("overlap") or {}
        rows.append({"Slide": s.number, "Title": s.title[:50], "Source": ss.meta[i].get("source"), "Lang": ss.script_lang[i],
                     "Words": len(ss.scripts[i].split()),
                     "Verbatim overlap": None if o.get("copy_ratio") is None else f"{o['copy_ratio']:.0%}",
                     "Longest copied run": o.get("longest_run"), "Attempts": ss.meta[i].get("attempts", "")})
    st.dataframe(rows, hide_index=True, width="stretch")

    for i, s in enumerate(slides):
        with st.expander(f"Slide {s.number}: {s.title}", expanded=(i == ss.cur)):
            cc = st.columns([3, 1])
            new = cc[0].text_area("Script (editable)", ss.scripts[i], height=170, key=f"ta_{i}_{ss.ta_ver}",
                                  label_visibility="collapsed")
            if new != ss.scripts[i]:
                ss.scripts[i] = new
                ss.meta[i] = {**ss.meta[i], "source": "edited", "overlap": overlap(new, s.full_text().replace(s.title, "", 1))
                              if LANGUAGES[ss.script_lang[i]]["iso"] == DECK_ISO else None}
            if cc[1].button("↻ Regenerate", key=f"rg_{i}_{ss.ta_ver}", disabled=(src == opts[0] and not cfg.ready)):
                try:
                    build(i); ss.ta_ver += 1; st.rerun()
                except Exception as e:
                    st.error(str(e))
            if cc[1].button("🔊 Preview", key=f"pv_{i}_{ss.ta_ver}"):
                r = audio_for(i)
                cc[1].audio(r["path"], autoplay=True)
            cc[1].caption(f"Notes: {'yes' if s.notes.strip() else 'none'}")

    st.divider()
    d = st.columns(3)
    title = f"Talk track: {ss.deck_name}"
    d[0].download_button("⬇️ TXT", talk_track_txt(slides, ss.scripts, title).encode("utf-8"), file_name="talk_track.txt")
    d[1].download_button("⬇️ DOCX", talk_track_docx(slides, ss.scripts, title), file_name="talk_track.docx",
                         mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    if ss.deck_path.lower().endswith(".pptx"):
        d[2].download_button("⬇️ PPTX with scripts in speaker notes", pptx_with_notes(ss.deck_path, ss.scripts),
                             file_name=Path(ss.deck_name).stem + "_with_talk_track.pptx",
                             mime="application/vnd.openxmlformats-officedocument.presentationml.presentation")

# ================================================================== LIVE
with tab_live:
    st.subheader("Live co-presenter: Q&A")
    st.caption("Ask by voice or text. I answer from the deck (current slide first), cite slide numbers, speak the answer and can jump to the "
               "relevant slide. Honest latency: expect roughly 1–2 s to transcribe, 1–4 s for the AI, 1–2 s to synthesise speech.")
    if not cfg.ready:
        st.warning("No AI key: I can only point to the most relevant slide and read the closest lines. Add a key for real answers.")
    lc1, lc2 = st.columns([2, 3])
    with lc1:
        slide_image(ss.cur)
        st.caption(f"On screen: slide {ss.cur + 1} / {N}")
        auto_jump = st.toggle("Jump to the relevant slide", value=True)
        speak = st.toggle("Speak the answer", value=True)
        autodetect = st.toggle("Auto-detect question language", value=False,
                               help=f"Off: questions are transcribed as {lang}. On: Whisper detects the language.")
    with lc2:
        q_audio = st.audio_input("🎤 Ask a question", key="qa_mic")
        q_text = st.text_input("…or type a question", key="qa_text", placeholder="e.g. How big will the market be by 2030?")
        ask = st.button("Ask", type="primary")
        question, stt_ms, stt_eng = None, 0, ""
        if q_audio is not None:
            data = q_audio.getvalue(); h = hashlib.sha1(data).hexdigest()
            if ("qa", h) not in ss.seen_audio:
                ss.seen_audio.add(("qa", h))
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                    f.write(data); pth = f.name
                with st.spinner("Transcribing…"):
                    tr = transcribe(pth, None if autodetect else lang, size=stt_size, api=stt_api)
                question, stt_ms, stt_eng = tr["text"], tr["ms"], tr["engine"]
        if ask and q_text.strip():
            question = q_text.strip()
        if question:
            cmd, arg = parse_command(question, lang)
            if cmd in ("next", "prev", "goto"):
                tgt = {"next": ss.cur + 1, "prev": ss.cur - 1}.get(cmd, (arg or 1) - 1 if arg != -1 else N - 1)
                goto(tgt, narrate=True)
                ss.qa_log.insert(0, {"q": question, "a": f"(command) moved to slide {ss.cur + 1}", "lat": {"stt": stt_ms}})
                st.rerun()
            t0 = time.time()
            try:
                with st.spinner("Thinking…"):
                    res = answer_question(cfg if cfg.ready else None, slides, question, ss.cur, language=lang)
            except Exception as e:
                from core.llm import keyword_answer
                res = keyword_answer(slides, question, ss.cur)
            if str(res.get("engine", "")).startswith("built-in") and ISO != DECK_ISO:
                try:
                    res["answer"] = translate(res["answer"], lang, ISO, None, L["locale"])["text"]
                except Exception:
                    pass
            tts_ms, apath = 0, None
            if speak:
                t1 = time.time()
                try:
                    a = synthesize(res["answer"], lang, voice, rate, pitch, 250, 500, engine, keys)
                    apath = a["path"]
                except Exception as e:
                    st.warning(f"Could not speak the answer: {e}")
                tts_ms = int((time.time() - t1) * 1000)
            if auto_jump and res.get("jump_to"):
                ss.cur = res["jump_to"] - 1
            ss.qa_log.insert(0, {"q": question, "a": res["answer"], "slides": res.get("slides"), "jump": res.get("jump_to"),
                                 "engine": res.get("engine"), "audio": apath, "nonce": time.time(),
                                 "lat": {"stt": stt_ms, "llm": res["ms"], "tts": tts_ms}, "stt_engine": stt_eng})
            st.rerun()
        for k, e in enumerate(ss.qa_log[:10]):
            with st.container(border=True):
                st.markdown(f"**Q:** {e['q']}")
                st.markdown(f"<div dir='{'rtl' if ISO in RTL else 'ltr'}'><b>A:</b> {e['a']}</div>", unsafe_allow_html=True)
                if e.get("audio"):
                    fresh = k == 0 and e.get("nonce") != ss.get("qa_played")
                    st.audio(e["audio"], autoplay=fresh)
                    if fresh:
                        ss.qa_played = e["nonce"]
                lat = e.get("lat", {})
                tot = sum(lat.values())
                st.caption(f"Cited slides: {e.get('slides') or '-'} · jumped to: {e.get('jump') or '-'} · "
                           f"latency: listen {lat.get('stt', 0) / 1000:.1f}s + think {lat.get('llm', 0) / 1000:.1f}s + speak "
                           f"{lat.get('tts', 0) / 1000:.1f}s = **{tot / 1000:.1f}s** · {e.get('engine', '')}")

# ================================================================== DECK DATA
with tab_deck:
    st.subheader("What I extracted")
    st.caption(f"Rendering: {ri.get('method')} {('· ' + ri['error']) if ri.get('error') else ''}")
    for s in slides:
        with st.expander(f"Slide {s.number}: {s.title}" + (" (hidden)" if s.hidden else "")):
            a, b = st.columns([1, 2])
            a.image(s.image_path, width="stretch")
            if s.bullets:
                b.markdown("**Body**\n" + "\n".join(f"{'  ' * lv}- {t}" for t, lv in zip(s.bullets, s.levels)))
            for t in s.tables:
                b.markdown("**Table**"); b.table(t)
            for ch in s.charts:
                b.markdown(f"**Chart:** {ch.get('title')} ({ch.get('type')})"); b.write(ch)
            if s.alt_texts:
                b.write(s.alt_texts)
            b.markdown("**Speaker notes:** " + (s.notes or "_none_"))
