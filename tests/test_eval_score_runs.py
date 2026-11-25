"""eval/score_runs.py on synthetic runs built with the real tools: one complete, one aborted mid-round.
Every column of runs.csv is checked."""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

import pytest

from stockdesk import common, confidence, verify

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "eval"))
import score_runs  # noqa: E402

COMPLETE, ABORTED, LEGACY = "r-20990101-01", "r-20990101-02", "r-20990101-03"


def put(run, fact, value, unit, tool="t.py"):
    return common.write_evidence(run, tool=tool, fact=fact, value=value, unit=unit, period="2099-Q1", source="s",
                                 url="https://x", locator="l", source_tier="T1")["id"]


def make_run(run, history):
    run_dir = common.evidence_root() / run
    (run_dir / "reports").mkdir(parents=True)
    (run_dir / "state.json").write_text(json.dumps({
        "run": run, "ticker": "TSTCO", "goal": "medium",
        "history": [{"at": at, "event": event} for at, event in history]}), encoding="utf-8")
    return run_dir


def check(run_dir, name, text):
    path = run_dir / "reports" / name
    path.write_text(text, encoding="utf-8")
    verify.main(["--text-file", str(path), "--run", run_dir.name])


def save(run_dir, name, text):
    (run_dir / "reports" / name).write_text(text, encoding="utf-8")


@pytest.fixture
def runs(tmp_path):
    # ---- complete run
    d = make_run(COMPLETE, [("2099-01-01T10:00:00Z", "start"), ("2099-01-01T10:00:30Z", "goal medium"),
                            ("2099-01-01T10:02:00Z", "round 2"), ("2099-01-01T10:04:00Z", "stop"),
                            ("2099-01-01T10:05:30Z", "end")])
    put(COMPLETE, "Revenue", 12_400_000_000, "USD", tool="fund.py")           # E1
    put(COMPLETE, "Revenue growth YoY", 0.0814, "ratio", tool="fund.py")      # E2
    put(COMPLETE, "Close", 61.4, "USD", tool="tech.py")                       # E3
    for window in (5, 30, 90, 250):                                           # E4-E7
        put(COMPLETE, f"Events used, {window}-session window, TSTCO", 4, "count", tool="precedent.py")
    put(COMPLETE, "Average news tone, query 'TSTCO', last 90 days", 0.31, "tone", tool="news.py")   # E8
    check(d, "fundamental-r1.txt", "Revenue $12.4B [E1]; growth 9.9% [E2].\n")      # first check FAIL
    check(d, "fundamental-r1.txt", "Revenue $12.4B [E1]; growth 8.1% [E2].\n")      # correction: PASS
    check(d, "technical-r1.txt", "Close 61.4 [E3].\nVolume ran at 3.3x.\n")          # FAIL: 1 uncited
    save(d, "technical-r1c.txt", "Correction: nothing changes.\n")                   # never checked
    check(d, "sentiment-r1.txt", "Tone is neutral and nothing stands out.\n")        # PASS, 0 numbers
    check(d, "fundamental-r2.txt", "Growth 8.1% [E2].\n")                            # PASS
    check(d, "technical-r2.txt", "Close 61.4 [E3] is the latest.\n")                 # PASS
    check(d, "card-draft.txt", "TSTCO bearish. Growth 8.1% [E2]. A strong buy.\n")   # ADVICE FAIL
    check(d, "card-draft.txt", "TSTCO bearish. Growth 8.1% [E2].\n")                 # rewritten: PASS
    for horizon in ("short", "medium", "long"):
        confidence.main(["--run", COMPLETE, "--horizon", horizon, "--direction", "bullish", "--fund", "bullish",
                         "--tech", "bullish", "--sent", "neutral" if horizon == "long" else "not_measured"])

    # ---- aborted mid-round: no end, the log stops inside a report check, no confidence.json
    a = make_run(ABORTED, [("2099-01-01T11:00:00Z", "start"), ("2099-01-01T11:00:20Z", "goal medium"),
                           ("2099-01-01T11:03:00Z", "round 2")])
    put(ABORTED, "Revenue growth YoY", 0.0814, "ratio")                      # E1
    put(ABORTED, "Close", 61.4, "USD")                                       # E2
    check(a, "fundamental-r1.txt", "Growth 9.9% [E1].\n")                   # FAIL, never corrected
    save(a, "technical-r1.txt", "Close 61.4 [E2].\n")
    common.append_verification(ABORTED, "E2", "61.4", "PASS", "report: matches stored 61.4 USD",
                               source="technical-r1.txt", source_sha256="0" * 64)   # no ADVICE row follows

    # ---- legacy: log rows without source fields (like the 7 Nov runs)
    g = make_run(LEGACY, [("2099-01-01T12:00:00Z", "start"), ("2099-01-01T12:04:00Z", "end")])
    put(LEGACY, "Close", 61.4, "USD")                                        # E1
    save(g, "technical-r1.txt", "Close 61.4 [E1].\nSee https://example.com/news/2586528264\n")
    (g / common.VERIFICATIONS_FILE).write_text(
        json.dumps({"id": "E1", "claimed": "61.4", "result": "PASS", "detail": "report: ok",
                    "checked_at": "2099-01-01T12:01:00Z"}) + "\n"
        + json.dumps({"id": "ADVICE", "claimed": None, "result": "PASS", "detail": "report: no advice words",
                      "checked_at": "2099-01-01T12:01:00Z"}) + "\n", encoding="utf-8")

    batch = tmp_path / "batch_runs.txt"
    batch.write_text(f"# test batch\n{COMPLETE}\n{ABORTED}\n{LEGACY}\n", encoding="utf-8")
    out = tmp_path / "out"
    snapshot = {p: p.read_bytes() for p in common.evidence_root().rglob("*") if p.is_file()}
    assert score_runs.main(["--root", str(common.evidence_root()), "--out", str(out), "--eval-runs", str(batch)]) == 0
    after = {p: p.read_bytes() for p in common.evidence_root().rglob("*") if p.is_file()}
    assert after == snapshot, "the scorer must not write to real runs"
    rows = {r["run"]: r for r in csv.DictReader(open(out / "runs.csv", encoding="utf-8"))}
    reports = {(r["run"], r["file"]): r for r in csv.DictReader(open(out / "reports.csv", encoding="utf-8"))}
    return rows, reports, out


def test_complete_run_every_column(runs):
    rows, _, _ = runs
    root = str(common.evidence_root())
    assert rows[COMPLETE] == {
        "run": COMPLETE, "root": root, "set": "eval", "exclusion_reason": "", "ticker": "TSTCO", "goal": "medium",
        "m1_completed": "yes", "m2_minutes": "5.5",
        # 6 analyst files; technical-r1c never checked; first pass: fund-r2, tech-r2, sent-r1; one correction
        "m3_reports": "6", "m3_checked": "5", "m3_first_pass": "3", "m3_not_checked": "1", "m3_corrections": "1",
        # E1 PASS, E2 FAIL then PASS, E3 PASS; uncited numbers are not IDs
        "m4_passed": "3", "m4_checked": "3", "m4_uncorrected": "0", "m4_uncorrected_ids": "",
        # final round: fundamental-r2 (1 number), technical-r2 (1), sentiment-r1 (0)
        "m5_final_reports": "3", "m5_numbers_first": "2", "m5_uncited_first": "0", "m5_numbers_final": "2",
        "m5_uncited_final": "0", "m5_numbers_median_final": "1.0", "m5_final_basis": "last check",
        # 8 report checks; the first card had advice words, the rewrite passed
        "m6_advice_checks": "8", "m6_advice_fails": "1", "m6_last_advice": "PASS", "m6_card_last": "PASS",
        "m6_report_first_fails": "0", "m6_report_last_fails": "0",
        # CAP: short/medium would be high but sentiment is not measured; long hits its own cap
        "m7_rule": "CAP", "m7_horizons": "3", "m7_match": "3", "m7b_match": "3/3",
        "dir_short": "bullish", "dir_medium": "bullish", "dir_long": "bullish",
        "conf_short": "medium", "conf_medium": "medium", "conf_long": "medium",
        "cap_short": "medium", "cap_medium": "medium", "cap_long": "medium",
        # fund/tech stances with fund.py/tech.py entries; sentiment not_measured short/medium, neutral long + tone entry
        "m12_checks": "9", "m12_match": "9", "m12_nodata_with_entries": "0",
        "notes": "",
    }


def test_aborted_run_every_column(runs):
    rows, _, _ = runs
    assert rows[ABORTED] == {
        "run": ABORTED, "root": str(common.evidence_root()), "set": "eval", "exclusion_reason": "",
        "ticker": "TSTCO", "goal": "medium",
        "m1_completed": "no", "m2_minutes": "",
        "m3_reports": "2", "m3_checked": "1", "m3_first_pass": "0", "m3_not_checked": "0", "m3_corrections": "0",
        "m4_passed": "1", "m4_checked": "2", "m4_uncorrected": "1", "m4_uncorrected_ids": "E1",
        "m5_final_reports": "2", "m5_numbers_first": "", "m5_uncited_first": "", "m5_numbers_final": "",
        "m5_uncited_final": "", "m5_numbers_median_final": "", "m5_final_basis": "",
        "m6_advice_checks": "1", "m6_advice_fails": "0", "m6_last_advice": "PASS", "m6_card_last": "card not checked",
        "m6_report_first_fails": "0", "m6_report_last_fails": "0",
        "m7_rule": "CAP", "m7_horizons": "", "m7_match": "", "m7b_match": "",
        "dir_short": "", "dir_medium": "", "dir_long": "", "conf_short": "", "conf_medium": "", "conf_long": "",
        "cap_short": "", "cap_medium": "", "cap_long": "",
        "m12_checks": "", "m12_match": "", "m12_nodata_with_entries": "",
        "notes": "M2: no end event; report check for technical-r1.txt has no ADVICE row (log ends mid-check); "
                 "M5: 1 of 2 final-round reports have no scored check; no confidence.json",
    }


def test_report_rows(runs):
    _, reports, _ = runs
    first = reports[(COMPLETE, "fundamental-r1.txt")]
    assert (first["checks"], first["first_result"], first["last_result"], first["final_round"]) == ("2", "FAIL", "PASS", "no")
    assert reports[(COMPLETE, "technical-r1.txt")]["first_uncited"] == "1"
    assert reports[(COMPLETE, "technical-r1c.txt")]["first_result"] == "not checked"
    assert reports[(ABORTED, "technical-r1.txt")]["notes"] == "first check interleaved or incomplete; not scored"


def test_legacy_log_leaves_m3_blank_and_reverifies_saved_text(runs):
    rows, reports, _ = runs
    row = rows[LEGACY]
    assert row["m3_reports"] == "1" and row["m3_checked"] == "" and row["m3_first_pass"] == ""
    assert "log predates source field" in row["notes"]
    rep = reports[(LEGACY, "technical-r1.txt")]
    assert rep["basis"] == "final report text" and rep["first_result"] == ""
    # The URL's digits are not a number (verify.py fix; before it, this was ("2", "1")).
    assert (rep["last_numbers"], rep["last_uncited"]) == ("1", "0")
    assert row["m5_final_basis"] == "final report text" and row["m6_card_last"] == ""


def test_summary_counts_have_denominators(runs):
    _, _, out = runs
    text = (out / "summary.md").read_text(encoding="utf-8")
    assert "- **M1 completed:** 2/3" in text
    assert "M7 saved confidence equals CAP rule re-run:** 3/3 (0 failures; 95% upper bound 3/3) horizons" in text
    assert "%" not in text.replace("95% upper bound", "")   # results are counts, never percentages


@pytest.mark.parametrize("run,files,completed,expected", [
    ("r-20261105-01", {"verifications.jsonl": True, "confidence.json": True}, True, ("excluded", "before 7 Nov 2026")),
    ("r-20261107-07", {"verifications.jsonl": True, "confidence.json": True}, True, ("excluded", "scripted tool check")),
    ("r-20261107-05", {"verifications.jsonl": True, "confidence.json": True}, True, ("pre-eval", "")),
    ("r-20261107-03", {"verifications.jsonl": False, "confidence.json": False}, True,
     ("excluded", "incomplete: no verifications.jsonl or confidence.json")),
    ("r-20261107-99", {"verifications.jsonl": True, "confidence.json": True}, False, ("excluded", "incomplete: no end")),
    ("r-20261201-01", {"verifications.jsonl": True, "confidence.json": True}, True, ("eval", "")),
])
def test_inclusion_rule(run, files, completed, expected):
    assert score_runs.classify(run, files, completed, {"r-20261201-01"}) == expected


def test_keep_rule_is_the_7_nov_rule():
    """Frozen copy: not_measured alone leaves high reachable (KEEP); the current rule caps it (CAP)."""
    import keep_rule
    args = ("medium", "bullish", {"fund": "bullish", "tech": "bullish", "sent": "not_measured"},
            {5: 4, 30: 4, 90: 4, 250: 4}, {"uncorrected": [], "all_pass": True})
    assert keep_rule.score(*args)[0] == "high" and confidence.score(*args)[0] == "medium"


# ---------------- M12: analyst status passed to confidence.py vs the ledger ----------------

FULL = {"fund.py": 3, "tech.py": 2, "news.py": 5}


@pytest.mark.parametrize("horizon,inputs,tools,tone,expected", [
    ("medium", {"fund": "bullish", "tech": "bullish", "sent": "not_measured"}, FULL, True, [True, True, True]),
    ("long", {"fund": "bullish", "tech": "bullish", "sent": "neutral"}, FULL, True, [True, True, True]),
    # sentiment passed as measured while news.py wrote nothing (the M12 example)
    ("long", {"fund": "bullish", "tech": "bullish", "sent": "neutral"}, {"fund.py": 3, "tech.py": 2}, False, [True, True, False]),
    # a measured short-term sentiment: news.py measures no short window
    ("short", {"fund": "bullish", "tech": "bullish", "sent": "positive"}, FULL, True, [True, True, False]),
    # no_data for long while the tone entry exists
    ("long", {"fund": "bullish", "tech": "bullish", "sent": "no_data"}, FULL, True, [True, True, False]),
    # no_data for long with no tone entry (GDELT refused): a match
    ("long", {"fund": "bullish", "tech": "bullish", "sent": "no_data"}, FULL, False, [True, True, True]),
    # stances with an empty ledger (r-20261107-07)
    ("short", {"fund": "bearish", "tech": "bearish", "sent": "not_measured"}, {}, False, [False, False, True]),
])
def test_m12_rules(horizon, inputs, tools, tone, expected):
    assert [ok for _, ok, _, _ in score_runs.m12_checks(horizon, inputs, tools, tone)] == expected


def test_m12_no_data_with_entries_is_a_match_listed_for_review():
    checks = score_runs.m12_checks("medium", {"fund": "no_data", "tech": "no_data", "sent": "no_data"}, FULL, True)
    assert [(a, ok, nd) for a, ok, nd, _ in checks] == [("fund", True, True), ("tech", True, True), ("sent", True, False)]
