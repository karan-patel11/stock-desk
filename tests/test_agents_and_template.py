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
    assert len(text.splitlines()) <= (80 if path.stem == "chief" else 60)
    assert "{" not in text and "}" not in text      # Switch would read braces as placeholders
    assert "\t" not in text
    assert "/home/" not in text and "/Users/" not in text and "@" not in re.sub(r"@desk-[a-z]+", "", text)
    for tool in re.findall(r"(?:tools|T)/([a-z_]+)\.py", text):
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


NEWS_CALL_AGENT = re.compile(r'tools/news\.py (--ticker) TICKER (--days \d+) --run RUN')
NEWS_CALL_WARM = re.compile(r'tools/news\.py (--ticker) "\$TICKER" (--days \d+) --run "\$RUN"')


def _one_news_call(text: str, pattern: re.Pattern, where: str) -> tuple[str, str]:
    assert len(re.findall(r'tools/news\.py ', text)) == 1, f"{where}: expected exactly one news.py call"
    assert not re.search(r'tools/news\.py "', text), f"{where}: free-text query; use --ticker"
    found = pattern.findall(text)
    assert len(found) == 1, f"{where}: news.py call is not the --ticker shape"
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


def test_warm_demo_needs_a_ticker():
    result = subprocess.run(["bash", str(ROOT / "scripts" / "warm_demo.sh")], capture_output=True, text=True)
    assert result.returncode == 2 and "usage" in result.stderr



ANALYSTS = ("fundamental", "technical", "sentiment")


def agent(name):
    return (ROOT / "agents" / f"{name}.md").read_text(encoding="utf-8")


def test_analysts_echo_scope_and_use_the_exact_stance_line():
    for name in ANALYSTS:
        text = agent(name)
        tag = name.upper()
        assert f"@desk-chief [{tag}] TICKER · Scope: SCOPE · Period: PERIOD · Goal: GOAL · run RUN" in text
        stance = next(line for line in text.splitlines() if line.startswith("Stance: "))
        if name == "sentiment":
            assert stance == "Stance: short=not_measured · medium=not_measured · long=<positive|negative|neutral|no_data>"
        else:
            assert stance == ("Stance: short=<bullish|bearish|neutral> · medium=<bullish|bearish|neutral> · "
                              "long=<bullish|bearish|neutral>")
        assert "at most 150 words" in text


def test_every_agent_ends_messages_with_a_voice_line():
    for name in ("chief",) + ANALYSTS:
        text = agent(name)
        assert "🔊" in text and "at most 25 words" in text and "no evidence IDs" in text


def test_analysts_run_tools_once_with_the_widest_settings():
    assert "fund.py TICKER --quarters 12 --run RUN" in agent("fundamental")
    assert "tech.py TICKER --lookback 2y --run RUN" in agent("technical")
    assert "news.py --ticker TICKER --days 90 --run RUN" in agent("sentiment")
    assert "News cached, fetched <data.fetched_at>" in agent("sentiment")
    assert "unweighted, tiers not applied" in agent("sentiment")


def test_chief_scopes_goal_question_confidence_and_card():
    text = agent("chief")
    assert "What's your goal for TICKER? Reply with a number:" in text
    for line in ("1 Short-term trade (1–4 weeks)", "2 Medium-term position (3–6 months)",
                 "3 Long-term investment (1–3 years)", "or 'all'."):
        assert line in text
    assert "@desk-fundamental Scope: earnings quality · Period: last 12 quarters" in text
    assert "@desk-technical Scope: trend and momentum · Period: 2y" in text
    assert "@desk-sentiment Scope: news tone and risk events · Period: 90 days (14/30/90 windows)" in text
    assert "T/confidence.py --run RUN --horizon" in text and "never set, raise or change it yourself" in text
    assert "--windows 5,30,90,250" in text and "T/evidence_table.py --run RUN" in text
    assert "T/verify.py E<n> --withdraw" in text and "T/round.py goal" in text
    card = text[text.index("TICKER · Your goal:"):text.index("Research only, not financial advice.")]
    for part in ("▶ <HEADLINE HORIZON>", "Confidence reasons:", "3 proofs:", "What flips it:", "Disagreement:",
                 "Precedent:", "Citations verified:", "🔊 "):
        assert part in card
    for command in ("explain E<n>", "evidence:", "ask fundamental|technical|sentiment", "verdict now", "pause"):
        assert command in text


def test_room_alias_and_rules():
    text = (ROOT / "switch" / "desk-team.template.yaml").read_text(encoding="utf-8")
    assert '  aliases:\n    desk-chief: "chief"\n' in text
    assert "Three layers" in text and "confidence.py" in text and "🔊" in text



def test_chief_passes_not_measured_through_and_errors_as_no_data():
    flat = " ".join(agent("chief").split())
    assert "not_measured passes through unchanged" in flat
    assert "insufficient_coverage, no_data or an error is no_data" in flat
    assert "short=not_measured, medium=not_measured" in " ".join(agent("sentiment").split())
