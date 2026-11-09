"""stockdesk template (Phase 5 of packaging)."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from stockdesk import cli, common, locate, template

ROOT = Path(__file__).resolve().parent.parent
EXE = "/opt/pipx/bin/stockdesk"
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")


@pytest.fixture
def fixed_exe(monkeypatch):
    monkeypatch.setattr(locate, "executable", lambda: ([EXE], "PATH"))
    return EXE


def generate(capsys, tmp_path, *argv):
    out = tmp_path / "out.yaml"
    code = template.main(["--out", str(out), *argv])
    captured = capsys.readouterr()
    return code, (out.read_text(encoding="utf-8") if out.is_file() else ""), captured


def test_desk_template_embeds_the_absolute_command_and_home(fixed_exe, _isolated_home, tmp_path, capsys):
    code, text, out = generate(capsys, tmp_path)
    assert code == 0, out.err
    prefix = f"STOCKDESK_HOME={_isolated_home} {EXE}"
    assert f"{prefix} NAME ARGS" in text                       # the chief's tool line
    for call in ("fund TICKER --quarters 12", "tech TICKER --lookback 2y", "news --ticker TICKER --days 90"):
        assert f"{prefix} {call} --run RUN" in text
    assert f"mkdir -p {_isolated_home}/evidence/RUN/reports" in text
    assert prefix in out.out


def test_desk_template_has_no_old_variables_emails_or_repo_paths(fixed_exe, _isolated_home, tmp_path, capsys):
    _, text, _ = generate(capsys, tmp_path)
    assert "$STOCKDESK_PY" not in text and "$STOCKDESK" not in text and not re.search(r"\$[A-Z_]{3,}", text)
    assert "{python}" not in text and "{stockdesk_home}" not in text and "tools/" not in text
    assert not EMAIL.search(text)                              # SEC_USER_AGENT is never copied in
    assert str(ROOT) not in text
    assert set(re.findall(r"\{[^}]*\}", text)) <= {"{$agents_dir}", "{$creator}", "{ticker}", "{bridge}"}


def test_desk_template_parses_as_a_switch_template(fixed_exe, _isolated_home, tmp_path, capsys):
    yaml = pytest.importorskip("yaml")
    _, text, out = generate(capsys, tmp_path, "--ticker", "nke")
    doc = yaml.safe_load(text)
    assert set(doc["params"]) == {"ticker", "bridge"} and doc["params"]["ticker"]["default"] == "NKE"
    assert "default" not in doc["params"]["bridge"]           # required: the deployer picks the connection
    assert [a["name"] for a in doc["agents"]] == template.DESK_AGENTS
    assert all(f"{EXE} " in a["instructions"] for a in doc["agents"])
    assert "YAML parsed: 4 agents" in out.out


def test_paths_with_spaces_are_quoted_and_still_parse(fixed_exe, tmp_path, monkeypatch, capsys):
    yaml = pytest.importorskip("yaml")
    home = tmp_path / "My Desk"
    monkeypatch.setenv("STOCKDESK_HOME", str(home))
    _, text, _ = generate(capsys, tmp_path)
    assert f"STOCKDESK_HOME='{home}' {EXE} fund" in text
    assert f"'{home}'/evidence/RUN/reports" in yaml.safe_load(text)["agents"][0]["instructions"]


def test_a_brace_in_the_home_is_refused(fixed_exe, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("STOCKDESK_HOME", str(tmp_path / "a{b}"))
    code, text, out = generate(capsys, tmp_path)
    assert code == 1 and text == "" and "brace" in out.err


def test_a_brace_in_an_agent_file_is_refused(fixed_exe, tmp_path, monkeypatch):
    agents = tmp_path / "agents"
    agents.mkdir()
    for name in template.AGENT_NAMES:
        (agents / f"{name}.md").write_text("ok $STOCKDESK x\n")
    (agents / "chief.md").write_text("use {this}\n")
    real = common.bundled
    monkeypatch.setattr(common, "bundled", lambda *p: agents / p[1] if p[0] == "agents" else real(*p))
    with pytest.raises(template.TemplateError, match="curly brace"):
        template.build_desk([EXE], tmp_path, "slack", None)


def test_mention_test_is_the_two_agent_template(_isolated_home, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert template.main(["--mention-test"]) == 0
    text = (tmp_path / "mention-test.template.yaml").read_text(encoding="utf-8")
    assert '- name: "s0-chief"' in text and '- name: "s0-technical"' in text and '- name: "desk-' not in text
    assert not EMAIL.search(text) and str(ROOT) not in text
    yaml = pytest.importorskip("yaml")
    assert [a["name"] for a in yaml.safe_load(text)["agents"]] == ["s0-chief", "s0-technical"]
    assert "MENTION TEST PASSED" in capsys.readouterr().out


def test_bridge_option_changes_only_the_form_description(fixed_exe, _isolated_home, tmp_path, capsys):
    _, slack, _ = generate(capsys, tmp_path)
    _, mattermost, out = generate(capsys, tmp_path, "--bridge", "mattermost")
    assert "Pick your Slack connection" in slack and "Pick your Mattermost connection" in mattermost
    assert "deploy/messaging-apps/mattermost" in out.out


def test_without_pyyaml_it_warns(fixed_exe, _isolated_home, tmp_path, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "yaml", None)            # import yaml now raises ImportError
    code, text, out = generate(capsys, tmp_path)
    assert code == 0 and text and "WARN: PyYAML not installed, YAML not validated" in out.out


@pytest.mark.parametrize("argv", [["--ticker", "not a ticker"], ["--bridge", "teams"], ["--mention-test", "--ticker", "NKE"]])
def test_bad_arguments_exit_1(argv, fixed_exe, _isolated_home, tmp_path, capsys):
    assert generate(capsys, tmp_path, *argv)[0] == 1


def test_next_steps_cite_the_switch_docs_and_say_what_is_not_documented(fixed_exe, _isolated_home, tmp_path, capsys):
    _, _, out = generate(capsys, tmp_path)
    assert "https://docs.switchagents.ai/flintai/switch/deploy/messaging-apps/slack" in out.out
    assert "docs/TEMPLATES.md" in out.out and "NOT DOCUMENTED" in out.out and "Templates page" in out.out


def test_executable_resolution_is_absolute():
    argv, how = locate.executable()
    assert Path(argv[0]).is_absolute() and Path(argv[0]).exists(), (argv, how)
    assert len(argv) == 1 or argv[1:] == ["-m", "stockdesk"]


def test_template_is_a_subcommand_and_the_old_script_is_a_shim(_isolated_home, tmp_path, capsys):
    assert cli.main(["template", "--out", str(tmp_path / "a.yaml")]) == 0
    capsys.readouterr()
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "STOCKDESK_HOME": str(_isolated_home),
           "PYTHONPATH": str(ROOT / "src")}
    done = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_template.py"), "--out", str(tmp_path / "b.yaml")],
                          capture_output=True, text=True, env=env)
    assert done.returncode == 0, done.stderr
    assert (tmp_path / "b.yaml").is_file()
