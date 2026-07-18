"""Glass-box retrieval: BM25, pure Python, fully inspectable.

Same design choice as ClearAnswer (Weekend Build #2): lexical BM25 instead of
embeddings, because a UM reviewer — or an auditor, or a regulator — must be
able to see WHY a passage was retrieved. Every retrieval carries term-level
scores and the exact matched terms. Deterministic, reproducible, zero
dependencies. In RightCall the retriever is only reachable through the
`lookup_rules` tool, so every retrieval is also a logged step in the agent's
audit trail.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from .corpus import Chunk
from .models import RetrievedChunk

K1 = 1.5
B = 0.75
STOP = set("a an and are as at be by for from has have in is it of on or that the this to was were will with your you".split())


def tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOP]


class BM25Index:
    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        self.docs = [tokenize(f"{c.title} {c.text}") for c in chunks]
        self.doc_len = [len(d) for d in self.docs]
        self.avg_len = sum(self.doc_len) / len(self.doc_len)
        self.tf = [Counter(d) for d in self.docs]
        df: Counter[str] = Counter()
        for d in self.docs:
            df.update(set(d))
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def search(self, query: str, k: int = 4) -> list[RetrievedChunk]:
        q_terms = tokenize(query)
        scored = []
        for i, c in enumerate(self.chunks):
            score, matched = 0.0, []
            for t in q_terms:
                f = self.tf[i].get(t, 0)
                if not f:
                    continue
                idf = self.idf.get(t, 0.0)
                score += idf * (f * (K1 + 1)) / (f + K1 * (1 - B + B * self.doc_len[i] / self.avg_len))
                matched.append(t)
            if score > 0:
                scored.append(RetrievedChunk(chunk_id=c.chunk_id, score=round(score, 3),
                                             matched_terms=sorted(set(matched))))
        scored.sort(key=lambda r: r.score, reverse=True)
        return scored[:k]
