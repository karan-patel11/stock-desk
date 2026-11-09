"""Packaging: `stockdesk <tool>` and the deprecated `python tools/<tool>.py` shims give identical JSON."""
from __future__ import annotations

import functools
import json
import os
import re
import runpy
import subprocess
import sys
import tomllib
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

import stockdesk
from stockdesk import cli, common, fund, precedent, tech

ROOT = Path(__file__).resolve().parent.parent
TODAY = date(2026, 11, 4)
CIK10 = "0001234567"
SESSIONS = [d.strftime("%Y-%m-%d") for d in pd.bdate_range(end="2026-11-04", periods=520)]
PRICES = pd.DataFrame({
    "Open": [100 + i * 0.1 for i in range(520)], "High": [101 + i * 0.1 for i in range(520)],
    "Low": [99 + i * 0.1 for i in range(520)], "Close": [100 + i * 0.1 + (i % 7) * 0.3 for i in range(520)],
    "Volume": [1e6 + (i % 5) * 1e5 for i in range(520)]}, index=SESSIONS)
GDELT_ARTICLES = {"articles": [
    {"url": f"https://example.com/s{n}", "title": f"Nike tariffs earnings story {n}", "seendate": f"2026110{n}T120000Z",
     "domain": "example.com", "language": "English", "sourcecountry": "United States"} for n in range(1, 5)]}
GDELT_TONE = {"timeline": [{"series": "Average Tone", "data": [
    {"date": "20261101T000000Z", "value": -1.0}, {"date": "20261102T000000Z", "value": -2.0}]}]}

# One fixture run per tool. "{run}" is the run id round start returned in the same home.
CASES = {
    "fund": ["TSTCO", "--quarters", "8", "--run", "{run}"],
    "tech": ["NKE", "--lookback", "2y", "--run", "{run}"],
    "news": ["--ticker", "NKE", "--days", "90", "--run", "{run}"],
    "precedent": ["NKE", "--dates", SESSIONS[300], "--windows", "5,30", "--etf", "XLY", "--run", "{run}"],
    "verify": ["E1", "--value", "0", "--run", "{run}"],
    "round": ["status", "--run", "{run}"],
    "confidence": ["--run", "{run}", "--horizon", "medium", "--direction", "bullish", "--fund", "bullish",
                   "--tech", "bullish", "--sent", "not_measured"],
    "evidence-table": ["--run", "{run}"],
}
SHIM = {name: ROOT / "tools" / f"{name.replace('-', '_')}.py" for name in CASES}


class Resp:
    def __init__(self, text, status=200):
        self.text, self.status_code, self.headers = text, status, {}


@pytest.fixture
def sources(monkeypatch, fixtures_dir):
    routes = {
        fund.TICKERS_URL: (fixtures_dir / "synthetic_company_tickers.json").read_text(),
        fund.SUBMISSIONS_URL.format(cik=CIK10): (fixtures_dir / "synthetic_submissions_tstco.json").read_text(),
        fund.FACTS_URL.format(cik=CIK10): (fixtures_dir / "synthetic_companyfacts_tstco.json").read_text(),
    }

    def fake_get(url, headers=None, timeout=None):
        if url in routes:
            return Resp(routes[url])
        if "mode=artlist" in url:
            return Resp(json.dumps(GDELT_ARTICLES))
        if "mode=timelinetone" in url:
            return Resp(json.dumps(GDELT_TONE))
        return Resp("not found", 404)

    monkeypatch.setattr(common, "_requests_get", fake_get)
    monkeypatch.setattr(common, "fetch_prices",
                        lambda t, **k: (PRICES if t == "NKE" else PRICES * 0.5, "2026-11-04T12:00:00Z"))
    for module in (fund, tech, precedent):  # pin "today" so the fixtures never go stale
        monkeypatch.setattr(module, "main", functools.partial(module.main, today=TODAY))


def via_cli(capsys, command, argv):
    code = cli.main([command, *argv])
    return code, capsys.readouterr().out


def via_shim(capsys, command, argv, monkeypatch):
    monkeypatch.setattr(sys, "argv", [str(SHIM[command]), *argv])
    with pytest.raises(SystemExit) as done:
        runpy.run_path(str(SHIM[command]), run_name="__main__")
    return int(done.value.code or 0), capsys.readouterr().out


def scenario(tmp_path, monkeypatch, capsys, label, command, invoke):
    home = tmp_path / label
    home.mkdir()
    monkeypatch.setenv("STOCKDESK_HOME", str(home))
    code, out = via_cli(capsys, "round", ["start", "NKE", "--goal", "medium"])
    assert code == 0, out
    run = json.loads(out)["run"]
    if command in ("verify", "confidence", "evidence-table"):  # these read what the data tools wrote
        assert via_cli(capsys, "tech", [a.replace("{run}", run) for a in CASES["tech"]])[0] == 0
    code, out = invoke(command, [a.replace("{run}", run) for a in CASES[command]])
    assert out.count("\n") == 1, "stdout must be exactly one JSON line"
    return code, re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", "<ts>", out)


@pytest.mark.parametrize("command", sorted(CASES))
def test_cli_and_shim_give_identical_json(command, sources, tmp_path, monkeypatch, capsys):
    new = scenario(tmp_path, monkeypatch, capsys, "cli", command, lambda c, a: via_cli(capsys, c, a))
    old = scenario(tmp_path, monkeypatch, capsys, "shim", command, lambda c, a: via_shim(capsys, c, a, monkeypatch))
    assert new == old
    code, out = new
    assert code == 0 and json.loads(out)["ok"] is True, out


@pytest.mark.parametrize("argv, detail", [
    ([], "missing command"),
    (["bogus"], "unknown command 'bogus'"),
    (["--nope"], "unrecognized arguments"),
    (["tech", "--nope"], "required: ticker"),
])
def test_bad_commands_are_bad_input_json(argv, detail, capsys):
    assert cli.main(argv) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and out["error"] == "bad_input" and detail in out["detail"]


def test_version(capsys):
    assert cli.main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == f"stockdesk {stockdesk.__version__}"


def _subprocess_env(home: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("STOCKDESK_")}
    env.update(STOCKDESK_HOME=str(home), HOME=str(home), PYTHONPATH=str(ROOT / "src"))
    return env


def test_shim_and_module_match_as_real_processes(tmp_path):
    """No network: round start/status and an unknown command, run exactly as a shell would."""
    outputs = []
    for label, prefix in (("shim", [str(ROOT / "tools" / "round.py")]), ("module", ["-m", "stockdesk", "round"])):
        home = tmp_path / label
        home.mkdir()
        env = _subprocess_env(home)
        start = subprocess.run([sys.executable, *prefix, "start", "NKE"], capture_output=True, text=True, env=env)
        status = subprocess.run([sys.executable, *prefix, "status"], capture_output=True, text=True, env=env)
        outputs.append((start.returncode, start.stdout, status.returncode, status.stdout))
    assert outputs[0] == outputs[1]
    assert outputs[0][0] == 0 and json.loads(outputs[0][1])["ok"] is True
    bad = subprocess.run([sys.executable, "-m", "stockdesk", "nope"], capture_output=True, text=True,
                         env=_subprocess_env(tmp_path))
    assert bad.returncode == 1 and json.loads(bad.stdout)["error"] == "bad_input"


def test_requirements_txt_matches_pyproject():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    declared = set(project["dependencies"]) | set(project["optional-dependencies"]["dev"])
    listed = {line.strip() for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
              if line.strip() and not line.startswith("#")}
    assert listed == declared
    assert {re.split(r"[<>=]", d)[0].lower() for d in project["dependencies"]} == {"requests", "pandas", "yfinance"}


def test_every_tool_has_a_subcommand_and_a_shim():
    assert set(cli.DATA_TOOLS) == set(CASES)
    for command, module in cli.DATA_TOOLS.items():
        assert (ROOT / "src" / "stockdesk" / f"{module}.py").is_file()
        shim = SHIM[command].read_text(encoding="utf-8")
        assert "Deprecated" in shim and f'main(["{command}", *sys.argv[1:]])' in shim
