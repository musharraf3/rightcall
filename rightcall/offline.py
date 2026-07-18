"""Offline demo mode: replays memos from REAL API runs (bundled in
examples/outputs/), so the demo needs no key — while the groundedness guard
and the policy layer still execute live in Python on your machine, every time.
The tool trace shown is the trace of the real run that produced the memo."""

from __future__ import annotations

import json
from pathlib import Path

from .corpus import chunk_index, load_corpus
from .grounding import apply_guard
from .models import ReviewResult
from .pipeline import apply_policy

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "examples" / "outputs"


def run_offline(request: dict, arm: str = "worker+skill") -> ReviewResult:
    path = OUTPUT_DIR / f"{request['request_id']}__{arm.replace('+', '_')}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"No cached output for {request['request_id']} / arm '{arm}'. "
            f"Set ANTHROPIC_API_KEY for live mode, or use a bundled example.")
    result = ReviewResult.from_dict(json.loads(path.read_text(encoding="utf-8")))
    result.mode = "offline-cache"
    result = apply_guard(result, chunk_index(load_corpus()))
    return apply_policy(result)
