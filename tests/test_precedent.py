from __future__ import annotations

import json
from datetime import date

import pandas as pd
import pytest

import common
import precedent
from common import ToolError

TODAY = date(2026, 11, 4)
SESSIONS = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2026-01-01", periods=60)]


def frame(fn):
    return pd.DataFrame({"Close": [float(fn(i)) for i in range(len(SESSIONS))]}, index=SESSIONS)


STOCK = frame(lambda i: 100 + i)     # day i closes at 100 + i
ETF = frame(lambda i: 200 + i)       # day i closes at 200 + i


@pytest.fixture
def prices(monkeypatch, run_id):
    calls = []

    def fake(ticker, **kwargs):
        calls.append((ticker, kwargs))
        return (ETF if ticker in {"XLY", "XLK"} else STOCK), "2026-11-04T12:00:00Z"

    monkeypatch.setattr(common, "fetch_prices", fake)
    return calls


def run(*argv):
    return precedent.main(list(argv), today=TODAY)


def test_single_event_by_hand(prices, run_id):
    event = SESSIONS[10]  # base = session 9 (close 109 / 209), window 5 -> session 14 (114 / 214)
    _, ids, data = run("NKE", "--dates", event, "--windows", "5", "--urls", "https://example.com/e")
    w = data["events"][0]["windows"]["5"]
    assert w["stock_return"]["value"] == pytest.approx(5 / 109, abs=1e-6)
    assert w["etf_return"]["value"] == pytest.approx(5 / 209, abs=1e-6)
    assert w["excess"]["value"] == pytest.approx(5 / 109 - 5 / 209, abs=2e-6)
    excess = common.read_evidence(run_id, w["excess"]["id"])
    assert excess["derived_from"] == [w["stock_return"]["id"], w["etf_return"]["id"], data["events"][0]["id"]]
    assert excess["period"] == f"{SESSIONS[9]}/{SESSIONS[14]}"
    assert "day 0 = first session on/after the event date" in excess["locator"]
    assert data["warnings"] == [] and set(data["events"][0]["skipped"]) == set()
    assert data["etf"] == "XLY"  # from config/sector_etf.json
    assert [c[0] for c in prices] == ["NKE", "XLY"]
    assert all(c[1]["auto_adjust"] is True for c in prices)
    assert all(i in ids for i in (w["excess"]["id"], data["events"][0]["id"]))


def test_weekend_event_rolls_to_next_session(prices, run_id):
    _, _, data = run("NKE", "--dates", "2026-01-10", "--windows", "5")  # Saturday -> Monday 2026-01-12
    w = data["events"][0]["windows"]["5"]
    assert w["stock_return"]["value"] == pytest.approx(5 / 106, abs=1e-6)  # base = Fri 2026-01-09 (idx 6)
    entry = common.read_evidence(run_id, w["stock_return"]["id"])
    assert entry["period"] == "2026-01-09/2026-01-16" and "day0 2026-01-12" in entry["locator"]


def test_mean_counts_and_small_sample_flag(prices, run_id):
    dates = ",".join(SESSIONS[i] for i in (10, 20))
    _, _, two = run("NKE", "--dates", dates, "--windows", "5")
    s = two["summary"]["5"]
    assert s["n"] == 2 and s["small_sample"] is True and two["small_sample"] is True
    e1, e2 = 5 / 109 - 5 / 209, 5 / 119 - 5 / 219
    assert s["mean_excess"]["value"] == pytest.approx((e1 + e2) / 2, abs=2e-6)
    mean_entry = common.read_evidence(run_id, s["mean_excess"]["id"])
    assert len(mean_entry["derived_from"]) == 2 and "small sample" in mean_entry["fact"]

    dates3 = ",".join(SESSIONS[i] for i in (10, 20, 30))
    _, _, three = run("NKE", "--dates", dates3, "--windows", "5")
    assert three["summary"]["5"]["n"] == 3 and three["summary"]["5"]["small_sample"] is False
    n_entry = common.read_evidence(run_id, three["summary"]["5"]["n_id"])
    assert n_entry["value"] == 3 and n_entry["unit"] == "count"


def test_incomplete_window_is_skipped_with_reason_and_excluded_from_mean(prices, run_id):
    dates = ",".join(SESSIONS[i] for i in (10, 40))  # event 40: base 39 + 30 = 69 >= 60 sessions
    _, _, data = run("NKE", "--dates", dates, "--windows", "5,30")
    late = [e for e in data["events"] if e["date"] == SESSIONS[40]][0]
    assert "30" in late["skipped"] and "not complete" in late["skipped"]["30"]
    assert "5" in late["windows"]
    assert data["summary"]["30"]["n"] == 1 and data["summary"]["5"]["n"] == 2


def test_no_usable_events_for_a_window_is_reported(prices, run_id):
    _, _, data = run("NKE", "--dates", SESSIONS[50], "--windows", "30")
    assert data["summary"]["30"] == {"n": 0, "mean_excess": None, "small_sample": True}
    assert any("no usable events" in w for w in data["warnings"])


def test_event_before_history_or_far_from_a_session_is_skipped(prices, run_id):
    _, _, data = run("NKE", "--dates", "2026-02-01,2026-03-01", "--windows", "5")  # both fine (weekends)
    assert data["events"][0]["windows"]
    # after the last session
    _, _, late = run("NKE", "--dates", "2026-09-01", "--windows", "5")
    assert "after the last available session" in late["events"][0]["skipped"]["5"]


def test_missing_urls_are_warned_not_hidden(prices, run_id):
    _, _, data = run("NKE", "--dates", SESSIONS[10], "--windows", "5")
    assert any("no source URL" in w for w in data["warnings"])
    entry = common.read_evidence(run_id, data["events"][0]["id"])
    assert entry["url"] == "none supplied" and "no source URL" in entry["source"]


def test_etf_flag_overrides_config_and_unmapped_ticker_fails_closed(prices, run_id):
    _, _, data = run("NKE", "--dates", SESSIONS[10], "--windows", "5", "--etf", "xlk")
    assert data["etf"] == "XLK"
    with pytest.raises(ToolError) as err:
        run("ZZZZ", "--dates", SESSIONS[10])
    assert err.value.code == "bad_input" and "--etf" in err.value.detail


@pytest.mark.parametrize("argv", [
    ["--dates", "2026-12-25"],                                   # future
    ["--dates", "2026-03-02,2026-03-02"],                         # duplicate
    ["--dates", "2026-03-02", "--urls", "https://a.test/1,https://a.test/2"],  # count mismatch
    ["--dates", "2026-03-02", "--urls", "not-a-url"],
    ["--dates", "2026-03-02", "--windows", "five"],
    ["--dates", "2026-03-02", "--windows", "0"],
    ["--dates", "2026-03-02", "--windows", "500"],
    ["--dates", "03/02/2026"],
    ["--dates", ","],
    ["--dates", ",".join(f"2025-{m:02d}-03" for m in range(1, 13)) + ",2025-12-04"],  # 13 events
])
def test_bad_input(prices, run_id, argv):
    with pytest.raises(ToolError) as err:
        run("NKE", *argv)
    assert err.value.code == "bad_input"


def test_price_source_failure_propagates(monkeypatch, run_id):
    def fail(ticker, **kwargs):
        raise ToolError("no_data", "no prices")

    monkeypatch.setattr(common, "fetch_prices", fail)
    with pytest.raises(ToolError) as err:
        run("NKE", "--dates", "2026-03-02")
    assert err.value.code == "no_data"


def test_cli_prints_only_json(prices, run_id, capsys):
    code = common.run_cli(lambda a: precedent.main(a, today=TODAY), ["NKE", "--dates", SESSIONS[10], "--windows", "5"])
    out = capsys.readouterr().out
    assert code == 0 and json.loads(out)["ok"] is True and out.count("\n") == 1


def test_tiers_market_data_t2_event_dates_unrated(prices, run_id):
    _, _, data = run("NKE", "--dates", SESSIONS[10], "--windows", "5", "--urls", "https://example.com/e")
    event = data["events"][0]
    assert common.read_evidence(run_id, event["id"])["source_tier"] == "unrated"
    window = event["windows"]["5"]
    stock = common.read_evidence(run_id, window["stock_return"]["id"])
    assert stock["source_tier"] == "T2" and stock["source"].startswith("Yahoo Finance via yfinance (unofficial, disclosed)")
    # the excess return is derived from the event date too, so it takes the weaker tier
    assert common.read_evidence(run_id, window["excess"]["id"])["source_tier"] == "unrated"


def test_250_session_window_is_accepted_and_needs_full_history(prices, run_id):
    _, _, data = run("NKE", "--dates", SESSIONS[5], "--windows", "5,30,90,250")
    assert data["windows"] == [5, 30, 90, 250]
    event = data["events"][0]
    assert set(event["windows"]) == {"5", "30"}            # 60 synthetic sessions: 90 and 250 do not fit
    assert set(event["skipped"]) == {"90", "250"}
    assert data["summary"]["250"] == {"n": 0, "mean_excess": None, "small_sample": True}
    with pytest.raises(ToolError):
        run("NKE", "--dates", SESSIONS[5], "--windows", "251")
