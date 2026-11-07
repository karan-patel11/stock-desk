from __future__ import annotations

import json
import multiprocessing
import os
import stat

import pytest
import requests

import common
from common import ToolError


class FakeResponse:
    def __init__(self, status=200, text="{}", headers=None):
        self.status_code = status
        self.text = text
        self.headers = headers or {}


def install_get(monkeypatch, responses):
    calls = []

    def fake(url, headers=None, timeout=None):
        calls.append({"url": url, "headers": headers})
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(common, "_requests_get", fake)
    return calls


# ---------------- evidence ledger ----------------

def test_evidence_ids_are_sequential_and_fields_complete(run_id):
    first = common.write_evidence(run_id, tool="t.py", fact="A", value=1, unit="USD", period="2026-01-01",
                                  source="s", url="https://x", locator="l", source_tier="T1")
    second = common.write_evidence(run_id, tool="t.py", fact="B", value=2.5, unit="ratio", period="2026-01-02",
                                   source="s", url="https://x", locator="l", source_tier="T1", derived_from=["E1"])
    assert (first["id"], second["id"]) == ("E1", "E2")
    stored = common.read_evidence(run_id, "E2")
    assert tuple(stored.keys()) == common.EVIDENCE_FIELDS
    assert stored["derived_from"] == ["E1"]
    assert stored["retrieved_at"].endswith("Z")


def test_missing_and_malformed_ids_read_as_none(run_id):
    assert common.read_evidence(run_id, "E99") is None
    assert common.read_evidence(run_id, "../etc/passwd") is None
    assert common.read_evidence(run_id, "e1") is None


def test_non_finite_values_are_refused(run_id):
    with pytest.raises(ToolError) as err:
        common.write_evidence(run_id, tool="t", fact="bad", value=float("nan"), unit="USD", period="p",
                              source="s", url="u", locator="l", source_tier="T1")
    assert err.value.code == "no_data"


def test_no_temp_files_left_behind(run_id, _isolated_home):
    common.write_evidence(run_id, tool="t", fact="A", value=1, unit="USD", period="p", source="s", url="u", locator="l", source_tier="T1")
    leftovers = [p.name for p in (_isolated_home / "evidence" / run_id).iterdir() if p.name.startswith(".tmp")]
    assert leftovers == []


def _writer(args):
    home, run, count = args
    os.environ["STOCKDESK_HOME"] = home
    for i in range(count):
        common.write_evidence(run, tool="race", fact=f"f{i}", value=i, unit="n", period="p",
                              source="s", url="u", locator="l", source_tier="T1")


def test_concurrent_writers_get_unique_contiguous_ids(run_id, _isolated_home):
    ctx = multiprocessing.get_context("fork")
    with ctx.Pool(4) as pool:
        pool.map(_writer, [(str(_isolated_home), run_id, 15)] * 4)
    entries = common.list_evidence(run_id)
    assert [e["id"] for e in entries] == [f"E{i}" for i in range(1, 61)]
    for entry in entries:  # every file is complete, valid JSON
        assert set(common.EVIDENCE_FIELDS) == set(entry)


def test_run_ids_increment_within_a_day():
    first = common.new_run_id()
    second = common.new_run_id()
    assert first.endswith("-01") and second.endswith("-02")


def test_resolve_run_uses_current_pointer(run_id):
    assert common.resolve_run(None) == run_id
    with pytest.raises(ToolError) as err:
        common.resolve_run("r-20200101-01")
    assert err.value.code == "bad_input"


# ---------------- config ----------------

def test_home_must_be_absolute(monkeypatch):
    monkeypatch.setenv("STOCKDESK_HOME", "relative/path")
    with pytest.raises(ToolError) as err:
        common.home()
    assert err.value.code == "bad_input"


def test_home_falls_back_to_repo_when_unset(monkeypatch):
    monkeypatch.delenv("STOCKDESK_HOME")
    assert common.home() == common.repo_root()


def test_sec_user_agent_rejects_placeholder(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "StockDesk your-name your-email@example.com")
    with pytest.raises(ToolError) as err:
        common.user_agent(required=True)
    assert err.value.code == "bad_input"


def test_generic_ua_never_carries_the_contact_email():
    assert "@" not in common.user_agent(required=False)
    assert "@" in common.user_agent(required=True)


# ---------------- HTTP ----------------

def test_http_caches_success(monkeypatch):
    calls = install_get(monkeypatch, [FakeResponse(200, '{"a": 1}')])
    first = common.http_get("https://x.test/a", params={"q": "1"})
    second = common.http_get("https://x.test/a", params={"q": "1"})
    assert first.text == second.text and not first.from_cache and second.from_cache
    assert len(calls) == 1


def test_http_retries_server_errors_then_succeeds(monkeypatch):
    calls = install_get(monkeypatch, [FakeResponse(503), FakeResponse(200, "ok")])
    assert common.http_get("https://x.test/b").text == "ok"
    assert len(calls) == 2


def test_http_rate_limited_after_retries(monkeypatch):
    install_get(monkeypatch, [FakeResponse(429)] * 3)
    with pytest.raises(ToolError) as err:
        common.http_get("https://x.test/c")
    assert err.value.code == "rate_limited"


def test_http_404_is_no_data_and_network_error_is_source_unavailable(monkeypatch):
    install_get(monkeypatch, [FakeResponse(404)])
    with pytest.raises(ToolError) as err:
        common.http_get("https://x.test/d")
    assert err.value.code == "no_data"
    install_get(monkeypatch, [requests.ConnectionError("boom")] * 3)
    with pytest.raises(ToolError) as err:
        common.http_get("https://x.test/e")
    assert err.value.code == "source_unavailable"


def test_validate_failure_is_not_cached(monkeypatch):
    def validate(text):
        if text == "Please limit requests":
            raise ToolError("rate_limited", "body says slow down")

    # 3 attempts all return a rate-limit body; retries exhaust
    install_get(monkeypatch, [FakeResponse(200, "Please limit requests")] * 3)
    with pytest.raises(ToolError):
        common.http_get("https://x.test/f", validate=validate)
    # Next call gets a clean response; the rate-limit body was never cached
    calls = install_get(monkeypatch, [FakeResponse(200, "fine")])
    assert common.http_get("https://x.test/f").text == "fine"
    assert len(calls) == 1


def test_rate_limit_body_is_retried_then_succeeds(monkeypatch):
    def validate(text):
        if text == "Please limit requests":
            raise ToolError("rate_limited", "body says slow down")

    slept = []
    monkeypatch.setattr(common, "_sleep", slept.append)
    calls = install_get(monkeypatch, [FakeResponse(200, "Please limit requests"), FakeResponse(200, "fine")])
    result = common.http_get("https://x.test/r", validate=validate, rate_limit_wait=7.0)
    assert result.text == "fine"
    assert len(calls) == 2
    assert slept.count(7.0) == 1  # first retry waits rate_limit_wait * 1


def test_non_rate_limit_validate_error_is_not_retried(monkeypatch):
    def validate(text):
        raise ToolError("no_data", "body is empty")

    calls = install_get(monkeypatch, [FakeResponse(200, "")])
    with pytest.raises(ToolError) as err:
        common.http_get("https://x.test/n", validate=validate)
    assert err.value.code == "no_data"
    assert len(calls) == 1


def test_sec_calls_send_the_configured_user_agent(monkeypatch):
    calls = install_get(monkeypatch, [FakeResponse(200, "{}")])
    common.http_get("https://data.sec.gov/x", sec=True)
    assert calls[0]["headers"]["User-Agent"] == "StockDeskTest tester@stockdesk.test"


def test_pacing_sleeps_between_requests_to_same_host(monkeypatch):
    slept = []
    monkeypatch.setattr(common, "_sleep", lambda s: slept.append(s))
    install_get(monkeypatch, [FakeResponse(200, "1"), FakeResponse(200, "2")])
    common.http_get("https://paced.test/a", min_interval=6.0)
    common.http_get("https://paced.test/b", min_interval=6.0)
    assert slept and slept[0] > 0


# ---------------- CLI contract ----------------

def test_run_cli_success_prints_one_json_object(capsys):
    code = common.run_cli(lambda argv: ("r-20260101-01", ["E1"], {"x": 1}), [])
    out = capsys.readouterr().out.strip().splitlines()
    assert code == 0 and len(out) == 1
    assert json.loads(out[0]) == {"ok": True, "run": "r-20260101-01", "evidence": ["E1"], "data": {"x": 1}}


def test_run_cli_tool_error_exits_one_with_code(capsys):
    def boom(argv):
        raise ToolError("no_data", "nothing here")

    assert common.run_cli(boom, []) == 1
    assert json.loads(capsys.readouterr().out) == {"ok": False, "error": "no_data", "detail": "nothing here"}


def test_run_cli_unexpected_exception_is_an_error_not_partial_data(capsys):
    def bug(argv):
        raise KeyError("oops")

    assert common.run_cli(bug, []) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False and payload["error"] == "source_unavailable"


def test_contract_parser_turns_bad_args_into_bad_input():
    parser = common.ContractParser()
    parser.add_argument("ticker")
    with pytest.raises(ToolError) as err:
        parser.parse_args([])
    assert err.value.code == "bad_input"


def test_normalize_ticker_and_dates():
    assert common.normalize_ticker(" nke ") == "NKE"
    for bad in ("", "1ABC", "A B", "WAYTOOLONGTICKER"):
        with pytest.raises(ToolError):
            common.normalize_ticker(bad)
    assert common.parse_date("2026-02-28") == "2026-02-28"
    with pytest.raises(ToolError):
        common.parse_date("2026-02-30")


def test_primary_entry_needs_a_valid_source_tier(run_id):
    for bad in (None, "T9", "official"):
        with pytest.raises(ToolError) as err:
            common.write_evidence(run_id, tool="t", fact="A", value=1, unit="USD", period="p", source="s",
                                  url="u", locator="l", source_tier=bad)
        assert err.value.code == "bad_input"


def test_derived_entry_takes_the_weakest_input_tier(run_id):
    def put(tier, parents=None):
        return common.write_evidence(run_id, tool="t", fact="f", value=1, unit="USD", period="p", source="s",
                                     url="u", locator="l", source_tier=tier, derived_from=parents)["id"]
    sec, market, news = put("T1"), put("T2"), put("T4")
    assert common.read_evidence(run_id, put("T1", [sec]))["source_tier"] == "T1"
    # the tier the caller passes is ignored for a derived entry: it can never look stronger than its inputs
    assert common.read_evidence(run_id, put("T1", [sec, market]))["source_tier"] == "T2"
    assert common.read_evidence(run_id, put(None, [market, news, sec]))["source_tier"] == "T4"
    assert common.read_evidence(run_id, put("T1", [sec, put("unrated")]))["source_tier"] == "unrated"
    with pytest.raises(ToolError):
        put("T1", ["E999"])


def test_old_entry_without_tier_counts_as_unrated(run_id):
    path = common.evidence_root() / run_id / "E1.json"
    path.write_text(json.dumps({"id": "E1", "value": 1, "unit": "USD"}))  # an old ledger entry, no source_tier
    derived = common.write_evidence(run_id, tool="t", fact="f", value=1, unit="USD", period="p", source="s",
                                    url="u", locator="l", derived_from=["E1"])
    assert derived["source_tier"] == "unrated"
    assert json.loads(path.read_text()) == {"id": "E1", "value": 1, "unit": "USD"}  # never rewritten


def test_weakest_tier_order():
    assert common.weakest_tier(["T1", "T2"]) == "T2"
    assert common.weakest_tier(["T3", "T4"]) == "T4"
    assert common.weakest_tier(["T4", "excluded"]) == "excluded"
    assert common.weakest_tier(["T1", "nonsense"]) == "unrated"
