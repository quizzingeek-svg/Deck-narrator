"""Keyless narrative engine: presenter-style scripts from slide content with NO API key.

Pipeline per slide:
  classify slide type -> pick a varied opener -> paraphrase bullets / notes into connected sentences
  -> add computed chart/table insights (core.insights) -> a 'so what' takeaway -> a transition that
  names the next slide's topic -> anti-verbatim pass (no run of 6+ ordinary words copied from the
  slide or notes; names and figures are exempt).
Deterministic (seeded by deck + slide) so the same deck always gives the same script.
"""
from __future__ import annotations

import hashlib
import random
import re
from typing import List, Optional, Tuple

from .deck import Slide
from .insights import slide_facts

MAX_RUN = 5  # longest run of ordinary slide/notes words allowed in the script

# --------------------------------------------------------------------------- vocabulary
SYN = {
    "growing": ["expanding", "climbing"], "grow": ["expand", "climb"], "grows": ["expands", "climbs"],
    "growth": ["expansion", "momentum"], "increase": ["rise", "jump"], "increasing": ["rising", "climbing"],
    "decrease": ["drop", "decline"], "decreasing": ["falling", "shrinking"], "largest": ["biggest"],
    "large": ["big", "sizeable"], "small": ["modest", "limited"], "major": ["key", "big"],
    "key": ["central", "core"], "important": ["significant", "critical"], "significant": ["meaningful", "sizeable"],
    "expanding": ["moving", "pushing"], "covers": ["reaches", "spans"], "cover": ["reach", "span"],
    "covering": ["spanning", "reaching"], "pushing": ["driving", "lifting"], "lack": ["are without", "go without"],
    "need": ["require"], "needed": ["required"], "provide": ["offer", "deliver"], "provides": ["offers", "delivers"],
    "build": ["create", "put together"], "building": ["creating", "developing"], "improve": ["lift", "strengthen"],
    "reduce": ["cut", "lower"], "reduces": ["cuts", "lowers"], "achieve": ["reach", "hit"], "target": ["aim for", "goal of"],
    "strategy": ["plan", "approach"], "strategic": ["long-term", "big-picture"], "approach": ["way in", "method"],
    "focus": ["emphasis", "priority"], "priority": ["focus", "top concern"], "priorities": ["focus areas"],
    "investment": ["spending", "capital"], "spending": ["outlay", "investment"], "expenditure": ["spending", "outlay"],
    "capacity": ["capability", "headroom"], "demand": ["need", "appetite"], "customers": ["clients", "buyers"],
    "partner": ["team up", "work"], "partners": ["allies", "collaborators"], "partnership": ["alliance", "tie-up"],
    "fastest": ["quickest"], "leading": ["top", "front-running"], "leads": ["is ahead", "tops the list"],
    "remains": ["is still", "stays"], "remain": ["stay", "are still"], "emerging": ["rising", "new"],
    "current": ["present", "today's"], "currently": ["right now", "today"], "overall": ["in total", "all told"],
    "approximately": ["about", "roughly"], "around": ["about", "roughly"], "including": ["such as", "like"],
    "across": ["throughout", "over"], "within": ["inside", "in"], 
    "assess": ["evaluate", "judge"], "assesses": ["evaluates", "looks at"], "assessment": ["review", "evaluation"],
    "analysis": ["review", "study"], "framework": ["structure", "lens"], "consistent": ["uniform", "steady"],
    "evolving": ["changing", "shifting"], "developments": ["changes", "shifts"], "development": ["progress", "build-out"],
    "modernization": ["upgrade", "renewal"], "industrial": ["manufacturing", "industry"], "requirements": ["needs"],
    "operational": ["field", "day-to-day"], "allocation": ["split", "distribution"], "procurement": ["purchasing", "buying"],
    "budget": ["funding", "spend"], "budgets": ["funding lines", "spend"], "trajectory": ["path", "direction"],
    "trajectories": ["paths", "directions"], "drivers": ["forces", "engines"], "driven": ["powered", "fuelled"],
    "plan": ["roadmap", "game plan"], "market": ["market"], "share": ["slice", "portion"], "decision": ["call", "choice"],
    "approve": ["sign off on", "green-light"], "guaranteed": ["locked-in", "assured"], "volume": ["throughput", "flow"],
    "network": ["web", "footprint"], "assisted": ["supported", "powered"], "bundles": ["packages", "kits"],
    "cities": ["towns", "urban centres"], "people": ["citizens", "individuals"], "new": ["fresh", "added"],
    "only": ["just", "merely"], "since": ["from"], "by": ["by"],
    "ensure": ["make sure", "guarantee"], "enable": ["allow", "unlock"], "support": ["back", "help"],
    "risk": ["exposure", "danger"], "risks": ["exposures", "threats"], "opportunity": ["opening", "prize"],
    "opportunities": ["openings", "prizes"], "challenges": ["hurdles", "obstacles"], "challenge": ["hurdle", "obstacle"],
    "global": ["worldwide", "international"], "world": ["globe"], "military": ["armed forces", "defence"],
    "defense": ["defence", "security"], "report": ["study", "paper"], "scope": ["remit", "coverage"],
    "show": ["reveal", "highlight"], "shows": ["reveals", "highlights"], "remaining": ["other", "outstanding"],
    "follow": ["come next", "arrive later"], "completed": ["finished", "done"], "draft": ["working version", "early cut"],
    "findings": ["conclusions", "insights"], "emerge": ["stand out", "come through"], "value": ["worth", "revenue"],
    "today": ["now", "at present"], "think": ["believe", "reckon"], "big": ["large", "sizeable"], "point": ["idea", "message"],
    "steady": ["stable", "consistent"], "piece": ["segment", "part"], "win": ["succeed", "come out ahead"], "want": ["would like"],
    "right": ["correct", "best"], "bet": ["move", "wager"], "prize": ["reward", "opportunity"], "phases": ["stages", "steps"],
    "add": ["layer in", "bring in"], "then": ["after that", "next"], "gap": ["shortfall", "hole"], "biggest": ["largest", "widest"],
    "model": ["setup", "structure"], "hospitals": ["hospital groups", "providers"], "clinics": ["practices", "clinics"],
    "should": ["ought to", "is set to"], "cross": ["pass", "top"], "away": ["home"],
    "walk": ["take", "guide"], "everyone": ["all", "everybody"], "together": ["combined", "jointly"], "every": ["each"],
    "make": ["create", "form"], "making": ["creating", "forming"], "help": ["assist", "support"], "high": ["elevated", "strong"],
    "low": ["weak", "limited"], "first": ["initial", "opening"], "second": ["next"], "next": ["following", "upcoming"],
    "level": ["tier", "degree"], "levels": ["tiers", "degrees"], "data": ["figures", "evidence"], "number": ["count", "figure"],
    "time": ["period", "stretch"], "year": ["twelve months"], "years": ["years"], "against": ["versus", "relative to"], "begin": ["start", "kick off"], "start": ["begin", "kick off"],
}
OPENERS = {
    "title": ["Good to have everyone here. Today's story is about {t}.", "Let's get started. The topic in front of us is {t}.",
              "Thanks for joining. Over the next few minutes we'll unpack {t}."],
    "agenda": ["Here's the road map for our time together.", "Before we dive in, a quick look at where we're headed.",
               "Let me lay out how this conversation will flow."],
    "data": ["Let's look at what the numbers are telling us on {t}.", "The data on {t} is worth a closer look.",
             "Here's where the evidence comes in: {t}."],
    "chart": ["This chart tells a clear story about {t}.", "Look at the shape of this chart on {t}.",
              "The picture here, {t}, is worth a moment."],
    "comparison": ["This one is a side-by-side: {t}.", "Let's weigh the options on {t}.", "Here we put things head to head: {t}."],
    "process": ["So how do we actually do it? {t}.", "Let me walk you through the sequence: {t}.", "Here's the step-by-step on {t}."],
    "quote": ["I want to pause on a line that captures this well.", "One voice sums it up nicely here."],
    "conclusion": ["Which brings us to the bottom line: {t}.", "Let's land this. {t}.", "So where does this leave us? {t}."],
    "content": ["Now let's turn to {t}.", "Next up, {t}.", "Shifting gears, let's talk about {t}.", "Here's the next piece: {t}.",
                "Building on that, {t}.", "This brings us to {t}."],
}
FIRST = ["The first thing to notice is that", "To start with,", "Most importantly,", "The headline here is that"]
MID = ["On top of that,", "Alongside this,", "Just as important,", "What's more,", "Equally,", "Beyond that,", "Meanwhile,"]
LAST = ["And finally,", "Rounding this out,", "Last but not least,", "To complete the picture,"]
SOWHAT = {
    "chart": ["The takeaway: the trend is clear, and it shapes how we should plan.", "So what? The direction matters more than any single bar.",
              "The bottom line is that this momentum is real and we should position for it."],
    "data": ["The message from this table is that the leaders are well ahead, and the gaps are where the openings are.",
             "So what does this mean? Where the field is crowded, we differentiate; where it's thin, we move first."],
    "comparison": ["The real question is which trade-off we're willing to make.", "So the choice comes down to what we value most."],
    "process": ["The point is that each step de-risks the next one.", "Sequencing it this way keeps risk low and learning high."],
    "agenda": ["Keep that structure in mind; each section builds on the last."],
    "conclusion": ["That's the decision in front of us.", "If we agree on this, we can move straight to action."],
    "content": ["Why does this matter? Because it changes how we prioritise {k}.", "The so-what: {k} is where we should focus our attention.",
                "Put simply, {k} is the lever that matters here.", "The implication is clear: we can't ignore {k}."],
}
TRANS = ["That sets us up for the next topic: {n}.", "With that in mind, let's move to {n}.", "Which leads naturally to {n}.",
         "Keep that in mind as we look at {n}.", "Next, we'll see how this connects to {n}."]
PHRASES = [(r"\bI want to\b", "I'd like to"), (r"\bwe think\b", "we believe"), (r"\bwalk you through\b", "take you through"),
           (r"\bhow big\b", "just how large"), (r"\bthe point to take away\b", "the key message"), (r"\bnot a bubble\b", "not a passing bubble"),
           (r"\bit will take\b", "it'll take"), (r"\bdon't need\b", "can skip"), (r"\bdo not\b", "don't"), (r"\bit is\b", "it's"),
           (r"\bwe are\b", "we're"), (r"\bthere is\b", "there's"), (r"\bin order to\b", "to"), (r"\bas well as\b", "plus"),
           (r"\bGood morning everyone\b", "Morning, all"), (r"\bwe go in\b", "we roll this out in")]
STOP = set("""a an the and or of to in on for with by at from as is are was were be been it its this that these those our we you
your their they them over under vs per into than more most less not no only up down out new via within across about after before
can will would should could may might has have had do does did using use used like s""".split())


# --------------------------------------------------------------------------- helpers
def _rng(*keys) -> random.Random:
    return random.Random(int(hashlib.md5("|".join(map(str, keys)).encode()).hexdigest()[:8], 16))


def _clean(b: str) -> str:
    b = " ".join(b.split()).strip(" -•·▪–")
    return b


def _usable(b: str) -> bool:
    letters = [c for c in b if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.7 and len(letters) > 6:
        return False   # ALL-CAPS headings / chart labels read badly as sentences
    if not b or b.upper() in ("WIP", "TBD", "DRAFT") or len(b) < 4:
        return False
    if re.fullmatch(r"[\d\W]+", b):   # lone numbers / symbols (e.g. markers "1", "2")
        return False
    return True


def _lc_title(t: str) -> str:
    t = t.rstrip(".:").strip()
    was_caps = t.split()[0].isupper() if t.split() else False
    t = " ".join(w.title() if w.isupper() and len(w) > 3 and not re.search(r"\d", w) else w for w in t.split())
    t = re.sub(r"\s*[|:]\s*", ", ", t)
    w0 = t.split()[0] if t.split() else ""
    if w0 and not (w0.isupper() or (len(w0) > 1 and w0[1].isupper()) or w0 in ("India", "US", "China", "Europe") or was_caps):
        t = t[:1].lower() + t[1:]
    return t


def classify(s: Slide, i: int, n: int) -> str:
    t = (s.title or "").lower()
    body = " ".join(s.bullets).lower()
    if re.search(r"\b(agenda|contents|outline|overview of the deck|what we'll cover)\b", t):
        return "agenda"
    if i == 0 or (len(s.bullets) <= 2 and not s.tables and not s.charts and i == 0):
        return "title"
    if re.search(r"\b(the ask|in summary|conclusions?|next steps|recommendation|takeaways?|bottom line|decision)\b", t) or (i == n - 1 and not s.charts):
        return "conclusion"
    if s.charts:
        return "chart"
    if s.tables:
        return "data"
    if any(q in body for q in ("“", "\"")) and len(s.bullets) <= 3:
        return "quote"
    if re.search(r"\b(vs\.?|versus|compared|comparison)\b", t):
        return "comparison"
    if sum(bool(re.match(r"(phase|step|stage)\s*\d|\d[.)]\s", b.lower())) for b in s.bullets) >= 2 or "→" in body:
        return "process"
    return "content"


def _rewrite(text: str, rng: random.Random) -> str:
    """Phrase-level paraphrase of one bullet or notes sentence."""
    t = _clean(text)
    t = re.sub(r"~\s?", "about ", t)
    t = re.sub(r"(\d[\d,.]*\s?(?:M|B|bn|mn|K|Cr|%)?)\+", r"more than \1", t)
    t = re.sub(r"\s=\s", " makes up ", t)
    t = re.sub(r"\s(?:vs\.?|versus)\s", " compared with ", t, flags=re.I)
    for a, b in PHRASES:
        t = re.sub(a, b, t, flags=re.I)
    t = t.replace("&", "and").replace("→", ", then").replace(" / ", " or ")
    t = re.sub(r"\s*\|\s*", "; ", t)
    # "Label: detail" -> "when it comes to label, detail"
    m = re.match(r"^([^:]{2,40}):\s*(.+)$", t)
    if m:
        lab, det = m.group(1).strip(), m.group(2).strip()
        lab_l = lab if re.match(r"[A-Z]{2,}|[A-Z][a-z]+\s[A-Z]", lab) else lab[:1].lower() + lab[1:]
        t = rng.choice(["when it comes to {l}, {d}", "on {l}, {d}", "for {l}, {d}"]).format(l=lab_l, d=det[:1].lower() + det[1:] if not re.match(r"[A-Z]{2}|[A-Z][a-z]+ [A-Z]", det) else det)
    # word-level synonyms (skip capitalised names and figures)
    out = []
    for w in re.findall(r"\w[\w'\-]*|[^\w\s]+|\s+", t):
        lw = w.lower()
        if lw in SYN and not (w[0].isupper() and out and not out[-1].strip() == "" and False) and rng.random() < 0.7:
            rep = rng.choice(SYN[lw])
            w = rep.capitalize() if w[0].isupper() and not w.isupper() else rep
        out.append(w)
    t = "".join(out).strip()
    return t.rstrip(".;,")


def _exempt(w: str) -> bool:
    return bool(re.search(r"\d", w)) or (w[:1].isupper() and len(w) > 1)


def _tokens(s: str) -> List[str]:
    return re.findall(r"[\w'\-]+", s)


def longest_run(script: str, source: str) -> Tuple[int, List[str]]:
    """Longest run of consecutive source words in the script, counting only ordinary words
    (names = capitalised, figures = digits do not count but do not break a run)."""
    sw = _tokens(script)
    src = [w.lower() for w in _tokens(source)]
    if not sw or not src:
        return 0, []
    best, best_seq = 0, []
    prev = [0] * (len(src) + 1)
    prevc = [0] * (len(src) + 1)
    for a in sw:
        cur = [0] * (len(src) + 1); curc = [0] * (len(src) + 1)
        for j, b in enumerate(src, 1):
            if a.lower() == b:
                cur[j] = prev[j - 1] + 1
                curc[j] = prevc[j - 1] + (0 if _exempt(a) else 1)
                if curc[j] > best:
                    best = curc[j]
        prev, prevc = cur, curc
    return best, best_seq


AUX = {"is", "are", "was", "were", "will", "should", "can", "could", "would", "must", "has", "have"}
INSERTS = ["really", "clearly", "in fact", "notably", "frankly", "importantly"]


def _worst_run(words: List[str], src: List[str]) -> Tuple[int, int, int]:
    """(ordinary-word count, start, end) of the longest copied run (names/figures don't count)."""
    best = (0, 0, 0)
    prev = [0] * (len(src) + 1); prevc = [0] * (len(src) + 1)
    for i, a in enumerate(words):
        cur = [0] * (len(src) + 1); curc = [0] * (len(src) + 1)
        al = a.lower()
        for j, b in enumerate(src, 1):
            if al == b:
                cur[j] = prev[j - 1] + 1
                curc[j] = prevc[j - 1] + (0 if _exempt(a) else 1)
                if curc[j] > best[0]:
                    best = (curc[j], i - cur[j] + 1, i)
        prev, prevc = cur, curc
    return best


def _break_runs(script: str, source: str, rng: random.Random, limit: int = MAX_RUN) -> str:
    """Rewrite until no run of more than `limit` ordinary source words remains."""
    src = [w.lower() for w in _tokens(source)]
    for _ in range(200):
        toks = re.findall(r"[\w'\-]+|[^\w'\-]+", script)
        idx = [k for k, t in enumerate(toks) if re.match(r"[\w'\-]", t)]
        words = [toks[k] for k in idx]
        c, a, b = _worst_run(words, src)
        if c <= limit:
            return script
        span = list(range(a, b + 1))
        mid = span[len(span) // 2:] + span[:len(span) // 2]
        done = False
        for wi in mid:
            w = words[wi]
            if w.lower() in SYN and not _exempt(w):
                opts = [o for o in SYN[w.lower()] if o.lower() != w.lower()]
                if opts:
                    toks[idx[wi]] = rng.choice(opts); done = True; break
        if not done:
            aux = [wi for wi in span[1:-1] if words[wi].lower() in AUX]
            if aux:   # "is" -> "is clearly"
                wi = aux[0]; toks[idx[wi]] = toks[idx[wi]] + " " + rng.choice(INSERTS)
            else:
                wi = span[len(span) // 2]
                toks[idx[wi]] = rng.choice(["—", ", really,", ", in short,"]) + " " + toks[idx[wi]] if False else ", and " + toks[idx[wi]] if words[wi].lower() in ("with", "so", "but") else rng.choice(INSERTS) + " " + toks[idx[wi]]
        script = "".join(toks)
    return script


def _join(parts: List[str]) -> str:
    out = []
    for p in parts:
        p = p.strip()
        if p:
            p = p[0].upper() + p[1:]
            out.append(p if p[-1] in ".!?" else p + ".")
    return " ".join(out)


def _keyphrase(s: Slide) -> str:
    t = (s.title or "").split(":")[0].split("|")[-1].strip().rstrip(".")
    words = [w for w in t.split() if w.lower() not in STOP]
    k = " ".join(words[:3]) or "this"
    return k if k.isupper() is False else k.title()


def _sentences(text: str) -> List[str]:
    return [x.strip() for x in re.split(r"(?<=[.!?])\s+|\n+", text) if x.strip()]


# --------------------------------------------------------------------------- main
def narrate(slides: List[Slide], i: int, notes_mode: str = "guide", deck_key: str = "") -> str:
    """notes_mode: 'exact' = read speaker notes verbatim (if present); 'guide' = paraphrase notes and blend with slide
    content; 'ignore' = slide content only."""
    s = slides[i]
    n = len(slides)
    nxt = slides[i + 1] if i + 1 < n else None
    if notes_mode == "exact" and s.notes.strip():
        return s.notes.strip()
    rng = _rng(deck_key or (slides[0].title if slides else ""), i, s.title)
    kind = classify(s, i, n)
    title = _lc_title(s.title or f"slide {s.number}")
    paras: List[str] = []

    # opener (avoid repeating the previous slide's opener family by rotating index)
    pool = OPENERS[kind]
    paras.append(pool[(i + rng.randrange(len(pool))) % len(pool)].format(t=title))

    bullets = [_clean(b) for b in s.bullets if _usable(_clean(b))]
    if s.charts or s.tables:   # drop short axis / legend labels that leak in as text boxes
        bullets = [b for b in bullets if len(b.split()) >= 5]
    notes = s.notes.strip() if notes_mode == "guide" else ""
    body: List[str] = []
    if kind == "title":
        if bullets:
            body.append(rng.choice(["This is framed as {b}", "We've set this up as {b}", "Think of this session as {b}"])
                        .format(b=_rewrite(bullets[0], rng)[:1].lower() + _rewrite(bullets[0], rng)[1:]))
        if notes:
            body += [_rewrite(x, rng) for x in _sentences(notes)[:4]]
        else:
            body.append("I'll keep it focused on what matters: where the opportunity is, how big it is, and what we should do next")
    elif kind == "agenda":
        items = bullets[:8]
        for t in s.tables:
            items += [r[0] if len(r) < 2 or not r[1].strip() else r[1] for r in t[1:9] if r and r[0].strip()]
        items = [_rewrite(x, rng) for x in items[:8] if _usable(x)]
        if items:
            body.append(f"We'll cover {len(items)} areas")
            body.append("We start with " + items[0] + (", move through " + ", ".join(items[1:-1]) if len(items) > 2 else "")
                        + (", and finish with " + items[-1] if len(items) > 1 else ""))
    else:
        src_sents = _sentences(notes) if notes else []
        lines = (src_sents[:5] if src_sents else []) + bullets[: (3 if src_sents else 6)]
        if kind == "quote" and bullets:
            body.append("In their words: " + bullets[0])
            lines = lines[1:]
        mids = rng.sample(MID, len(MID)) * 3
        for k, line in enumerate(lines):
            pm = re.match(r"(?i)^(phase|step|stage)\s*(\d+)\s*(?:\(([^)]*)\))?\s*[:\-–]\s*(.+)$", line) if kind == "process" else None
            r = (f"{pm.group(1).lower()} {pm.group(2)}" + (f", in {pm.group(3)}" if pm.group(3) else "") + ", "
                 + _rewrite(pm.group(4), rng)) if pm else _rewrite(line, rng)
            if len(r.split()) > 45:
                r = " ".join(r.split()[:40]) + ", and so on"
            con = FIRST[rng.randrange(len(FIRST))] if k == 0 else (LAST[rng.randrange(len(LAST))] if k == len(lines) - 1 and k > 1 else mids.pop(0))
            if kind == "process" and re.match(r"(?i)(phase|step|stage)\s*\d", line):
                ph = sum(1 for x in lines[:k] if re.match(r"(?i)(phase|step|stage)\s*\d", x))
                con = ["We kick off with", "From there, we move to", "Then comes", "After that,", "And finally,"][min(ph, 4)]
            r0 = r[:1].lower() + r[1:] if not re.match(r"[A-Z]{2}|[A-Z][a-z]+ [A-Z]|I\b", r) else r
            body.append(f"{con} {r0}")
        facts = slide_facts(s)
        if facts:
            body.append(rng.choice(["Reading the numbers,", "If we look closely at the data,", "Digging into the figures,"])
                        + " " + facts[0][:1].lower() + facts[0][1:])
            body += facts[1:4]
    paras.append(_join(body))

    # so what + transition
    sw = SOWHAT.get(kind, SOWHAT["content"]) if kind != "title" else []
    if sw:
        kp = _keyphrase(s)
        paras.append(rng.choice(sw).format(k=kp if (kp.split()[0].isupper() or kp.split()[0] in ("India", "US", "China")) else kp.lower()))
    if nxt is not None:
        paras.append(TRANS[(i + rng.randrange(len(TRANS))) % len(TRANS)].format(n=_lc_title(nxt.title or f"slide {nxt.number}")))
    else:
        paras.append(rng.choice(["That's the full picture. I'm happy to take your questions.", "Thank you. Let's open it up for questions."]))

    script = "\n\n".join(p for p in paras if p.strip())
    script = re.sub(r"([.?!]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), script)
    source = s.full_text() + "\n" + s.notes + ("\n" + nxt.title if nxt else "")
    return _break_runs(script, source, rng)
