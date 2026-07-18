"""The auditable agent loop — pure standard library (urllib), no SDK.

Three arms, same as the series convention:

  worker         — Haiku 4.5 with tools, no skill pack (baseline)
  worker+skill   — Haiku 4.5 + the Fable-5-authored skill pack (the product config)
  teacher+skill  — Fable 5 + skill pack (quality ceiling / eval reference)

The loop: the model may only reach the rulebook, the clock, and the file
checks through tools; every call is dispatched deterministically and logged.
The final message must be a JSON review memo. Hard caps keep the loop finite.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import MODEL_TEACHER, MODEL_WORKER
from .tools import TOOL_DEFS, ToolRuntime

API_URL = "https://api.anthropic.com/v1/messages"
SKILL_PATH = Path(__file__).resolve().parent.parent / "skills" / "um-predenial.md"
MAX_STEPS = 8

ARMS = {
    "worker": (MODEL_WORKER, False),
    "worker+skill": (MODEL_WORKER, True),
    "teacher+skill": (MODEL_TEACHER, True),
}

SYSTEM = """You are RightCall, a pre-decision quality reviewer for a Medicare Advantage \
plan's utilization management team. A draft coverage decision is about to be finalized; \
your job is to catch avoidable errors BEFORE any notice goes out.

Hard rules:
1. NEVER compute dates or deadlines yourself — call get_deadline. NEVER re-derive file \
completeness or compliance findings — call get_file_checks and repeat its conclusions.
2. Every statement about a regulation, coverage criterion, plan rule, or dual-eligible \
protection MUST carry a citation: the chunk_id of a passage returned by lookup_rules plus \
a short EXACT verbatim quote from it. Quotes are machine-verified; copy characters exactly. \
You may only cite chunks you retrieved through lookup_rules in THIS review.
3. Decide one of: "approve" (criteria clearly met), "request_documentation" (file \
incomplete — never deny an incomplete file for medical necessity), "denial_supported" \
(criteria clearly unmet on a complete file, with a specific member-readable reason), \
"escalate_human" (conflicting evidence, code-detected compliance risk, or anything you \
cannot support with citations). When in doubt, escalate — routing to a human is a \
feature, not a failure.
4. A denial recommendation must never rest on internal criteria where Medicare coverage \
criteria exist, never use improvement-standard reasoning for skilled care, and never \
impose cost sharing on a QMB member.
5. The memo is for a clinician reviewer: professional, specific, no hedging. \
member_impact is for the member: plain language, 8th-grade reading level, calm.

When your review is complete, respond with ONLY JSON:
{"decision": "approve"|"request_documentation"|"denial_supported"|"escalate_human",
 "memo": str, "member_impact": str, "missing_documents": [str],
 "recommended_actions": [str],
 "citations": [{"chunk_id": str, "quote": str}],
 "escalate": bool, "escalate_reason": str|null}"""


def _extract_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Models sometimes wrap the JSON in prose; parse the first object found.
        start = text.find("{")
        if start == -1:
            raise
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
        return obj


def load_skill() -> str:
    return SKILL_PATH.read_text(encoding="utf-8")


def build_user_prompt(request: dict) -> str:
    return ("COVERAGE REQUEST FILE (synthetic), with the reviewer's DRAFT decision "
            "attached. Review it before it is finalized:\n"
            + json.dumps(request, indent=2)
            + "\n\nUse your tools to check the clock, the file, and the rulebook; "
              "then return the JSON review memo.")


def _post(payload: dict, retries: int = 3) -> dict:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not set — use --offline for the demo mode.")
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        method="POST",
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:400]
            if e.code in (429, 500, 502, 503, 529) and attempt < retries - 1:
                time.sleep(4 * (attempt + 1))
                continue
            raise RuntimeError(f"API error {e.code}: {body}") from e
    raise RuntimeError("unreachable")


def _text_of(data: dict) -> str:
    # Some models emit a thinking block before the text block.
    return next(b["text"] for b in data["content"] if b.get("type") == "text")


def run_agent(arm: str, request: dict, runtime: ToolRuntime) -> tuple[dict, dict, str]:
    """Runs the tool loop. Returns (parsed_memo_json, usage_totals, model_id)."""
    model, use_skill = ARMS[arm]
    system = SYSTEM + ("\n\n=== SKILL PACK (authored by claude-fable-5) ===\n" + load_skill()
                       if use_skill else "")
    messages: list[dict] = [{"role": "user", "content": build_user_prompt(request)}]
    usage = {"input_tokens": 0, "output_tokens": 0}

    for step in range(MAX_STEPS + 1):
        payload = {"model": model, "max_tokens": 3000, "system": system,
                   "messages": messages, "tools": TOOL_DEFS}
        if step == MAX_STEPS:  # out of budget: force a final answer
            payload["tool_choice"] = {"type": "none"}
        data = _post(payload)
        usage["input_tokens"] += data["usage"]["input_tokens"]
        usage["output_tokens"] += data["usage"]["output_tokens"]

        if data.get("stop_reason") != "tool_use":
            return _extract_json(_text_of(data)), usage, model

        messages.append({"role": "assistant", "content": data["content"]})
        results = []
        for block in data["content"]:
            if block.get("type") == "tool_use":
                out = runtime.dispatch(block["name"], block.get("input", {}))
                results.append({"type": "tool_result", "tool_use_id": block["id"],
                                "content": out})
        messages.append({"role": "user", "content": results})

    raise RuntimeError("agent loop exceeded step budget without a final answer")
