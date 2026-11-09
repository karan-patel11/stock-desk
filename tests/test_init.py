"""stockdesk init (Phase 3 of packaging)."""
from __future__ import annotations

import json
import os
import stat
import sys

import pytest

from stockdesk import cli, common, init


@pytest.fixture
def user_home(tmp_path, monkeypatch):
    monkeypatch.delenv("STOCKDESK_HOME", raising=False)
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    return tmp_path / "user"


def run_init(capsys, *argv, prompt=None):
    code = init.main(list(argv), prompt=prompt or (lambda q: pytest.fail(f"unexpected prompt {q!r}")))
    return code, capsys.readouterr()


def test_non_interactive_happy_path(user_home, capsys):
    code, out = run_init(capsys, "--non-interactive", "--sec-email", "jane@uni.edu")
    assert code == 0, out.err
    home = user_home / ".stockdesk"
    for sub in ("evidence", "cache", "config"):
        assert (home / sub).is_dir()
    assert common.read_config_env(home / "config.env") == {"SEC_USER_AGENT": "StockDesk jane@uni.edu"}
    assert common.home() == home and common.user_agent(required=True) == "StockDesk jane@uni.edu"
    assert out.out.rstrip().endswith("Next:\n  stockdesk doctor\n  stockdesk template")


def test_app_name_and_json_output(user_home, capsys):
    code, out = run_init(capsys, "--non-interactive", "--sec-email", "jane@uni.edu", "--app-name", "GW Desk", "--json")
    result = json.loads(out.out)
    assert code == 0 and result["ok"] is True and result["sec_user_agent"] == "GW Desk jane@uni.edu"
    assert result["next"] == ["stockdesk doctor", "stockdesk template"]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_config_env_is_mode_0600(user_home, capsys):
    run_init(capsys, "--non-interactive", "--sec-email", "jane@uni.edu")
    mode = stat.S_IMODE(os.stat(user_home / ".stockdesk" / "config.env").st_mode)
    assert mode == 0o600


def test_refuses_to_overwrite_without_force_and_shows_the_change(user_home, capsys):
    run_init(capsys, "--non-interactive", "--sec-email", "jane@uni.edu")
    path = user_home / ".stockdesk" / "config.env"
    path.write_text(path.read_text() + "SLACK_CHANNEL_ID=C123\n")
    before = path.read_text()
    code, out = run_init(capsys, "--non-interactive", "--sec-email", "new@uni.edu")
    assert code == 1 and path.read_text() == before
    assert "'StockDesk jane@uni.edu' -> 'StockDesk new@uni.edu'" in out.err and "--force" in out.err
    code, out = run_init(capsys, "--non-interactive", "--sec-email", "new@uni.edu", "--force")
    assert code == 0
    assert common.read_config_env(path) == {"SEC_USER_AGENT": "StockDesk new@uni.edu", "SLACK_CHANNEL_ID": "C123"}


def test_rerun_with_the_same_values_is_fine(user_home, capsys):
    run_init(capsys, "--non-interactive", "--sec-email", "jane@uni.edu")
    code, out = run_init(capsys, "--non-interactive", "--sec-email", "jane@uni.edu")
    assert code == 0 and "already up to date" in out.out


@pytest.mark.parametrize("email", ["not-an-email", "a@b", "you@example.com", "your-email@uni.edu", "a b@uni.edu"])
def test_bad_email_exits_1_and_writes_nothing(email, user_home, capsys):
    code, out = run_init(capsys, "--non-interactive", "--sec-email", email, "--json")
    assert code == 1 and json.loads(out.out)["error"] == "bad_input"
    assert not (user_home / ".stockdesk").exists()


def test_non_interactive_needs_the_email(user_home, capsys):
    code, out = run_init(capsys, "--non-interactive")
    assert code == 1 and "--sec-email" in out.err


def test_bad_flag_exits_1(user_home, capsys):
    assert run_init(capsys, "--nope")[0] == 1


def test_interactive_prompts_explain_why_and_retry_a_bad_email(user_home, capsys):
    answers = iter(["oops", "jane@uni.edu", ""])
    code, out = run_init(capsys, prompt=lambda q: next(answers))
    assert code == 0 and "fair-access" in out.out and "not an email" in out.err
    assert common.read_config_env(user_home / ".stockdesk" / "config.env")["SEC_USER_AGENT"] == "StockDesk jane@uni.edu"


def test_custom_home_is_recorded_in_the_default_config_file(user_home, tmp_path, capsys):
    custom = tmp_path / "desk-data"
    code, _ = run_init(capsys, "--non-interactive", "--sec-email", "jane@uni.edu", "--home", str(custom))
    assert code == 0
    assert common.read_config_env(user_home / ".stockdesk" / "config.env") == {"STOCKDESK_HOME": str(custom)}
    assert common.home() == custom and (custom / "evidence").is_dir()
    assert common.user_agent(required=True) == "StockDesk jane@uni.edu"


def test_custom_home_does_not_silently_repoint_an_existing_default_home(user_home, tmp_path, capsys):
    run_init(capsys, "--non-interactive", "--sec-email", "jane@uni.edu")
    code, out = run_init(capsys, "--non-interactive", "--sec-email", "jane@uni.edu", "--home", str(tmp_path / "x"))
    assert code == 1 and "STOCKDESK_HOME" in out.err
    assert not (tmp_path / "x").exists() and common.home() == user_home / ".stockdesk"


def test_copy_config_copies_the_bundled_json_and_keeps_edits(user_home, capsys):
    run_init(capsys, "--non-interactive", "--sec-email", "jane@uni.edu", "--copy-config")
    config = user_home / ".stockdesk" / "config"
    for name in init.CONFIG_NAMES:
        assert (config / name).read_bytes() == common.bundled("config", name).read_bytes()
    (config / "peers.json").write_text('{"NKE": ["ADDYY"]}')
    code, out = run_init(capsys, "--non-interactive", "--sec-email", "jane@uni.edu", "--copy-config")
    assert code == 0 and "kept" in out.out and (config / "peers.json").read_text() == '{"NKE": ["ADDYY"]}'


def test_init_is_a_stockdesk_subcommand(user_home, capsys):
    assert cli.main(["init", "--non-interactive", "--sec-email", "jane@uni.edu", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
