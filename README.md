# 🎙️ Deck Narrator & Co-Presenter (Streamlit)

Upload a PowerPoint (`.pptx`) or PDF deck and the bot will **explain** it out loud in 60+ languages with natural
neural voices: from your speaker notes, from an AI-written talk track, as an automatic walkthrough, at your pace
("please move to the next slide"... waits for you), or as a live co-presenter that answers questions about the deck.

## Easiest: Docker (plug-and-play, Windows / Mac / Linux)
Install Docker Desktop once, then double-click `start-windows.bat`, `start-mac.command` or `start-linux.sh`.
The app opens at **http://localhost:8502**. Stop it with the matching `stop-*` script. Optional keys go in `.env`
(see `.env.example`). Non-technical guide, plus offline image sharing (`docker save | gzip` / `docker load`): **SHARING.md**.
Manual: `cp .env.example .env && docker compose up -d --build`.

The image (~2.3 GB) contains LibreOffice Impress, poppler, ffmpeg, Noto fonts (Latin/Cyrillic/Greek/Arabic/Hebrew/Indic/Thai/CJK/
Ethiopic...) and the Whisper `base` model, so speech recognition works offline. It runs as a non-root user and has a
healthcheck; generated audio is kept in the `audio_cache` volume.

## Quick start without Docker
```bash
# system packages (Ubuntu/Debian). macOS: brew install --cask libreoffice && brew install ffmpeg poppler
sudo apt-get install -y libreoffice-impress ffmpeg poppler-utils fonts-noto
pip install -r requirements.txt
./run.sh                      # http://localhost:8502   (or: streamlit run app.py)
```
Click **Load sample deck** to try it (`samples/sample_deck.pptx`, 6 slides, notes on 3, a chart and a table).
Windows: install LibreOffice + ffmpeg + poppler, add them to PATH, then `streamlit run app.py`.

The first voice-command / question transcription downloads the Whisper model (~140 MB for `base`, ~480 MB for `small`).

## Two modes (▶️ Present tab → "Choose a mode")

1. **🎬 Narrated walkthrough**: slides appear one by one with narration auto-played.
2. **🎤 Live co-presenter**: you present; pacing "On demand" (narrate when you click) or "Presenter-paced" (narrate, then wait for "next"). Audience questions: 💬 Live Q&A tab.

Both modes use the sidebar **Narration language** (62 languages): the script is translated (AI key, else free Google Translate, else free MyMemory) and spoken with a matching voice.

### Details
| Mode | What it does | Needs AI key? |
|---|---|---|
| Narrate (manual) | Speaks the current slide's script; you move with Prev/Next/Jump | No |
| Auto walkthrough | Slide image + voice, advances by itself (pause/prev/next/progress); export **HTML player** or **MP4** | No |
| Presenter-paced | Narrates a slide, says *"Please move to the next slide"* in the chosen language, then **waits**. Advance with **Next ▶**, keys **→ / PageDown / N** (← / P back, R repeat), or by saying **"next"** into the mic. Also "previous", "repeat", "go to slide 4". | No |
| Live Q&A (💬 tab) | Ask by voice or text; answers from the deck (current slide first), cites slides, speaks the answer, jumps to the relevant slide; shows latency (listen + think + speak) | Yes for real answers (no key = points to the best-matching slide) |

**Driving PowerPoint/Teams yourself?** Turn on *"I'm driving PowerPoint separately"*. The app hides the slide and keeps
narrating. When it asks, advance PowerPoint, then press Next / say "next" in the app. (A clicker or keyboard only
controls the window that has focus, so voice "next" is the easiest option when PowerPoint is in front.)

## Explaining, not reading (✍️ Talk track tab)
* **Explain with AI** (default when a key is set): writes a spoken script per slide that explains the *so what*,
  interprets charts and tables (trends, comparisons, computed CAGR and leader gaps are passed in as verified facts),
  connects points, and ends with a transition to the next slide. Speaker notes are treated as intent and **rewritten**
  into natural speech (or choose *Use speaker notes as-is*). Tone: Conversational / Formal / Executive; length; audience.
* **Verbatim check:** every script is scored against the slide text: *copy ratio* (share of its 4-word phrases copied
  from the slide) and *longest copied run*. Above the threshold (default 15% or 8+ words) it is regenerated, up to 2 times.
* **No key:** uses speaker notes, or a templated outline that does **not** read bullets (themes, computed chart/table
  insights, key numbers, transition). Real explanations need an LLM; Gemini's free tier is enough.
* Scripts are editable; download **TXT / DOCX**, or a **PPTX with the scripts written into the speaker notes**.

## Voices (natural first)
* Default engine: **edge-tts** (free Microsoft neural voices). Curated defaults per language, e.g. en-US
  *AvaMultilingual/AndrewMultilingual*, en-IN *NeerjaExpressive/Prabhat*, hi-IN *Swara/Madhur*, fr *Vivienne/Remy
  Multilingual*, de *Seraphina/Florian Multilingual*, ja *Nanami/Keita*, ar-SA *Zariyah/Hamed*.
* Natural pacing: text is cleaned for speech (no bullets/symbols/URLs read out; "USD 45M" → "45 million dollars",
  "~9% CAGR" → "about 9 percent C-A-G-R", "e.g." → "for example"), split into sentence groups and stitched with real
  pauses (sentence and paragraph pause sliders), plus rate and pitch control.
* **gTTS is only used if edge-tts fails**, and the app shows a warning (it sounds more robotic). Punjabi has no free
  neural voice, so it uses gTTS unless you pick a premium engine.
* Optional premium engines (sidebar → Voice engine): **OpenAI TTS**, **ElevenLabs** (multilingual v2), **Azure Speech**
  (same voices as Edge, with real SSML breaks).
* Audio is cached per text + voice + rate + pitch + pauses in `data/audio_cache/`.

## AI provider (sidebar)
Any OpenAI-compatible endpoint. Presets: **Google Gemini** (free tier, `https://generativelanguage.googleapis.com/v1beta/openai/`,
`gemini-2.5-flash`), **Groq** (free tier, `llama-3.3-70b-versatile`), **OpenAI** (`gpt-4o-mini`), **Ollama** local (`http://localhost:11434/v1`).
You can also set the env vars `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`.

## Languages
62 options covering ~55 languages: English (US/UK/India), Hindi, Bengali, Tamil, Telugu, Marathi, Gujarati, Kannada, Malayalam,
Punjabi, Urdu, Nepali, Sinhala, Spanish (ES/MX), Portuguese (BR/PT), French, German, Italian, Dutch, Arabic (SA/EG), Chinese
(Mandarin simplified/Taiwan, Cantonese), Japanese, Korean, Russian, Ukrainian, Turkish, Persian, Hebrew, Indonesian, Malay,
Vietnamese, Thai, Filipino, Swahili, Amharic, Zulu, Afrikaans, Greek, Polish, Czech, Slovak, Romanian, Hungarian, Bulgarian,
Croatian, Serbian, Swedish, Danish, Norwegian, Finnish, Kazakh, Uzbek, Burmese and Khmer. Each has a native "next slide" cue and
voice-command words (Indic languages also accept the romanised forms Whisper sometimes outputs, like "agli slide").
**Translation:** if the narration language differs from the deck, scripts are translated by the AI model, or by free
Google Translate / MyMemory (deep-translator) without a key, which can be rate-limited or blocked on some networks.
Better: generate the talk track directly in the target language.

## Speech recognition
Local **faster-whisper** (`base` by default, `small` is more accurate for Indic languages), free and offline after the first
download. Optional: any OpenAI-compatible `/audio/transcriptions` API. Mic input uses Streamlit's `st.audio_input`
(the browser asks for permission; it needs `localhost` or HTTPS).

## Tests
```bash
python scripts/mock_llm.py 8765 &           # stand-in OpenAI-compatible server (NOT a real model)
python tests/test_e2e.py                    # parse/render, TTS in 9 languages, STT + commands, paced flow, Q&A, exports
python -m pytest -q tests/                  # + Streamlit AppTest UI smoke tests
```

## Limitations
* "Live" is not instantaneous: each spoken answer takes a few seconds (transcribe → AI → voice).
* Voice "next" is push-to-talk (record a short clip), not always-on listening.
* The app cannot click through PowerPoint/Teams itself; present from the app window, or drive PowerPoint and confirm with Next / "next".
* Rendering uses LibreOffice, so fonts and animations can differ from PowerPoint; if rendering fails you get text cards.
* Charts: python-pptx reads native chart data; charts pasted as images are only described by their alt text.
* Without a key, "explanations" are a templated outline, not real understanding.
