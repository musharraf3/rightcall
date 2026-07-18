"""Orchestration: code checks → agent loop (tools) → groundedness guard → policy.

The policy layer is the part that matters: trust rules live in code, not in
prompts. If the model's recommendation contradicts an error-level code finding,
the pipeline does not argue with it — it forces escalation and says why. The
system can be wrong in only one direction: toward a human.
"""

from __future__ import annotations

from .agent import run_agent
from .checks import deadline_status, run_checks
from .corpus import chunk_index, load_corpus, load_facts
from .grounding import apply_guard
from .models import Citation, Decision, ReviewResult, Severity
from .retriever import BM25Index
from .tools import ToolRuntime


def apply_policy(result: ReviewResult) -> ReviewResult:
    """Code-enforced guardrails on the model's recommendation.

    Soft errors (documentation, specific_reason) are remediable by requesting
    documents or rewriting the notice; hard errors (deadline breach, QMB cost
    sharing, criteria precedence, improvement standard, overturn risk) are not
    — those always go to a human unless the memo already says so.
    """
    error_checks = {f.check for f in result.findings if f.severity == Severity.ERROR}
    soft = {"documentation", "specific_reason"}
    hard_errors = error_checks - soft

    if hard_errors and result.decision != Decision.ESCALATE_HUMAN:
        prev = result.decision.value
        result.decision = Decision.ESCALATE_HUMAN
        result.escalate = True
        result.escalate_reason = (
            "Policy override: code-level checks found non-remediable compliance risk "
            f"({', '.join(sorted(hard_errors))}) but the memo recommended '{prev}'. "
            "A human decides — the system may only err toward review.")
        result.policy_notes.append(
            f"decision overridden in code: {prev} → escalate_human "
            f"(hard error findings: {', '.join(sorted(hard_errors))})")

    if "documentation" in error_checks and result.decision == Decision.APPROVE:
        result.decision = Decision.ESCALATE_HUMAN
        result.escalate = True
        result.escalate_reason = result.escalate_reason or (
            "Policy override: approval recommended on an incomplete file — a human "
            "should confirm the missing documents are immaterial.")
        result.policy_notes.append(
            "decision overridden in code: approve → escalate_human (file incomplete)")

    doc = next((f for f in result.findings
                if f.check == "documentation" and f.severity == Severity.ERROR), None)
    if doc and doc.data:
        # The authoritative missing-docs list comes from code, not the memo.
        result.missing_documents = doc.data.get("missing", result.missing_documents)

    if result.decision == Decision.ESCALATE_HUMAN and not result.escalate:
        result.escalate = True
        result.escalate_reason = result.escalate_reason or "Reviewer requested human hand-off."
    return result


def run_review(request: dict, arm: str) -> ReviewResult:
    chunks = load_corpus()
    index = BM25Index(chunks)
    by_id = chunk_index(chunks)

    findings = run_checks(request, load_facts("docreq"), load_facts("criteria"))
    runtime = ToolRuntime(index=index, by_id=by_id, request=request, findings=findings)

    raw, usage, model = run_agent(arm, request, runtime)

    raw_decision = str(raw.get("decision", ""))
    try:
        decision = Decision(raw_decision)
        invalid_note = None
    except ValueError:
        # Output outside the contract is untrusted output: a human decides.
        decision = Decision.ESCALATE_HUMAN
        invalid_note = (f"model returned invalid decision {raw_decision!r} — "
                        "treated as escalate_human")

    result = ReviewResult(
        request_id=request["request_id"], model=model, arm=arm, mode="live",
        decision=decision, memo=raw["memo"],
        member_impact=raw.get("member_impact", ""),
        missing_documents=list(raw.get("missing_documents", [])),
        recommended_actions=list(raw.get("recommended_actions", [])),
        citations=[Citation.from_dict(c) for c in raw.get("citations", [])],
        findings=findings, deadline=deadline_status(request),
        retrieval=runtime.retrieval, tool_trace=runtime.trace,
        escalate=bool(raw.get("escalate", False)),
        escalate_reason=raw.get("escalate_reason"),
        usage=usage,
    )
    result.model_decision = raw_decision
    if invalid_note:
        result.policy_notes.append(invalid_note)
        result.escalate = True
        result.escalate_reason = result.escalate_reason or invalid_note
    result = apply_guard(result, by_id)
    return apply_policy(result)
