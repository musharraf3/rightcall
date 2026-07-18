"""HTML report renderer — the RightCall 'glass box' UI.

One self-contained HTML file per review: no frameworks, no build step, no
external assets. The panel that matters most is the AGENT TOOL TRACE — the
step-by-step log of every tool the model called to build its memo. That panel
is the answer to "how did the AI reach this recommendation?"
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from .corpus import Chunk
from .models import ReviewResult, Severity

CSS = """
:root{--ink:#1a202c;--sub:#5a6472;--line:#e2e8f0;--brand:#1d4e89;--brand-lt:#e8f0fa;
--ok:#1a7f37;--ok-bg:#e8f5ec;--warn:#9a6700;--warn-bg:#fff8e5;--err:#b42318;--err-bg:#fdecea;
--chip:#eef2f7;--trace:#102a43}
*{box-sizing:border-box;margin:0}
body{font-family:'Segoe UI',system-ui,-apple-system,Arial,sans-serif;color:var(--ink);
background:#f5f7fa;padding:28px;line-height:1.55}
.wrap{max-width:900px;margin:0 auto}
header{display:flex;align-items:baseline;gap:14px;margin-bottom:6px}
header h1{font-size:26px;color:var(--brand)}
header .tag{color:var(--sub);font-size:13px}
.banner{border-radius:10px;padding:12px 16px;font-weight:700;margin:14px 0;font-size:15px}
.banner.approve{background:var(--ok-bg);border:1.5px solid var(--ok);color:var(--ok)}
.banner.request_documentation{background:var(--brand-lt);border:1.5px solid var(--brand);color:var(--brand)}
.banner.denial_supported{background:var(--chip);border:1.5px solid var(--sub);color:var(--ink)}
.banner.escalate_human{background:var(--warn-bg);border:1.5px solid var(--warn);color:var(--warn)}
.clock{display:inline-block;font-family:Consolas,monospace;font-size:12.5px;padding:3px 10px;
border-radius:999px;background:var(--chip)}
.clock.breach{background:var(--err-bg);color:var(--err);font-weight:700}
.card{background:#fff;border:1px solid var(--line);border-radius:12px;padding:18px 20px;
margin:14px 0;box-shadow:0 1px 2px rgba(16,24,40,.04)}
.card h2{font-size:15px;text-transform:uppercase;letter-spacing:.06em;color:var(--sub);
margin-bottom:10px}
.finding{border-left:4px solid;border-radius:6px;padding:10px 14px;margin:8px 0;font-size:14px}
.finding.error{border-color:var(--err);background:var(--err-bg)}
.finding.warning{border-color:var(--warn);background:var(--warn-bg)}
.finding.info{border-color:var(--sub);background:var(--chip)}
.badge{display:inline-block;font-size:11px;font-weight:700;letter-spacing:.04em;
padding:2px 9px;border-radius:999px;text-transform:uppercase}
.badge.code{background:var(--trace);color:#fff}
.badge.err{background:var(--err-bg);color:var(--err)}
.badge.ok{background:var(--ok-bg);color:var(--ok)}
.trace{font-family:Consolas,monospace;font-size:12.5px}
.trace .step{display:flex;gap:10px;padding:7px 10px;border-left:3px solid var(--brand);
background:#fafbfc;border-radius:6px;margin:6px 0;align-items:baseline}
.trace .n{color:#fff;background:var(--brand);border-radius:999px;min-width:20px;height:20px;
display:inline-flex;align-items:center;justify-content:center;font-size:11px;flex:none}
.trace .tool{color:var(--brand);font-weight:700}
.trace .in{color:var(--sub)}
.memo{font-size:14.5px;white-space:pre-wrap}
.impact{background:var(--brand-lt);border:1px solid var(--brand);border-radius:8px;
padding:10px 14px;font-size:14px;margin-top:10px}
.cite{background:#fafbfc;border:1px solid var(--line);border-radius:8px;padding:8px 12px;
margin:8px 0 0;font-size:13.5px}
.cite .src{color:var(--brand);font-weight:600}
.cite .q{font-style:italic;color:var(--sub)}
.retr{font-size:12.5px;color:var(--sub);margin-top:8px;font-family:Consolas,monospace}
.retr .bar{display:inline-block;height:8px;background:var(--brand);border-radius:4px;
vertical-align:middle;margin-right:6px}
.actions li{margin:6px 0 6px 4px}
.policy{background:var(--err-bg);border:1.5px solid var(--err);border-radius:10px;
padding:12px 16px;margin:14px 0;font-size:13.5px}
.policy b{color:var(--err)}
.escalate{background:var(--warn-bg);border:1.5px solid var(--warn);color:var(--warn);
border-radius:10px;padding:12px 16px;font-weight:600;margin:14px 0}
footer{color:var(--sub);font-size:12.5px;margin-top:18px;border-top:1px solid var(--line);
padding-top:12px}
.gg{font-weight:600}
"""

BANNER = {
    "approve": "APPROVE — coverage criteria met",
    "request_documentation": "REQUEST DOCUMENTATION — do not deny an incomplete file",
    "denial_supported": "DENIAL SUPPORTED — complete file, criteria clearly unmet, specific reason present",
    "escalate_human": "ESCALATE — a human decides this one",
}


def _e(t) -> str:
    return html.escape(str(t))


def render(result: ReviewResult, request: dict, by_id: dict[str, Chunk]) -> str:
    d = result.deadline
    clock = ""
    if d:
        label = ("CLOCK BREACHED" if d.breached
                 else f"{d.hours_remaining:.0f}h remaining")
        clock = (f'<span class="clock{" breach" if d.breached else ""}">'
                 f'{_e(d.track)} track · due {_e(d.due_at)} · {label}</span>')

    parts = [f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>RightCall — {_e(result.request_id)}</title><style>{CSS}</style></head><body><div class="wrap">
<header><h1>RightCall</h1><span class="tag">pre-decision review ·
{_e(request['member']['plan'])} · {_e(result.model)} · arm: {_e(result.arm)}</span></header>
<div style="margin:6px 0 0">{clock}</div>
<div class="banner {result.decision.value}">{BANNER[result.decision.value]}</div>
<div class="card"><h2>Case</h2>
<p><b>{_e(request['service']['description'])}</b> — {_e(request['member']['name'])},
{_e(request['member']['member_id'])}{", dual status: " + _e(request['member']['dual_status'])
    if request['member'].get('dual_status', 'none') != 'none' else ""}</p>
<p style="color:var(--sub);font-size:13.5px;margin-top:6px">{_e(request.get('clinical_summary', ''))}</p></div>"""]

    if result.findings:
        rows = []
        for f in result.findings:
            rows.append(f'<div class="finding {f.severity.value}"><b>{_e(f.check)}</b>'
                        f'<div>{_e(f.detail)}</div></div>')
        parts.append(f'<div class="card"><h2>Pre-decision checks <span class="badge code">'
                     f'computed in code — not by AI</span></h2>{"".join(rows)}</div>')

    if result.tool_trace:
        steps = []
        for t in result.tool_trace:
            arg = json.dumps(t.tool_input) if t.tool_input else ""
            steps.append(f'<div class="step"><span class="n">{t.step}</span>'
                         f'<span><span class="tool">{_e(t.tool)}</span>'
                         f'<span class="in">({_e(arg)})</span> → {_e(t.result_digest)}</span></div>')
        parts.append(f'<div class="card"><h2>Agent tool trace <span class="badge code">'
                     f'every step logged</span></h2><div class="trace">{"".join(steps)}</div></div>')

    parts.append(f'<div class="card"><h2>Review memo</h2><div class="memo">{_e(result.memo)}</div>'
                 + (f'<div class="impact"><b>Member impact (plain language):</b> '
                    f'{_e(result.member_impact)}</div>' if result.member_impact else "")
                 + '</div>')

    if result.missing_documents:
        items = "".join(f"<li>{_e(m)}</li>" for m in result.missing_documents)
        parts.append(f'<div class="card"><h2>Missing documents <span class="badge code">'
                     f'authoritative list from code</span></h2><ul class="actions">{items}</ul></div>')

    if result.citations:
        cites = []
        for c in result.citations:
            mark = ('<span class="badge ok">verified</span>' if c.verified
                    else '<span class="badge err">not verified — human review</span>')
            title = by_id[c.chunk_id].title if c.chunk_id in by_id else "unknown source"
            cites.append(f'<div class="cite"><span class="src">[{_e(c.chunk_id)}] {_e(title)}'
                         f'</span> {mark}<div class="q">“{_e(c.quote)}”</div></div>')
        retr = ""
        if result.retrieval:
            max_score = max(r.score for r in result.retrieval) or 1.0
            spans = []
            for r in sorted(result.retrieval, key=lambda x: -x.score)[:5]:
                w = max(6, int(70 * r.score / max_score))
                spans.append(f'<div><span class="bar" style="width:{w}px"></span>'
                             f'{_e(r.chunk_id)} · BM25 {r.score:g} · matched: '
                             f'{_e(", ".join(r.matched_terms[:6]))}</div>')
            retr = (f'<div class="retr"><b>why these sources (retrieval scores):</b>'
                    f'{"".join(spans)}</div>')
        parts.append(f'<div class="card"><h2>Citations — machine-verified</h2>'
                     f'{"".join(cites)}{retr}</div>')

    if result.recommended_actions:
        acts = "".join(f"<li>{_e(a)}</li>" for a in result.recommended_actions)
        parts.append(f'<div class="card"><h2>Recommended actions</h2><ol class="actions">{acts}</ol></div>')

    if result.policy_notes:
        notes = "<br>".join(_e(n) for n in result.policy_notes)
        parts.append(f'<div class="policy"><b>Policy layer (code-enforced):</b><br>{notes}</div>')

    if result.escalate:
        parts.append(f'<div class="escalate">⚠ Human hand-off: {_e(result.escalate_reason)}</div>')

    g = result.groundedness
    gg = (f'{g.verified_quotes}/{g.total_quotes} citations verified verbatim against chunks '
          f'actually retrieved in this review' if g else "n/a")
    parts.append(f"""<footer><span class="gg">Groundedness guard: {gg}.</span>
The decision clock, file checks, citation verification, and policy overrides are
deterministic code — inspect them in the repo. RightCall supports human reviewers;
it does not make coverage decisions. All data on this page is synthetic.</footer>
</div></body></html>""")
    return "".join(parts)


def write_report(result: ReviewResult, request: dict, by_id: dict[str, Chunk],
                 out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{result.request_id}__{result.arm.replace('+', '_')}.html"
    path.write_text(render(result, request, by_id), encoding="utf-8")
    return path
