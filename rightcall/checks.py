"""Deterministic pre-decision checks — computed in code, never by the model.

Six checks, each one traceable to a public rule or a published oversight
finding. These run BEFORE the model sees the case; their findings are both
injected into the review and enforced as policy by the pipeline. AI drafts the
memo; code decides what the memo is not allowed to get wrong.

  documentation        file completeness vs the service type's required documents
  deadline             the regulatory decision clock (72h expedited / 7 calendar
                       days standard for prior auth, per the 2026-era rules)
  specific_reason      a draft denial must carry a specific, member-readable reason
  criteria_precedence  a denial may not rest on internal criteria where Medicare
                       coverage criteria are established (CMS-4201-F era rule)
  improvement_standard skilled-care denials may not use an "improvement standard"
                       (Jimmo v. Sebelius: maintenance coverage is covered)
  dual_qmb             QMB-tier duals cannot be charged Medicare cost sharing
  overturn_risk        composite risk score from published overturn patterns
                       (OIG 2026: 95% of appealed SNF denials overturned;
                       nursing-home residents denied at 40% vs 11%)
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .models import DeadlineStatus, Finding, Severity

EXPEDITED_HOURS = 72
STANDARD_DAYS = 7

IMPROVEMENT_RED_FLAGS = [
    "no significant improvement", "not improving", "improvement potential",
    "plateau", "has plateaued", "restorative potential", "no rehab potential",
    "failure to progress", "custodial only",
]

QMB_TIERS = {"qmb", "qmb_plus", "full_dual_qmb"}


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def deadline_status(request: dict) -> DeadlineStatus:
    received = _parse(request["received_at"])
    as_of = _parse(request["as_of"])
    expedited = bool(request["service"].get("expedited"))
    due = received + (timedelta(hours=EXPEDITED_HOURS) if expedited
                      else timedelta(days=STANDARD_DAYS))
    remaining = (due - as_of).total_seconds() / 3600
    return DeadlineStatus(
        track="expedited" if expedited else "standard",
        received_at=request["received_at"], as_of=request["as_of"],
        due_at=due.isoformat().replace("+00:00", "Z"),
        hours_remaining=round(remaining, 1), breached=remaining < 0)


def check_documentation(request: dict, docreq: dict) -> list[Finding]:
    stype = request["service"]["type"]
    spec = docreq.get(stype)
    if spec is None:
        return [Finding("documentation", Severity.WARNING,
                        f"No documentation checklist defined for service type '{stype}' — "
                        "completeness cannot be verified in code.")]
    required = spec["required_documents"]
    submitted = set(request.get("documents_submitted", []))
    missing = [d for d in required if d not in submitted]
    if not missing:
        return [Finding("documentation", Severity.INFO,
                        f"File is complete: all {len(required)} required documents for "
                        f"{stype} are present.", data={"missing": []})]
    return [Finding("documentation", Severity.ERROR,
                    f"File is INCOMPLETE: {len(missing)} of {len(required)} required "
                    f"documents missing ({', '.join(missing)}). A medical-necessity "
                    "denial on an incomplete file is the classic avoidable overturn — "
                    "request the documents instead.",
                    data={"missing": missing})]


def check_deadline(request: dict) -> list[Finding]:
    ds = deadline_status(request)
    if ds.breached:
        return [Finding("deadline", Severity.ERROR,
                        f"Decision clock BREACHED: the {ds.track} deadline was "
                        f"{ds.due_at} and it is now {ds.as_of}. An untimely adverse "
                        "determination is itself a compliance failure — escalate.",
                        data={"hours_remaining": ds.hours_remaining})]
    if ds.hours_remaining <= 24:
        return [Finding("deadline", Severity.WARNING,
                        f"Decision clock: {ds.hours_remaining:.0f} hours remain on the "
                        f"{ds.track} track (due {ds.due_at}). Prioritize this file.",
                        data={"hours_remaining": ds.hours_remaining})]
    return [Finding("deadline", Severity.INFO,
                    f"Decision clock: {ds.hours_remaining:.0f} hours remain on the "
                    f"{ds.track} track (due {ds.due_at}).",
                    data={"hours_remaining": ds.hours_remaining})]


def check_specific_reason(request: dict) -> list[Finding]:
    draft = request.get("draft_decision") or {}
    if draft.get("action") != "deny":
        return []
    reason = (draft.get("specific_reason") or "").strip()
    if len(reason) >= 20:
        return []
    return [Finding("specific_reason", Severity.ERROR,
                    "Draft denial has no specific, member-readable reason. A denial must "
                    "state exactly why the request does not meet coverage criteria — "
                    "'not medically necessary' alone is not a specific reason.")]


def check_criteria_precedence(request: dict, criteria: dict) -> list[Finding]:
    draft = request.get("draft_decision") or {}
    if draft.get("action") != "deny":
        return []
    stype = request["service"]["type"]
    spec = criteria.get(stype) or {}
    if draft.get("basis") == "internal_criteria" and spec.get("medicare_criteria_established"):
        return [Finding("criteria_precedence", Severity.ERROR,
                        f"Draft denial rests on internal criteria "
                        f"({draft.get('criteria_id', '?')}), but Medicare coverage "
                        f"criteria for {stype} are established "
                        f"(see {spec.get('criteria_chunk')}). Where Medicare criteria "
                        "exist, they govern — internal criteria may only fill gaps.")]
    return []


def check_improvement_standard(request: dict) -> list[Finding]:
    draft = request.get("draft_decision") or {}
    if draft.get("action") != "deny":
        return []
    if request["service"]["type"] not in ("snf_admission", "home_health", "outpatient_therapy"):
        return []
    text = " ".join([draft.get("rationale", ""), draft.get("specific_reason") or ""]).lower()
    hits = [p for p in IMPROVEMENT_RED_FLAGS if p in text]
    if hits:
        return [Finding("improvement_standard", Severity.ERROR,
                        f"Draft denial rationale uses improvement-standard language "
                        f"({'; '.join(repr(h) for h in hits)}). Skilled care to MAINTAIN "
                        "function or slow decline is covered — improvement is not "
                        "required. This is among the most-overturned denial rationales.")]
    return []


def check_dual_qmb(request: dict) -> list[Finding]:
    member = request.get("member", {})
    dual = (member.get("dual_status") or "none").lower()
    findings: list[Finding] = []
    if dual in QMB_TIERS:
        findings.append(Finding("dual_qmb", Severity.INFO,
                                "Member is QMB-tier dual eligible: zero Medicare cost "
                                "sharing may be charged, and providers may not balance "
                                "bill. Medicaid coordinates as secondary payer.",
                                data={"dual_status": dual}))
        draft = request.get("draft_decision") or {}
        if draft.get("member_cost_share", 0) > 0:
            findings.append(Finding("dual_qmb", Severity.ERROR,
                                    f"Draft decision imposes ${draft['member_cost_share']:.2f} "
                                    "cost sharing on a QMB member. QMB members owe $0 — "
                                    "this must be corrected before any notice goes out."))
    return findings


def check_overturn_risk(request: dict, findings: list[Finding]) -> list[Finding]:
    draft = request.get("draft_decision") or {}
    if draft.get("action") != "deny":
        return []
    factors, merits_factors = [], 0
    if request["service"]["type"] == "snf_admission":
        factors.append("SNF denial (95% of appealed SNF denials are overturned — OIG 2026)")
        merits_factors += 1
    if request.get("member", {}).get("setting") == "nursing_home":
        factors.append("nursing-home resident (denied at 40% vs 11% for others — OIG 2026)")
        merits_factors += 1
    error_checks = {f.check for f in findings if f.severity == Severity.ERROR}
    for chk, label, merits in [
            ("documentation", "denial drafted on an incomplete file", False),
            ("criteria_precedence", "internal criteria conflict with Medicare criteria", True),
            ("improvement_standard", "improvement-standard rationale", True),
            ("specific_reason", "no specific denial reason", False)]:
        if chk in error_checks:
            factors.append(label)
            merits_factors += merits
    if not factors:
        return []
    # Paperwork-only risk stays a warning (remediable by requesting documents);
    # error level requires a merits-based factor plus at least one more.
    sev = (Severity.ERROR if merits_factors >= 1 and len(factors) >= 2
           else Severity.WARNING)
    return [Finding("overturn_risk", sev,
                    f"Overturn-risk factors present ({len(factors)}): "
                    + "; ".join(factors) + ". Published pattern: 81% of appealed MA "
                    "denials are overturned — a denial with these markers is unlikely "
                    "to survive review.",
                    data={"factors": factors})]


def run_checks(request: dict, docreq: dict, criteria: dict) -> list[Finding]:
    findings: list[Finding] = []
    findings += check_documentation(request, docreq)
    findings += check_deadline(request)
    findings += check_specific_reason(request)
    findings += check_criteria_precedence(request, criteria)
    findings += check_improvement_standard(request)
    findings += check_dual_qmb(request)
    findings += check_overturn_risk(request, findings)
    return findings
