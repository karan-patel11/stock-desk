#!/usr/bin/env python3
"""round.py: run lifecycle and the two-round cap.

  round.py start TICKER [--goal short|medium|long|all]   new run, round 1
  round.py goal short|medium|long|all                     set the user's goal later
  round.py status         current state plus the exact next action for the chief
  round.py next           round 1 -> 2, then returns STOP: write verdict
  round.py end            close the run

State lives in evidence/<run>/state.json. The round cap is enforced here, in code:
the chief cannot reach round 3 no matter what the instructions say.
The goal only picks the headline horizon (all -> medium); all three horizons are always computed.
"""
from __future__ import annotations

import json
import sys
from typing import Any, Sequence

import common
from common import ToolError

MAX_ROUNDS = 2
GOALS = ("short", "medium", "long", "all")
ASK_GOAL = ("ASK GOAL: ask the user's goal for the ticker (1 short-term, 2 medium-term, 3 long-term, or all), "
            "then run round.py goal <short|medium|long|all>. If still unclear after asking twice, use all.")

NEXT_ACTION = {
    "round_1": (
        "ROUND 1: mention desk-fundamental, desk-technical and desk-sentiment in ONE message, each with its scope line. "
        "For each report, save it to a file and run verify.py --text-file on it. "
        "Reply to every failure naming the claim and the stored value. Then run round.py next."
    ),
    "round_2": (
        "ROUND 2: ask 1-3 targeted questions to specific analysts about the weakest or most "
        "contradictory claims. Ask desk-sentiment for dates of past comparable events with opened "
        "source links, then run precedent.py yourself. Verify every new report. Then run round.py next."
    ),
    "verdict": (
        "STOP: write verdict. Run confidence.py for short, medium and long. Post the verdict card in the main "
        "channel, run evidence_table.py, save the card and the table with create_room_document as "
        "verdict-<TICKER>-<YYYY-MM-DD>, then run round.py end."
    ),
    "ended": "Run is closed. Start a new run with round.py start TICKER.",
}


def _state_file(run: str):
    return common.evidence_root() / run / "state.json"


def _load(run: str) -> dict[str, Any]:
    path = _state_file(run)
    if not path.is_file():
        raise ToolError("bad_input", f"run {run} has no state.json; create runs with round.py start")
    return json.loads(path.read_text(encoding="utf-8"))


def _save(run: str, state: dict[str, Any]) -> None:
    state["updated_at"] = common.utc_iso()
    common.write_atomic(_state_file(run), json.dumps(state, indent=2) + "\n")


def _step(state: dict[str, Any]) -> str:
    if state["status"] == "ended":
        return "ended"
    if state["stopped"]:
        return "verdict"
    return f"round_{state['round']}"


def _view(state: dict[str, Any]) -> dict[str, Any]:
    step = _step(state)
    goal = state.get("goal")
    action = NEXT_ACTION[step]
    if goal is None and step == "round_1":
        action = ASK_GOAL
    return {
        "run": state["run"],
        "ticker": state["ticker"],
        "round": state["round"],
        "max_rounds": MAX_ROUNDS,
        "stop": state["stopped"],
        "status": state["status"],
        "step": step,
        "goal": goal,
        "headline": None if goal is None else ("medium" if goal == "all" else goal),
        "next_action": action,
        "evidence_count": len(common.list_evidence(state["run"])),
    }


def cmd_start(ticker_raw: str, goal: str | None = None) -> tuple[str, list[str], dict[str, Any]]:
    ticker = common.normalize_ticker(ticker_raw)
    run = common.new_run_id()
    now = common.utc_iso()
    state = {
        "run": run, "ticker": ticker, "round": 1, "max_rounds": MAX_ROUNDS,
        "stopped": False, "status": "active", "goal": goal, "created_at": now, "updated_at": now,
        "history": [{"at": now, "event": "start" if goal is None else f"start, goal {goal}"}],
    }
    _save(run, state)
    common.set_current_run(run)
    return run, [], _view(state)


def cmd_status(run: str) -> tuple[str, list[str], dict[str, Any]]:
    return run, [], _view(_load(run))


def cmd_next(run: str) -> tuple[str, list[str], dict[str, Any]]:
    state = _load(run)
    if state["status"] == "ended":
        raise ToolError("bad_input", f"run {run} has ended")
    if state["round"] < MAX_ROUNDS:
        state["round"] += 1
        event = f"round {state['round']}"
    else:
        state["stopped"] = True
        event = "stop"
    state["history"].append({"at": common.utc_iso(), "event": event})
    _save(run, state)
    view = _view(state)
    view["message"] = "STOP: write verdict" if state["stopped"] else f"ROUND {state['round']}/{MAX_ROUNDS}"
    return run, [], view


def cmd_goal(run: str, goal: str) -> tuple[str, list[str], dict[str, Any]]:
    state = _load(run)
    if state["status"] == "ended":
        raise ToolError("bad_input", f"run {run} has ended")
    state["goal"] = goal
    state["history"].append({"at": common.utc_iso(), "event": f"goal {goal}"})
    _save(run, state)
    return run, [], _view(state)


def cmd_end(run: str) -> tuple[str, list[str], dict[str, Any]]:
    state = _load(run)
    if state["status"] != "ended":
        state["status"] = "ended"
        state["history"].append({"at": common.utc_iso(), "event": "end"})
        _save(run, state)
    return run, [], _view(state)


def main(argv: Sequence[str]) -> tuple[str | None, list[str], dict[str, Any]]:
    parser = common.ContractParser(prog="round.py", description="Run lifecycle and round cap.")
    sub = parser.add_subparsers(dest="command", required=True, parser_class=common.ContractParser)
    start = sub.add_parser("start", help="start a new run")
    start.add_argument("ticker")
    start.add_argument("--goal", choices=GOALS, default=None, help="the user's goal, if already known")
    goal = sub.add_parser("goal", help="set the user's goal")
    goal.add_argument("value", choices=GOALS)
    common.add_run_argument(goal)
    for name in ("status", "next", "end"):
        cmd = sub.add_parser(name)
        common.add_run_argument(cmd)
    args = parser.parse_args(list(argv))
    if args.command == "start":
        return cmd_start(args.ticker, args.goal)
    run = common.resolve_run(args.run)
    if args.command == "goal":
        return cmd_goal(run, args.value)
    return {"status": cmd_status, "next": cmd_next, "end": cmd_end}[args.command](run)


if __name__ == "__main__":
    sys.exit(common.run_cli(main))
