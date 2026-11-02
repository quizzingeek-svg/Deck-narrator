"""No-API-key narration. Without an LLM the bot cannot truly *explain* a slide, so it:
1) uses the presenter's own speaker notes when present (they are already spoken language), or
2) builds a templated walkthrough that does NOT read raw bullets: theme keywords, computed chart/table
   insights, the key numbers with minimal context, and a transition to the next slide."""
from __future__ import annotations

import re
from collections import Counter
from typing import List, Optional

from .deck import Slide
from .insights import slide_facts

STOP = set("""a an the and or of to in on for with by at from as is are was were be been it its this that these those
our we you your their they them over under vs per into than more most less not no only up down out new via within
across about after before can will would should could may might has have had do does did using use used like
q1 q2 q3 q4 fy million billion thousand crore lakh phase""".split())


def _keywords(text: str, k: int = 3) -> List[str]:
    words = [w.strip("-") for w in re.findall(r"[A-Za-z][A-Za-z\-]{3,}", text)]
    words = [w for w in words if len(w) > 3 and w.lower() not in STOP]
    cnt = Counter(w.lower() for w in words)
    caps = {w.lower(): w for w in words}
    return [caps[w] if caps[w].isupper() else w for w, _ in cnt.most_common(k)]


def _numbers(text: str, k: int = 3) -> List[str]:
    found = re.findall(r"(?<![A-Za-z\-/])(?:USD|INR|EUR|\$|₹|€|£)?\s?~?\d[\d,.]*\s?(?:%|M|B|bn|mn|Cr|K|million|billion|crore)?\+?", text)
    found = [f.strip() for f in found if re.search(r"\d", f) and len(f.strip()) > 1]
    seen = []
    for f in found:
        if f not in seen and not re.fullmatch(r"(19|20)\d\d", f):
            seen.append(f)
    return seen[:k]


def opener(i: int, total: int, title: str) -> str:
    t = title.rstrip(".:")
    if i == 0:
        return f"Let's begin. {t}."
    if i == total - 1:
        return f"Which brings us to the final slide: {t}."
    return ["Now let's turn to {t}.", "Moving on, {t}.", "Next, {t}.", "Here's where it gets interesting: {t}."][i % 4].format(t=t)


def transition(nxt: Optional[Slide]) -> str:
    if nxt is None:
        return "That's the full picture. Happy to take questions."
    return f"With that in mind, let's look at {nxt.title.rstrip('.:')}."


def basic_script(slides: List[Slide], i: int, use_notes: bool = True, notes_exact: bool = False) -> str:
    """Keyless narration via the rule-based narrative engine (core.narrate).
    Notes are paraphrased and used as guidance; read verbatim only when notes_exact=True."""
    from .narrate import narrate
    mode = "exact" if (use_notes and notes_exact) else ("guide" if use_notes else "ignore")
    return narrate(slides, i, notes_mode=mode)


def legacy_basic_script(slides: List[Slide], i: int, use_notes: bool = True) -> str:
    s = slides[i]
    nxt = slides[i + 1] if i + 1 < len(slides) else None
    if use_notes and s.notes.strip():
        return s.notes.strip()
    parts = [opener(i, len(slides), s.title or f"slide {s.number}")]
    body = s.body_text()
    if s.bullets:
        kws = _keywords(body)
        if len(s.bullets) > 1 and kws:
            parts.append(f"There are {len(s.bullets)} points here, and the common thread runs through "
                         + (", ".join(kws[:-1]) + " and " + kws[-1] if len(kws) > 1 else kws[0]) + ".")
        nums = _numbers(body)
        if len(nums) >= 2:
            parts.append("The numbers worth holding on to are " + ", ".join(nums[:-1]) + (" and " if len(nums) > 1 else "") + nums[-1] + ".")
    facts = slide_facts(s)
    if facts:
        parts += facts[:4]
    if s.bullets or s.tables:
        parts.append("Take a moment with the detail on screen.")
    parts.append(transition(nxt))
    return "\n\n".join(parts)
