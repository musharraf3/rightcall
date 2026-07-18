"""Typed schemas. Stdlib-only (dataclasses) so the offline demo needs no installs."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Optional


class Decision(str, Enum):
    APPROVE = "approve"
    REQUEST_DOCUMENTATION = "request_documentation"
    DENIAL_SUPPORTED = "denial_supported"
    ESCALATE_HUMAN = "escalate_human"


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class Finding:
    """Produced by deterministic code, never by the model."""

    check: str              # e.g. "documentation", "deadline", "criteria_precedence"
    severity: Severity
    detail: str
    data: Optional[dict] = None  # structured payload (missing docs, hours left, ...)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Finding":
        return cls(check=d["check"], severity=Severity(d["severity"]),
                   detail=d["detail"], data=d.get("data"))


@dataclass
class DeadlineStatus:
    """Computed by code from the request timestamps. The model never does date math."""

    track: str              # "expedited" | "standard"
    received_at: str
    as_of: str
    due_at: str
    hours_remaining: float
    breached: bool

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DeadlineStatus":
        return cls(**d)


@dataclass
class RetrievedChunk:
    chunk_id: str
    score: float
    matched_terms: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RetrievedChunk":
        return cls(chunk_id=d["chunk_id"], score=d["score"],
                   matched_terms=list(d.get("matched_terms", [])))


@dataclass
class ToolCall:
    """One logged step of the agent loop — the audit trail of how the memo was built."""

    step: int
    tool: str
    tool_input: dict
    result_digest: str      # human-readable summary of what the tool returned

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ToolCall":
        return cls(step=d["step"], tool=d["tool"],
                   tool_input=d.get("tool_input", {}), result_digest=d["result_digest"])


@dataclass
class Citation:
    chunk_id: str
    quote: str
    verified: Optional[bool] = None  # set by groundedness guard, in code

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Citation":
        return cls(chunk_id=d["chunk_id"], quote=d["quote"], verified=d.get("verified"))


@dataclass
class GroundednessReport:
    total_quotes: int
    verified_quotes: int
    unverified: list[str] = field(default_factory=list)

    @property
    def rate(self) -> float:
        return self.verified_quotes / self.total_quotes if self.total_quotes else 1.0


@dataclass
class ReviewResult:
    request_id: str
    model: str
    arm: str                          # "worker" | "worker+skill" | "teacher+skill"
    mode: str                         # "live" | "offline-cache"
    decision: Decision
    memo: str                         # the pre-decision review memo (professional tone)
    member_impact: str                # plain language: what this means for the member
    missing_documents: list[str]
    recommended_actions: list[str]
    citations: list[Citation]
    findings: list[Finding]           # injected by code, shown to model AND reviewer
    deadline: Optional[DeadlineStatus]
    retrieval: list[RetrievedChunk] = field(default_factory=list)  # from lookup_rules calls
    tool_trace: list[ToolCall] = field(default_factory=list)
    escalate: bool = False            # True => a human decides, not the system
    escalate_reason: Optional[str] = None
    policy_notes: list[str] = field(default_factory=list)  # code-enforced overrides
    model_decision: Optional[str] = None  # the model's raw call, before policy overrides —
                                          # evals score THIS, so policy never flatters the model
    groundedness: Optional[GroundednessReport] = None
    usage: Optional[dict] = None      # real token counts summed across the loop

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ReviewResult":
        g = d.get("groundedness")
        return cls(
            request_id=d["request_id"], model=d["model"], arm=d["arm"], mode=d["mode"],
            decision=Decision(d["decision"]), memo=d["memo"],
            member_impact=d.get("member_impact", ""),
            missing_documents=list(d.get("missing_documents", [])),
            recommended_actions=list(d.get("recommended_actions", [])),
            citations=[Citation.from_dict(c) for c in d.get("citations", [])],
            findings=[Finding.from_dict(f) for f in d.get("findings", [])],
            deadline=DeadlineStatus.from_dict(d["deadline"]) if d.get("deadline") else None,
            retrieval=[RetrievedChunk.from_dict(r) for r in d.get("retrieval", [])],
            tool_trace=[ToolCall.from_dict(t) for t in d.get("tool_trace", [])],
            escalate=d.get("escalate", False), escalate_reason=d.get("escalate_reason"),
            policy_notes=list(d.get("policy_notes", [])),
            model_decision=d.get("model_decision"),
            groundedness=GroundednessReport(**g) if g else None,
            usage=d.get("usage"),
        )

    def to_json(self, indent: int = 2) -> str:
        def enc(o: Any) -> Any:
            if isinstance(o, Enum):
                return o.value
            raise TypeError(str(type(o)))
        return json.dumps(asdict(self), indent=indent, default=enc)
