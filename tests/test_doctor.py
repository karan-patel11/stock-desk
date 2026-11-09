"""stockdesk doctor (Phase 4 of packaging). Claude Code, the network and the clock are all mocked."""
from __future__ import annotations

import json
import subprocess

import pandas as pd
import pytest

from stockdesk import cli, common, doctor


class Resp:
    def __init__(self, text, status=200):
        self.text, self.status_code, self.headers = text, status, {}


@pytest.fixture
def claude(monkeypatch):
    """Claude Code present by default; tests flip state['path'] / state['run'] to change that."""
    state = {"path": "/opt/bin/claude", "which": [], "run": []}

    def which(name):
        state["which"].append(name)
        return state["path"] if name == "claude" else None

    def run(cmd, **kwargs):
        state["run"].append((cmd, kwargs))
        behaviour = state.get("behaviour", "ok")
        if behaviour == "timeout":
            raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])
        code = 0 if behaviour == "ok" else 3
        return subprocess.CompletedProcess(cmd, code, stdout="2.1.310 (Claude Code)\n", stderr="")

    monkeypatch.setattr(doctor, "_which", which)
    monkeypatch.setattr(doctor, "_run", run)
    return state


@pytest.fixture
def ready_home(_isolated_home):
    for sub in ("evidence", "cache"):
        (_isolated_home / sub).mkdir(exist_ok=True)
    return _isolated_home


def checks_of(capsys, *argv):
    code = doctor.main(["--json", *argv])
    out = json.loads(capsys.readouterr().out)
    return code, {c["name"]: c for c in out["checks"]}, out


def test_all_good_offline_exits_0(claude, ready_home, capsys):
    code, checks, out = checks_of(capsys, "--offline")
    assert code == 0 and out["ok"] is True
    for name in ("python", "home", "sec_user_agent", "claude_code", "bundled_data"):
        assert checks[name]["status"] == "PASS", checks[name]
    assert checks["claude_code"]["detail"].endswith("2.1.310 (Claude Code)")
    assert claude["run"][0][0] == ["/opt/bin/claude", "--version"] and claude["run"][0][1]["timeout"] == 10.0


def test_executable_check_names_the_command_the_template_embeds(claude, ready_home, capsys):
    from stockdesk import locate

    _, checks, _ = checks_of(capsys, "--offline")
    assert locate.command_text() in checks["stockdesk"]["detail"]


def test_missing_claude_code_is_fail_with_a_fix(claude, ready_home, capsys):
    claude["path"] = None
    code, checks, _ = checks_of(capsys, "--offline")
    assert code == 1 and checks["claude_code"]["status"] == "FAIL" and "install Claude Code" in checks["claude_code"]["fix"]
    assert claude["run"] == []


@pytest.mark.parametrize("behaviour", ["timeout", "nonzero"])
def test_claude_code_that_does_not_answer_is_a_warning(behaviour, claude, ready_home, capsys):
    claude["behaviour"] = behaviour
    code, checks, _ = checks_of(capsys, "--offline")
    assert code == 0 and checks["claude_code"]["status"] == "WARN"


def test_switch_console_is_a_warning_and_no_command_is_guessed(claude, ready_home, capsys):
    _, checks, _ = checks_of(capsys, "--offline")
    assert checks["switch_console"]["status"] == "WARN"
    assert "cannot detect Switch Console automatically" in checks["switch_console"]["detail"]
    assert "docs.switchagents.ai" in checks["switch_console"]["fix"]
    assert claude["which"] == ["claude"]          # nothing else is looked up on PATH


def test_missing_sec_user_agent_is_fail(claude, ready_home, monkeypatch, capsys):
    monkeypatch.delenv("SEC_USER_AGENT")
    code, checks, _ = checks_of(capsys, "--offline")
    assert code == 1 and checks["sec_user_agent"]["status"] == "FAIL" and "stockdesk init" in checks["sec_user_agent"]["fix"]


def test_sec_user_agent_email_is_masked(claude, ready_home, capsys):
    _, checks, _ = checks_of(capsys, "--offline")
    assert "tester@" not in checks["sec_user_agent"]["detail"] and "t***@stockdesk.test" in checks["sec_user_agent"]["detail"]


def test_missing_home_is_fail(claude, _isolated_home, capsys):
    code, checks, _ = checks_of(capsys, "--offline")   # the isolated home has no evidence/ or cache/ yet
    assert code == 1 and checks["home"]["status"] == "FAIL" and checks["home"]["fix"] == "run `stockdesk init`"


def test_offline_makes_no_network_calls(claude, ready_home, monkeypatch, capsys):
    for probe in ("check_sec_network", "check_prices_network", "check_gdelt_network"):
        monkeypatch.setattr(doctor, probe, lambda: pytest.fail("network probe ran with --offline"))
    _, checks, _ = checks_of(capsys, "--offline")
    assert checks["network"]["status"] == "WARN" and "--offline" in checks["network"]["detail"]


@pytest.fixture
def network(monkeypatch):
    from stockdesk import fund

    state = {"gdelt": (json.dumps({"articles": []}), 200), "calls": []}

    def fake_get(url, headers=None, timeout=None):
        state["calls"].append((url, headers["User-Agent"]))
        if url == fund.TICKERS_URL:
            return Resp(json.dumps({"0": {"ticker": "NKE"}, "1": {"ticker": "AAPL"}}))
        if "gdeltproject" in url:
            return Resp(*state["gdelt"])
        return Resp("nf", 404)

    frame = pd.DataFrame({"Close": [500.0]}, index=["2026-11-06"])
    monkeypatch.setattr(common, "_requests_get", fake_get)
    monkeypatch.setattr(common, "fetch_prices", lambda t, **k: (frame, "2026-11-06T21:00:00Z"))
    return state


def test_network_checks_pass(claude, ready_home, network, capsys):
    code, checks, _ = checks_of(capsys)
    assert code == 0
    assert [checks[n]["status"] for n in ("network_sec", "network_yfinance", "network_gdelt")] == ["PASS"] * 3
    sec_ua = next(ua for url, ua in network["calls"] if "sec.gov" in url)
    gdelt_ua = next(ua for url, ua in network["calls"] if "gdelt" in url)
    assert "@" in sec_ua and "@" not in gdelt_ua          # the contact email goes to SEC only


def test_gdelt_rate_limit_is_a_warning_not_a_failure(claude, ready_home, network, capsys):
    network["gdelt"] = ("too many", 429)
    code, checks, _ = checks_of(capsys)
    assert code == 0 and checks["network_gdelt"]["status"] == "WARN"
    assert sum("gdelt" in url for url, _ in network["calls"]) == 1      # one request, no retry


def test_gdelt_check_uses_the_cache(claude, ready_home, network, capsys):
    checks_of(capsys)
    _, checks, _ = checks_of(capsys)
    assert sum("gdelt" in url for url, _ in network["calls"]) == 1 and "cached" in checks["network_gdelt"]["detail"]


def test_unreachable_sec_is_fail(claude, ready_home, network, monkeypatch, capsys):
    import requests

    monkeypatch.setattr(common, "_requests_get", lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError()))
    code, checks, _ = checks_of(capsys)
    assert code == 1 and checks["network_sec"]["status"] == "FAIL"


def test_human_output_has_one_line_per_check(claude, ready_home, capsys):
    assert cli.main(["doctor", "--offline"]) == 0
    lines = [l for l in capsys.readouterr().out.splitlines() if l[:4] in ("PASS", "WARN", "FAIL")]
    assert len(lines) == 8


def test_bad_flag_exits_1(capsys):
    assert doctor.main(["--nope"]) == 1
