"""RightCall — a glass-box pre-decision copilot for Medicare Advantage
utilization management.

Before a denial is finalized: deterministic code validates the file, computes
the regulatory clock, and scores overturn risk; the model — running an
auditable tool-use loop — writes the review memo with machine-verified
citations. High-risk decisions are flagged to a human BEFORE they go out.
"""

MODEL_TEACHER = "claude-fable-5"
MODEL_WORKER = "claude-haiku-4-5-20251001"

__version__ = "0.1.0"
