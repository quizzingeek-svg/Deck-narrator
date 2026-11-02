"""Speech-to-text (local faster-whisper by default, optional OpenAI-compatible API) and
voice-command detection ("next", "previous", "repeat", "go to slide 4") in every supported language."""
from __future__ import annotations

import re
import time
import unicodedata
from typing import Dict, Optional, Tuple

from .languages import LANGUAGES

_MODELS: Dict[str, object] = {}

NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
             "ten": 10, "eleven": 11, "twelve": 12, "first": 1, "second": 2, "third": 3, "last": -1}


def get_model(size: str = "base"):
    if size not in _MODELS:
        from faster_whisper import WhisperModel
        _MODELS[size] = WhisperModel(size, device="cpu", compute_type="int8")
    return _MODELS[size]


def transcribe(path: str, lang: Optional[str] = None, size: str = "base", api: Optional[dict] = None,
               short_command: bool = False) -> Dict:
    """Returns {text, language, ms, engine}. lang = language name from LANGUAGES or None (auto-detect)."""
    iso = LANGUAGES[lang]["iso"] if lang in LANGUAGES else None
    t0 = time.time()
    if api and api.get("key"):
        from openai import OpenAI
        c = OpenAI(api_key=api["key"], base_url=(api.get("base_url") or None), timeout=60)
        with open(path, "rb") as f:
            r = c.audio.transcriptions.create(model=api.get("model") or "whisper-1", file=f, **({"language": iso} if iso else {}))
        return {"text": r.text.strip(), "language": iso or "", "ms": int((time.time() - t0) * 1000), "engine": "API"}
    m = get_model(size)
    segs, info = m.transcribe(load_audio(path), language=iso, beam_size=1 if short_command else 5, vad_filter=not short_command,
                              initial_prompt=None)
    text = " ".join(s.text.strip() for s in segs).strip()
    return {"text": text, "language": info.language, "ms": int((time.time() - t0) * 1000), "engine": f"faster-whisper-{size}"}


def load_audio(path: str, sr: int = 16000):
    """Decode any audio (webm/wav/mp3/ogg from the browser) with ffmpeg -> float32 mono 16 kHz array.
    Avoids PyAV version clashes inside faster-whisper."""
    import subprocess
    import numpy as np
    out = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", path, "-f", "s16le", "-ac", "1", "-ar", str(sr), "-"],
                         capture_output=True, check=True, timeout=120).stdout
    return np.frombuffer(out, np.int16).astype(np.float32) / 32768.0


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFC", s or "").lower()
    return re.sub(r"[^\w\s]", " ", s)


def parse_command(text: str, lang: str = "English (US)") -> Tuple[Optional[str], Optional[int]]:
    """-> ('next'|'prev'|'repeat'|'goto'|'stop', slide_number or None) or (None, None) if not a command."""
    t = _norm(text)
    if not t.strip():
        return None, None
    L = LANGUAGES.get(lang, LANGUAGES["English (US)"])
    en = LANGUAGES["English (US)"]
    m = re.search(r"(?:slide|go to|jump to|number)\s*(\d+|" + "|".join(NUM_WORDS) + r")\b", t)
    if m:
        v = m.group(1)
        return "goto", int(v) if v.isdigit() else NUM_WORDS[v]
    if re.search(r"\b(stop|pause|wait)\b", t):
        return "stop", None
    # whole-utterance short commands only, so a question that contains "next" is not a command
    words = t.split()

    def hit(keys):
        for k in keys:
            k = _norm(k).strip()
            if not k:
                continue
            if re.search(r"[a-z]", k):
                if re.search(rf"\b{re.escape(k)}\b", t):
                    return True
            elif k in t:            # scripts without spaces (zh/ja/th)
                return True
        return False
    short = len(words) <= 6 or len(t.replace(" ", "")) <= 14
    if short:
        if hit(L["prev"] + en["prev"]):
            return "prev", None
        if hit(L["repeat"] + en["repeat"]):
            return "repeat", None
        if hit(L["next"] + en["next"]):
            return "next", None
    return None, None
