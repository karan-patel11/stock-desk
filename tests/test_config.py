"""Data home, config.env and config JSON lookup (Phase 2 of packaging)."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

import stockdesk
from stockdesk import common, fund, round as rnd, tech
from stockdesk.common import ToolError

PACKAGE_DIR = Path(stockdesk.__file__).resolve().parent


@pytest.fixture
def user_home(tmp_path, monkeypatch):
    """~ for this test, with no STOCKDESK_HOME in the environment."""
    monkeypatch.delenv("STOCKDESK_HOME", raising=False)
    return tmp_path / "user"


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ---------------- home precedence ----------------

def test_default_home_is_dot_stockdesk(user_home):
    assert common.home_source() == (user_home / ".stockdesk", "default")


def test_config_file_home_beats_default(user_home, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    write(user_home / ".stockdesk" / "config.env", f"STOCKDESK_HOME={elsewhere}\n")
    path, source = common.home_source()
    assert path == elsewhere and "config.env" in source


def test_environment_beats_config_file(user_home, tmp_path, monkeypatch):
    write(user_home / ".stockdesk" / "config.env", f"STOCKDESK_HOME={tmp_path / 'from-file'}\n")
    monkeypatch.setenv("STOCKDESK_HOME", str(tmp_path / "from-env"))
    assert common.home_source() == (tmp_path / "from-env", "environment variable STOCKDESK_HOME")


@pytest.mark.parametrize("where", ["env", "file"])
def test_relative_home_is_bad_input(where, user_home, monkeypatch):
    if where == "env":
        monkeypatch.setenv("STOCKDESK_HOME", "relative/home")
    else:
        write(user_home / ".stockdesk" / "config.env", "STOCKDESK_HOME=relative/home\n")
    with pytest.raises(ToolError) as err:
        common.home()
    assert err.value.code == "bad_input" and "absolute" in err.value.detail


def test_empty_values_count_as_unset(user_home, monkeypatch):
    monkeypatch.setenv("STOCKDESK_HOME", "  ")
    write(user_home / ".stockdesk" / "config.env", "STOCKDESK_HOME=\n")
    assert common.home() == user_home / ".stockdesk"


def test_no_repo_root_fallback_any_more():
    assert not hasattr(common, "repo_root")


# ---------------- config.env keys ----------------

def test_env_reads_home_config_file_and_environment_wins(_isolated_home, monkeypatch):
    write(_isolated_home / "config.env", '# comment\nSEC_USER_AGENT="FileApp file@uni.edu"\nOTHER = x\n')
    monkeypatch.delenv("SEC_USER_AGENT")
    assert common.env("SEC_USER_AGENT") == "FileApp file@uni.edu" and common.env("OTHER") == "x"
    monkeypatch.setenv("SEC_USER_AGENT", "EnvApp env@uni.edu")
    assert common.env("SEC_USER_AGENT") == "EnvApp env@uni.edu"


def test_keys_fall_back_to_the_default_config_file_when_home_moved(user_home, tmp_path, monkeypatch):
    elsewhere = tmp_path / "elsewhere"
    write(user_home / ".stockdesk" / "config.env", f"STOCKDESK_HOME={elsewhere}\nSEC_USER_AGENT=A a@uni.edu\n")
    monkeypatch.delenv("SEC_USER_AGENT")
    assert common.config_files() == [elsewhere / "config.env", user_home / ".stockdesk" / "config.env"]
    assert common.env("SEC_USER_AGENT") == "A a@uni.edu"
    write(elsewhere / "config.env", "SEC_USER_AGENT=B b@uni.edu\n")
    assert common.env("SEC_USER_AGENT") == "B b@uni.edu"   # the home's own file wins


def test_dot_env_is_not_read_any_more(_isolated_home, monkeypatch):
    write(_isolated_home / ".env", "SEC_USER_AGENT=Old old@uni.edu\n")
    monkeypatch.delenv("SEC_USER_AGENT")
    assert common.env("SEC_USER_AGENT") is None


# ---------------- config JSON: override or bundled, never merged ----------------

def test_override_is_used_whole_and_logged(_isolated_home, capsys):
    write(_isolated_home / "config" / "peers.json", json.dumps({"ZZZ": ["AAA"]}))
    assert common.load_config("peers.json") == {"ZZZ": ["AAA"]}   # nothing from the bundled copy
    assert "using override" in capsys.readouterr().err


def test_bundled_copy_is_used_without_an_override(_isolated_home, capsys):
    (_isolated_home / "config" / "peers.json").unlink()
    bundled = json.loads(common.bundled("config", "peers.json").read_text(encoding="utf-8"))
    assert common.load_config("peers.json") == bundled and bundled
    assert "using bundled default" in capsys.readouterr().err


def test_bad_override_is_an_error_not_a_silent_fallback(_isolated_home):
    write(_isolated_home / "config" / "peers.json", "{not json")
    with pytest.raises(ToolError) as err:
        common.load_config("peers.json")
    assert err.value.code == "bad_input"


def test_bundled_configs_ship_in_the_package():
    for name in ("peers.json", "sector_etf.json", "news_names.json"):
        assert json.loads(common.bundled("config", name).read_text(encoding="utf-8"))


# ---------------- SEC_USER_AGENT fails closed ----------------

def _no_requests(monkeypatch):
    calls = []
    monkeypatch.setattr(common, "_requests_get", lambda url, **k: calls.append(url))
    return calls


@pytest.mark.parametrize("value", [None, "StockDesk", "StockDesk your-name your-email@example.com"])
def test_fund_without_a_real_sec_contact_is_bad_input(value, monkeypatch, run_id):
    calls = _no_requests(monkeypatch)
    if value is None:
        monkeypatch.delenv("SEC_USER_AGENT")
    else:
        monkeypatch.setenv("SEC_USER_AGENT", value)
    with pytest.raises(ToolError) as err:
        fund.main(["NKE", "--run", run_id])
    assert err.value.code == "bad_input" and "run `stockdesk init`" in err.value.detail
    assert calls == []                                   # nothing sent without a contact, no default email


def test_missing_sec_contact_via_the_cli_is_contract_json(monkeypatch, run_id, capsys):
    from stockdesk import cli

    _no_requests(monkeypatch)
    monkeypatch.delenv("SEC_USER_AGENT")
    assert cli.main(["fund", "NKE", "--run", run_id]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out == {"ok": False, "error": "bad_input", "detail": out["detail"]} and "stockdesk init" in out["detail"]


# ---------------- nothing writes inside the installed package ----------------

def _tree(root: Path) -> dict[str, tuple[int, int]]:
    return {str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts}


def test_tools_never_write_inside_the_package(monkeypatch, user_home, capsys):
    before = _tree(PACKAGE_DIR)
    index = [d.strftime("%Y-%m-%d") for d in pd.bdate_range(end="2026-11-04", periods=300)]
    frame = pd.DataFrame({c: [100.0 + i for i in range(300)] for c in ("Open", "High", "Low", "Close", "Volume")},
                         index=index)
    monkeypatch.setattr(common, "fetch_prices", lambda t, **k: (frame, "2026-11-04T12:00:00Z"))
    run, _, _ = rnd.main(["start", "NKE"])                         # default home, ~/.stockdesk
    tech.main(["NKE", "--run", run], today=pd.Timestamp("2026-11-04").date())
    common.load_config("sector_etf.json")
    assert (user_home / ".stockdesk" / "evidence" / run).is_dir()
    assert _tree(PACKAGE_DIR) == before
