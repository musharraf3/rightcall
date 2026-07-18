"""Corpus loader. Six sources, all bundled and human-readable:

  data/regs/timeframes.json        — decision-clock rules (CMS-0057-F era timeframes)
  data/regs/coverage_rules.json    — criteria-precedence rules (CMS-4201-F era)
  data/criteria/medicare_criteria.json — Medicare coverage criteria (synthetic NCD/LCD-style)
  data/plan/internal_criteria.json — the plan's internal clinical criteria (synthetic)
  data/duals/dual_rules.json       — dual-eligible coordination and QMB protections
  data/docreq/documentation.json   — required documentation per service type

Every chunk has a stable ID so memos can cite exactly where a rule came from.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"

SOURCES = [
    ("regs", DATA / "regs" / "timeframes.json"),
    ("regs", DATA / "regs" / "coverage_rules.json"),
    ("criteria", DATA / "criteria" / "medicare_criteria.json"),
    ("plan", DATA / "plan" / "internal_criteria.json"),
    ("duals", DATA / "duals" / "dual_rules.json"),
    ("docreq", DATA / "docreq" / "documentation.json"),
]


@dataclass
class Chunk:
    chunk_id: str
    source: str
    title: str
    text: str


def load_corpus() -> list[Chunk]:
    chunks: list[Chunk] = []
    for source, path in SOURCES:
        for item in json.loads(path.read_text(encoding="utf-8"))["chunks"]:
            chunks.append(Chunk(chunk_id=item["id"], source=source,
                                title=item["title"], text=item["text"]))
    return chunks


def load_facts(name: str) -> dict:
    """Structured facts used by the deterministic checks (never by the model)."""
    paths = {
        "docreq": DATA / "docreq" / "documentation.json",
        "criteria": DATA / "criteria" / "medicare_criteria.json",
    }
    return json.loads(paths[name].read_text(encoding="utf-8"))["facts"]


def chunk_index(chunks: list[Chunk]) -> dict[str, Chunk]:
    return {c.chunk_id: c for c in chunks}
