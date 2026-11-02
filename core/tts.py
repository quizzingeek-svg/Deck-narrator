"""Text-to-speech with natural pacing.

Default engine: edge-tts (free Microsoft neural voices). Text is cleaned for speech, split into
sentence groups, synthesised in parallel and stitched with short pauses between sentence groups and
longer pauses between paragraphs (edge-tts does not accept custom SSML, so pauses are real silence).
Fallback: gTTS (only if edge-tts fails; flagged with a warning). Optional premium engines:
OpenAI TTS, ElevenLabs, Azure Speech (true SSML breaks)."""
from __future__ import annotations

import asyncio
import hashlib
import html
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional

from .languages import LANGUAGES, default_voice
from .speech_text import chunks_for_pacing, pronounce, speakable

CACHE = Path(__file__).resolve().parent.parent / "data" / "audio_cache"
CACHE.mkdir(parents=True, exist_ok=True)

ENGINES = ["Edge neural (free)", "OpenAI TTS (key)", "ElevenLabs (key)", "Azure Speech (key)"]


def _rate_str(rate_pct: int) -> str:
    return f"{'+' if rate_pct >= 0 else ''}{int(rate_pct)}%"


def _pitch_str(hz: int) -> str:
    return f"{'+' if hz >= 0 else ''}{int(hz)}Hz"


def _ff(args: List[str]):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"] + args, check=True, capture_output=True, timeout=300)


def _silence(ms: int, d: Path) -> Path:
    p = d / f"sil_{ms}.mp3"
    if not p.exists():
        _ff(["-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", f"{ms / 1000:.2f}", "-c:a", "libmp3lame", "-q:a", "6", str(p)])
    return p


def _concat(parts: List[Path], out: Path):
    if len(parts) == 1:
        shutil.copy(parts[0], out); return
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        for p in parts:
            f.write(f"file '{p.resolve()}'\n")
        lst = f.name
    _ff(["-f", "concat", "-safe", "0", "-i", lst, "-ar", "24000", "-ac", "1", "-c:a", "libmp3lame", "-q:a", "4", str(out)])


def duration_s(path: str) -> float:
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                           capture_output=True, text=True, timeout=30)
        return float(r.stdout.strip())
    except Exception:
        return 0.0


async def _edge_one(text: str, voice: str, rate: str, pitch: str, path: Path):
    import edge_tts
    last = None
    for attempt in range(3):
        try:
            await edge_tts.Communicate(text, voice, rate=rate, pitch=pitch).save(str(path))
            if path.exists() and path.stat().st_size > 0:
                return
        except Exception as e:  # noqa
            last = e
            await asyncio.sleep(0.6 * (attempt + 1))
    raise RuntimeError(f"edge-tts failed: {last}")


async def _edge_many(jobs):
    sem = asyncio.Semaphore(4)

    async def run(j):
        async with sem:
            await _edge_one(*j)
    await asyncio.gather(*(run(j) for j in jobs))


def _run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(1) as ex:
        return ex.submit(asyncio.run, coro).result()


def synthesize(text: str, lang: str, voice: Optional[str] = None, rate_pct: int = 0, pitch_hz: int = 0,
               sentence_pause_ms: int = 350, para_pause_ms: int = 750, engine: str = ENGINES[0],
               keys: Optional[Dict[str, str]] = None, prepared: bool = False) -> Dict:
    """Returns {path, engine, voice, warning, seconds, cached, ms}."""
    keys = keys or {}
    L = LANGUAGES[lang]
    voice = voice or default_voice(lang)
    clean = pronounce(text if prepared else speakable(text, L["iso"]), L["iso"])
    if not clean.strip():
        clean = "."
    sig = json.dumps([engine, voice, rate_pct, pitch_hz, sentence_pause_ms, para_pause_ms, clean], ensure_ascii=False)
    key = hashlib.sha1(sig.encode()).hexdigest()[:20]
    out = CACHE / f"{key}.mp3"
    meta = CACHE / f"{key}.json"
    if out.exists() and meta.exists():
        m = json.loads(meta.read_text()); m.update(path=str(out), cached=True, ms=0)
        return m
    t0 = time.time()
    warning = ""
    used_engine, used_voice = engine, voice
    work = Path(tempfile.mkdtemp(prefix="tts_"))
    try:
        if engine.startswith("Edge"):
            if not voice:
                raise RuntimeError(f"No edge-tts voice for {lang}")
            _edge_paced(clean, voice, rate_pct, pitch_hz, sentence_pause_ms, para_pause_ms, work, out)
        elif engine.startswith("OpenAI"):
            _openai_tts(clean, keys, rate_pct, out)
            used_voice = keys.get("openai_voice", "alloy")
        elif engine.startswith("ElevenLabs"):
            _eleven(clean, keys, out); used_voice = keys.get("eleven_voice_id", "")
        elif engine.startswith("Azure"):
            _azure(clean, voice, rate_pct, pitch_hz, sentence_pause_ms, para_pause_ms, keys, out)
    except Exception as e:  # noqa
        # last-resort fallback: gTTS (more robotic) - warn loudly
        try:
            _gtts(clean, L["gtts"], out)
            warning = (f"⚠️ {engine} failed ({str(e)[:140]}). Fell back to gTTS, which sounds noticeably more robotic."
                       if voice or not engine.startswith("Edge") else
                       f"⚠️ No free neural voice exists for {lang}; using gTTS (more robotic). Use Azure/ElevenLabs/OpenAI for a natural voice.")
            used_engine, used_voice = "gTTS (fallback)", L["gtts"]
        except Exception as e2:
            shutil.rmtree(work, ignore_errors=True)
            raise RuntimeError(f"All TTS engines failed: {e} / gTTS: {e2}")
    shutil.rmtree(work, ignore_errors=True)
    m = {"engine": used_engine, "voice": used_voice, "warning": warning, "seconds": round(duration_s(str(out)), 2)}
    meta.write_text(json.dumps(m))
    m.update(path=str(out), cached=False, ms=int((time.time() - t0) * 1000))
    return m


def _edge_paced(clean, voice, rate_pct, pitch_hz, sp_ms, pp_ms, work: Path, out: Path):
    paras = chunks_for_pacing(clean)
    jobs, layout = [], []
    n = 0
    for pi, groups in enumerate(paras):
        for gi, g in enumerate(groups):
            p = work / f"c{n:03d}.mp3"; n += 1
            jobs.append((g, voice, _rate_str(rate_pct), _pitch_str(pitch_hz), p))
            layout.append(p)
            if gi < len(groups) - 1 and sp_ms:
                layout.append(("sil", sp_ms))
        if pi < len(paras) - 1 and pp_ms:
            layout.append(("sil", pp_ms))
    _run_async(_edge_many(jobs))
    parts = [_silence(x[1], work) if isinstance(x, tuple) else x for x in layout]
    _concat(parts, out)


def _gtts(text, code, out: Path):
    from gtts import gTTS
    gTTS(text, lang=code or "en").save(str(out))


def _openai_tts(text, keys, rate_pct, out: Path):
    import requests
    base = (keys.get("openai_tts_base") or "https://api.openai.com/v1").rstrip("/")
    r = requests.post(f"{base}/audio/speech", timeout=120,
                      headers={"Authorization": f"Bearer {keys['openai_tts_key']}"},
                      json={"model": keys.get("openai_tts_model", "gpt-4o-mini-tts"), "voice": keys.get("openai_voice", "alloy"),
                            "input": text[:4000], "speed": max(0.25, min(4.0, 1 + rate_pct / 100)),
                            "instructions": "Speak like a warm, confident presenter explaining a slide. Natural pauses."})
    r.raise_for_status(); out.write_bytes(r.content)


def _eleven(text, keys, out: Path):
    import requests
    vid = keys.get("eleven_voice_id") or "21m00Tcm4TlvDq8ikWAM"
    r = requests.post(f"https://api.elevenlabs.io/v1/text-to-speech/{vid}", timeout=120,
                      headers={"xi-api-key": keys["eleven_key"], "accept": "audio/mpeg"},
                      json={"text": text, "model_id": "eleven_multilingual_v2"})
    r.raise_for_status(); out.write_bytes(r.content)


def _azure(text, voice, rate_pct, pitch_hz, sp_ms, pp_ms, keys, out: Path):
    import requests
    region = keys.get("azure_region", "eastus")
    locale = "-".join(voice.split("-")[:2])
    body = []
    for groups in chunks_for_pacing(text):
        body.append(f'<break time="{sp_ms}ms"/>'.join(html.escape(g) for g in groups))
    inner = f'<break time="{pp_ms}ms"/>'.join(body)
    ssml = (f'<speak version="1.0" xml:lang="{locale}"><voice name="{voice}">'
            f'<prosody rate="{_rate_str(rate_pct)}" pitch="{_pitch_str(pitch_hz)}">{inner}</prosody></voice></speak>')
    r = requests.post(f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1", timeout=120, data=ssml.encode(),
                      headers={"Ocp-Apim-Subscription-Key": keys["azure_key"], "Content-Type": "application/ssml+xml",
                               "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3"})
    r.raise_for_status(); out.write_bytes(r.content)


_VOICES: List[dict] = []


def edge_voice_list() -> List[dict]:
    global _VOICES
    if not _VOICES:
        try:
            import edge_tts
            _VOICES = _run_async(edge_tts.list_voices())
        except Exception:
            _VOICES = []
    return _VOICES


def with_lead(path: str, lead_ms: int = 700) -> str:
    """Copy of an mp3 with `lead_ms` of silence in front, so the slide is on screen before the voice
    starts even when the browser starts playback as soon as the page renders. Cached next to the file."""
    if lead_ms <= 0:
        return path
    src = Path(path)
    out = src.with_name(f"{src.stem}.lead{int(lead_ms)}.mp3")
    if out.exists() and out.stat().st_size > 0:
        return str(out)
    try:
        _ff(["-i", str(src), "-af", f"adelay={int(lead_ms)}:all=1", "-c:a", "libmp3lame", "-q:a", "3", str(out)])
        return str(out)
    except Exception:
        return path
