"""stockdesk doctor: check that this machine can run the Stock Desk agents.

  stockdesk doctor [--offline] [--json]

One line per check, PASS, WARN or FAIL, each WARN/FAIL with a plain-English fix. Exit 0 when nothing FAILs.
--offline skips the three network checks. --json prints {"ok": ..., "checks": [...]}.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from typing import Sequence

from . import __version__, common, locate

SWITCH_INSTALL_DOCS = "https://docs.switchagents.ai/flintai/switch/getting-started/install-switch-console"
CLAUDE_CODE_DOCS = "https://docs.anthropic.com/en/docs/claude-code/setup"
MIN_PYTHON = (3, 11)
CLAUDE_TIMEOUT = 10.0
AGENTS = ("chief.md", "fundamental.md", "technical.md", "sentiment.md")
CONFIGS = ("peers.json", "sector_etf.json", "news_names.json")
TEMPLATES = ("desk-team.skeleton", "mention-test.template.yaml")
GDELT_PROBE = {"query": "Apple sourcelang:english", "mode": "artlist", "maxrecords": 1, "format": "json",
               "timespan": "1d"}  # its own query, so it never touches the sentiment agent's cached one
PRICE_PROBE = "SPY"

_which = shutil.which
_run = subprocess.run


@dataclass
class Check:
    name: str
    status: str  # PASS | WARN | FAIL
    detail: str
    fix: str = ""


def check_python() -> Check:
    found = ".".join(map(str, sys.version_info[:3]))
    if sys.version_info[:2] >= MIN_PYTHON:
        return Check("python", "PASS", f"Python {found}")
    return Check("python", "FAIL", f"Python {found}", "install Python 3.11 or newer, then reinstall with pipx")


def check_executable() -> Check:
    argv, how = locate.executable()
    text = locate.command_text(argv)
    if len(argv) == 1:
        return Check("stockdesk", "PASS", f"stockdesk {__version__}; template will call {text} ({how})")
    return Check("stockdesk", "WARN", f"stockdesk {__version__}; template would call {text} ({how})",
                 "install with `pipx install git+https://github.com/<owner>/stock-desk` so a stockdesk executable exists")


def check_home() -> Check:
    try:
        path, source = common.home_source()
    except common.ToolError as exc:
        return Check("home", "FAIL", exc.detail, "set STOCKDESK_HOME to an absolute path, or unset it")
    if not path.is_dir():
        return Check("home", "FAIL", f"{path} does not exist ({source})", "run `stockdesk init`")
    try:
        with tempfile.TemporaryFile(dir=path):
            pass
    except OSError as exc:
        return Check("home", "FAIL", f"{path} is not writable: {exc.strerror}", f"fix the permissions of {path}")
    missing = [sub for sub in ("evidence", "cache") if not (path / sub).is_dir()]
    if missing:
        return Check("home", "FAIL", f"{path} has no {' or '.join(missing)}/", "run `stockdesk init`")
    return Check("home", "PASS", f"{path} ({source}), writable, evidence/ and cache/ present")


def _mask_email(text: str) -> str:
    return re.sub(r"([^@\s])[^@\s]*@", r"\1***@", text)


def check_sec_user_agent() -> Check:
    try:
        ua = common.env(common.SEC_UA_ENV) or ""
    except common.ToolError as exc:
        return Check("sec_user_agent", "FAIL", exc.detail, "fix STOCKDESK_HOME first")
    if not ua:
        return Check("sec_user_agent", "FAIL", "SEC_USER_AGENT is not set", "run `stockdesk init`")
    if not common.sec_user_agent_ok(ua):
        return Check("sec_user_agent", "FAIL", "SEC_USER_AGENT has no real contact email",
                     "run `stockdesk init --force` with your email")
    return Check("sec_user_agent", "PASS", f"set: {_mask_email(ua)}")


def check_claude() -> Check:
    path = _which("claude")
    if not path:
        return Check("claude_code", "FAIL", "the claude command is not on PATH",
                     f"install Claude Code ({CLAUDE_CODE_DOCS}) and sign in; Switch Console runs the agents with it")
    try:
        done = _run([path, "--version"], capture_output=True, text=True, timeout=CLAUDE_TIMEOUT)
    except subprocess.TimeoutExpired:
        return Check("claude_code", "WARN", f"{path} --version did not answer in {CLAUDE_TIMEOUT:.0f} s",
                     "run `claude --version` yourself and check it starts")
    except OSError as exc:
        return Check("claude_code", "FAIL", f"{path} could not run: {exc}", f"reinstall Claude Code ({CLAUDE_CODE_DOCS})")
    version = (done.stdout or done.stderr or "").strip().splitlines()[:1]
    if done.returncode != 0:
        return Check("claude_code", "WARN", f"{path} --version exited {done.returncode}",
                     "run `claude --version` yourself and fix what it reports")
    return Check("claude_code", "PASS", f"{path}: {version[0] if version else 'version unknown'}")


def check_switch_console() -> Check:
    # The Switch docs (sandbox-quantum/switch, docs/official/getting-started/install-switch-console.md) describe a
    # desktop app and document no command or file to detect it by, so this check does not guess one.
    return Check("switch_console", "WARN", "cannot detect Switch Console automatically",
                 f"confirm it is installed and running: {SWITCH_INSTALL_DOCS}")


def check_sec_network() -> Check:
    from . import fund

    try:
        ua_ok = common.sec_user_agent_ok(common.env(common.SEC_UA_ENV) or "")
    except common.ToolError:
        ua_ok = False
    if not ua_ok:
        return Check("network_sec", "WARN", "skipped: SEC_USER_AGENT is not set", "run `stockdesk init`, then doctor again")
    try:
        result = common.http_get(fund.TICKERS_URL, sec=True, ttl=-1, attempts=1, timeout=20,
                                 min_interval=fund.SEC_INTERVAL)
        count = len(json.loads(result.text))
    except common.ToolError as exc:
        return _network_problem("network_sec", "sec.gov", exc)
    except ValueError:
        return Check("network_sec", "FAIL", "sec.gov answered with something that is not JSON",
                     "try again later; check https://www.sec.gov is reachable from this machine")
    return Check("network_sec", "PASS", f"sec.gov ticker map: {count} companies, with your User-Agent")


def check_prices_network() -> Check:
    try:
        frame, _ = common.fetch_prices(PRICE_PROBE, period="1d", ttl=-1)
    except common.ToolError as exc:
        if exc.code == "no_data":
            return Check("network_yfinance", "WARN", f"Yahoo returned no bar for {PRICE_PROBE} today ({exc.detail})",
                         "usually a market holiday; try again on a trading day")
        return _network_problem("network_yfinance", "Yahoo (yfinance)", exc)
    return Check("network_yfinance", "PASS", f"Yahoo (yfinance): {PRICE_PROBE} bar for {frame.index[-1]}")


def check_gdelt_network() -> Check:
    from . import news

    try:
        result = common.http_get(news.GDELT_URL, params=GDELT_PROBE, ttl=news.news_cache_ttl(),
                                 min_interval=news.GDELT_INTERVAL, attempts=1, retry_rate_limited=False,
                                 validate=news._validate_body)
    except common.ToolError as exc:
        return _network_problem("network_gdelt", "GDELT", exc)
    how = f"cached, fetched {result.fetched_at}" if result.from_cache else "fresh request"
    return Check("network_gdelt", "PASS", f"GDELT answered ({how}; requests spaced {news.GDELT_INTERVAL:.1f} s apart)")


def _network_problem(name: str, host: str, exc: common.ToolError) -> Check:
    if exc.code == "rate_limited":
        return Check(name, "WARN", f"{host} is rate limiting this machine: {exc.detail}",
                     "wait (GDELT can block for hours after refusals) and run doctor again; the desk will report gaps")
    return Check(name, "FAIL", f"{host}: {exc.code}: {exc.detail}",
                 "check this machine's internet connection, proxy or firewall")


def check_bundled_data() -> Check:
    expected = [("agents", n) for n in AGENTS] + [("config", n) for n in CONFIGS] + [("templates", n) for n in TEMPLATES]
    missing = [f"{folder}/{name}" for folder, name in expected if not common.bundled(folder, name).is_file()]
    if missing:
        return Check("bundled_data", "FAIL", f"missing from the installed package: {', '.join(missing)}",
                     "reinstall: pipx reinstall stock-desk")
    return Check("bundled_data", "PASS", f"{len(AGENTS)} agents, {len(CONFIGS)} configs, {len(TEMPLATES)} templates")


def run_checks(offline: bool) -> list[Check]:
    checks = [check_python(), check_executable(), check_home(), check_sec_user_agent(), check_claude(),
              check_switch_console()]
    if offline:
        checks.append(Check("network", "WARN", "skipped (--offline)", "run `stockdesk doctor` without --offline"))
    else:
        for probe in (check_sec_network, check_prices_network, check_gdelt_network):
            try:
                checks.append(probe())
            except Exception as exc:  # a doctor must report, not crash
                checks.append(Check(probe.__name__.replace("check_", ""), "FAIL", f"{type(exc).__name__}: {exc}",
                                    "run the matching stockdesk tool to see the full error"))
    checks.append(check_bundled_data())
    return checks


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stockdesk doctor", description="Check this machine's Stock Desk setup.")
    parser.add_argument("--offline", action="store_true", help="skip the network checks")
    parser.add_argument("--json", action="store_true", help="print one JSON object instead of text")
    try:
        args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as exc:
        return 0 if exc.code == 0 else 1
    checks = run_checks(args.offline)
    ok = not any(c.status == "FAIL" for c in checks)
    if args.json:
        print(json.dumps({"ok": ok, "checks": [asdict(c) for c in checks]}))
    else:
        width = max(len(c.name) for c in checks)
        for c in checks:
            print(f"{c.status:<4}  {c.name:<{width}}  {c.detail}")
            if c.fix and c.status != "PASS":
                print(f"{'':<4}  {'':<{width}}  fix: {c.fix}")
        print("OK: no failures." if ok else "Some checks FAILED; apply the fixes above, then run `stockdesk doctor` again.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
