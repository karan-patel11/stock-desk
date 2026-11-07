"""scripts/narrator.py with Slack fixtures (tests/fixtures/slack/): no network, no speech."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import narrator  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "slack"
START = 1762480000.0
TOKEN = "xoxb-test-not-a-real-token"


class Resp:
    def __init__(self, body, status=200, headers=None):
        self._body, self.status_code, self.headers = body, status, headers or {}

    def json(self):
        return self._body


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


class FakeSlack:
    def __init__(self, history="history.json", replies="replies.json"):
        self.calls = []
        self.queue = {"conversations.history": [], "conversations.replies": []}
        self.default = {"conversations.history": load(history), "conversations.replies": load(replies)}

    def __call__(self, url, params=None, timeout=None, headers=None):
        method = url.rsplit("/", 1)[-1]
        self.calls.append((method, dict(params or {}), headers))
        if self.queue.get(method):
            return self.queue[method].pop(0)
        return Resp(self.default[method])


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("SLACK_CHANNEL_ID", "C0TEST")


def run_main(argv, slack, which=lambda c: "/usr/bin/say" if c == "say" else None, spoken=None, sleeps=None):
    spoken = [] if spoken is None else spoken
    return narrator.main(argv, get=slack, which=which, run=lambda cmd, check: spoken.append(cmd),
                         sleep=(sleeps.append if sleeps is not None else (lambda s: None)), now=lambda: START), spoken


def test_speaks_only_new_voice_lines_in_order_once(env, capsys):
    slack = FakeSlack()
    code, spoken = run_main(["--once"], slack)
    assert code == 0
    lines = [cmd[1] for cmd in spoken]
    assert lines == [
        "Technical: the price is below its 200-day average & momentum is weak.",   # &amp; undone
        "Fundamental: revenue fell <2 percent, margins held.",                      # &lt; undone, indented line ok
        "Chief: the medium-term outlook is bearish with low confidence, because news coverage is thin.",
    ]
    assert all(cmd[0] == "/usr/bin/say" and len(cmd) == 2 for cmd in spoken)  # argument list, no shell
    out = capsys.readouterr()
    assert TOKEN not in out.out + out.err


def test_read_only_calls_and_thread_polling(env):
    slack = FakeSlack()
    run_main(["--once"], slack)
    methods = [m for m, _, _ in slack.calls]
    assert set(methods) <= set(narrator.READ_METHODS)
    replies = [p for m, p, _ in slack.calls if m == "conversations.replies"]
    assert [p["ts"] for p in replies] == ["1762479000.000100"]  # the old thread with no new reply is skipped
    history = [p for m, p, _ in slack.calls if m == "conversations.history"][0]
    assert history["channel"] == "C0TEST" and history["oldest"] == f"{START - 7200:.6f}"
    assert all(h["Authorization"] == f"Bearer {TOKEN}" for _, _, h in slack.calls)


def test_second_poll_repeats_nothing():
    slack = FakeSlack()
    n = narrator.Narrator(narrator.SlackReader(TOKEN, "C0TEST", get=slack), lambda line: None,
                          narrator.Decimal(f"{START:.6f}"), 7200)
    assert len(n.poll_once()) == 3
    assert n.poll_once() == []


def test_refuses_any_write_method():
    reader = narrator.SlackReader(TOKEN, "C0TEST", get=FakeSlack())
    with pytest.raises(narrator.NarratorError, match="read-only"):
        reader._call("chat.postMessage", {"text": "hi"})


def test_no_tts_command_is_a_clear_error(env, capsys):
    code, spoken = run_main(["--once"], FakeSlack(), which=lambda c: None)
    assert code == 1 and spoken == []
    assert "no speech command found" in capsys.readouterr().err


def test_espeak_is_used_when_say_is_missing(env):
    _, spoken = run_main(["--once"], FakeSlack(), which=lambda c: "/usr/bin/espeak" if c == "espeak" else None)
    assert spoken and spoken[0][0] == "/usr/bin/espeak"


def test_dry_run_prints_and_needs_no_tts(env, capsys):
    code, spoken = run_main(["--once", "--dry-run"], FakeSlack(), which=lambda c: None)
    assert code == 0 and spoken == []
    assert "🔊 Technical: the price is below" in capsys.readouterr().out


def test_missing_settings(monkeypatch, capsys):
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.setenv("SLACK_CHANNEL_ID", "C0TEST")
    code, _ = run_main(["--once"], FakeSlack())
    assert code == 1 and "SLACK_BOT_TOKEN" in capsys.readouterr().err


def test_fatal_slack_error_stops_with_message(env, capsys):
    slack = FakeSlack()
    slack.queue["conversations.history"].append(Resp(load("error_invalid_auth.json")))
    code, _ = run_main(["--once"], slack)
    err = capsys.readouterr().err
    assert code == 1 and "invalid_auth" in err and TOKEN not in err


def test_rate_limit_waits_retry_after(env):
    slack = FakeSlack()
    slack.queue["conversations.history"].append(Resp({}, status=429, headers={"Retry-After": "7"}))
    sleeps = []
    code, spoken = run_main(["--once"], slack, sleeps=sleeps)
    assert code == 0 and 7.0 in sleeps and len(spoken) == 3


def test_rate_limit_that_never_ends_is_an_error(env, capsys):
    slack = FakeSlack()
    slack.queue["conversations.history"].extend(Resp({}, status=429) for _ in range(narrator.MAX_RETRIES))
    code, _ = run_main(["--once"], slack)
    assert code == 1 and "rate limited" in capsys.readouterr().err


def test_pagination_follows_the_cursor(env):
    first = {"ok": True, "has_more": True, "response_metadata": {"next_cursor": "abc"},
             "messages": [{"ts": "1762480010.000001", "text": "🔊 Page one."}]}
    second = {"ok": True, "has_more": False, "messages": [{"ts": "1762480020.000001", "text": "🔊 Page two."}]}
    slack = FakeSlack()
    slack.queue["conversations.history"].extend([Resp(first), Resp(second)])
    _, spoken = run_main(["--once"], slack)
    assert [c[1] for c in spoken] == ["Page one.", "Page two."]
    assert [p.get("cursor") for m, p, _ in slack.calls if m == "conversations.history"] == [None, "abc"]


@pytest.mark.parametrize("text,lines", [
    ("🔊 One.\n🔊 Two.", ["One.", "Two."]),
    ("no voice here", []),
    ("🔊 ", []),
    ("🔊no space", []),
])
def test_voice_lines(text, lines):
    assert narrator.voice_lines(text) == lines


def test_bad_interval(env, capsys):
    code, _ = run_main(["--once", "--interval", "0.5"], FakeSlack())
    assert code == 1 and "--interval" in capsys.readouterr().err
