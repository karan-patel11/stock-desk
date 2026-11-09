#!/usr/bin/env python3
"""narrator.py: read the desk's Slack channel aloud, one 🔊 line at a time. Read-only.

  python3 scripts/narrator.py [--interval 4] [--lookback-min 120] [--once] [--dry-run]

- Polls conversations.history for the channel and conversations.replies for its active threads, with
  SLACK_BOT_TOKEN and SLACK_CHANNEL_ID from .env. The token needs channels:history (groups:history for a
  private channel) and the app must be in the channel.
- Speaks ONLY lines that start with "🔊 ", and each line once, in the order Slack posted them.
- Speaks only messages posted after it started. --lookback-min is how far back it looks for thread parents,
  so replies in a run that began before the narrator started are still heard.
- Uses `say` (macOS) or `espeak` (Linux). If neither is found it exits with an error. --dry-run prints the
  lines instead and needs no speech command.
- Never posts, reacts or talks to agents: it only calls the two read methods above. It does not bypass Switch.
- Slack rate limits (HTTP 429) are respected with Retry-After. A fatal Slack error (bad token, missing scope,
  channel not found, not in channel) stops it with a clear message. The token is never printed.
"""
from __future__ import annotations

import argparse
import html
import shutil
import subprocess
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Sequence

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))  # a repo checkout without pip install
from stockdesk import common  # noqa: E402  (reads .env; no other tool code is used)

API = "https://slack.com/api/"
READ_METHODS = ("conversations.history", "conversations.replies")
PREFIX = "🔊 "
FATAL = {"invalid_auth", "not_authed", "account_inactive", "token_revoked", "token_expired", "missing_scope",
         "channel_not_found", "not_in_channel", "no_permission", "ekm_access_denied"}
MAX_RETRIES = 3


class NarratorError(Exception):
    pass


def voice_lines(text: str) -> list[str]:
    """The 🔊 lines of a Slack message, prefix removed, Slack's &amp; &lt; &gt; escapes undone."""
    lines = []
    for raw in html.unescape(text or "").splitlines():
        line = raw.strip()
        if line.startswith(PREFIX) and line[len(PREFIX):].strip():
            lines.append(line[len(PREFIX):].strip())
    return lines


def find_tts(which: Callable[[str], str | None] = shutil.which) -> list[str]:
    for command in ("say", "espeak"):
        path = which(command)
        if path:
            return [path]
    raise NarratorError("no speech command found: install espeak (Linux) or run on macOS (say), or use --dry-run")


class SlackReader:
    """The two read-only Slack Web API calls this script is allowed to make."""

    def __init__(self, token: str, channel: str, get: Callable[..., Any] = requests.get,
                 sleep: Callable[[float], None] = time.sleep):
        self._token, self.channel, self._get, self._sleep = token, channel, get, sleep

    def _call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method not in READ_METHODS:
            raise NarratorError(f"refusing to call {method}: the narrator is read-only")
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = self._get(API + method, params=params, timeout=20,
                                     headers={"Authorization": f"Bearer {self._token}"})
            except requests.RequestException as exc:
                if attempt == MAX_RETRIES:
                    raise NarratorError(f"{method}: network error ({type(exc).__name__})") from exc
                self._sleep(2.0 * attempt)
                continue
            if response.status_code == 429:
                try:
                    wait = float(response.headers.get("Retry-After", "5"))
                except ValueError:
                    wait = 5.0
                common.log(f"narrator: Slack rate limit on {method}, waiting {wait:.0f}s")
                self._sleep(min(wait, 120.0))
                continue
            if response.status_code != 200:
                raise NarratorError(f"{method}: HTTP {response.status_code}")
            body = response.json()
            if not body.get("ok"):
                code = str(body.get("error", "unknown_error"))
                if code in FATAL:
                    raise NarratorError(f"{method}: Slack says {code}; check the token, its scopes and the channel")
                raise NarratorError(f"{method}: Slack error {code}")
            return body
        raise NarratorError(f"{method}: still rate limited after {MAX_RETRIES} attempts")

    def _pages(self, method: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        cursor = None
        while True:
            body = self._call(method, {**params, **({"cursor": cursor} if cursor else {})})
            messages.extend(body.get("messages") or [])
            cursor = (body.get("response_metadata") or {}).get("next_cursor")
            if not body.get("has_more") or not cursor:
                return messages

    def history(self, oldest: str) -> list[dict[str, Any]]:
        return self._pages("conversations.history", {"channel": self.channel, "oldest": oldest, "limit": 200})

    def replies(self, thread_ts: str, oldest: str) -> list[dict[str, Any]]:
        return self._pages("conversations.replies",
                           {"channel": self.channel, "ts": thread_ts, "oldest": oldest, "limit": 200})


def _ts(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(0)


class Narrator:
    def __init__(self, reader: SlackReader, speak: Callable[[str], None], start: Decimal, lookback_s: float):
        self.reader, self.speak, self.start, self.lookback_s = reader, speak, start, lookback_s
        self.spoken: set[tuple[str, int]] = set()      # (message ts, line number)
        self.thread_seen: dict[str, Decimal] = {}      # thread ts -> newest reply already handled

    def _say_message(self, message: dict[str, Any], out: list[tuple[Decimal, str, int, str]]) -> None:
        ts = str(message.get("ts", ""))
        if _ts(ts) <= self.start or message.get("subtype") in ("message_changed", "message_deleted"):
            return
        for number, line in enumerate(voice_lines(str(message.get("text", "")))):
            if (ts, number) not in self.spoken:
                out.append((_ts(ts), ts, number, line))

    def poll_once(self) -> list[str]:
        """One pass over the channel and its active threads. Returns the lines spoken, in posting order."""
        pending: list[tuple[Decimal, str, int, str]] = []
        oldest = f"{self.start - Decimal(str(self.lookback_s)):.6f}"
        for parent in self.reader.history(oldest):
            self._say_message(parent, pending)
            thread_ts = str(parent.get("thread_ts") or "")
            latest = _ts(parent.get("latest_reply"))
            if not thread_ts or thread_ts != parent.get("ts") or latest == 0:
                continue
            seen = self.thread_seen.get(thread_ts, self.start)
            if latest <= seen:
                continue
            for reply in self.reader.replies(thread_ts, f"{seen:.6f}"):
                if reply.get("ts") != thread_ts:  # the parent is returned again; it was handled above
                    self._say_message(reply, pending)
            self.thread_seen[thread_ts] = latest
        spoken = []
        for _, ts, number, line in sorted(pending):
            self.spoken.add((ts, number))
            self.speak(line)
            spoken.append(line)
        return spoken


def main(argv: Sequence[str] | None = None, *, get: Callable[..., Any] = requests.get,
         which: Callable[[str], str | None] = shutil.which, run: Callable[..., Any] = subprocess.run,
         sleep: Callable[[float], None] = time.sleep, now: Callable[[], float] = time.time) -> int:
    parser = argparse.ArgumentParser(description="Speak the 🔊 lines posted in the desk's Slack channel (read-only).")
    parser.add_argument("--interval", type=float, default=4.0, help="seconds between polls (minimum 2)")
    parser.add_argument("--lookback-min", type=float, default=120.0, help="minutes back to look for thread parents")
    parser.add_argument("--once", action="store_true", help="poll once and exit")
    parser.add_argument("--dry-run", action="store_true", help="print the lines instead of speaking them")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    try:
        if args.interval < 2 or args.lookback_min < 0:
            raise NarratorError("--interval must be at least 2 seconds and --lookback-min at least 0")
        token, channel = common.env("SLACK_BOT_TOKEN"), common.env("SLACK_CHANNEL_ID")
        if not token or not channel:
            raise NarratorError("set SLACK_BOT_TOKEN and SLACK_CHANNEL_ID in .env (see .env.example)")
        if args.dry_run:
            def speak(line: str) -> None:
                print(f"🔊 {line}", flush=True)
        else:
            tts = find_tts(which)

            def speak(line: str) -> None:
                print(f"🔊 {line}", flush=True)
                run(tts + [line], check=False)  # argument list, never a shell
        narrator = Narrator(SlackReader(token, channel, get=get, sleep=sleep), speak,
                            Decimal(f"{now():.6f}"), args.lookback_min * 60)
        common.log(f"narrator: listening to channel {channel} (read-only); Ctrl-C to stop")
        while True:
            narrator.poll_once()
            if args.once:
                return 0
            sleep(args.interval)
    except NarratorError as exc:
        print(f"narrator: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
