from __future__ import annotations

import json

import pytest

import common
import confidence
from common import ToolError


def put(run, fact, value, unit="ratio", tool="t.py", tier="T1"):
    return common.write_evidence(run, tool=tool, fact=fact, value=value, unit=unit, period="p", source="s",
                                 url="u", locator="l", source_tier=tier)["id"]


def precedent(run, **counts):
    """counts like w5=4, w30=3 -> precedent.py 'Events used' entries."""
    for key, n in counts.items():
        put(run, f"Events used, {key[1:]}-session window, NKE", n, unit="count", tool="precedent.py", tier="T2")


@pytest.fixture
def clean(run_id):
    """A run with no penalties: precedent n=4 in every window and one passing citation."""
    precedent(run_id, w5=4, w30=4, w90=4, w250=4)
    eid = put(run_id, "Revenue", 1.0)
    common.append_verification(run_id, eid, "1.0", "PASS", "ok")
    return run_id


def conf(run, horizon="medium", direction="bullish", fund="bullish", tech="bullish", sent="neutral"):
    _, evidence, data = confidence.main(["--run", run, "--horizon", horizon, "--direction", direction,
                                         "--fund", fund, "--tech", tech, "--sent", sent])
    assert evidence == []  # confidence is a label, never an evidence entry
    return data


# ---------------- high path ----------------

@pytest.mark.parametrize("horizon,stances", [
    ("short", {"tech": "bullish", "fund": "bearish"}),     # only tech is CORE for short
    ("medium", {"tech": "bullish", "fund": "bullish"}),
])
def test_high_path(clean, horizon, stances):
    data = conf(clean, horizon=horizon, **stances)
    assert data["confidence"] == "high" and data["reasons"] == [] and data["citations"] == "1/1"


def test_medium_needs_both_core_analysts(clean):
    assert conf(clean, horizon="medium", fund="neutral")["confidence"] == "medium"


def test_long_is_capped_at_medium(clean):
    data = conf(clean, horizon="long", fund="bullish", tech="bearish")
    assert data["confidence"] == "medium"
    assert data["reasons"] == [confidence.LONG_CAP_REASON]


def test_long_cap_reason_only_when_the_cap_applied(clean):
    data = conf(clean, horizon="long", fund="neutral")  # not high anyway -> cap did not apply
    assert data["confidence"] == "medium" and data["reasons"] == []


def test_neutral_direction_can_be_high(clean):
    assert conf(clean, direction="neutral", fund="neutral", tech="neutral", sent="positive")["confidence"] == "high"


def test_no_checks_is_not_high(run_id):
    precedent(run_id, w5=4, w30=4, w90=4, w250=4)
    data = conf(run_id)
    assert data["confidence"] == "medium" and data["citations"] == "0/0"


# ---------------- each penalty alone ----------------

@pytest.mark.parametrize("kwargs,reason", [
    ({"fund": "no_data"}, "fundamental: no data"),
    ({"tech": "no_data"}, "technical: no data"),
    ({"sent": "no_data"}, "sentiment: no data"),
    ({"sent": "negative"}, "news sentiment disagrees"),
])
def test_single_stance_penalty(clean, kwargs, reason):
    data = conf(clean, **kwargs)
    assert data["confidence"] == "low" and data["reasons"] == [reason]


def test_bearish_vs_positive_sentiment(clean):
    data = conf(clean, direction="bearish", fund="bearish", tech="bearish", sent="positive")
    assert data["reasons"] == ["news sentiment disagrees"] and data["confidence"] == "low"


def test_neutral_direction_ignores_sentiment(clean):
    data = conf(clean, direction="neutral", fund="bullish", tech="bearish", sent="negative")
    assert data["reasons"] == [] and data["confidence"] == "medium"


def test_sentiment_never_raises(clean):
    # a matching sentiment does not make high when a CORE analyst disagrees
    assert conf(clean, fund="bearish", sent="positive")["confidence"] == "medium"


def test_few_precedent_events(run_id):
    precedent(run_id, w5=2, w30=4, w90=4)
    eid = put(run_id, "x", 1.0)
    common.append_verification(run_id, eid, "1", "PASS", "ok")
    assert conf(run_id, horizon="short")["reasons"] == ["only 2 precedent events"]
    assert conf(run_id, horizon="medium")["confidence"] == "high"
    assert conf(run_id, horizon="long")["reasons"] == ["only 0 precedent events"]  # 250 window never computed


def test_medium_uses_the_smaller_window(run_id):
    precedent(run_id, w30=5, w90=2)
    assert conf(run_id)["reasons"] == ["only 2 precedent events"]


def test_latest_precedent_entry_wins(run_id):
    precedent(run_id, w5=1)
    precedent(run_id, w5=4)
    assert conf(run_id, horizon="short")["reasons"] == []


def test_missing_precedent(run_id):
    eid = put(run_id, "x", 1.0)
    common.append_verification(run_id, eid, "1", "PASS", "ok")
    data = conf(run_id)
    assert data["reasons"] == ["no precedent check"] and data["confidence"] == "low"


def test_uncorrected_vs_corrected_and_withdrawn(clean):
    bad = put(clean, "y", 2.0)
    common.append_verification(clean, bad, "3", "FAIL", "value_differs")
    data = conf(clean)
    assert data["reasons"] == [f"uncorrected citation failure: {bad}"] and data["uncorrected"] == [bad]
    assert data["confidence"] == "low" and data["citations"] == "1/2"
    common.append_verification(clean, bad, "2", "PASS", "corrected")
    assert conf(clean)["confidence"] == "high"
    other = put(clean, "z", 3.0)
    common.append_verification(clean, other, "9", "FAIL", "value_differs")
    common.append_verification(clean, other, None, "WITHDRAWN", "withdrawn")
    data = conf(clean)
    assert data["confidence"] == "high" and data["citations"] == "2/2"


# ---------------- combined penalties clamp at low ----------------

def test_combined_penalties_clamp_at_low(run_id):
    bad = put(run_id, "y", 2.0)
    common.append_verification(run_id, bad, "3", "FAIL", "x")
    data = conf(run_id, fund="no_data", tech="no_data", sent="negative")
    assert data["confidence"] == "low"
    assert len(data["reasons"]) == 5  # fund, tech, no precedent, uncorrected, sentiment


# ---------------- record and contract ----------------

def test_written_to_confidence_json_by_horizon(clean):
    conf(clean, horizon="short")
    conf(clean, horizon="long")
    stored = json.loads((common.evidence_root() / clean / "confidence.json").read_text())
    assert set(stored) == {"short", "long"}
    assert stored["short"]["confidence"] == "high" and stored["short"]["inputs"]["tech"] == "bullish"
    assert not any(e["tool"] == "confidence.py" for e in common.list_evidence(clean))


@pytest.mark.parametrize("argv", [
    ["--horizon", "weekly", "--direction", "bullish", "--fund", "bullish", "--tech", "bullish", "--sent", "neutral"],
    ["--horizon", "short", "--direction", "buy", "--fund", "bullish", "--tech", "bullish", "--sent", "neutral"],
    ["--horizon", "short", "--direction", "bullish", "--fund", "positive", "--tech", "bullish", "--sent", "neutral"],
    ["--horizon", "short", "--direction", "bullish", "--fund", "bullish", "--tech", "bullish", "--sent", "bullish"],
    ["--horizon", "short", "--direction", "bullish", "--fund", "bullish", "--tech", "bullish"],
])
def test_bad_input(clean, argv):
    with pytest.raises(ToolError) as err:
        confidence.main(argv + ["--run", clean])
    assert err.value.code == "bad_input"


def test_unknown_run_is_bad_input(run_id):
    with pytest.raises(ToolError) as err:
        conf("r-20000101-01")
    assert err.value.code == "bad_input"


def test_cli_contract(clean, capsys):
    code = common.run_cli(confidence.main, ["--run", clean, "--horizon", "short", "--direction", "bullish",
                                            "--fund", "bullish", "--tech", "bullish", "--sent", "neutral"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["ok"] is True and out["run"] == clean
    assert set(out["data"]) == {"horizon", "direction", "confidence", "reasons", "citations", "uncorrected"}



# ---------------- sentiment not measured (interim news mode) ----------------

def not_measured(horizon):
    return f"sentiment: not measured for {horizon} (interim mode)"


@pytest.mark.parametrize("horizon,stances", [
    ("short", {"tech": "bullish", "fund": "bearish"}),
    ("medium", {"tech": "bullish", "fund": "bullish"}),
])
def test_not_measured_is_no_penalty_and_high_is_unaffected(clean, horizon, stances):
    data = conf(clean, horizon=horizon, sent="not_measured", **stances)
    assert data["confidence"] == "high" and data["reasons"] == [not_measured(horizon)]


def test_not_measured_keeps_medium_where_no_data_drops_to_low(clean):
    measured = conf(clean, fund="neutral", sent="not_measured")
    missing = conf(clean, fund="neutral", sent="no_data")
    assert measured["confidence"] == "medium" and measured["reasons"] == [not_measured("medium")]
    assert missing["confidence"] == "low" and missing["reasons"] == ["sentiment: no data"]


def test_not_measured_on_long_still_hits_the_cap(clean):
    data = conf(clean, horizon="long", fund="bullish", sent="not_measured")
    assert data["confidence"] == "medium"
    assert data["reasons"] == [not_measured("long"), confidence.LONG_CAP_REASON]


def test_not_measured_does_not_hide_real_penalties(run_id):
    data = conf(run_id, sent="not_measured")  # no precedent, no checks
    assert data["confidence"] == "low" and data["reasons"] == ["no precedent check", not_measured("medium")]


def test_gdelt_refused_is_still_no_data_with_the_penalty(clean):
    """A refused news call is an error; the chief passes no_data, which keeps its -1
    (chief.md wording: tests/test_agents_and_template.py)."""
    data = conf(clean, sent="no_data")
    assert data["confidence"] == "low" and data["reasons"] == ["sentiment: no data"]


def test_not_measured_only_for_sentiment(clean):
    with pytest.raises(ToolError) as err:
        conf(clean, fund="not_measured")
    assert err.value.code == "bad_input"
