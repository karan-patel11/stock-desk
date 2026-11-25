"""Fail-closed cases (eval Phase 3, M9). Offline: recorded and synthetic fixtures only.

Each case: input -> the tool result the code gives NOW -> the effect on confidence. Where current behaviour differs
from the Phase 3 spec, the test asserts current behaviour and its docstring says so (decided 24 Nov 2026: test current
behaviour, report the difference in docs/EVALUATION.md). Test names start with fc<case>_ so eval/fail_closed.py can
group them. Case 6 documents a known limitation and is reported as "documented", not as pass or fail.
"""
from __future__ import annotations

import itertools
import json
from datetime import date

import pytest

from stockdesk import common, confidence, fund, news, tech
from stockdesk import round as round_tool
from stockdesk.common import ToolError
from test_fund import TODAY, sec  # noqa: F401  (fixture: SEC routed to the synthetic filer)
from test_news import gdelt  # noqa: F401  (fixture: GDELT routed to canned responses)
from test_tech import make_frame

REVENUE_TAGS = ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
                "RevenueFromContractWithCustomerIncludingAssessedTax")
PRECEDENT_OK = {5: 4, 30: 4, 90: 4, 250: 4}
ALL_PASS = {"uncorrected": [], "all_pass": True}


def level(horizon, stances, direction="bullish", precedent=PRECEDENT_OK, citations=ALL_PASS):
    return confidence.score(horizon, direction, stances, precedent, citations)[0]


RANK = {"low": 0, "medium": 1, "high": 2}


def latest(data):
    return next(q for q in data["quarters"] if q["end"] == data["latest_quarter_end"])


# ---------------- case 1: bank (JPM-style revenue tag) ----------------

def test_fc1_jpm_style_bank_revenue_no_data_net_income_and_eps_kept(sec, run_id):
    """JPM: quarterly us-gaap:Revenues stops in 2014; current revenue is RevenuesNetOfInterestExpense, which fund.py
    does not read. Revenue is unavailable as stale; net income and EPS are still reported. Matches the spec."""
    _, install = sec

    def jpm(facts):
        gaap = facts["facts"]["us-gaap"]
        current = None
        for tag in REVENUE_TAGS:
            if tag in gaap:
                current = gaap.pop(tag)
        gaap["RevenuesNetOfInterestExpense"] = json.loads(json.dumps(current))
        old = json.loads(json.dumps(current))
        old["units"]["USD"] = [f for f in old["units"]["USD"] if f["end"] <= "2024-11-30"]
        gaap["Revenues"] = old   # the legacy tag, stale
    install(jpm)
    _, _, data = fund.main(["TSTCO", "--run", run_id], today=TODAY)
    assert any(u["metric"] == "revenue" and u["reason"].endswith("; stale") for u in data["unavailable"])
    row = latest(data)
    assert "revenue" not in row["metrics"] and {"net_income", "eps_diluted"} <= set(row["metrics"])


def test_fc1_bank_without_a_legacy_revenue_tag_loses_every_metric(sec, run_id):
    """DIFFERS FROM SPEC: a bank whose only revenue tag is RevenuesNetOfInterestExpense gets no_data for the whole
    tool ("no quarterly revenue found"), so net income and EPS are not reported either. Still fails closed."""
    _, install = sec

    def bank(facts):
        gaap = facts["facts"]["us-gaap"]
        for tag in REVENUE_TAGS:
            if tag in gaap:
                gaap["RevenuesNetOfInterestExpense"] = gaap.pop(tag)
    install(bank)
    with pytest.raises(ToolError) as err:
        fund.main(["TSTCO", "--run", run_id], today=TODAY)
    assert err.value.code == "no_data" and err.value.detail == "no quarterly revenue found for TSTCO"
    assert_profile_entries_only(run_id)


def assert_profile_entries_only(run_id):
    """Found in Phase 3: fund.py writes the filer's SIC code and fiscal year end before it refuses, so a refused call
    still leaves 2 fund.py entries in the ledger. No financial metric is written."""
    facts = [e["fact"] for e in common.list_evidence(run_id)]
    assert facts == ["SIC code, TSTCO", "Fiscal year end (MMDD), TSTCO"]


@pytest.mark.parametrize("horizon", ["medium", "long"])
def test_fc1_confidence_is_lowered_only_when_the_chief_passes_no_data(horizon):
    """DIFFERS FROM SPEC: nothing in code links fund.py's partial no_data to confidence. Confidence drops only if the
    fundamental stance passed is no_data (chief.md maps a tool error to no_data). Then it is -1 and capped."""
    measured = level(horizon, {"fund": "bullish", "tech": "bullish", "sent": "neutral"})
    missing = level(horizon, {"fund": "no_data", "tech": "bullish", "sent": "neutral"})
    assert RANK[missing] < RANK[measured] and missing == "low"


# ---------------- case 2: unknown ticker ----------------

def test_fc2_unknown_ticker_is_no_data_exit_1(sec, run_id, capsys):
    """DIFFERS FROM SPEC (spec: bad_input). A well-formed ticker that is not in the SEC ticker map is no_data."""
    code = common.run_cli(lambda argv: fund.main(argv, today=TODAY), ["ZZZQ", "--run", run_id])
    out = json.loads(capsys.readouterr().out)
    assert code == 1 and out == {"ok": False, "error": "no_data", "detail": "ZZZQ is not in the SEC ticker map"}


def test_fc2_malformed_ticker_is_bad_input_exit_1(run_id, capsys):
    code = common.run_cli(lambda argv: fund.main(argv, today=TODAY), ["1BAD!", "--run", run_id])
    out = json.loads(capsys.readouterr().out)
    assert code == 1 and out["error"] == "bad_input"


def test_fc2_a_run_can_start_for_an_unknown_ticker_but_gets_no_confidence():
    """round start checks the ticker's form only. With no evidence, confidence.py refuses (fixed 24 Nov 2026)."""
    _, _, state = round_tool.main(["start", "ZZZQ"])
    with pytest.raises(ToolError) as err:
        confidence.main(["--run", state["run"], "--horizon", "medium", "--direction", "bullish",
                         "--fund", "no_data", "--tech", "no_data", "--sent", "no_data"])
    assert err.value.code == "no_data"


# ---------------- case 3: GDELT HTTP 429 ----------------

def test_fc3_gdelt_429_is_rate_limited_and_not_retried(gdelt, run_id):
    calls, state = gdelt
    state["articles_status"] = 429
    with pytest.raises(ToolError) as err:
        news.main(["--ticker", "NKE", "--days", "90", "--run", run_id])
    assert err.value.code == "rate_limited" and len(calls) == 1
    assert not [e for e in common.list_evidence(run_id) if e["tool"] == "news.py"]


def test_fc3_sentiment_never_raises_any_horizon():
    """Every combination of horizon, direction, fund/tech stance, precedent and citations: no sentiment value gives a
    higher label than neutral, and no_data (what the chief passes after rate_limited) is strictly lower than any
    medium or high."""
    stances = ("bullish", "bearish", "neutral", "no_data")
    precedents = (PRECEDENT_OK, {5: 1, 30: 1, 90: 1, 250: 1}, None)
    citations = (ALL_PASS, {"uncorrected": [], "all_pass": False}, {"uncorrected": ["E1"], "all_pass": False})
    checked = 0
    for horizon, direction, f, t, p, c in itertools.product(("short", "medium", "long"), ("bullish", "bearish", "neutral"),
                                                           stances, stances, precedents, citations):
        base = RANK[level(horizon, {"fund": f, "tech": t, "sent": "neutral"}, direction, p, c)]
        for sent in confidence.SENTIMENTS:
            assert RANK[level(horizon, {"fund": f, "tech": t, "sent": sent}, direction, p, c)] <= base
        missing = RANK[level(horizon, {"fund": f, "tech": t, "sent": "no_data"}, direction, p, c)]
        assert missing < base or base == 0
        checked += 1
    assert checked == 3 * 3 * 4 * 4 * 3 * 3


# ---------------- case 4: stale EPS ----------------

def test_fc4_stale_eps_is_no_data_never_current(sec, run_id):
    """EPS whose latest quarter is past the 200-day limit is listed as stale and absent from every quarter; it is
    never filled from an annual value. Other fresh metrics stay. Matches the spec."""
    _, install = sec

    def stop_eps(facts):
        node = facts["facts"]["us-gaap"]["EarningsPerShareDiluted"]["units"]["USD/shares"]
        node[:] = [f for f in node if f["end"] <= "2025-11-30" or (f.get("start") and
                   (date.fromisoformat(f["end"]) - date.fromisoformat(f["start"])).days > 300)]
    install(stop_eps)
    _, _, data = fund.main(["TSTCO", "--run", run_id], today=TODAY)
    assert {"metric": "eps_diluted", "reason": "latest quarterly value ends 2025-11-30; stale"} in data["unavailable"]
    assert all("eps_diluted" not in q["metrics"] for q in data["quarters"])
    assert "revenue" in latest(data)["metrics"]
    assert not [e for e in common.list_evidence(run_id) if "EPS" in e["fact"]]


# ---------------- case 5: foreign filer ----------------

def test_fc5_20f_filer_with_us_gaap_fails_closed_without_saying_why(sec, run_id):
    """DIFFERS FROM SPEC (spec: a clear detail). A 20-F filer's us-gaap facts are all annual 20-F forms, which fund.py
    filters out (10-Q/10-K only), so it fails closed with no_data, but the detail does not mention 20-F or a foreign
    filer. Future fix, not built: say so in the detail."""
    _, install = sec

    def to_20f(facts):
        for node in facts["facts"]["us-gaap"].values():
            for items in node["units"].values():
                for item in items:
                    item["form"] = "20-F"
    install(to_20f)
    with pytest.raises(ToolError) as err:
        fund.main(["TSTCO", "--run", run_id], today=TODAY)
    assert err.value.code == "no_data" and err.value.detail == "no quarterly revenue found for TSTCO"
    assert "20-F" not in err.value.detail and "foreign" not in err.value.detail
    assert_profile_entries_only(run_id)


def test_fc5_ifrs_only_filer_fails_closed_with_a_clear_detail(sec, run_id):
    _, install = sec
    install(lambda facts: facts["facts"].update({"ifrs-full": facts["facts"].pop("us-gaap")}))
    with pytest.raises(ToolError) as err:
        fund.main(["TSTCO", "--run", run_id], today=TODAY)
    assert err.value.code == "no_data" and "foreign filer" in err.value.detail


# ---------------- case 6: partial bar (known limitation, documented) ----------------

def test_fc6_documented_partial_bar_is_reported_as_the_last_close(monkeypatch, run_id):
    """KNOWN LIMITATION, not fixed: a bar from a session still trading (dated today, fetched 15:30 UTC) is reported
    as last_close with as_of today and nothing in the output marks it as partial."""
    frame = make_frame(end="2026-11-04")
    monkeypatch.setattr(common, "fetch_prices", lambda ticker, **kw: (frame, "2026-11-04T15:30:00Z"))
    _, _, data = tech.main(["TSTCO", "--run", run_id, "--lookback", "2y"], today=date(2026, 11, 4))
    assert data["as_of"] == "2026-11-04"
    assert data["metrics"]["last_close"]["value"] == pytest.approx(float(frame["Close"].iloc[-1]), abs=1e-6)
    assert "partial" not in json.dumps(data).lower()
