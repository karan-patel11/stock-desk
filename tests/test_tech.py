from __future__ import annotations

import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

import common
import tech
from common import ToolError


def series(values, start="2026-01-01"):
    index = [d.strftime("%Y-%m-%d") for d in pd.bdate_range(start, periods=len(values))]
    return pd.Series([float(v) for v in values], index=index)


# ---------------- indicators vs hand-computed values ----------------

def test_sma_by_hand():
    s = series([1, 2, 3, 4, 5])
    assert tech.sma(s, 3).iloc[-1] == pytest.approx(4.0)       # (3+4+5)/3
    assert np.isnan(tech.sma(s, 3).iloc[1])


def test_rsi_wilder_by_hand_period_3():
    # closes 44, 44.5, 44, 43.5, 44.5, 45 -> changes +.5 -.5 -.5 +1 +.5
    # seed: gain .5/3, loss 1/3, RS .5 -> RSI 33.3333
    # +1: gain (1/6*2+1)/3=.444444, loss (1/3*2)/3=.222222, RS 2 -> 66.6667
    # +.5: gain (.444444*2+.5)/3=.462963, loss .222222*2/3=.148148, RS 3.125 -> 75.7576
    s = series([44, 44.5, 44, 43.5, 44.5, 45])
    out = tech.rsi(s, 3)
    assert np.isnan(out.iloc[2])
    assert out.iloc[3] == pytest.approx(33.3333, abs=1e-3)
    assert out.iloc[4] == pytest.approx(66.6667, abs=1e-3)
    assert out.iloc[5] == pytest.approx(75.7576, abs=1e-3)


def test_rsi_all_gains_is_100_and_flat_is_nan():
    assert tech.rsi(series([1, 2, 3, 4, 5]), 3).iloc[-1] == pytest.approx(100.0)
    assert np.isnan(tech.rsi(series([5, 5, 5, 5, 5]), 3).iloc[-1])


def test_atr_wilder_by_hand_period_3():
    # TR: bar1 2, bar2 2, bar3 2.5, bar4 1.5; first ATR (bar3) = 2.1667; bar4 = (2.1667*2+1.5)/3 = 1.9444
    high = series([10, 11, 12, 13, 12.5])
    low = series([8, 9, 10, 10.5, 11])
    close = series([9, 10, 11, 12, 11.5])
    out = tech.atr(high, low, close, 3)
    assert np.isnan(out.iloc[2])
    assert out.iloc[3] == pytest.approx(2.16667, abs=1e-4)
    assert out.iloc[4] == pytest.approx(1.94444, abs=1e-4)


def test_atr_uses_gaps_in_true_range():
    # bar1 gaps up: high-low = 1 but |high - prev close| = 5
    high = series([10, 15, 15, 15])
    low = series([9, 14, 14, 14])
    close = series([10, 14.5, 14.5, 14.5])
    assert tech.atr(high, low, close, 3).iloc[3] == pytest.approx((5 + 1 + 1) / 3)


def test_latest_cross_golden_death_and_none():
    slow = series([3, 3, 3, 3, 3, 3])
    golden = tech.latest_cross(series([1, 2, 3, 4, 5, 6]), slow)
    assert golden == ("golden", str(slow.index[3]))
    death = tech.latest_cross(series([6, 5, 4, 3, 2, 1]), slow)
    assert death[0] == "death"
    assert tech.latest_cross(series([4, 5, 6, 7, 8, 9]), slow) is None
    both = tech.latest_cross(series([1, 5, 5, 1, 1, 1]), slow)
    assert both[0] == "death"  # most recent wins


def test_volume_ratio_excludes_the_latest_bar_from_the_average():
    v = series([100] * 20 + [250])
    latest, average, ratio = tech.volume_ratio(v, 20)
    assert (latest, average, ratio) == (250.0, 100.0, 2.5)
    assert tech.volume_ratio(series([100] * 20), 20) is None


# ---------------- tool ----------------

def make_frame(n=300, end="2026-11-03", seed_trend=0.1):
    dates = [d.strftime("%Y-%m-%d") for d in pd.bdate_range(end=end, periods=n)]
    i = np.arange(n)
    close = 100 + seed_trend * i + 5 * np.sin(i / 10)
    frame = pd.DataFrame({
        "Open": close - 0.3, "High": close + 1.0, "Low": close - 1.0, "Close": close,
        "Volume": 1_000_000 + (i % 7) * 10_000.0,
    }, index=dates)
    frame.iloc[-1, frame.columns.get_loc("Volume")] = 2_000_000.0
    frame.index.name = "date"
    return frame


@pytest.fixture
def patched(monkeypatch, run_id):
    frame = make_frame()
    calls = []

    def fake(ticker, **kwargs):
        calls.append((ticker, kwargs))
        return frame, "2026-11-04T12:00:00Z"

    monkeypatch.setattr(common, "fetch_prices", fake)
    return frame, calls, run_id


TODAY = date(2026, 11, 4)


def test_happy_path_values_and_evidence(patched):
    frame, calls, run = patched
    _, ids, data = tech.main(["nke", "--run", run], today=TODAY)
    assert calls[0][0] == "NKE" and calls[0][1]["auto_adjust"] is False and calls[0][1]["period"] == "1y"
    m = data["metrics"]
    close = frame["Close"]
    assert m["last_close"]["value"] == pytest.approx(round(close.iloc[-1], 6))
    assert m["sma50"]["value"] == pytest.approx(close.iloc[-50:].sum() / 50, abs=1e-5)
    assert m["sma200"]["value"] == pytest.approx(close.iloc[-200:].sum() / 200, abs=1e-5)
    assert m["volume_latest"]["value"] == 2_000_000.0
    prior = frame["Volume"].iloc[-21:-1]
    assert m["volume_ratio"]["value"] == pytest.approx(2_000_000.0 / prior.mean(), abs=1e-5)
    assert m["high_52w"]["value"] >= m["last_close"]["value"] - 1.0
    assert m["low_52w"]["value"] <= m["last_close"]["value"] + 1.0
    assert 0 < m["rsi14"]["value"] <= 100 and m["atr14"]["value"] > 0
    assert data["unavailable"] == [] and data["as_of"] == "2026-11-03"
    assert ids == [e["id"] for e in common.list_evidence(run)]


def test_evidence_entries_have_correct_fields_and_derivations(patched):
    _, _, run = patched
    _, ids, data = tech.main(["NKE", "--run", run], today=TODAY)
    ratio_entry = common.read_evidence(run, data["metrics"]["volume_ratio"]["id"])
    assert ratio_entry["derived_from"] == [data["metrics"]["volume_latest"]["id"], data["metrics"]["volume_avg20"]["id"]]
    assert ratio_entry["unit"] == "x" and ratio_entry["retrieved_at"] == "2026-11-04T12:00:00Z"
    cross_entry = common.read_evidence(run, data["metrics"]["cross"]["id"])
    assert cross_entry["derived_from"] == [data["metrics"]["sma50"]["id"], data["metrics"]["sma200"]["id"]]
    for entry in common.list_evidence(run):
        assert tuple(entry.keys()) == common.EVIDENCE_FIELDS
        assert entry["source"].startswith("Yahoo Finance via yfinance (unofficial, disclosed)")
        assert "auto_adjust=False" in entry["locator"] and entry["source_tier"] == "T2"
        assert entry["url"].startswith("https://finance.yahoo.com/quote/NKE")


def test_short_history_lists_unavailable_instead_of_guessing(monkeypatch, run_id):
    frame = make_frame(n=60)
    monkeypatch.setattr(common, "fetch_prices", lambda t, **k: (frame, "2026-11-04T12:00:00Z"))
    _, _, data = tech.main(["NKE", "--run", run_id], today=TODAY)
    missing = {item["metric"] for item in data["unavailable"]}
    assert {"sma200", "cross", "range_52w"} <= missing
    assert "sma50" in data["metrics"] and "sma200" not in data["metrics"]


def test_too_few_bars_for_anything_but_close(monkeypatch, run_id):
    frame = make_frame(n=5)
    monkeypatch.setattr(common, "fetch_prices", lambda t, **k: (frame, "2026-11-04T12:00:00Z"))
    _, _, data = tech.main(["NKE", "--run", run_id], today=TODAY)
    assert set(data["metrics"]) == {"last_close"}
    assert {"rsi14", "atr14", "volume_ratio"} <= {u["metric"] for u in data["unavailable"]}


def test_stale_data_fails_closed(monkeypatch, run_id):
    monkeypatch.setattr(common, "fetch_prices", lambda t, **k: (make_frame(end="2026-10-01"), "x"))
    with pytest.raises(ToolError) as err:
        tech.main(["NKE", "--run", run_id], today=TODAY)
    assert err.value.code == "source_unavailable" and "stale" in err.value.detail


def test_no_data_from_source_propagates(monkeypatch, run_id):
    def none(ticker, **kwargs):
        raise ToolError("no_data", f"no daily price data returned for {ticker}")

    monkeypatch.setattr(common, "fetch_prices", none)
    with pytest.raises(ToolError) as err:
        tech.main(["ZZZZ", "--run", run_id], today=TODAY)
    assert err.value.code == "no_data"


def test_bad_input(run_id):
    for argv in ([], ["1BAD"], ["NKE", "--lookback", "3d"]):
        with pytest.raises(ToolError) as err:
            tech.main(argv + ["--run", run_id], today=TODAY)
        assert err.value.code == "bad_input"


def test_requires_a_run(monkeypatch):
    monkeypatch.setattr(common, "fetch_prices", lambda t, **k: (make_frame(), "x"))
    with pytest.raises(ToolError) as err:
        tech.main(["NKE"], today=TODAY)
    assert err.value.code == "bad_input"


def test_cli_prints_only_json(patched, capsys):
    _, _, run = patched
    code = common.run_cli(lambda argv: tech.main(argv, today=TODAY), ["NKE", "--run", run])
    out = capsys.readouterr().out.strip().splitlines()
    assert code == 0 and len(out) == 1
    payload = json.loads(out[0])
    assert payload["ok"] is True and payload["run"] == run and payload["evidence"]



@pytest.mark.parametrize("kind,word", [("golden", "above"), ("death", "below")])
def test_cross_label_matches_its_direction(patched, monkeypatch, kind, word):
    monkeypatch.setattr(tech, "latest_cross", lambda fast, slow: (kind, "2026-01-02"))
    run, _, data = tech.main(["NKE", "--run", common.resolve_run(None)], today=TODAY)
    fact = common.read_evidence(run, data["metrics"]["cross"]["id"])["fact"]
    assert f"({kind} = SMA50 crossed {word} SMA200)" in fact
