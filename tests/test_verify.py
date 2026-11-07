from __future__ import annotations

import json

import pytest

import common
import verify
from common import ToolError


def put(run, fact, value, unit):
    return common.write_evidence(run, tool="t.py", fact=fact, value=value, unit=unit, period="2026-Q1",
                                 source="SEC EDGAR companyfacts", url="https://data.sec.gov/x", locator="loc", source_tier="T1")["id"]


@pytest.fixture
def ledger(run_id):
    ids = {
        "revenue": put(run_id, "Revenue", 12_400_000_000, "USD"),          # E1
        "growth": put(run_id, "Revenue growth YoY", 0.0814, "ratio"),     # E2
        "margin_change": put(run_id, "Gross margin change YoY", -0.0203, "ratio"),  # E3
        "volume": put(run_id, "Volume vs 20-day average", 1.83, "x"),     # E4
        "eps": put(run_id, "Diluted EPS", 1.23, "USD/share"),             # E5
        "rsi": put(run_id, "RSI(14)", 61.4, "index"),                     # E6
        "name": put(run_id, "Latest cross", "golden", "event"),           # E7
    }
    return run_id, ids


def single(run, eid, value, tol=None):
    argv = [eid, "--value", value, "--run", run]
    if tol is not None:
        argv += ["--tol", str(tol)]
    _, _, data = verify.main(argv)
    return data


# ---------------- single mode ----------------

def test_pass_with_rounding_tolerance(ledger):
    run, ids = ledger
    assert single(run, ids["revenue"], "12.4B")["result"] == "PASS"
    assert single(run, ids["growth"], "8.1%")["result"] == "PASS"
    assert single(run, ids["growth"], "0.081")["result"] == "PASS"
    assert single(run, ids["volume"], "1.8x")["result"] == "PASS"
    assert single(run, ids["eps"], "$1.23")["result"] == "PASS"


def test_fail_beyond_rounding_and_returns_stored_value(ledger):
    run, ids = ledger
    data = single(run, ids["revenue"], "12.5B")
    assert data["result"] == "FAIL" and data["stored_value"] == 12_400_000_000
    assert data["unit"] == "USD" and "SEC" in data["source"]
    assert single(run, ids["growth"], "8.3%")["result"] == "FAIL"


def test_unit_normalization_scale_suffixes(ledger):
    run, ids = ledger
    assert single(run, ids["revenue"], "12400M")["result"] == "PASS"
    assert single(run, ids["revenue"], "12,400,000,000")["result"] == "PASS"
    assert single(run, ids["revenue"], "12.4T")["result"] == "FAIL"


def test_bare_number_is_not_guessed_to_be_a_percent(ledger):
    run, ids = ledger
    data = single(run, ids["growth"], "8.1")
    assert data["result"] == "FAIL"


def test_unit_mismatch_is_a_fail(ledger):
    run, ids = ledger
    assert "unit_mismatch" in single(run, ids["revenue"], "8.1%")["reason"]
    assert "unit_mismatch" in single(run, ids["growth"], "1.8x")["reason"]
    assert "unit_mismatch" in single(run, ids["rsi"], "61B")["reason"]


def test_explicit_tolerance_widens_the_match(ledger):
    run, ids = ledger
    assert single(run, ids["revenue"], "12.5B")["result"] == "FAIL"
    assert single(run, ids["revenue"], "12.5B", tol=0.01)["result"] == "PASS"


def test_points_suffix_and_negative_values(ledger):
    run, ids = ledger
    assert single(run, ids["margin_change"], "-2.0 pts")["result"] == "PASS"
    assert single(run, ids["margin_change"], "2.0 pts")["result"] == "FAIL"


def test_missing_id_is_fail_not_found(ledger):
    run, _ = ledger
    data = single(run, "E99", "1.0")
    assert data["result"] == "FAIL" and data["reason"] == "not_found"


def test_non_numeric_stored_value_fails_closed(ledger):
    run, ids = ledger
    assert single(run, ids["name"], "1.0")["reason"] == "stored_value_not_numeric"


def test_bad_arguments(ledger):
    run, _ = ledger
    for argv in ([], ["E1"], ["E1", "--value", "abc", "--run", run], ["E1", "--value", "1", "--text", "x"]):
        with pytest.raises(ToolError) as err:
            verify.main(argv)
        assert err.value.code == "bad_input"


def test_cli_contract_output(ledger, capsys):
    run, ids = ledger
    code = common.run_cli(verify.main, [ids["revenue"], "--value", "12.4B", "--run", run])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0 and payload["ok"] is True and payload["data"]["result"] == "PASS"
    assert payload["evidence"] == [ids["revenue"]]


# ---------------- report mode ----------------

GOOD = """\
[FUNDAMENTAL] NKE — run r-20261105-01
Stance: bearish-leaning
• Revenue +8.1% YoY to $12.4B [E1, E2]
• Gross margin down 2.0 pts [E3]
• Volume 1.8× the 20-day average [E4]
• Diluted EPS $1.23 [E5]
Risk: guidance cut
Gaps: none
"""


def report(run, text, tol=None):
    _, evidence, data = verify.main(["--text", text, "--run", run] + (["--tol", str(tol)] if tol else []))
    return evidence, data


def test_clean_report_passes(ledger):
    run, _ = ledger
    evidence, data = report(run, GOOD)
    assert data["result"] == "PASS", data
    assert data["failed"] == [] and data["uncited"] == [] and data["missing_ids"] == []
    assert data["checked"] == 5 and set(evidence) == {"E1", "E2", "E3", "E4", "E5"}


def test_header_run_id_rounds_and_indicator_names_are_not_flagged(ledger):
    run, _ = ledger
    text = "[ROUND 2/2] @desk-technical: Does the SMA50 cross hold over a 20-day window? RSI(14) check.\n"
    _, data = report(run, text)
    assert data["result"] == "PASS" and data["uncited"] == []


def test_fabricated_number_fails_with_stored_value(ledger):
    run, _ = ledger
    _, data = report(run, "• Revenue +9.9% YoY [E2]\n")
    assert data["result"] == "FAIL"
    failure = data["failed"][0]
    assert failure["number"] == "+9.9%" and failure["stored"][0]["value"] == 0.0814


def test_uncited_number_is_flagged(ledger):
    run, _ = ledger
    _, data = report(run, "• Revenue grew 8.1% year over year\n")
    assert data["result"] == "FAIL" and data["uncited"][0]["number"] == "8.1%"


def test_citing_a_missing_id_fails_even_without_numbers(ledger):
    run, _ = ledger
    _, data = report(run, "• Management tone is cautious [E42]\n")
    assert data["result"] == "FAIL" and data["missing_ids"] == ["E42"]


def test_number_may_match_any_id_cited_on_its_line(ledger):
    run, _ = ledger
    _, data = report(run, "• $12.4B revenue, +8.1% [E2, E1]\n")
    assert data["result"] == "PASS"


def test_direction_warning_when_text_says_down_but_value_positive(ledger):
    run, _ = ledger
    _, data = report(run, "• Revenue fell 8.1% [E2]\n")
    assert data["result"] == "PASS"
    assert data["warnings"] and "positive" in data["warnings"][0]["warning"]


def test_plain_small_integers_are_not_treated_as_claims(ledger):
    run, _ = ledger
    _, data = report(run, "• 3 risks, 2 catalysts, one 14 point checklist\n")
    assert data["result"] == "PASS"


def test_text_file_mode(ledger, tmp_path):
    run, _ = ledger
    path = tmp_path / "report.txt"
    path.write_text(GOOD, encoding="utf-8")
    _, _, data = verify.main(["--text-file", str(path), "--run", run])
    assert data["result"] == "PASS"
    with pytest.raises(ToolError):
        verify.main(["--text-file", str(tmp_path / "nope.txt"), "--run", run])


# ---------------- verification log ----------------

def log(run):
    return common.read_verifications(run)


def test_single_checks_are_logged_and_entries_untouched(ledger):
    run, ids = ledger
    before = (common.evidence_root() / run / f"{ids['growth']}.json").read_text()
    single(run, ids["growth"], "8.1%")
    single(run, ids["growth"], "9.9%")
    records = log(run)
    assert [r["result"] for r in records] == ["PASS", "FAIL"]
    assert records[0]["id"] == ids["growth"] and records[0]["claimed"] == "8.1%"
    assert "stored 0.0814" in records[1]["detail"] and records[1]["checked_at"].endswith("Z")
    assert set(records[0]) == {"id", "claimed", "result", "detail", "checked_at"}
    assert (common.evidence_root() / run / f"{ids['growth']}.json").read_text() == before


def test_not_found_is_logged_as_fail(ledger):
    run, _ = ledger
    single(run, "E999", "1.0")
    assert log(run)[-1]["result"] == "FAIL" and "not_found" in log(run)[-1]["detail"]


def test_withdraw(ledger):
    run, ids = ledger
    single(run, ids["growth"], "9.9%")
    _, evidence, data = verify.main([ids["growth"], "--withdraw", "--run", run])
    assert data["result"] == "WITHDRAWN" and evidence == [ids["growth"]]
    assert log(run)[-1] == {**log(run)[-1], "id": ids["growth"], "claimed": None, "result": "WITHDRAWN"}
    assert data["citations"]["display"] == "0/0" and data["citations"]["withdrawn"] == [ids["growth"]]


@pytest.mark.parametrize("argv", [["E1", "--withdraw", "--value", "1"], ["--withdraw", "--text", "x"]])
def test_withdraw_bad_input(ledger, argv):
    run, _ = ledger
    with pytest.raises(ToolError) as err:
        verify.main(argv + ["--run", run])
    assert err.value.code == "bad_input"


def test_pass_rate_corrected_uncorrected_withdrawn(ledger):
    run, ids = ledger
    single(run, ids["revenue"], "12.4B")                     # PASS
    single(run, ids["growth"], "9.9%")                       # FAIL ...
    single(run, ids["growth"], "8.1%")                       # ... corrected by PASS
    single(run, ids["volume"], "2.5x")                       # FAIL, uncorrected
    single(run, ids["eps"], "9.99")                          # FAIL ...
    verify.main([ids["eps"], "--withdraw", "--run", run])    # ... withdrawn: excluded
    summary = common.citation_summary(run)
    assert summary["display"] == "2/3"
    assert summary["uncorrected"] == [ids["volume"]]
    assert summary["corrected"] == [ids["growth"], ids["eps"]]
    assert summary["withdrawn"] == [ids["eps"]]
    assert summary["all_pass"] is False


def test_pass_rate_with_no_checks(run_id):
    assert common.citation_summary(run_id) == {"checked": 0, "passed": 0, "display": "0/0", "uncorrected": [],
                                               "corrected": [], "withdrawn": [], "all_pass": False}


def test_report_mode_logs_failures_after_passes(ledger):
    run, ids = ledger
    text = (f"Revenue 12.4B [{ids['revenue']}]\n"
            f"Revenue was 13.0B [{ids['revenue']}]\n"     # same ID, wrong number
            f"Volume 1.83x [{ids['volume']}] and EPS 1.23 [E999]")
    verify.main(["--text", text, "--run", run])
    latest = common.latest_verifications(run)
    assert latest[ids["revenue"]]["result"] == "FAIL"   # the failure is not hidden by the earlier pass
    assert latest[ids["volume"]]["result"] == "PASS"
    assert latest["E999"]["result"] == "FAIL" and "not_found" in latest["E999"]["detail"]


def test_torn_log_line_is_an_error(ledger):
    run, ids = ledger
    single(run, ids["revenue"], "12.4B")
    with open(common.evidence_root() / run / "verifications.jsonl", "a") as handle:
        handle.write('{"id": "E1", "res')
    with pytest.raises(ToolError) as err:
        common.read_verifications(run)
    assert err.value.code == "source_unavailable"


# ---------------- advice-word scan (report mode) ----------------

def advice_report(run, text):
    _, _, data = verify.main(["--text", text, "--run", run])
    return data


@pytest.mark.parametrize("text,phrase", [
    ("We would buy here.", "buy"),
    ("BUY now", "buy"),
    ("Time to sell.", "sell"),
    ("Our price target is high.", "price target"),
    ("No price targets given.", "price targets"),
    ("This looks good to buy.", "good to buy"),
    ("A strong buy.", "strong buy"),
    ("Investors should hold.", "should hold"),
    ("Returns are guaranteed.", "guaranteed"),
    ("No guarantee of anything.", "guarantee"),
    ("Good  to\tBuy", "good to buy"),
])
def test_each_banned_phrase_fails(ledger, text, phrase):
    run, _ = ledger
    data = advice_report(run, text)
    assert data["result"] == "FAIL" and data["advice"]["result"] == "FAIL"
    assert [m["phrase"] for m in data["advice"]["matches"]] == [phrase]
    record = common.latest_verifications(run)["ADVICE"]
    assert record["result"] == "FAIL" and record["claimed"] == [phrase] and phrase in record["detail"]


@pytest.mark.parametrize("text", [
    "The sell-off deepened.",
    "A selloff in retail stocks.",
    "The buyback continues.",
    "A buy-back was announced.",
    "Sellers outnumbered buyers.",
    "Shares hold above the 200-day average.",
    "Analysts expect the trend to hold.",
    "Research only, not financial advice.",
])
def test_allowed_words_pass(ledger, text):
    run, _ = ledger
    data = advice_report(run, text)
    assert data["advice"] == {"result": "PASS", "matches": []} and data["result"] == "PASS"
    assert common.latest_verifications(run)["ADVICE"]["result"] == "PASS"


def test_advice_is_logged_but_not_in_the_pass_rate(ledger):
    run, ids = ledger
    data = advice_report(run, f"Revenue 12.4B [{ids['revenue']}]. A strong buy.")
    assert data["result"] == "FAIL" and data["citations"]["display"] == "1/1"
    assert data["citations"]["uncorrected"] == []
    advice_report(run, f"Revenue 12.4B [{ids['revenue']}].")  # rewritten draft
    assert common.latest_verifications(run)["ADVICE"]["result"] == "PASS"


def test_single_check_mode_does_not_scan_or_log_advice(ledger):
    run, ids = ledger
    single(run, ids["revenue"], "12.4B")
    assert "ADVICE" not in common.latest_verifications(run)
