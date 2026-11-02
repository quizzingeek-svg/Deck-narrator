"""Verbatim-overlap check: how much of a script is just the slide text read out."""
from __future__ import annotations

import re
from typing import Dict, List


def _words(s: str) -> List[str]:
    return re.findall(r"\w+", (s or "").lower())


def _ngrams(ws: List[str], n: int):
    return [tuple(ws[i:i + n]) for i in range(len(ws) - n + 1)]


def overlap(script: str, slide_text: str, n: int = 4) -> Dict[str, float]:
    """copy_ratio: share of the script's word n-grams that appear verbatim on the slide.
    longest_run: longest run of consecutive slide words reproduced in the script."""
    sw, tw = _words(script), _words(slide_text)
    if len(sw) < n or len(tw) < n:
        return {"copy_ratio": 0.0, "longest_run": 0, "script_words": len(sw)}
    slide_ng = set(_ngrams(tw, n))
    sg = _ngrams(sw, n)
    copied = sum(1 for g in sg if g in slide_ng)
    # longest common substring over words (DP, small inputs)
    best = 0
    prev = [0] * (len(tw) + 1)
    for a in sw:
        cur = [0] * (len(tw) + 1)
        for j, b in enumerate(tw, 1):
            if a == b:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return {"copy_ratio": round(copied / max(1, len(sg)), 3), "longest_run": best, "script_words": len(sw)}


def too_verbatim(o: Dict[str, float], max_ratio: float = 0.15, max_run: int = 8) -> bool:
    return o["copy_ratio"] > max_ratio or o["longest_run"] >= max_run
