#!/usr/bin/env python3
"""score_runs.py [--root PATH ...] [--out eval/results] [--eval-runs FILE]

Scores every run folder under each evidence root for M1-M7 (eval/METRICS.md) and writes:
  <out>/runs.csv     one row per run
  <out>/reports.csv  one row per report file (the per-report detail behind M3, M5, M6)
  <out>/summary.md   totals, medians and counts with denominators, per set (eval batch, pre-eval runs)

Read-only on real runs. Anything that has to run project code against a run's data (citation summaries, re-verifying
saved report text) works on copies in a temporary STOCKDESK_HOME that is deleted afterwards.
A value that can't be computed is left blank and the reason goes in `notes`. The scorer never guesses a value.

--root defaults to ~/.stockdesk/evidence and the repo's evidence/, whichever exist.
--eval-runs is a text file of run ids (one per line, # comments allowed) that make up the Phase 4 batch.
Stdlib plus this repo's own stockdesk package; no other dependencies.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import json
import os
import re
import shutil
import statistics
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterator

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(HERE))

from stockdesk import common, confidence, verify  # noqa: E402
from stockdesk.common import ToolError  # noqa: E402
import keep_rule  # noqa: E402

HORIZONS = ("short", "medium", "long")
ANALYSTS = ("fundamental", "technical", "sentiment")
REPORT_RE = re.compile(r"^(fundamental|technical|sentiment)-r(\d+)([a-z]*)\.txt$")
CARD_FILE = "card-draft.txt"
RUN_DIR_RE = re.compile(r"^r-(\d{8})-\d{2,}$")

# Inclusion rule, METRICS.md. Fixed lists, written down before scoring.
PRE_EVAL = ("r-20261107-05", "r-20261107-11", "r-20261107-18")
SCRIPTED = {
    "r-20261107-01": "scripted tool check",
    "r-20261107-02": "scripted tool check",
    "r-20261107-07": "scripted tool check",
    "r-20261107-08": "scripted tool check",
}
FIRST_INCLUDED_DATE = "20261107"
LEGACY_NOTE = "log predates source field"

RUN_COLUMNS = [
    "run", "root", "set", "exclusion_reason", "ticker", "goal",
    "m1_completed", "m2_minutes",
    "m3_reports", "m3_checked", "m3_first_pass", "m3_not_checked", "m3_corrections",
    "m4_passed", "m4_checked", "m4_uncorrected", "m4_uncorrected_ids",
    "m5_final_reports", "m5_numbers_first", "m5_uncited_first", "m5_numbers_final", "m5_uncited_final",
    "m5_numbers_median_final", "m5_final_basis",
    "m6_advice_checks", "m6_advice_fails", "m6_last_advice", "m6_card_last", "m6_report_first_fails",
    "m6_report_last_fails",
    "m7_rule", "m7_horizons", "m7_match", "m7b_match",
    "dir_short", "dir_medium", "dir_long", "conf_short", "conf_medium", "conf_long",
    "cap_short", "cap_medium", "cap_long",
    "notes",
]
REPORT_COLUMNS = [
    "run", "set", "file", "analyst", "round", "final_round", "checks",
    "first_result", "first_numbers", "first_uncited", "first_advice",
    "last_result", "last_numbers", "last_uncited", "last_advice", "basis", "notes",
]


# --------------------------------------------------------------------------- helpers

@contextlib.contextmanager
def temp_home() -> Iterator[Path]:
    """A throwaway STOCKDESK_HOME, so project code never reads or writes a real run."""
    old = os.environ.get("STOCKDESK_HOME")
    path = Path(tempfile.mkdtemp(prefix="stockdesk-eval-"))
    os.environ["STOCKDESK_HOME"] = str(path)
    try:
        yield path
    finally:
        if old is None:
            os.environ.pop("STOCKDESK_HOME", None)
        else:
            os.environ["STOCKDESK_HOME"] = old
        shutil.rmtree(path, ignore_errors=True)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_log(path: Path) -> list[dict[str, Any]]:
    """verifications.jsonl rows. Raises ValueError on a line that isn't JSON (reported, never skipped)."""
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"verifications.jsonl line {number} is not JSON") from exc
    return rows


def citation_summary(run: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """stockdesk.common.citation_summary over exactly these rows, on a copy in a temp home."""
    with temp_home() as home:
        run_dir = home / "evidence" / run
        run_dir.mkdir(parents=True)
        (run_dir / common.VERIFICATIONS_FILE).write_text(
            "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        return common.citation_summary(run)


def minutes_between(start: str, end: str) -> float:
    from datetime import datetime
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return round((datetime.strptime(end, fmt) - datetime.strptime(start, fmt)).total_seconds() / 60, 1)


def blank(value: Any) -> Any:
    return "" if value is None else value


# --------------------------------------------------------------------------- report checks from the log

def report_checks(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Group new-format report-mode rows into checks: a contiguous block with one (source, source_sha256),
    closed by its ADVICE row. A block broken by another row before its ADVICE is flagged as interleaved."""
    checks: list[dict[str, Any]] = []
    notes: list[str] = []
    current: dict[str, Any] | None = None
    for index, row in enumerate(rows):
        sha = row.get("source_sha256")
        if sha is None:          # single check, withdrawal, or a legacy row
            if current is not None:
                current["interleaved"] = True
            continue
        key = (row.get("source"), sha)
        if current is not None and current["key"] != key:
            current["interleaved"] = True
            checks.append(current)
            notes.append(f"report check for {current['key'][0]} has no ADVICE row before line {index + 1}")
            current = None
        if current is None:
            current = {"key": key, "source": key[0], "sha": sha, "rows": [], "advice": None, "interleaved": False}
        current["rows"].append(row)
        if row.get("id") == common.ADVICE_ID:
            current["advice"] = row
            checks.append(current)
            current = None
    if current is not None:
        checks.append(current)
        notes.append(f"report check for {current['source']} has no ADVICE row (log ends mid-check)")
    for check in checks:
        advice = check["advice"] or {}
        if not advice:
            check["result"] = None   # incomplete check: not scored
        elif all(r.get("result") != "FAIL" for r in check["rows"]) and advice.get("uncited") == 0:
            check["result"] = "PASS"  # verify.py's data.result rule: no failed, missing or advice row, no uncited
        else:
            check["result"] = "FAIL"
        check["numbers"] = advice.get("numbers")
        check["uncited"] = advice.get("uncited")
        check["advice_result"] = advice.get("result")
    return checks, notes


def reverify_saved_text(run_dir: Path, report: Path) -> dict[str, Any]:
    """verify --text-file on a copy of a saved report and its run's ledger (M5 'final report text')."""
    run = run_dir.name
    with temp_home() as home:
        copy = home / "evidence" / run
        copy.mkdir(parents=True)
        for entry in run_dir.glob("E*.json"):
            shutil.copy2(entry, copy / entry.name)
        _, data = verify.verify_report(run, report.read_text(encoding="utf-8"), None, source=report.name)
    numbers = data["checked"] + len(data["uncited"])
    return {"result": data["result"], "numbers": numbers, "uncited": len(data["uncited"]),
            "advice": data["advice"]["result"]}


# --------------------------------------------------------------------------- one run

def classify(run: str, files: dict[str, bool], completed: bool | None, eval_runs: set[str]) -> tuple[str, str]:
    if run in eval_runs:
        return "eval", ""
    if run in PRE_EVAL:
        return "pre-eval", ""
    match = RUN_DIR_RE.match(run)
    if match and match.group(1) < FIRST_INCLUDED_DATE:
        return "excluded", "before 7 Nov 2026"
    if run in SCRIPTED:
        return "excluded", SCRIPTED[run]
    if not completed:
        return "excluded", "incomplete: no end"
    missing = [name for name in ("verifications.jsonl", "confidence.json") if not files[name]]
    if missing:
        return "excluded", "incomplete: no " + " or ".join(missing)
    return "excluded", "not in the eval batch or the pre-eval set"


def score_run(run_dir: Path, eval_runs: set[str]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    run = run_dir.name
    row: dict[str, Any] = {c: "" for c in RUN_COLUMNS}
    row.update(run=run, root=str(run_dir.parent))
    notes: list[str] = []
    files = {name: (run_dir / name).is_file() for name in ("state.json", "verifications.jsonl", "confidence.json")}

    # M1, M2
    completed = None
    if files["state.json"]:
        try:
            state = read_json(run_dir / "state.json")
            row["ticker"], row["goal"] = blank(state.get("ticker")), blank(state.get("goal"))
            history = state.get("history") or []
            completed = any(h.get("event") == "end" for h in history)
            row["m1_completed"] = "yes" if completed else "no"
            start = next((h["at"] for h in history if str(h.get("event", "")).startswith("start")), None)
            end = next((h["at"] for h in history if h.get("event") == "end"), None)
            if start and end:
                row["m2_minutes"] = minutes_between(start, end)
            else:
                notes.append("M2: no " + ("start" if not start else "end") + " event")
        except (ValueError, KeyError, TypeError) as exc:
            notes.append(f"state.json unreadable: {exc}")
    else:
        notes.append("no state.json")
    row["set"], row["exclusion_reason"] = classify(run, files, completed, eval_runs)

    # Report files
    reports_dir = run_dir / "reports"
    analyst_files = sorted(p for p in reports_dir.glob("*.txt") if REPORT_RE.match(p.name)) if reports_dir.is_dir() else []
    if not reports_dir.is_dir():
        notes.append("no reports/")
    last_round: dict[str, int] = {}
    for path in analyst_files:
        name, rnd, _ = REPORT_RE.match(path.name).groups()
        last_round[name] = max(last_round.get(name, 0), int(rnd))

    # Log
    rows: list[dict[str, Any]] | None = None
    if files["verifications.jsonl"]:
        try:
            rows = read_log(run_dir / "verifications.jsonl")
        except ValueError as exc:
            notes.append(str(exc))
    else:
        notes.append("no verifications.jsonl")
    legacy = rows is not None and bool(rows) and not any("source_sha256" in r for r in rows)
    checks: list[dict[str, Any]] = []
    if rows is not None and not legacy:
        checks, check_notes = report_checks(rows)
        notes.extend(check_notes)
        inline = sum(1 for c in checks if c["source"] is None)
        if inline:
            notes.append(f"{inline} report check(s) by --text or stdin (no source file)")
        known = {p.name for p in analyst_files} | {CARD_FILE}
        stray = sorted({c["source"] for c in checks if c["source"] and c["source"] not in known})
        if stray:
            notes.append("checked sources not in reports/: " + ", ".join(stray))

    # Per report: M3, M5, M6
    report_rows: list[dict[str, Any]] = []
    for path in analyst_files:
        name, rnd, _ = REPORT_RE.match(path.name).groups()
        rep: dict[str, Any] = {c: "" for c in REPORT_COLUMNS}
        rep.update(run=run, set=row["set"], file=path.name, analyst=name, round=int(rnd),
                   final_round="yes" if int(rnd) == last_round[name] else "no")
        mine = [c for c in checks if c["source"] == path.name]
        if rows is None:
            rep["notes"] = "no verifications.jsonl"
        elif legacy:
            rep["notes"] = LEGACY_NOTE
        else:
            rep["checks"] = len(mine)
            if mine:
                first, last = mine[0], mine[-1]
                if first["interleaved"] or first["advice"] is None:
                    rep["notes"] = "first check interleaved or incomplete; not scored"
                else:
                    rep.update(first_result=first["result"], first_numbers=blank(first["numbers"]),
                               first_uncited=blank(first["uncited"]), first_advice=blank(first["advice_result"]))
                if not (last["interleaved"] or last["advice"] is None):
                    rep.update(last_result=last["result"], last_numbers=blank(last["numbers"]),
                               last_uncited=blank(last["uncited"]), last_advice=blank(last["advice_result"]))
                rep["basis"] = "log"
            else:
                rep["first_result"] = "not checked"
        if legacy or rows is None:
            try:
                again = reverify_saved_text(run_dir, path)
                rep.update(last_result=again["result"], last_numbers=again["numbers"],
                           last_uncited=again["uncited"], last_advice=again["advice"], basis="final report text")
            except (ToolError, OSError, UnicodeDecodeError) as exc:
                rep["notes"] = (rep["notes"] + "; " if rep["notes"] else "") + f"re-verify failed: {exc}"
        report_rows.append(rep)

    # M3 (run level)
    row["m3_reports"] = len(analyst_files)
    if rows is None:
        pass
    elif legacy:
        notes.append(f"M3, per-report M5/M6: {LEGACY_NOTE}")
    else:
        scored = [r for r in report_rows if r["first_result"] in ("PASS", "FAIL")]
        row["m3_checked"] = len(scored)
        row["m3_first_pass"] = sum(r["first_result"] == "PASS" for r in scored)
        row["m3_not_checked"] = sum(r["first_result"] == "not checked" for r in report_rows)
        row["m3_corrections"] = sum(max(0, int(r["checks"] or 0) - 1) for r in report_rows)

    # M4
    if rows is not None:
        try:
            summary = citation_summary(run, rows)
            row.update(m4_passed=summary["passed"], m4_checked=summary["checked"],
                       m4_uncorrected=len(summary["uncorrected"]), m4_uncorrected_ids=" ".join(summary["uncorrected"]))
        except ToolError as exc:
            notes.append(f"M4: {exc.detail}")

    # M5 (run level, final-round reports)
    finals = [r for r in report_rows if r["final_round"] == "yes"]
    row["m5_final_reports"] = len(finals) if analyst_files else ""
    if finals:
        firsts = [r for r in finals if r["first_numbers"] != ""]
        if firsts and len(firsts) == len(finals):
            row["m5_numbers_first"] = sum(int(r["first_numbers"]) for r in firsts)
            row["m5_uncited_first"] = sum(int(r["first_uncited"]) for r in firsts)
        lasts = [r for r in finals if r["last_numbers"] != ""]
        if lasts and len(lasts) == len(finals):
            row["m5_numbers_final"] = sum(int(r["last_numbers"]) for r in lasts)
            row["m5_uncited_final"] = sum(int(r["last_uncited"]) for r in lasts)
            row["m5_numbers_median_final"] = round(float(statistics.median(int(r["last_numbers"]) for r in lasts)), 1)
            row["m5_final_basis"] = "last check" if lasts[0]["basis"] == "log" else "final report text"
        elif finals:
            notes.append(f"M5: {len(finals) - len(lasts)} of {len(finals)} final-round reports have no scored check")

    # M6
    if rows is not None:
        advice_rows = [r for r in rows if r.get("id") == common.ADVICE_ID]
        row["m6_advice_checks"] = len(advice_rows)
        row["m6_advice_fails"] = sum(r.get("result") == "FAIL" for r in advice_rows)
        row["m6_last_advice"] = advice_rows[-1]["result"] if advice_rows else ""
        if legacy:
            pass
        else:
            cards = [c for c in checks if c["source"] == CARD_FILE and c["advice"] is not None]
            row["m6_card_last"] = cards[-1]["advice_result"] if cards else "card not checked"
            scored = [r for r in report_rows if r["first_advice"]]
            row["m6_report_first_fails"] = sum(r["first_advice"] == "FAIL" for r in scored)
            row["m6_report_last_fails"] = sum(r["last_advice"] == "FAIL" for r in report_rows if r["last_advice"])

    # M7
    row["m7_rule"] = "CAP" if row["set"] == "eval" else "KEEP"
    rule = confidence.score if row["set"] == "eval" else keep_rule.score
    if files["confidence.json"]:
        try:
            stored = read_json(run_dir / "confidence.json")
        except ValueError:
            stored = None
            notes.append("confidence.json is not JSON")
        if stored is not None:
            horizons = matches = b_checked = b_matches = 0
            for horizon in HORIZONS:
                entry = stored.get(horizon)
                if not isinstance(entry, dict):
                    notes.append(f"M7: no {horizon} in confidence.json")
                    continue
                row[f"dir_{horizon}"], row[f"conf_{horizon}"] = entry.get("direction", ""), entry.get("confidence", "")
                inputs = entry.get("inputs") or {}
                try:
                    passed, checked = (int(x) for x in str(entry["citations"]).split("/"))
                    stances = {k: inputs[k] for k in ("fund", "tech", "sent")}
                    events = inputs.get("precedent_events")
                    precedent = None if events is None else {int(k): v for k, v in events.items()}
                    citations = {"uncorrected": list(entry.get("uncorrected") or []),
                                 "all_pass": checked > 0 and passed == checked}
                except (KeyError, ValueError, AttributeError) as exc:
                    notes.append(f"M7: {horizon} inputs incomplete ({exc})")
                    continue
                horizons += 1
                level, _ = rule(horizon, entry["direction"], stances, precedent, citations)
                if level == entry.get("confidence"):
                    matches += 1
                else:
                    notes.append(f"M7: {horizon} saved {entry.get('confidence')} but {row['m7_rule']} gives {level}")
                row[f"cap_{horizon}"] = confidence.score(horizon, entry["direction"], stances, precedent, citations)[0]
                # M7b: log state at computed_at
                if rows is not None and entry.get("computed_at"):
                    b_checked += 1
                    seen = citation_summary(run, [r for r in rows if str(r.get("checked_at", "")) <= entry["computed_at"]])
                    if seen["display"] == entry["citations"] and seen["uncorrected"] == citations["uncorrected"]:
                        b_matches += 1
                    else:
                        notes.append(f"M7b: {horizon} saved {entry['citations']} {citations['uncorrected']}, "
                                     f"log at computed_at gives {seen['display']} {seen['uncorrected']}")
            row.update(m7_horizons=horizons, m7_match=matches)
            row["m7b_match"] = f"{b_matches}/{b_checked}" if b_checked else ""
    else:
        notes.append("no confidence.json")

    row["notes"] = "; ".join(notes)
    return row, report_rows


# --------------------------------------------------------------------------- summary

def count(k: int, n: int, failures: int | None = None) -> str:
    """'k/n', plus the rule-of-three bound when there were zero failures."""
    text = f"{k}/{n}"
    if failures is None:
        failures = n - k
    if n and failures == 0:
        text += f" (0 failures; 95% upper bound 3/{n})"
    return text


def ints(rows: list[dict[str, Any]], key: str) -> list[int]:
    return [int(r[key]) for r in rows if r[key] != ""]


def spread(values: list[float]) -> str:
    if not values:
        return "no values"
    return (f"median {round(float(statistics.median(values)), 1)} (n={len(values)}, "
            f"min {min(values)}, max {max(values)})")


def summarize(runs: list[dict[str, Any]], reports: list[dict[str, Any]]) -> str:
    import hashlib
    digest = hashlib.sha256(Path(verify.__file__).read_bytes()).hexdigest()[:16]
    lines = ["# Run scores", "", f"Generated by `eval/score_runs.py` (verify.py sha256 {digest}). "
             "Definitions: `eval/METRICS.md`. "
             "Counts are k/n; where there were zero failures the rule-of-three 95% upper bound is given as 3/n.", ""]
    for label, key in (("Eval batch", "eval"), ("Pre-eval runs", "pre-eval")):
        group = [r for r in runs if r["set"] == key]
        reps = [r for r in reports if r["set"] == key]
        lines += [f"## {label}", ""]
        if not group:
            lines += ["No runs.", ""]
            continue
        lines.append(f"Runs: {len(group)} ({', '.join(r['run'] + ' ' + r['ticker'] for r in group)})")
        lines.append("")
        done = [r for r in group if r["m1_completed"] == "yes"]
        lines.append(f"- **M1 completed:** {count(len(done), len(group))}")
        lines.append(f"- **M2 minutes, start to end:** {spread([float(r['m2_minutes']) for r in done if r['m2_minutes'] != ''])}")
        m3 = [r for r in group if r["m3_checked"] != ""]
        if m3:
            first_pass, checked = sum(ints(m3, "m3_first_pass")), sum(ints(m3, "m3_checked"))
            lines.append(f"- **M3 first-pass citation result:** {count(first_pass, checked)} reports passed on first check; "
                         f"not checked {sum(ints(m3, 'm3_not_checked'))}/{sum(ints(m3, 'm3_reports'))}; "
                         f"later checks (corrections) {sum(ints(m3, 'm3_corrections'))}")
            for analyst in ANALYSTS:
                mine = [r for r in reps if r["analyst"] == analyst and r["first_result"] in ("PASS", "FAIL")]
                lines.append(f"  - {analyst}: {count(sum(r['first_result'] == 'PASS' for r in mine), len(mine))}")
        else:
            lines.append(f"- **M3 first-pass citation result:** blank ({LEGACY_NOTE})")
        m4 = [r for r in group if r["m4_checked"] != ""]
        passed, checked = sum(ints(m4, "m4_passed")), sum(ints(m4, "m4_checked"))
        with_unc = sum(1 for r in m4 if int(r["m4_uncorrected"]) > 0)
        lines.append(f"- **M4 final citation pass rate:** {count(passed, checked)} cited IDs; runs with an uncorrected "
                     f"FAIL {count(with_unc, len(m4), failures=with_unc)}")
        finals = [r for r in reps if r["final_round"] == "yes" and r["last_numbers"] != ""]
        basis = sorted({r["basis"] for r in finals})
        nums = [int(r["last_numbers"]) for r in finals]
        unc = sum(int(r["last_uncited"]) for r in finals)
        lines.append(f"- **M5 numbers per final-round report ({' / '.join(basis) or 'no basis'}):** {spread(nums)}; "
                     f"uncited {unc}/{sum(nums)} numbers")
        firsts = [r for r in reps if r["final_round"] == "yes" and r["first_numbers"] != ""]
        if firsts:
            fn = [int(r["first_numbers"]) for r in firsts]
            lines.append(f"  - at first check: {spread(fn)}; uncited {sum(int(r['first_uncited']) for r in firsts)}/{sum(fn)}")
        m6 = [r for r in group if r["m6_advice_checks"] != ""]
        lines.append(f"- **M6 advice scan:** {sum(ints(m6, 'm6_advice_fails'))}/{sum(ints(m6, 'm6_advice_checks'))} "
                     f"ADVICE checks failed; runs whose last ADVICE row passed "
                     f"{count(sum(r['m6_last_advice'] == 'PASS' for r in m6), len(m6))}")
        cards = [r for r in group if r["m6_card_last"] not in ("",)]
        if cards:
            lines.append(f"  - card's last check passed: {count(sum(r['m6_card_last'] == 'PASS' for r in cards), len(cards))}; "
                         f"reports with an ADVICE FAIL on first check {sum(ints(cards, 'm6_report_first_fails'))}; "
                         f"on last check {sum(ints(cards, 'm6_report_last_fails'))}")
        else:
            lines.append(f"  - per report and card: blank ({LEGACY_NOTE})")
        m7 = [r for r in group if r["m7_horizons"] != ""]
        h, m = sum(ints(m7, "m7_horizons")), sum(ints(m7, "m7_match"))
        rules = sorted({r["m7_rule"] for r in m7})
        lines.append(f"- **M7 saved confidence equals {'/'.join(rules)} rule re-run:** {count(m, h)} horizons")
        b = [r["m7b_match"].split("/") for r in m7 if r["m7b_match"]]
        if b:
            bk, bn = sum(int(x[0]) for x in b), sum(int(x[1]) for x in b)
            lines.append(f"  - M7b log state at computed_at matches the saved tally: {count(bk, bn)} horizons")
        for horizon in HORIZONS:
            saved = [r[f"conf_{horizon}"] for r in m7 if r[f"conf_{horizon}"]]
            dist = ", ".join(f"{lvl} {saved.count(lvl)}" for lvl in ("low", "medium", "high"))
            lines.append(f"  - {horizon}: {dist} (n={len(saved)})")
        if "KEEP" in rules:
            changed = [(r["run"], hz, r[f"conf_{hz}"], r[f"cap_{hz}"]) for r in m7 for hz in HORIZONS
                       if r[f"conf_{hz}"] and r[f"cap_{hz}"] != r[f"conf_{hz}"]]
            lines.append(f"  - under the CAP rule instead: {len(changed)}/{h} horizon labels change"
                         + ("" if not changed else ": " + "; ".join(f"{a} {b} {c} → {d}" for a, b, c, d in changed)))
        lines.append("")
    excluded = [r for r in runs if r["set"] == "excluded"]
    lines += ["## Excluded runs", "", f"{len(excluded)} runs, no metrics.", "", "| Run | Ticker | Reason |", "|---|---|---|"]
    lines += [f"| {r['run']} | {r['ticker']} | {r['exclusion_reason']} |" for r in excluded]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- main

def default_roots() -> list[Path]:
    return [p for p in (Path.home() / ".stockdesk" / "evidence", REPO / "evidence") if p.is_dir()]


def read_eval_runs(path: Path | None) -> set[str]:
    if path is None or not path.is_file():
        return set()
    return {line.split("#")[0].strip() for line in path.read_text(encoding="utf-8").splitlines()} - {""}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", action="append", type=Path, help="evidence root (repeatable)")
    parser.add_argument("--out", type=Path, default=HERE / "results")
    parser.add_argument("--eval-runs", type=Path, default=HERE / "results" / "batch_runs.txt")
    args = parser.parse_args(argv)
    roots = args.root or default_roots()
    eval_runs = read_eval_runs(args.eval_runs)
    runs: list[dict[str, Any]] = []
    reports: list[dict[str, Any]] = []
    seen: set[str] = set()
    for root in roots:
        for run_dir in sorted(p for p in root.iterdir() if p.is_dir() and RUN_DIR_RE.match(p.name)):
            if run_dir.name in seen:
                print(f"warning: {run_dir.name} appears under more than one root; scoring the first", file=sys.stderr)
                continue
            seen.add(run_dir.name)
            try:
                row, rep = score_run(run_dir, eval_runs)
            except Exception as exc:  # never crash on one run: blank row with the reason
                row = {c: "" for c in RUN_COLUMNS}
                row.update(run=run_dir.name, root=str(root), set="excluded",
                           exclusion_reason="scorer error", notes=f"scorer error: {type(exc).__name__}: {exc}")
                rep = []
            runs.append(row)
            reports.extend(rep)
    args.out.mkdir(parents=True, exist_ok=True)
    for name, columns, data in (("runs.csv", RUN_COLUMNS, runs), ("reports.csv", REPORT_COLUMNS, reports)):
        with open(args.out / name, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(data)
    (args.out / "summary.md").write_text(summarize(runs, reports), encoding="utf-8")
    print(f"scored {len(runs)} runs, {len(reports)} report files -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
