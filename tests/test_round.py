from __future__ import annotations

import json

import pytest

import common
import round as rnd
from common import ToolError


def call(*argv):
    return rnd.main(list(argv))


def test_start_creates_run_state_and_pointer():
    run, evidence, data = call("start", "nke")
    assert run.startswith("r-") and evidence == []
    assert data["ticker"] == "NKE" and data["round"] == 1 and data["stop"] is False
    assert data["step"] == "round_1" and "ROUND 1" in data["next_action"]
    assert common.resolve_run(None) == run
    state = json.loads((common.evidence_root() / run / "state.json").read_text())
    assert state["status"] == "active"


def test_next_goes_round_two_then_stop_and_never_round_three():
    run, _, _ = call("start", "NKE")
    _, _, second = call("next")
    assert second["round"] == 2 and second["stop"] is False and second["message"] == "ROUND 2/2"
    _, _, stop = call("next")
    assert stop["stop"] is True and stop["message"] == "STOP: write verdict" and stop["round"] == 2
    _, _, again = call("next")
    assert again["round"] == 2 and again["message"] == "STOP: write verdict"
    assert "STOP: write verdict" in again["next_action"]


def test_status_reports_step_and_evidence_count(run_id):
    call("start", "AAPL")
    run = common.resolve_run(None)
    common.write_evidence(run, tool="t", fact="f", value=1, unit="USD", period="p", source="s", url="u", locator="l", source_tier="T1")
    _, _, data = call("status")
    assert data["evidence_count"] == 1 and data["step"] == "round_1"


def test_end_closes_run_and_blocks_further_next():
    call("start", "MSFT")
    _, _, ended = call("end")
    assert ended["status"] == "ended" and ended["step"] == "ended"
    with pytest.raises(ToolError) as err:
        call("next")
    assert err.value.code == "bad_input"
    _, _, still = call("end")  # ending twice is harmless
    assert still["status"] == "ended"


def test_explicit_run_argument():
    first, _, _ = call("start", "NKE")
    second, _, _ = call("start", "TSLA")
    assert first != second
    _, _, data = call("status", "--run", first)
    assert data["ticker"] == "NKE"


def test_bad_input_cases():
    for argv in (["start"], ["start", "1ABC"], ["bogus"], []):
        with pytest.raises(ToolError) as err:
            call(*argv)
        assert err.value.code == "bad_input"
    with pytest.raises(ToolError):
        call("status")  # no run yet


def test_run_without_state_file_is_rejected(run_id):
    with pytest.raises(ToolError) as err:
        call("status", "--run", run_id)
    assert err.value.code == "bad_input"


def test_cli_output_is_contract_json(capsys):
    assert common.run_cli(rnd.main, ["start", "NKE"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True and payload["data"]["ticker"] == "NKE"
