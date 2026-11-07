#!/usr/bin/env python3
"""confidence.py --run RUN --horizon short|medium|long --direction bullish|bearish|neutral
                 --fund S --tech S --sent S

Deterministic confidence label (low | medium | high) for one horizon. No LLM, no judgment.
Analyst stances come from the arguments (fund/tech: bullish|bearish|neutral|no_data;
sent: positive|negative|neutral|no_data|not_measured). Precedent and verification data are read from the
run's ledger only: precedent.py "Events used" entries and evidence/<run>/verifications.jsonl.

Rule (README, "How confidence works"):
  start at medium (score 1), then -1 for each of:
    each analyst whose stance is no_data (sentiment not_measured is NOT a penalty: the interim news mode does not
      measure that window; it only adds the reason "sentiment: not measured for <horizon> (interim mode)")
    precedent ran but has fewer than 3 events in the horizon's window(s)
    precedent was not run in this run (then the event-count penalty is not added on top)
    any uncorrected citation failure (latest check FAIL)
    news sentiment opposes the direction (negative vs bullish, positive vs bearish; never when neutral)
  high (score 2) only if there were no penalties, every citation checked passes (at least one check),
  and every CORE analyst for the horizon agrees with the direction. Sentiment can only lower confidence.
  final = clamp(min(score, CAP[horizon]), 0, 2).
The result is a judgment label, not a fact: it is not written as evidence, only to
evidence/<run>/confidence.json, keyed by horizon.
"""
from __future__ import annotations

import json
import re
import sys
from typing import Any, Sequence

import common
from common import ToolError

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


def precedent_counts(run: str) -> dict[int, int] | None:
    """Events used per window from precedent.py entries (latest entry per window wins).
    None means precedent.py wrote nothing in this run."""
    entries = [e for e in common.list_evidence(run) if e.get("tool") == "precedent.py"]
    if not entries:
        return None
    counts: dict[int, int] = {}
    for entry in entries:  # list_evidence is in ID order, so later entries overwrite earlier ones
        match = _EVENTS_USED.match(str(entry.get("fact", "")))
        if match and isinstance(entry.get("value"), int):
            counts[int(match.group(1))] = entry["value"]
    return counts


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


def main(argv: Sequence[str]) -> tuple[str | None, list[str], dict[str, Any]]:
    parser = common.ContractParser(prog="confidence.py", description="Deterministic confidence label for one horizon.")
    parser.add_argument("--horizon", required=True, choices=sorted(CORE))
    parser.add_argument("--direction", required=True, choices=["bullish", "bearish", "neutral"])
    parser.add_argument("--fund", required=True, choices=STANCES)
    parser.add_argument("--tech", required=True, choices=STANCES)
    parser.add_argument("--sent", required=True, choices=SENTIMENTS)
    common.add_run_argument(parser)
    args = parser.parse_args(list(argv))
    if not args.run:
        raise ToolError("bad_input", "--run is required")
    run = common.resolve_run(args.run)

    stances = {"fund": args.fund, "tech": args.tech, "sent": args.sent}
    citations = common.citation_summary(run)
    precedent = precedent_counts(run)
    level, reasons = score(args.horizon, args.direction, stances, precedent, citations)
    data = {"horizon": args.horizon, "direction": args.direction, "confidence": level, "reasons": reasons,
            "citations": citations["display"], "uncorrected": citations["uncorrected"]}

    path = common.evidence_root() / run / "confidence.json"
    try:
        stored = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except json.JSONDecodeError as exc:
        raise ToolError("source_unavailable", "confidence.json is not valid JSON") from exc
    stored[args.horizon] = {**data, "inputs": {**stances, "precedent_events": precedent},
                            "computed_at": common.utc_iso()}
    common.write_atomic(path, json.dumps(stored, indent=2) + "\n")
    return run, [], data


if __name__ == "__main__":
    sys.exit(common.run_cli(main))
