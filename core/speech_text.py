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
    t = pronounce(t, iso).replace("|", ", ")
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


# ---------------------------------------------------------------- pronunciation
# Spoken-only fixes (never applied to on-screen text). Neural voices blend "R&D" / "R and D" into
# words like "Randy", so ampersand acronyms are spelled out as separate letters, and a small list of
# business acronyms is spaced into letters. Applied to every engine, every language, after translation.
AMP_WORD = {"en": "and"}
SPELL = ["B2B", "B2C", "B2G", "D2C", "C2C", "P2P", "G2C", "CEO", "CFO", "CTO", "COO", "CIO", "CISO", "CHRO", "CMO",
         "ESG", "LSHC", "TMT", "GPS", "FS", "HR", "IT", "SME", "SMEs", "MSME", "ROE", "ROCE", "NPA", "NPAs", "NIM",
         "ARR", "MRR", "ARPU", "CAC", "LTV", "NPS", "SLA", "SLAs", "API", "APIs", "IoT", "UAV", "UAVs", "EV", "EVs",
         "GDP", "FDI", "IPO", "PE", "VC", "OEM", "OEMs", "B2B2C", "GCC", "GCCs", "BFSI", "FMCG", "CPG", "QSR", "PLI",
         "SKU", "SKUs", "KYC", "AML", "UPI", "NBFC", "NBFCs", "ICU", "OPD", "EHR", "PPP", "KPI", "KPIs", "ROI",
         "CAGR", "YTD", "AI", "ML", "MRI", "CT"]
_NUM_WORD = {"2": "to", "4": "for"}


def _letters(tok: str) -> str:
    """'ER' -> 'E R', 'SMEs' -> 'S M Es', 'B2B' -> 'B to B'."""
    out, plural = [], tok.endswith("s") and tok[:-1].isupper() and len(tok) > 2
    core = tok[:-1] if plural else tok
    for ch in core:
        out.append(_NUM_WORD.get(ch, ch) if ch.isdigit() else ch.upper())
    s = " ".join(out)
    return s + "s" if plural else s


_AMP_RE = re.compile(r"(?<![A-Za-z0-9])([A-Z]{1,4})\s*&\s*([A-Z]{1,4})(?![A-Za-z0-9])")
_SPELL_RE = re.compile(r"(?<![A-Za-z0-9&-])(" + "|".join(sorted(map(re.escape, SPELL), key=len, reverse=True)) + r")(?![A-Za-z0-9&-])")


def pronounce(text: str, iso: str = "en") -> str:
    """Spoken-form normaliser for TTS input. Expands ampersand acronyms (R&D -> 'R and D',
    ER&I -> 'E R and I'), spells common business acronyms as letters, decodes HTML entities such as
    '&amp;', and never leaves a glued 'X&Y' token for an engine to misread (edge-tts and Azure
    XML-escape whatever '&' remains)."""
    import html as _h
    t = _h.unescape(text or "")
    amp = AMP_WORD.get(iso, "and")
    t = _AMP_RE.sub(lambda m: f"{_letters(m.group(1))} {amp} {_letters(m.group(2))}", t)
    t = _SPELL_RE.sub(lambda m: _letters(m.group(1)), t)
    # leftover '&' between words: English 'and'; other languages a spaced '&' that the voice reads
    # natively (edge-tts and Azure XML-escape it, see core/tts.py), never a bare 'X&Y' token
    t = re.sub(r"\s*&\s*", " and " if iso == "en" else " & ", t)
    t = t.replace("<", " ").replace(">", " ")
    return re.sub(r"[ \t]+", " ", t).strip()
