"""Compute plain-language facts from charts and tables so narration can interpret numbers
(trends, comparisons) instead of reading cells. Used by the LLM prompt and by the no-key fallback."""
from __future__ import annotations

import re
from typing import List, Optional

from .deck import Slide


def _num(s: str) -> Optional[float]:
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", str(s))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _fmt(v: float) -> str:
    return f"{v:,.0f}" if abs(v) >= 100 else f"{v:,.1f}".rstrip("0").rstrip(".")


def chart_facts(c: dict) -> List[str]:
    out = []
    cats = c.get("categories", [])
    name = c.get("title") or "the chart"
    for s in c.get("series", []):
        vals = [(cats[i] if i < len(cats) else str(i + 1), v) for i, v in enumerate(s["values"]) if v is not None]
        if len(vals) < 2:
            continue
        (c0, v0), (c1, v1) = vals[0], vals[-1]
        if v0:
            ch = (v1 - v0) / abs(v0) * 100
            direction = "rises" if v1 > v0 else "falls"
            out.append(f"In {name}, {s['name']} {direction} from {_fmt(v0)} in {c0} to {_fmt(v1)} in {c1}, "
                       f"a change of {ch:+.0f}% overall.")
            y0, y1 = _num(c0), _num(c1)
            if y0 and y1 and 1900 < y0 < y1 < 2200 and v0 > 0 and v1 > 0:
                cagr = ((v1 / v0) ** (1 / (y1 - y0)) - 1) * 100
                out.append(f"That is roughly {cagr:.1f}% growth a year between {c0} and {c1}.")
        hi = max(vals, key=lambda x: x[1]); lo = min(vals, key=lambda x: x[1])
        if hi != vals[-1] or lo != vals[0]:
            out.append(f"The peak is {_fmt(hi[1])} in {hi[0]} and the low point is {_fmt(lo[1])} in {lo[0]}.")
        jumps = [(vals[i][0], vals[i + 1][0], vals[i + 1][1] - vals[i][1]) for i in range(len(vals) - 1)]
        big = max(jumps, key=lambda j: abs(j[2]))
        out.append(f"The biggest single step is between {big[0]} and {big[1]} ({big[2]:+,.0f}).")
    return out


def table_facts(t: List[List[str]]) -> List[str]:
    if len(t) < 3:
        return []
    head, rows = t[0], t[1:]
    out = [f"The table compares {len(rows)} rows across {', '.join(h for h in head[1:] if h)}."]
    for ci in range(1, len(head)):
        nums = [(r[0], _num(r[ci])) for r in rows if ci < len(r)]
        nums = [(k, v) for k, v in nums if v is not None]
        if len(nums) >= max(2, int(0.6 * len(rows))):
            srt = sorted(nums, key=lambda x: -x[1])
            unit = "%" if any("%" in r[ci] for r in rows if ci < len(r)) else ""
            lead, second = srt[0], srt[1]
            out.append(f"On {head[ci]}, {lead[0]} leads with {_fmt(lead[1])}{unit}, ahead of {second[0]} at "
                       f"{_fmt(second[1])}{unit}; {srt[-1][0]} is lowest at {_fmt(srt[-1][1])}{unit}.")
            if unit == "%" and len(srt) >= 3:
                top3 = sum(v for _, v in srt[:3])
                out.append(f"The top three together account for about {_fmt(top3)}% on {head[ci]}.")
    return out


def slide_facts(s: Slide) -> List[str]:
    f = []
    for c in s.charts:
        f += chart_facts(c)
    for t in s.tables:
        f += table_facts(t)
    return f
