"""The confidence rule as it stood on 7 Nov 2026 ("KEEP": sentiment not_measured is no penalty and no ceiling).
Frozen verbatim from src/stockdesk/confidence.py at commit 5f51d81, the last commit before the CAP rule (4fa63c8).
Used only to re-score pre-eval runs with the rule that produced them (METRICS.md, M7). Do not edit."""
from __future__ import annotations

from typing import Any

import re

LEVELS = ["low", "medium", "high"]
CORE = {"short": ["tech"], "medium": ["fund", "tech"], "long": ["fund"]}
CAP = {"short": 2, "medium": 2, "long": 1}
PRECEDENT_WINDOWS = {"short": [5], "medium": [30, 90], "long": [250]}
MIN_EVENTS = 3
ANALYST_NAMES = {"fund": "fundamental", "tech": "technical", "sent": "sentiment"}
STANCES = ("bullish", "bearish", "neutral", "no_data")
SENTIMENTS = ("positive", "negative", "neutral", "no_data", "not_measured")
LONG_CAP_REASON = "capped: about 3 years of filings, no valuation data"
_EVENTS_USED = re.compile(r"^Events used, (\d+)-session window\b")


def score(horizon: str, direction: str, stances: dict[str, str], precedent: dict[int, int] | None,
          citations: dict[str, Any]) -> tuple[str, list[str]]:
    reasons: list[str] = []  # penalties: each one lowers the score by one level
    notes: list[str] = []    # shown with the result, never a penalty
    for key in ("fund", "tech", "sent"):
        if stances[key] == "no_data":
            reasons.append(f"{ANALYST_NAMES[key]}: no data")
    if stances["sent"] == "not_measured":
        notes.append(f"sentiment: not measured for {horizon} (interim mode)")
    if precedent is None:
        reasons.append("no precedent check")
    else:
        n = min(precedent.get(window, 0) for window in PRECEDENT_WINDOWS[horizon])
        if n < MIN_EVENTS:
            reasons.append(f"only {n} precedent events")
    if citations["uncorrected"]:
        reasons.append("uncorrected citation failure: " + ", ".join(citations["uncorrected"]))
    sent = stances["sent"]
    if (direction == "bullish" and sent == "negative") or (direction == "bearish" and sent == "positive"):
        reasons.append("news sentiment disagrees")

    value = 1 - len(reasons)
    if not reasons and citations["all_pass"] and all(stances[a] == direction for a in CORE[horizon]):
        value = 2
    capped = min(value, CAP[horizon])
    shown = reasons + notes
    if horizon == "long" and capped < value:
        shown.append(LONG_CAP_REASON)
    return LEVELS[max(0, min(capped, 2))], shown
