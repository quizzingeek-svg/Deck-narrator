"""Provider-agnostic LLM layer (any OpenAI-compatible endpoint): talk-track generation that EXPLAINS
slides (with a verbatim-overlap check + regeneration), translation, and grounded live Q&A."""
from __future__ import annotations

import json
import math
import re
import hashlib
import time
from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Optional

from .deck import Slide
from .insights import slide_facts
from .overlap import overlap, too_verbatim

PRESETS = {
    "Google Gemini (free tier)": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
                                  "model": "gemini-2.5-flash", "key_hint": "Free key: aistudio.google.com/apikey"},
    "Groq (free tier)": {"base_url": "https://api.groq.com/openai/v1", "model": "llama-3.3-70b-versatile",
                         "key_hint": "Free key: console.groq.com/keys"},
    "OpenAI": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini", "key_hint": "platform.openai.com (paid)"},
    "Ollama (local)": {"base_url": "http://localhost:11434/v1", "model": "llama3.1", "key_hint": "Any text, e.g. 'ollama'"},
    "Custom OpenAI-compatible": {"base_url": "", "model": "", "key_hint": "Any OpenAI-compatible endpoint"},
}

LENGTHS = {"Short (~45 s)": 90, "Medium (~1 min)": 140, "Long (~2 min)": 260}
TONES = {
    "Conversational": "warm, conversational, like a confident colleague talking to the room; contractions are fine",
    "Formal": "polished and formal, precise wording, no slang",
    "Executive": "crisp executive briefing: lead with the 'so what', decisions and implications first, minimal detail",
}


@dataclass
class LLMConfig:
    api_key: str = ""
    base_url: str = ""
    model: str = ""

    @property
    def ready(self) -> bool:
        return bool(self.api_key and self.model)


# ------------------------------------------------------------------ AI circuit breaker
# If the (shared) key runs out of quota, is invalid, or the network is down, we stop calling the AI for a
# while so the app stays fast, and every caller falls back to the free built-in narrator.
class AIUnavailable(RuntimeError):
    """Raised instead of calling the AI while it's in cooldown (or when a call fails)."""


COOLDOWN = {"quota": 600, "auth": 3600, "timeout": 120, "network": 120, "other": 60}
_DOWN: Dict[str, tuple] = {}   # key fingerprint -> (until_ts, kind, message)


def _fp(cfg: "LLMConfig") -> str:
    return hashlib.sha1(f"{cfg.api_key}|{cfg.base_url}|{cfg.model}".encode()).hexdigest()[:12]


def classify_error(e: Exception) -> str:
    name = type(e).__name__.lower()
    msg = str(e).lower()
    code = getattr(e, "status_code", None) or getattr(getattr(e, "response", None), "status_code", None)
    if code == 429 or "ratelimit" in name or any(w in msg for w in ("429", "quota", "rate limit", "resource_exhausted", "exhausted")):
        return "quota"
    if code in (401, 403) or "authentication" in name or "permission" in name or any(
            w in msg for w in ("api key not valid", "valid api key", "invalid api key", "api_key", "api_key_invalid", "unauthorized", "incorrect api key", "401", "403")):
        return "auth"
    if "timeout" in name or "timed out" in msg:
        return "timeout"
    if "connection" in name or any(w in msg for w in ("connection", "network", "name resolution", "unreachable")):
        return "network"
    return "other"


def ai_status(cfg: Optional["LLMConfig"]) -> Optional[dict]:
    """None if the AI is usable right now; else {kind, message, seconds_left}."""
    if not (cfg and cfg.ready):
        return {"kind": "nokey", "message": "no key", "seconds_left": 0}
    d = _DOWN.get(_fp(cfg))
    if d and time.time() < d[0]:
        return {"kind": d[1], "message": d[2], "seconds_left": int(d[0] - time.time())}
    return None


def ai_ok(cfg: Optional["LLMConfig"]) -> bool:
    return ai_status(cfg) is None


def mark_down(cfg: "LLMConfig", e: Exception) -> str:
    kind = classify_error(e)
    _DOWN[_fp(cfg)] = (time.time() + COOLDOWN[kind], kind, str(e)[:200])
    return kind


def reset_breaker():
    _DOWN.clear()


def client(cfg: LLMConfig):
    from openai import OpenAI
    return OpenAI(api_key=cfg.api_key, base_url=(cfg.base_url.rstrip("/") + "/") if cfg.base_url else None,
                  timeout=25, max_retries=0)


def chat(cfg: LLMConfig, messages: List[dict], temperature: float = 0.6, max_tokens: int = 900, json_mode=False) -> str:
    st_ = ai_status(cfg)
    if st_ is not None:
        raise AIUnavailable(f"AI skipped ({st_['kind']}, cooldown {st_['seconds_left']}s)")
    try:
        return _chat(cfg, messages, temperature, max_tokens, json_mode)
    except AIUnavailable:
        raise
    except Exception as e:
        kind = mark_down(cfg, e)
        raise AIUnavailable(f"AI call failed ({kind}): {str(e)[:160]}") from e


def _chat(cfg: LLMConfig, messages: List[dict], temperature: float, max_tokens: int, json_mode: bool) -> str:
    kw = {}
    if json_mode:
        kw["response_format"] = {"type": "json_object"}
    try:
        r = client(cfg).chat.completions.create(model=cfg.model, messages=messages, temperature=temperature,
                                                max_tokens=max_tokens, **kw)
    except Exception as e:
        if json_mode and "response_format" in str(e):
            r = client(cfg).chat.completions.create(model=cfg.model, messages=messages, temperature=temperature, max_tokens=max_tokens)
        else:
            raise
    return (r.choices[0].message.content or "").strip()


def test_connection(cfg: LLMConfig) -> str:
    t = time.time()
    out = chat(cfg, [{"role": "user", "content": "Reply with the single word: ready"}], max_tokens=10, temperature=0)
    return f"OK ({int((time.time() - t) * 1000)} ms): {out[:40]}"


# ------------------------------------------------------------------ talk track
SYSTEM_SCRIPT = """You are an expert presentation coach writing the SPOKEN talk track a presenter says while a slide is on screen.
The audience can already SEE the slide, so your job is to EXPLAIN it, not read it.
Hard rules:
- NEVER read bullets out verbatim or list them one by one. Never reproduce more than 5 consecutive words from the slide (proper names and figures excepted).
- Explain the meaning: the 'so what', the insight, why it matters to this audience, and how the points connect to each other and to the story so far.
- Charts and tables: interpret them. Describe the trend or pattern, compare the important numbers (who leads, by how much, growth, gaps), and say what it implies. Do not recite every cell.
- If speaker notes are provided, treat them as the presenter's intent and keep their key messages, but rephrase them as natural, flowing speech.
- Sound human: short sentences, varied rhythm, an occasional rhetorical question; no headings, no bullet points, no markdown, no emojis, no stage directions, no 'this slide shows'.
- Write numbers the way a person says them (e.g. 'about one point six billion dollars' or '1.6 billion dollars'; never '~', '+', '/', '&').
- End with ONE short natural transition sentence that leads into the next slide (given below); on the last slide end with a clear close or call to action.
- Do not invent facts or numbers that are not on the slide, in the notes, or in the computed facts.
- Output ONLY the words to be spoken, in {language}."""


def _slide_block(s: Slide) -> str:
    lines = [f"Title: {s.title}"]
    if s.bullets:
        lines.append("Body:\n" + "\n".join(("  " * lv) + "- " + b for b, lv in zip(s.bullets, s.levels or [0] * len(s.bullets))))
    for t in s.tables:
        lines.append("Table:\n" + "\n".join(" | ".join(r) for r in t))
    for c in s.charts:
        lines.append(f"Chart ({c.get('type')}): {c.get('title')}; categories {c.get('categories')}; "
                     + "; ".join(f"{x['name']}={x['values']}" for x in c.get('series', [])))
    if s.alt_texts:
        lines.append("Images: " + "; ".join(s.alt_texts))
    f = slide_facts(s)
    if f:
        lines.append("Computed facts (verified from the data):\n" + "\n".join("- " + x for x in f))
    return "\n".join(lines)


def generate_script(cfg: LLMConfig, slides: List[Slide], i: int, *, language="English", tone="Conversational",
                    length="Medium (~1 min)", audience="general business audience", notes_mode="rewrite",
                    same_language_as_deck=True, max_ratio=0.15, max_run=8, retries=2) -> Dict:
    """notes_mode: 'rewrite' (default: explain using notes as intent) or 'ignore'.
    Returns {script, overlap, attempts, regenerated, ms}."""
    s = slides[i]
    prev_t = slides[i - 1].title if i > 0 else "(none: this is the opening slide)"
    next_t = slides[i + 1].title if i + 1 < len(slides) else "(none: this is the last slide)"
    outline = "\n".join(f"{x.number}. {x.title}" for x in slides)
    words = LENGTHS.get(length, 140)
    user = (f"Deck outline:\n{outline}\n\nAudience: {audience}\nTone: {TONES.get(tone, tone)}\n"
            f"Target length: about {words} words.\nThis is slide {s.number} of {len(slides)}. "
            f"Previous slide: {prev_t}. Next slide: {next_t}.\n\nSLIDE CONTENT (visible to audience):\n{_slide_block(s)}\n")
    if notes_mode == "rewrite" and s.notes.strip():
        user += f"\nSPEAKER NOTES (presenter's intent, rephrase naturally):\n{s.notes.strip()}\n"
    msgs = [{"role": "system", "content": SYSTEM_SCRIPT.replace("{language}", language)}, {"role": "user", "content": user}]
    slide_text = s.full_text().replace(s.title, "", 1)   # restating the title is fine; reading the body is not
    t0 = time.time()
    best, best_o, attempts = None, None, 0
    for attempt in range(retries + 1):
        attempts += 1
        txt = _clean_script(chat(cfg, msgs, temperature=0.7 + 0.1 * attempt, max_tokens=int(words * 3.5) + 200))
        o = overlap(txt, slide_text) if same_language_as_deck else {"copy_ratio": None, "longest_run": None,
                                                                     "script_words": len(txt.split())}
        if best is None or (same_language_as_deck and o["copy_ratio"] < best_o["copy_ratio"]):
            best, best_o = txt, o
        if not same_language_as_deck or not too_verbatim(o, max_ratio, max_run):
            break
        msgs = msgs + [{"role": "assistant", "content": txt},
                       {"role": "user", "content": (
                           f"Too close to the slide text: {o['copy_ratio']:.0%} of your 4-word phrases are copied verbatim and "
                           f"the longest copied run is {o['longest_run']} words. Rewrite it as an explanation in your own words: "
                           "talk about what it means and why it matters, without repeating the slide's phrasing.")}]
    return {"script": best, "overlap": best_o, "attempts": attempts, "regenerated": attempts > 1,
            "ms": int((time.time() - t0) * 1000)}


def _clean_script(t: str) -> str:
    t = re.sub(r"^\s*(?:script|talk track|narration)\s*:\s*", "", t, flags=re.I)
    t = re.sub(r"\*\*|__|#+\s", "", t)
    t = re.sub(r"^\s*[-*•]\s+", "", t, flags=re.M)
    t = re.sub(r"\[(?:pause|beat|smile)[^\]]*\]|\((?:pause|beat)[^)]*\)", "", t, flags=re.I)
    return t.strip().strip('"').strip()


# ------------------------------------------------------------------ translation
_FREE_DOWN_UNTIL = 0.0

def translate(text: str, target_lang_name: str, target_iso: str, cfg: Optional[LLMConfig] = None,
              target_locale: str = "") -> Dict:
    """LLM translation if configured, else free deep-translator (Google, then MyMemory). Raises if all fail."""
    if not text.strip():
        return {"text": text, "engine": "none"}
    if ai_ok(cfg):
      try:
        out = chat(cfg, [{"role": "system", "content": f"Translate the user's presentation script into natural, spoken {target_lang_name}. "
                                                        "Keep it conversational, keep names and numbers accurate. Output only the translation."},
                         {"role": "user", "content": text}], temperature=0.3, max_tokens=1500)
        return {"text": _clean_script(out), "engine": f"LLM ({cfg.model})"}
      except AIUnavailable:
        pass   # fall back to free translation below
    # disk cache: same text + target -> reuse (saves free-API quota; survives reruns of the same deck)
    import json as _json
    from pathlib import Path as _P
    _cf = _P(__file__).resolve().parent.parent / "data" / "translation_cache.json"
    _key = target_iso + "|" + hashlib.sha1(text.encode()).hexdigest()
    try:
        _cache = _json.loads(_cf.read_text()) if _cf.exists() else {}
    except Exception:
        _cache = {}
    if _key in _cache:
        return {"text": _cache[_key], "engine": "cached translation"}

    def _save(res):
        try:
            _cache[_key] = res["text"]; _cf.parent.mkdir(parents=True, exist_ok=True)
            _cf.write_text(_json.dumps(_cache, ensure_ascii=False))
        except Exception:
            pass
        return res
    global _FREE_DOWN_UNTIL
    if time.time() < _FREE_DOWN_UNTIL:
        raise RuntimeError("Free translation was unreachable a moment ago (skipping for 10 min). "
                           "Add an LLM key (Gemini free tier) for translation.")
    errs = []

    def google():
        from deep_translator import GoogleTranslator
        code = {"zh": "zh-CN", "he": "iw"}.get(target_iso, target_iso)
        out = [GoogleTranslator(source="auto", target=code).translate(p) if p.strip() else "" for p in text.split("\n")]
        return {"text": "\n".join(x or "" for x in out), "engine": "Google Translate (free, deep-translator)"}

    def mymemory():
        # direct MyMemory REST API (free, no key); split into <450-char chunks so long scripts aren't cut off
        import re
        import requests
        tgt = {"zh": "zh-CN", "he": "he-IL"}.get(target_iso, target_iso)
        out_paras = []
        for para in text.split("\n"):
            if not para.strip():
                out_paras.append(""); continue
            chunks, cur = [], ""
            for sent in re.split(r"(?<=[.!?])\s+", para):
                if len(cur) + len(sent) + 1 > 450 and cur:
                    chunks.append(cur); cur = sent
                else:
                    cur = (cur + " " + sent).strip()
            if cur:
                chunks.append(cur)
            done = []
            for c in chunks:
                r = requests.get("https://api.mymemory.translated.net/get",
                                 params={"q": c[:480], "langpair": f"en|{tgt}"}, timeout=10)
                r.raise_for_status()
                j = r.json()
                if str(j.get("responseStatus")) != "200":
                    raise RuntimeError(j.get("responseDetails", "MyMemory error"))
                done.append(j["responseData"]["translatedText"])
            out_paras.append(" ".join(done))
        return {"text": "\n".join(out_paras), "engine": "MyMemory (free)"}

    for name, fn in (("Google", google), ("MyMemory", mymemory)):
        ok, val = _run_with_timeout(fn, 40)
        if ok:
            return _save(val)
        errs.append(f"{name}: {val}")
    _FREE_DOWN_UNTIL = time.time() + 600
    raise RuntimeError("Free translation unavailable (" + "; ".join(errs) + "). Add an LLM key (Gemini free tier) for translation.")


def _run_with_timeout(fn, seconds: float):
    """Run fn in a daemon thread (free translators have no timeout option and can hang)."""
    import queue
    import threading
    q: "queue.Queue" = queue.Queue()

    def wrap():
        try:
            q.put((True, fn()))
        except Exception as e:  # noqa
            q.put((False, type(e).__name__))
    threading.Thread(target=wrap, daemon=True).start()
    try:
        return q.get(timeout=seconds)
    except queue.Empty:
        return False, "timeout"


# ------------------------------------------------------------------ Q&A
_QSTOP = set("""the a an is are was be by of to in on for and or what which who whom how why when where do does did you your
we our us it its this that there their they can could would should will much many more most about tell me please explain
give show any some with from at as than have has had need slide deck""".split())
_SYN = {"leader": ["share", "largest", "leads"], "leading": ["share"], "biggest": ["share", "largest", "size"],
        "big": ["size", "market"], "size": ["market", "usd"], "money": ["usd", "ask", "invest", "budget"],
        "cost": ["usd", "capex", "ask"], "invest": ["usd", "ask"], "investment": ["usd", "ask"], "budget": ["usd", "ask"],
        "growth": ["cagr", "growing"], "grow": ["cagr", "growing"], "competitors": ["competitive", "share", "player"],
        "competition": ["competitive", "player"], "plan": ["phase", "market"], "timeline": ["phase", "fy26", "fy27", "fy28"],
        "profit": ["break", "even"], "lead": ["share", "player", "competitive"], "leads": ["share", "player", "competitive"],
        "ask": ["ask", "usd", "approve", "decision"], "asking": ["ask", "usd", "approve"], "need": ["ask", "usd"], "breakeven": ["break", "even"], "risk": ["gap", "weak"]}


def _tok(s: str, query: bool = False) -> List[str]:
    s = re.sub(r"(\d)([a-zA-Z])", r"\1 \2", s.lower())
    toks = [t for t in re.findall(r"\w+", s) if len(t) > 1]
    if query:
        toks = [t for t in toks if t not in _QSTOP]
        toks += [x for t in list(toks) for x in _SYN.get(t, [])]
    return [_stem(t) for t in toks]


def _stem(t: str) -> str:
    for suf in ("ing", "ers", "er", "es", "ed", "s"):
        if len(t) > len(suf) + 3 and t.endswith(suf):
            return t[: -len(suf)]
    return t


def rank_slides(slides: List[Slide], query: str, current: int, boost: float = 0.6) -> List[tuple]:
    docs = [_tok(s.full_text(with_notes=True)) for s in slides]
    N = len(docs); avg = sum(map(len, docs)) / max(1, N)
    df = Counter(t for d in docs for t in set(d))
    q = _tok(query, query=True)
    scores = []
    for i, d in enumerate(docs):
        tf = Counter(d); sc = 0.0
        for t in q:
            if t in tf:
                idf = math.log(1 + (N - df[t] + 0.5) / (df[t] + 0.5))
                sc += idf * tf[t] * 2.2 / (tf[t] + 1.2 * (0.25 + 0.75 * len(d) / max(1, avg)))
        if i == current:
            sc += boost
        scores.append((sc, i))
    return sorted(scores, reverse=True)


SYSTEM_QA = """You are a live co-presenter answering an audience question about the deck that is being presented.
Use ONLY the slide content provided. The CURRENT slide is on screen: prioritise it when relevant.
Answer in {language}, in 2-4 spoken sentences (it will be read aloud): natural, direct, no markdown, no lists.
Cite slide numbers in the answer like [Slide 3]. If the deck does not contain the answer, say so honestly and suggest what would answer it.
Return JSON: {"answer": "...", "slides": [numbers used], "jump_to": slide number worth showing or null}"""


def answer_question(cfg: Optional[LLMConfig], slides: List[Slide], question: str, current: int,
                    language: str = "English") -> Dict:
    t0 = time.time()
    ranked = rank_slides(slides, question, current)
    picked = sorted({current} | {i for sc, i in ranked[:3] if sc > 0})
    if not ai_ok(cfg):
        return keyword_answer(slides, question, current, ranked, t0, picked)
    ctx = "\n\n".join(f"[Slide {slides[i].number}{' - CURRENT' if i == current else ''}]\n{slides[i].full_text(with_notes=True)}" for i in picked)
    outline = "\n".join(f"{s.number}. {s.title}" for s in slides)
    try:
        raw = chat(cfg, [{"role": "system", "content": SYSTEM_QA.replace("{language}", language)},
                     {"role": "user", "content": f"Deck outline:\n{outline}\n\nRelevant slides:\n{ctx}\n\nQuestion: {question}"}],
               temperature=0.3, max_tokens=500, json_mode=True)
    except AIUnavailable:
        return keyword_answer(slides, question, current, ranked, t0, picked)
    data = _parse_json(raw)
    ans = data.get("answer") or raw
    cited = [int(x) for x in data.get("slides", []) if str(x).isdigit()] or [int(n) for n in re.findall(r"Slide (\d+)", ans)]
    jump = data.get("jump_to")
    try:
        jump = int(jump) if jump not in (None, "", "null") else None
    except (TypeError, ValueError):
        jump = None
    if jump and not (1 <= jump <= len(slides)):
        jump = None
    return {"answer": ans, "slides": cited, "jump_to": jump, "ms": int((time.time() - t0) * 1000),
            "engine": cfg.model, "context_slides": [slides[i].number for i in picked]}


def keyword_answer(slides: List[Slide], question: str, current: int, ranked=None, t0=None, picked=None) -> Dict:
    """Free Q&A: find the best-matching slides by keywords and answer with their most relevant sentences."""
    t0 = t0 or time.time()
    ranked = ranked or rank_slides(slides, question, current)
    picked = picked or [current]
    qset = set(_stem(w) for w in _tok(question, query=True)) or set(_tok(question))
    cands = []
    for sc, i in ranked[:3]:
        s = slides[i]
        text = s.full_text(with_notes=True)
        for t in s.tables:   # make table rows readable as sentences
            text += "\n" + "\n".join(", ".join(c for c in r if c) for r in t[1:])
        for sent in re.split(r"(?<=[.!?])\s+|\n", text):
            sent = sent.strip()
            if len(sent) < 4:
                continue
            hits = len(qset & set(_stem(w) for w in _tok(sent)))
            cands.append((hits + (0.3 if re.search(r"\d", sent) else 0) + 0.2 * sc, s.number, sent))
    cands.sort(key=lambda x: -x[0])
    good, seen = [], set()
    for c in cands:
        k = re.sub(r"\W+", " ", c[2].lower()).strip()
        if c[0] < 1 or k in seen:
            continue
        seen.add(k); good.append(c)
        if len(good) == 3:
            break
    if not good:
        s = slides[ranked[0][1]] if ranked else slides[current]
        ans = (f"I don't see a direct answer to that in the deck. The closest part is slide {s.number}, {s.title}.")
        nums = [s.number]
    else:
        nums = sorted({c[1] for c in good})
        lead = good[0][1]
        body = " ".join(c[2].replace(" | ", ", ").rstrip(".") + "." for c in good
                        if c[2].strip().lower() != slides[c[1] - 1].title.strip().lower()) or good[0][2]
        ans = f"Based on slide {lead}, {slides[lead - 1].title.rstrip('.')}: {body}" + (
            f" See also slide {', '.join(str(n) for n in nums if n != lead)}." if len(nums) > 1 else "")
    jump = nums[0] if nums and nums[0] - 1 != current else None
    return {"answer": ans, "slides": nums, "jump_to": jump, "ms": int((time.time() - t0) * 1000),
            "engine": "built-in (keyword search)", "context_slides": [slides[i].number for i in picked]}


def _parse_json(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {}
