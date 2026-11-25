"""Eval Phase 4 protocol check: starting a new run while an earlier run never ended (the ZZZQ setup kickoff, run 0).

Facts the runbook relies on: round start never fails because an earlier run is open, it moves the shared current-run
pointer to the new run, and it leaves the old run's files byte-identical. The chief's `round goal`, `round status` and
`round next` calls carry no --run (chief.md), so they act on whichever run the pointer names: overlapping runs would
write into each other's state, which is why the batch runs one at a time.
"""
from __future__ import annotations

from stockdesk import common
from stockdesk import round as round_tool


def snapshot(run):
    root = common.evidence_root() / run
    return {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def pointer():
    return (common.evidence_root() / "current_run.txt").read_text(encoding="utf-8").strip()


def test_new_run_while_run_0_never_ended():
    _, _, run0 = round_tool.main(["start", "ZZZQ"])          # setup kickoff: never gets a goal, never ends
    zero = run0["run"]
    before = snapshot(zero)
    assert pointer() == zero and run0["status"] == "active"

    _, _, run1 = round_tool.main(["start", "NKE", "--goal", "all"])   # batch run 1
    one = run1["run"]
    assert one != zero and pointer() == one                 # no error; pointer moves to the new run
    assert snapshot(zero) == before                          # run 0's files untouched

    _, _, view = round_tool.main(["next"])                   # no --run, as the chief calls it
    assert view["run"] == one and view["round"] == 2
    assert snapshot(zero) == before

    _, _, old = round_tool.main(["status", "--run", zero])   # run 0 still readable, still open
    assert old["status"] == "active" and old["round"] == 1 and old["ticker"] == "ZZZQ"

    _, _, ended = round_tool.main(["end", "--run", one])
    assert ended["status"] == "ended" and snapshot(zero) == before


def test_a_late_call_without_run_goes_to_the_newest_run():
    """Why one run at a time: a pointer-based call from an older session lands on the newest run."""
    _, _, old = round_tool.main(["start", "ZZZQ"])
    _, _, new = round_tool.main(["start", "NKE"])
    _, _, view = round_tool.main(["goal", "medium"])          # meant for the old run, no --run
    assert view["run"] == new["run"] and view["goal"] == "medium"
    _, _, untouched = round_tool.main(["status", "--run", old["run"]])
    assert untouched["goal"] is None
