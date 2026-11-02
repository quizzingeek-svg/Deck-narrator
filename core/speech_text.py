"""Make text sound spoken, not read: strip bullets/markdown/URLs/symbols, expand common business
abbreviations, currency and numbers (English), and split into sentence/paragraph chunks for pacing."""
from __future__ import annotations

import re
from typing import List

ABBREV_EN = {
    r"\bYoY\b": "year on year", r"\bQoQ\b": "quarter on quarter", r"\bMoM\b": "month on month",
    r"\bCAGR\b": "C-A-G-R", r"\bKPIs?\b": "K-P-Is", r"\bROI\b": "R-O-I", r"\bGTM\b": "go-to-market",
    r"\bTAM\b": "total addressable market", r"\bSAM\b": "serviceable market", r"\bSOM\b": "obtainable market",
    r"\be\.g\.": "for example", r"\bi\.e\.": "that is", r"\betc\.": "and so on", r"\bvs\.?\b": "versus",
    r"\bapprox\.?\b": "approximately", r"\bw/o\b": "without", r"\bw/\b": "with", r"\bYTD\b": "year to date",
    r"\bFY\s?(\d{2,4})\b": r"F-Y \1",
    r"\bkm\b": "kilometres", r"\bcapex\b": "capex", r"\bavg\.?\b": "average", r"\bno\.\s?(\d)": r"number \1",
    r"\bMRI\b": "M-R-I", r"\bCT\b": "C-T", r"\bAI\b": "A-I",
}
CURRENCY = {"$": "dollars", "USD": "dollars", "US$": "dollars", "€": "euros", "EUR": "euros", "£": "pounds",
            "GBP": "pounds", "₹": "rupees", "INR": "rupees", "Rs.": "rupees", "Rs": "rupees", "¥": "yen",
            "JPY": "yen", "AED": "dirhams", "SAR": "riyals", "SGD": "Singapore dollars"}
SCALE = {"k": "thousand", "K": "thousand", "m": "million", "M": "million", "mn": "million", "Mn": "million",
         "b": "billion", "B": "billion", "bn": "billion", "Bn": "billion", "T": "trillion", "tn": "trillion",
         "Cr": "crore", "cr": "crore", "crore": "crore", "L": "lakh", "lakh": "lakh", "million": "million",
         "billion": "billion", "trillion": "trillion", "thousand": "thousand"}

_cur_pat = "|".join(re.escape(c) for c in sorted(CURRENCY, key=len, reverse=True))
_scale_pat = "|".join(sorted(SCALE, key=len, reverse=True))
MONEY_RE = re.compile(rf"(?<![A-Za-z])({_cur_pat})\s?(\d[\d,]*(?:\.\d+)?)\s?({_scale_pat})?(?![A-Za-z])")


def _money(m):
    cur, num, sc = m.group(1), m.group(2), m.group(3)
    return f"{num}{' ' + SCALE[sc] if sc else ''} {CURRENCY[cur]}"


def speakable(text: str, iso: str = "en") -> str:
    """Return text suitable for TTS in the given language."""
    t = text or ""
    t = re.sub(r"https?://\S+|www\.\S+", "the link on the slide", t)
    t = re.sub(r"\S+@\S+\.\w+", "the email on the slide", t)
    t = re.sub(r"\[(?:slide|Slide|S)\s*\d+(?:\s*[,–-]\s*\d+)*\]", "", t)       # citation tags
    t = re.sub(r"\*\*|__|`|#+\s", "", t)                                        # markdown
    t = re.sub(r"^\s*(?:[-*•▪◦●■►➢✓✔→]|\d+[.)])\s+", "", t, flags=re.M)         # bullet markers
    t = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", t)                   # emoji
    t = t.replace("&", " and " if iso == "en" else " & ").replace("|", ", ")
    t = re.sub(r"\s*[→⇒]\s*", ", then ", t) if iso == "en" else t
    if iso == "en":
        t = MONEY_RE.sub(_money, t)
        t = re.sub(r"(\d)\s?(bn|Bn|mn|Mn|B|M|K|Cr)\b", lambda m: f"{m.group(1)} {SCALE[m.group(2)]}", t)
        t = re.sub(r"~\s?(?=\d)", "about ", t)
        t = re.sub(r"(\d)\s?%", r"\1 percent", t)
        t = re.sub(r"(\d|thousand|million|billion|trillion|crore|lakh)\+", r"\1-plus", t)
        t = re.sub(r"\b(\d{1,2})/(\d)\b(?!\d)", r"\1 and \2", t)                # Tier-2/3
        for pat, rep in ABBREV_EN.items():
            t = re.sub(pat, rep, t)
        t = t.replace("=", " is ").replace(" x ", " times ")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\s+([,.;:!?])", r"\1", t)
    return t.strip()


_SENT_RE = re.compile(r"(?<=[.!?।۔。！？])\s+|(?<=[。！？])")


def chunks_for_pacing(text: str, max_chars: int = 260) -> List[List[str]]:
    """Paragraphs -> list of sentence groups. Pauses go between groups (short) and paragraphs (long)."""
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n", text or "") if p.strip()]
    out = []
    for p in paras:
        sents = [s.strip() for s in _SENT_RE.split(p) if s.strip()]
        groups, cur = [], ""
        for s in sents:
            if cur and len(cur) + len(s) > max_chars:
                groups.append(cur); cur = s
            else:
                cur = (cur + " " + s).strip()
        if cur:
            groups.append(cur)
        out.append(groups)
    return out
