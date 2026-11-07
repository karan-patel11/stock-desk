"""Static checks on the agent instruction files and the generated Switch template (no network, no Switch)."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
AGENT_FILES = sorted((ROOT / "agents").glob("*.md"))
TOOLS = {p.stem for p in (ROOT / "tools").glob("*.py")}


def test_four_agent_files():
    assert [p.stem for p in AGENT_FILES] == ["chief", "fundamental", "sentiment", "technical"]


@pytest.mark.parametrize("path", AGENT_FILES, ids=lambda p: p.stem)
def test_agent_file_rules(path):
    text = path.read_text(encoding="utf-8")
    assert len(text.splitlines()) <= 60
    assert "{" not in text and "}" not in text      # Switch would read braces as placeholders
    assert "\t" not in text
    assert "/home/" not in text and "/Users/" not in text and "@" not in re.sub(r"@desk-[a-z]+", "", text)
    for tool in re.findall(r"tools/([a-z_]+)\.py", text):
        assert tool in TOOLS, f"{path.name} references missing tool {tool}.py"
    assert re.findall(r"\$[A-Z_]{3,}", text) and set(re.findall(r"\$[A-Z_]{3,}", text)) <= {"$STOCKDESK_HOME", "$STOCKDESK_PY"}


def test_each_agent_states_the_no_advice_and_citation_rules():
    for path in AGENT_FILES:
        text = path.read_text(encoding="utf-8").lower()
        assert "evidence id" in text or "evidence ids" in text
        assert "buy, sell" in text and "price target" in text


def test_only_the_chief_writes_the_verdict_and_it_ends_with_the_disclaimer():
    chief = (ROOT / "agents" / "chief.md").read_text(encoding="utf-8")
    assert "Research only, not financial advice." in chief
    assert "round.py status" in chief and "round.py next" in chief and "round.py end" in chief
    assert "verify.py --text-file" in chief and "create_room_document" in chief
    for name in ("fundamental", "technical", "sentiment"):
        assert "create_room_document" not in (ROOT / "agents" / f"{name}.md").read_text(encoding="utf-8")


def test_analysts_answer_only_the_chief():
    for name in ("fundamental", "technical", "sentiment"):
        text = (ROOT / "agents" / f"{name}.md").read_text(encoding="utf-8")
        assert text.count("@desk-chief") >= 2
        assert not re.search(r"@desk-(fundamental|technical|sentiment)", text)


def test_generated_template_is_up_to_date():
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_template.py"), "--check"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_template_has_no_hardcoded_paths_or_emails():
    for name in ("desk-team.template.yaml", "mention-test.template.yaml"):
        text = (ROOT / "switch" / name).read_text(encoding="utf-8")
        assert "/home/" not in text and "/Users/" not in text
        assert not re.search(r"[\w.]+@[\w.]+\.\w+", text)
        placeholders = set(re.findall(r"\{[^}]*\}", text))
        assert placeholders <= {"{$agents_dir}", "{$creator}", "{ticker}", "{bridge}", "{stockdesk_home}", "{python}"}


def test_build_fails_on_braces_in_an_agent_file(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_template

    bad = tmp_path / "agents"
    bad.mkdir()
    for name in ("chief", "fundamental", "technical", "sentiment"):
        (bad / f"{name}.md").write_text("ok\n")
    (bad / "chief.md").write_text("use {this}\n")
    monkeypatch.setattr(build_template, "AGENTS", bad)
    with pytest.raises(SystemExit) as err:
        build_template.build()
    assert "curly brace" in str(err.value)


NEWS_CALL_AGENT = re.compile(r'tools/news\.py "COMPANY ([^"]*)" (--days \d+)')
NEWS_CALL_WARM = re.compile(r'tools/news\.py "\$COMPANY ([^"]*)" (--days \d+)')


def _one_news_call(text: str, pattern: re.Pattern, where: str) -> tuple[str, str]:
    assert len(re.findall(r'tools/news\.py "', text)) == 1, f"{where}: expected exactly one news.py call"
    found = pattern.findall(text)
    assert len(found) == 1, f"{where}: news.py call does not have the COMPANY-first shape"
    return found[0]


def test_warm_demo_uses_the_sentiment_agents_exact_news_query():
    """The demo cache is keyed on the exact query text, so the warm-up must match the agent verbatim."""
    agent = _one_news_call((ROOT / "agents" / "sentiment.md").read_text(encoding="utf-8"), NEWS_CALL_AGENT,
                           "agents/sentiment.md")
    template = _one_news_call((ROOT / "switch" / "desk-team.template.yaml").read_text(encoding="utf-8"),
                              NEWS_CALL_AGENT, "switch/desk-team.template.yaml")
    warm = _one_news_call((ROOT / "scripts" / "warm_demo.sh").read_text(encoding="utf-8"), NEWS_CALL_WARM,
                          "scripts/warm_demo.sh")
    assert warm == agent == template, f"query drift: warm_demo.sh {warm} vs sentiment.md {agent} vs template {template}"


def test_warm_demo_needs_ticker_and_company():
    result = subprocess.run(["bash", str(ROOT / "scripts" / "warm_demo.sh")], capture_output=True, text=True)
    assert result.returncode == 2 and "usage" in result.stderr


def test_room_alias_and_rules():
    text = (ROOT / "switch" / "desk-team.template.yaml").read_text(encoding="utf-8")
    assert '  aliases:\n    desk-chief: "chief"\n' in text
    assert "Three layers" in text and "confidence.py" in text and "🔊" in text
