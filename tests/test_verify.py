from __future__ import annotations

import json

import pytest

import common
import verify
from common import ToolError


def put(run, fact, value, unit):
    return common.write_evidence(run, tool="t.py", fact=fact, value=value, unit=unit, period="2026-Q1",
                                 source="SEC EDGAR companyfacts", url="https://data.sec.gov/x", locator="loc")["id"]


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
