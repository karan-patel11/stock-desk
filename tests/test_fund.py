from __future__ import annotations

import json

import pytest
import requests

import common
import fund
from common import ToolError

CIK10 = "0001234567"
URLS = {
    "tickers": fund.TICKERS_URL,
    "subs": fund.SUBMISSIONS_URL.format(cik=CIK10),
    "facts": fund.FACTS_URL.format(cik=CIK10),
}


class Resp:
    def __init__(self, text, status=200):
        self.text, self.status_code, self.headers = text, status, {}


@pytest.fixture
def sec(monkeypatch, fixtures_dir):
    """Route SEC URLs to the synthetic fixtures. Returns (calls, install) where install(tweak) rebuilds routes."""
    calls: list[tuple[str, str]] = []
    state: dict = {}

    def install(tweak=None):
        facts = json.loads((fixtures_dir / "synthetic_companyfacts_tstco.json").read_text())
        if tweak:
            tweak(facts)
        state["routes"] = {
            URLS["tickers"]: (fixtures_dir / "synthetic_company_tickers.json").read_text(),
            URLS["subs"]: (fixtures_dir / "synthetic_submissions_tstco.json").read_text(),
            URLS["facts"]: json.dumps(facts),
        }

    def fake_get(url, headers=None, timeout=None):
        calls.append((url, headers["User-Agent"]))
        body = state["routes"].get(url)
        return Resp(body) if body is not None else Resp("not found", 404)

    monkeypatch.setattr(common, "_requests_get", fake_get)
    install()
    return calls, install


def run_fund(run, *extra):
    return fund.main(["TSTCO", "--run", run, *extra])


def row(data, end):
    return next(q for q in data["quarters"] if q["end"] == end)


# ---------------- happy path ----------------

def test_latest_quarter_values_growth_and_margins(sec, run_id):
    _, ids, data = run_fund(run_id)
    assert data["latest_quarter_end"] == "2026-08-31" and len(data["quarters"]) == 8
    latest = row(data, "2026-08-31")
    assert latest["metrics"]["revenue"]["value"] == 1_166_400_000
    assert latest["metrics"]["gross_profit"]["value"] == 443_232_000
    assert latest["metrics"]["eps_diluted"]["value"] == pytest.approx(0.9331)
    assert latest["metrics"]["total_debt"]["value"] == 560_000_000
    assert latest["yoy"]["revenue"]["value"] == pytest.approx(0.08)
    assert latest["margins"]["gross_margin"]["value"] == pytest.approx(0.38)
    assert latest["margin_change"]["gross_margin"]["value"] == pytest.approx(-0.02)
    assert latest["margin_change"]["operating_margin"]["value"] == pytest.approx(0.01)
    assert ids == [e["id"] for e in common.list_evidence(run_id)]


def test_yoy_only_where_the_prior_year_quarter_is_in_the_window(sec, run_id):
    _, _, data = run_fund(run_id)
    with_yoy = [q["end"] for q in data["quarters"] if q["yoy"]]
    assert with_yoy == ["2025-11-30", "2026-02-28", "2026-05-31", "2026-08-31"]


def test_derived_q4_is_fy_minus_nine_months_with_both_inputs_in_the_ledger(sec, run_id):
    _, _, data = run_fund(run_id)
    q4 = row(data, "2026-05-31")["metrics"]["revenue"]
    assert q4["derived_q4"] is True and q4["value"] == 1_400_000_000   # 4,920M - 3,520M
    entry = common.read_evidence(run_id, q4["id"])
    assert len(entry["derived_from"]) == 2 and "derived" in entry["source"]
    inputs = [common.read_evidence(run_id, i) for i in entry["derived_from"]]
    assert sorted(i["value"] for i in inputs) == [3_520_000_000, 4_920_000_000]
    assert {i["fact"].split(" ended")[0].split(", TSTCO ")[1] for i in inputs} == {"fiscal year", "nine months"}
    assert entry["period"] == "2026-03-01/2026-05-31"


def test_q4_eps_is_never_derived(sec, run_id):
    _, _, data = run_fund(run_id)
    assert "eps_diluted" not in row(data, "2026-05-31")["metrics"]
    reasons = {u["metric"]: u["reason"] for u in data["unavailable"]}
    assert "not derivable" in reasons["eps_diluted@2026-05-31"]


def test_tags_are_merged_across_a_tag_change(sec, run_id):
    _, _, data = run_fund(run_id, "--quarters", "12")
    assert data["tags_used"]["revenue"] == ["RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"]
    oldest = row(data, "2024-02-29")["metrics"]["revenue"]
    assert oldest["value"] == 1_000_000_000
    assert common.read_evidence(run_id, oldest["id"])["locator"].startswith("us-gaap:SalesRevenueNet")


def test_evidence_entries_are_complete_and_traceable(sec, run_id):
    _, ids, data = run_fund(run_id)
    entries = common.list_evidence(run_id)
    assert len({e["id"] for e in entries}) == len(entries)
    for entry in entries:
        assert tuple(entry.keys()) == common.EVIDENCE_FIELDS
        assert entry["tool"] == "fund.py" and entry["retrieved_at"].endswith("Z")
        for parent in entry["derived_from"]:
            assert common.read_evidence(run_id, parent) is not None
    raw = common.read_evidence(run_id, row(data, "2026-08-31")["metrics"]["revenue"]["id"])
    assert raw["unit"] == "USD" and raw["source"] == "SEC EDGAR companyfacts, 10-Q"
    assert raw["url"].endswith("CIK0001234567.json") and raw["locator"] == "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax, accn 0001234567-26-000111"
    growth = common.read_evidence(run_id, row(data, "2026-08-31")["yoy"]["revenue"]["id"])
    assert growth["unit"] == "ratio" and len(growth["derived_from"]) == 2
    assert growth["source"].startswith("Derived by fund.py")
    assert raw["source_tier"] == "T1" and growth["source_tier"] == "T1"
    curated = {data.get("sector_etf_id"), data.get("peers_id")} - {None}
    for entry in entries:
        assert entry["source_tier"] == ("unrated" if entry["id"] in curated else "T1")


def test_sic_peers_and_sector_etf(sec, run_id, _isolated_home):
    _, _, data = run_fund(run_id)
    assert data["sic"] == "3021" and data["fiscal_year_end"] == "0531"
    assert common.read_evidence(run_id, data["sic_id"])["value"] == 3021
    assert data["peers"] == [] and any(u["metric"] == "peers" for u in data["unavailable"])
    assert data["sector_etf"] is None and any(u["metric"] == "sector_etf" for u in data["unavailable"])


def test_configured_peers_and_etf_are_returned_with_evidence(sec, run_id, _isolated_home):
    (_isolated_home / "config" / "peers.json").write_text(json.dumps({"TSTCO": ["AAA", "BBB"]}))
    (_isolated_home / "config" / "sector_etf.json").write_text(json.dumps({"overrides": {"TSTCO": "XLY"}, "sic_ranges": []}))
    _, _, data = run_fund(run_id)
    assert data["peers"] == ["AAA", "BBB"] and data["sector_etf"] == "XLY"
    assert common.read_evidence(run_id, data["peers_id"])["value"] == "AAA,BBB"
    assert common.read_evidence(run_id, data["sector_etf_id"])["source"].startswith("config/sector_etf.json")


def test_sec_requests_carry_the_configured_user_agent_and_hit_expected_urls(sec, run_id):
    calls, _ = sec
    run_fund(run_id)
    assert [u for u, _ in calls] == [URLS["tickers"], URLS["subs"], URLS["facts"]]
    assert {ua for _, ua in calls} == {"StockDeskTest tester@stockdesk.test"}


def test_second_run_uses_the_cache(sec, run_id):
    calls, _ = sec
    run_fund(run_id)
    run_fund(run_id)
    assert len(calls) == 3


# ---------------- fail closed ----------------

def test_missing_gross_profit_tag_is_reported_not_guessed(sec, run_id):
    _, install = sec
    install(lambda facts: facts["facts"]["us-gaap"].pop("GrossProfit"))
    _, _, data = run_fund(run_id)
    assert any(u["metric"] == "gross_profit" for u in data["unavailable"])
    latest = row(data, "2026-08-31")
    assert "gross_profit" not in latest["metrics"] and "gross_margin" not in latest["margins"]
    assert latest["margins"]["operating_margin"]["value"] == pytest.approx(0.11)


def _split_debt(facts, drop_current_at=None):
    """Nike-style filer: LongTermDebt only at fiscal year end, current + noncurrent every quarter."""
    g = facts["facts"]["us-gaap"]
    items = g["LongTermDebt"]["units"]["USD"]
    current = [dict(i, val=100_000_000) for i in items if i["end"] != drop_current_at]
    noncurrent = [dict(i, val=i["val"] - 100_000_000) for i in items]
    g["LongTermDebtCurrent"] = {"units": {"USD": current}}
    g["LongTermDebtNoncurrent"] = {"units": {"USD": noncurrent}}
    g["LongTermDebt"]["units"]["USD"] = [i for i in items if i["form"] == "10-K"]


def test_total_debt_falls_back_to_current_plus_noncurrent(sec, run_id):
    _, install = sec
    install(_split_debt)
    _, _, data = run_fund(run_id)
    latest = row(data, "2026-08-31")["metrics"]["total_debt"]
    assert latest["value"] == 560_000_000 and latest["derived_from_parts"]
    stored = common.read_evidence(run_id, latest["id"])
    assert len(stored["derived_from"]) == 2
    parts = [common.read_evidence(run_id, i)["value"] for i in stored["derived_from"]]
    assert sum(parts) == 560_000_000
    assert "LongTermDebtNoncurrent" in data["tags_used"]["total_debt"]
    assert not any(u["metric"].startswith("total_debt") for u in data["unavailable"])


def test_total_debt_stays_unavailable_when_a_part_is_missing(sec, run_id):
    _, install = sec
    install(lambda facts: _split_debt(facts, drop_current_at="2026-08-31"))
    _, _, data = run_fund(run_id)
    assert "total_debt" not in row(data, "2026-08-31")["metrics"]
    assert {"metric": "total_debt@2026-08-31", "reason": "no value for this period"} in data["unavailable"]


def test_non_positive_prior_value_makes_growth_undefined(sec, run_id):
    _, install = sec

    def tweak(facts):
        for item in facts["facts"]["us-gaap"]["NetIncomeLoss"]["units"]["USD"]:
            if item["end"] == "2025-02-28" and item["fp"] == "Q3" and item["start"] == "2024-12-01":
                item["val"] = -5_000_000
    install(tweak)
    _, _, data = run_fund(run_id)
    assert "net_income" not in row(data, "2026-02-28")["yoy"]
    assert any(u["metric"] == "net_income_yoy@2026-02-28" and "not positive" in u["reason"] for u in data["unavailable"])
    assert "revenue" in row(data, "2026-02-28")["yoy"]


def test_too_few_quarters_for_yoy_is_stated(sec, run_id):
    _, _, data = run_fund(run_id, "--quarters", "3")
    assert all(q["yoy"] == {} for q in data["quarters"])
    assert any(u["metric"] == "yoy" for u in data["unavailable"])


def test_unknown_ticker_is_no_data(sec, run_id):
    with pytest.raises(ToolError) as err:
        fund.main(["NOPE", "--run", run_id])
    assert err.value.code == "no_data"


def test_filer_without_us_gaap_is_no_data(sec, run_id):
    _, install = sec
    install(lambda facts: facts["facts"].clear())
    with pytest.raises(ToolError) as err:
        run_fund(run_id)
    assert err.value.code == "no_data"


def test_no_revenue_at_all_is_no_data(sec, run_id):
    _, install = sec

    def tweak(facts):
        for tag in ("SalesRevenueNet", "RevenueFromContractWithCustomerExcludingAssessedTax"):
            facts["facts"]["us-gaap"].pop(tag)
    install(tweak)
    with pytest.raises(ToolError) as err:
        run_fund(run_id)
    assert err.value.code == "no_data"


def test_bad_input(sec, run_id, monkeypatch):
    for argv in (["1BAD"], ["TSTCO", "--quarters", "0"], ["TSTCO", "--quarters", "13"], []):
        with pytest.raises(ToolError) as err:
            fund.main(argv + ["--run", run_id])
        assert err.value.code == "bad_input"
    monkeypatch.setenv("SEC_USER_AGENT", "StockDesk your-name your-email@example.com")
    with pytest.raises(ToolError) as err:
        run_fund(run_id)
    assert err.value.code == "bad_input"


def test_sec_outage_and_forbidden_are_source_unavailable(monkeypatch, run_id):
    monkeypatch.setattr(common, "_requests_get", lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError("down")))
    with pytest.raises(ToolError) as err:
        run_fund(run_id)
    assert err.value.code == "source_unavailable"
    monkeypatch.setattr(common, "_requests_get", lambda *a, **k: Resp("forbidden", 403))
    with pytest.raises(ToolError) as err:
        run_fund(run_id)
    assert err.value.code == "source_unavailable" and "SEC_USER_AGENT" in err.value.detail


def test_non_json_body_is_source_unavailable(monkeypatch, run_id):
    monkeypatch.setattr(common, "_requests_get", lambda *a, **k: Resp("<html>maintenance</html>"))
    with pytest.raises(ToolError) as err:
        run_fund(run_id)
    assert err.value.code == "source_unavailable"


# ---------------- unit tests for the parsing helpers ----------------

def test_dedupe_keeps_the_latest_filing_for_a_period():
    old = fund.Fact("2025-06-01", "2025-08-31", 100, "A-1", "10-Q", "2025-10-05", "Revenues")
    restated = fund.Fact("2025-06-01", "2025-08-31", 105, "A-2", "10-Q", "2026-10-05", "Revenues")
    other = fund.Fact("2025-09-01", "2025-11-30", 50, "A-3", "10-Q", "2026-01-05", "Revenues")
    kept = fund.dedupe([restated, old, other])
    assert kept[("2025-06-01", "2025-08-31")].val == 105 and len(kept) == 2


def test_direct_q4_value_is_preferred_over_derivation():
    q4 = fund.Fact("2026-03-01", "2026-05-31", 1500, "K-1", "10-K", "2026-07-20", "Revenues")
    fy = fund.Fact("2025-06-01", "2026-05-31", 5000, "K-1", "10-K", "2026-07-20", "Revenues")
    nine = fund.Fact("2025-06-01", "2026-02-28", 3500, "Q-3", "10-Q", "2026-04-04", "Revenues")
    periods = fund.flow_periods([q4, fy, nine], additive=True)
    assert periods["2026-05-31"].val == 1500 and periods["2026-05-31"].derived is False


def test_amended_forms_and_non_numeric_values_are_ignored():
    gaap = {"Revenues": {"units": {"USD": [
        {"start": "2025-06-01", "end": "2025-08-31", "val": 1, "form": "10-Q/A", "accn": "x", "filed": "2025-10-05"},
        {"start": "2025-06-01", "end": "2025-08-31", "val": "n/a", "form": "10-Q", "accn": "y", "filed": "2025-10-05"},
        {"start": "2025-06-01", "end": "2025-08-31", "val": 7, "form": "10-Q", "accn": "z", "filed": "2025-10-05"},
    ]}}}
    facts = fund.extract_facts(gaap, "Revenues", "USD")
    assert [f.val for f in facts] == [7]
