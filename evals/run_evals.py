"""Three-arm eval harness for RightCall.

Arms:
  worker         Haiku 4.5 with tools, no skill pack (baseline)
  worker+skill   Haiku 4.5 + Fable-5-authored skill pack (the product config)
  teacher+skill  Fable 5 + skill pack (quality ceiling)

Metrics per arm:
  * decision accuracy vs gold accept-lists — scored on the MODEL'S raw decision,
    before the code policy layer can rescue it (policy never flatters the model)
  * must-mention coverage (key concepts present in memo + member_impact)
  * citation groundedness (verbatim quotes verified against chunks the agent
    actually retrieved, in code)
  * escalation accuracy (escalates exactly when it should)
  * tool discipline (all required tools called during the loop)
  * reading grade level of member_impact (Flesch-Kincaid, in code; target <= 9)
  * real token usage and real dollar cost from the API responses

Usage:
  python evals/run_evals.py                  # run all arms live (needs ANTHROPIC_API_KEY)
  python evals/run_evals.py --skip-cached    # reuse cached outputs where present
  python evals/run_evals.py --arms worker+skill

Every live result is cached to examples/outputs/ so the offline demo replays
REAL model outputs, tool traces included.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rightcall.corpus import chunk_index, load_corpus  # noqa: E402
from rightcall.grounding import apply_guard  # noqa: E402
from rightcall.models import ReviewResult  # noqa: E402
from rightcall.pipeline import apply_policy  # noqa: E402

REQS = ROOT / "examples" / "requests"
OUT = ROOT / "examples" / "outputs"
GOLD = json.loads((ROOT / "evals" / "gold.json").read_text(encoding="utf-8"))
ARMS = ["worker", "worker+skill", "teacher+skill"]

# $/1M tokens (input, output) — Anthropic list prices, July 2026
PRICE = {"claude-haiku-4-5-20251001": (1.0, 5.0), "claude-fable-5": (10.0, 50.0)}


def fk_grade(text: str) -> float:
    sentences = max(1, len(re.findall(r"[.!?]+", text)))
    words = re.findall(r"[a-zA-Z]+", text)
    if not words:
        return 0.0
    def syl(w: str) -> int:
        w = w.lower()
        groups = len(re.findall(r"[aeiouy]+", w))
        if w.endswith("e") and groups > 1:
            groups -= 1
        return max(1, groups)
    syllables = sum(syl(w) for w in words)
    return 0.39 * (len(words) / sentences) + 11.8 * (syllables / len(words)) - 15.59


def score_case(r: ReviewResult, gold: dict) -> dict:
    model_decision = r.model_decision or r.decision.value
    dec_ok = model_decision in gold["decision"]

    text = " ".join([r.memo, r.member_impact] + r.recommended_actions).lower()
    mm_ok = sum(any(v.lower() in text for v in variants) for variants in gold["must_mention"])
    mm_n = len(gold["must_mention"])

    called = {t.tool for t in r.tool_trace}
    tools_ok = all(t in called for t in gold["required_tools"])

    g = r.groundedness
    return {
        "dec_ok": dec_ok, "mm_ok": mm_ok, "mm_n": mm_n, "tools_ok": tools_ok,
        "esc_ok": r.escalate == gold["expected_escalate"],
        "quotes_ok": g.verified_quotes, "quotes_n": g.total_quotes,
        "fk": fk_grade(r.member_impact or r.memo),
        "in_tok": (r.usage or {}).get("input_tokens", 0),
        "out_tok": (r.usage or {}).get("output_tokens", 0),
        "model": r.model, "model_decision": model_decision,
    }


def get_result(request: dict, arm: str, skip_cached: bool) -> ReviewResult:
    cache = OUT / f"{request['request_id']}__{arm.replace('+', '_')}.json"
    if skip_cached and cache.exists():
        r = ReviewResult.from_dict(json.loads(cache.read_text(encoding="utf-8")))
        r = apply_guard(r, chunk_index(load_corpus()))
        return apply_policy(r)
    from rightcall.pipeline import run_review
    r = run_review(request, arm)
    OUT.mkdir(parents=True, exist_ok=True)
    cache.write_text(r.to_json(), encoding="utf-8")
    return r


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", default=",".join(ARMS))
    ap.add_argument("--skip-cached", action="store_true")
    args = ap.parse_args()
    arms = [a.strip() for a in args.arms.split(",")]

    cases = sorted(REQS.glob("*.json"))
    table_rows = []

    for arm in arms:
        agg = {k: 0 for k in ["dec_ok", "mm_ok", "mm_n", "esc_ok", "tools_ok",
                              "quotes_ok", "quotes_n", "in_tok", "out_tok"]}
        fks, model_id = [], "?"
        for path in cases:
            request = json.loads(path.read_text(encoding="utf-8"))
            r = get_result(request, arm, args.skip_cached)
            s = score_case(r, GOLD[request["request_id"]])
            model_id = s["model"]
            for k in ["mm_ok", "mm_n", "quotes_ok", "quotes_n", "in_tok", "out_tok"]:
                agg[k] += s[k]
            for k in ["dec_ok", "esc_ok", "tools_ok"]:
                agg[k] += s[k]
            fks.append(s["fk"])
            print(f"{arm:14s} {request['request_id']}: dec "
                  f"{'OK  ' if s['dec_ok'] else 'MISS'} ({s['model_decision']}) "
                  f"mention {s['mm_ok']}/{s['mm_n']} grounded {s['quotes_ok']}/{s['quotes_n']} "
                  f"esc {'OK' if s['esc_ok'] else 'MISS'} "
                  f"tools {'OK' if s['tools_ok'] else 'MISS'} fk {s['fk']:.1f}")

        pin, pout = PRICE.get(model_id, (0, 0))
        cost = agg["in_tok"] / 1e6 * pin + agg["out_tok"] / 1e6 * pout
        n = len(cases)
        row = {
            "dec": f"{agg['dec_ok']}/{n} ({agg['dec_ok']/n:.0%})",
            "mm": f"{agg['mm_ok']}/{agg['mm_n']} ({agg['mm_ok']/max(1,agg['mm_n']):.0%})",
            "ground": f"{agg['quotes_ok']}/{agg['quotes_n']} ({agg['quotes_ok']/max(1,agg['quotes_n']):.0%})",
            "esc": f"{agg['esc_ok']}/{n}", "tools": f"{agg['tools_ok']}/{n}",
            "fk": f"{sum(fks)/len(fks):.1f}",
            "cost": f"${cost:.4f}",
        }
        table_rows.append(f"| {arm} | {model_id} | {row['dec']} | {row['mm']} | {row['ground']} "
                          f"| {row['esc']} | {row['tools']} | {row['fk']} | {row['cost']} |")
        print(f"== {arm}: {row}\n")

    md = f"""# RightCall eval results

Generated {date.today().isoformat()} · {len(cases)} synthetic UM cases · all numbers from REAL API runs
(cached in `examples/outputs/`, tool traces included). Decision accuracy is scored on the model's
RAW decision, before the code policy layer can rescue it — the policy layer exists to protect the
member, not the metric. Code-level flag detection is deterministic and identical across arms.

| Arm | Model | Decision acc. | Must-mention coverage | Citation groundedness | Escalation acc. | Tool discipline | FK grade | Total cost |
|---|---|---|---|---|---|---|---|---|
{chr(10).join(table_rows)}

**Reading the table:** "worker" is Haiku 4.5 with tools; "worker+skill" adds the skill pack
authored by Claude Fable 5 (`skills/um-predenial.md`); "teacher+skill" is Fable 5 itself, as the
quality ceiling. Prices: Haiku 4.5 $1/$5 per 1M tokens; Fable 5 $10/$50 per 1M tokens (list, July 2026).
"""
    (ROOT / "evals" / "results.md").write_text(md, encoding="utf-8")
    print("Wrote evals/results.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
