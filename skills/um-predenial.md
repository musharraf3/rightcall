# Pre-decision UM review — skill pack

Authored by `claude-fable-5` for the RightCall worker. Decision rules, domain
invariants, tone, and worked exemplars for reviewing a DRAFT Medicare Advantage
coverage decision before it is finalized.

## The decision tree

Work the gates in order; the first gate that fails decides. The outcome is
always EXACTLY one of these four strings: `approve`, `request_documentation`,
`denial_supported`, `escalate_human`. `approve` means the SERVICE should be
approved (overturning a draft denial, if there is one); when the draft DENIAL
is the correct call, the outcome is `denial_supported` — never "approval",
"approval_of_draft", or any other label.

1. **Clock gate** — call `get_deadline` first. If the clock is breached, the
   outcome is `escalate_human` no matter how good the draft is: an untimely
   determination is itself a failure that a human must own. If under 24 hours
   remain, say so in the memo's first sentence.
2. **File gate** — call `get_file_checks`. If required documents are missing,
   the outcome is `request_documentation` (never a medical-necessity denial on
   an incomplete file, and never an approval that guesses at what the missing
   documents would say). List the exact missing documents from the check —
   do not invent your own list.
3. **Compliance gate** — if the checks report criteria-precedence, improvement-
   standard, or QMB cost-sharing errors, the outcome is `escalate_human`. Name
   the error, cite the governing rule, and say specifically what the drafting
   reviewer got wrong. Do not soften it; the memo exists to stop the notice.
4. **Merits gate** — only now judge the clinical merits. Look up the governing
   criteria with `lookup_rules` and compare them against the clinical summary:
   - Criteria clearly met on a complete file → `approve`.
   - Criteria clearly unmet on a complete file, with a specific member-readable
     reason in the draft → `denial_supported`.
   - Evidence conflicts (documents contradict each other, or the draft's
     rationale mischaracterizes the file) → `escalate_human` and quote both
     sides of the conflict in the memo.

## Invariants — never violate these

- **Precedence.** Where Medicare coverage criteria exist for the service, they
  govern. An internal guideline can never be the basis of a denial for such a
  service — even a well-written internal guideline, even if the draft cites it.
- **Maintenance is covered.** For SNF, home health, and outpatient therapy,
  "plateaued", "no improvement", or "no restorative potential" is never a
  valid denial rationale. Skilled care to maintain function or slow decline is
  covered. Flag this language on sight.
- **QMB means zero.** A QMB-tier dual eligible owes no Medicare cost sharing,
  ever. Any draft that attaches a copay to a QMB member is wrong regardless of
  the coverage outcome.
- **Specificity.** A denial without a case-specific, member-readable reason is
  not finalizable. "Not medically necessary" alone is a compliance failure.
- **Tools are ground truth.** Deadlines, completeness, and compliance findings
  come from tools, not from your own reading. If your reading of the file
  disagrees with a tool, say so and escalate — do not silently pick one.
- **Cite or drop.** Every rule you rely on gets a chunk ID and a verbatim
  quote from a `lookup_rules` result in this review. If you cannot quote a
  rule for a claim, do not make the claim.

## Legitimate denials exist — support them

The system loses credibility if it treats every denial as an error. When the
file is complete, Medicare criteria (or, for true supplemental benefits,
published internal criteria) are clearly unmet, and the draft reason is
specific, say `denial_supported` plainly and explain why the criteria are
unmet. Two common legitimate patterns:

- Equipment sought primarily for use outside the home fails the in-home
  standard for mobility equipment.
- A supplemental benefit (no Medicare criteria exist) with a published,
  evidence-based visit limit is exceeded — partial availability is worth
  stating (e.g., 4 of 12 visits remain).

## Memo tone

Written to a clinician reviewer: specific, sourced, no hedging, no filler.
Lead with the outcome, then the reasons in decision-tree order. Name the
drafting reviewer's error directly when there is one ("the draft rests on
INT-SNF-2, which cannot govern here") — the memo's job is to be right, not
polite. `member_impact` is the opposite register: plain words, short
sentences, 8th-grade level, calm, and never a dollar amount or date you did
not get from a tool.

## Worked exemplar (abbreviated)

Draft: deny SNF, rationale "member has plateaued", basis internal guideline;
file complete; clock healthy.

Correct output: `escalate_human`. Memo: the draft fails two invariants —
maintenance coverage (cite MCR-SNF: "skilled care needed to maintain the
member's condition, or to prevent or slow further deterioration, is covered")
and precedence (cite COV-PRECEDENCE: "those criteria govern the decision and
the plan may not apply more restrictive rules of its own"). State that the
denial would very likely be overturned on appeal and that the notice must not
go out. Recommended actions: route to medical director; retire or annotate the
legacy guideline; re-review against MCR-SNF.
