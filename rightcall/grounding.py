"""Groundedness guard v3.

Same contract as ClearAnswer's v2 — each citation names a chunk_id and the
quote must exist verbatim (normalized, fuzzy >= 0.85) in THAT chunk — plus one
stricter rule for the agentic setting: the cited chunk must actually have been
retrieved through a logged lookup_rules call in this review. A citation to a
chunk the agent never looked up is unverified by definition, even if the quote
happens to match. Pure Python, runs in every mode.
"""

from __future__ import annotations

import difflib
import re

from .corpus import Chunk
from .models import GroundednessReport, ReviewResult

FUZZY = 0.85


def _norm(t: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", re.sub(r"\s+", " ", t.lower())).strip()


def _in_chunk(quote: str, chunk_text: str) -> bool:
    q, h = _norm(quote), _norm(chunk_text)
    if not q:
        return False
    if q in h:
        return True
    hw, qw = h.split(), q.split()
    win = len(qw)
    for i in range(0, max(1, len(hw) - win + 1)):
        if difflib.SequenceMatcher(None, q, " ".join(hw[i:i + win])).ratio() >= FUZZY:
            return True
    return False


def apply_guard(result: ReviewResult, index: dict[str, Chunk]) -> ReviewResult:
    retrieved_ids = {r.chunk_id for r in result.retrieval}
    total = ok = 0
    bad: list[str] = []
    for cit in result.citations:
        total += 1
        chunk = index.get(cit.chunk_id)
        if not chunk:
            cit.verified = False
            bad.append(f"[{cit.chunk_id}] (unknown chunk) “{cit.quote}”")
            continue
        if retrieved_ids and cit.chunk_id not in retrieved_ids:
            cit.verified = False
            bad.append(f"[{cit.chunk_id}] (cited but never retrieved via lookup_rules) "
                       f"“{cit.quote}”")
            continue
        cit.verified = _in_chunk(cit.quote, f"{chunk.title}. {chunk.text}")
        if cit.verified:
            ok += 1
        else:
            bad.append(f"[{cit.chunk_id}] (quote not found in cited chunk) “{cit.quote}”")
    result.groundedness = GroundednessReport(total_quotes=total, verified_quotes=ok,
                                             unverified=bad)
    if total and ok / total < 0.8 and not result.escalate:
        result.escalate = True
        result.escalate_reason = (
            "Groundedness below threshold — too many memo statements could not be "
            "verified against the retrieved sources. Route to a human reviewer.")
    return result
