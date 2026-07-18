# RightCall eval results

Generated 2026-07-17 · 10 synthetic UM cases · all numbers from REAL API runs
(cached in `examples/outputs/`, tool traces included). Decision accuracy is scored on the model's
RAW decision, before the code policy layer can rescue it — the policy layer exists to protect the
member, not the metric. Code-level flag detection is deterministic and identical across arms.

| Arm | Model | Decision acc. | Must-mention coverage | Citation groundedness | Escalation acc. | Tool discipline | FK grade | Total cost |
|---|---|---|---|---|---|---|---|---|
| worker | claude-haiku-4-5-20251001 | 10/10 (100%) | 29/29 (100%) | 34/36 (94%) | 8/10 | 10/10 | 9.1 | $0.1369 |
| worker+skill | claude-haiku-4-5-20251001 | 10/10 (100%) | 29/29 (100%) | 25/26 (96%) | 9/10 | 9/10 | 8.1 | $0.1489 |
| teacher+skill | claude-fable-5 | 10/10 (100%) | 28/29 (97%) | 49/49 (100%) | 10/10 | 10/10 | 6.8 | $2.3337 |

**Reading the table:** "worker" is Haiku 4.5 with tools; "worker+skill" adds the skill pack
authored by Claude Fable 5 (`skills/um-predenial.md`); "teacher+skill" is Fable 5 itself, as the
quality ceiling. Prices: Haiku 4.5 $1/$5 per 1M tokens; Fable 5 $10/$50 per 1M tokens (list, July 2026).
