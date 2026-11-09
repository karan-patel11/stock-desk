"""stockdesk init: create the data home and write config.env.

  stockdesk init [--home PATH] [--sec-email EMAIL] [--app-name NAME] [--copy-config] [--force]
                 [--non-interactive] [--json]

Creates <home>/{evidence,cache,config}/ and <home>/config.env (mode 0600) with
SEC_USER_AGENT="<app name> <email>". An existing config.env is never changed without --force; without it, init
shows what would change and exits 1. Other keys already in the file are kept. With a --home other than
~/.stockdesk, init also records it as STOCKDESK_HOME in ~/.stockdesk/config.env so every command finds it.

Human-readable output (this is a setup command, not a data tool); --json prints one JSON object instead.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Callable, Sequence

from . import common
from .common import CONFIG_FILE, HOME_ENV, SEC_UA_ENV

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
APP_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._/-]{0,59}$")
DEFAULT_APP_NAME = "StockDesk"
WHY_EMAIL = ("SEC asks every program that downloads its filings to send a contact email in its User-Agent "
             "(fair-access policy). It is sent to sec.gov only.")
NEXT_STEPS = ("stockdesk doctor", "stockdesk template")
CONFIG_NAMES = ("peers.json", "sector_etf.json", "news_names.json")


class InitError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):  # type: ignore[override]
        raise InitError(message)


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="stockdesk init", description="Create the Stock Desk data home and config.env.")
    parser.add_argument("--home", help="data home (default: STOCKDESK_HOME, else ~/.stockdesk)")
    parser.add_argument("--sec-email", help="your contact email for SEC requests")
    parser.add_argument("--app-name", help=f"app name sent to SEC before the email (default {DEFAULT_APP_NAME})")
    parser.add_argument("--copy-config", action="store_true",
                        help="copy the bundled peers/sector/news JSON into <home>/config/ to edit them")
    parser.add_argument("--force", action="store_true", help="change an existing config.env or config copy")
    parser.add_argument("--non-interactive", action="store_true", help="never prompt; take everything from flags")
    parser.add_argument("--json", action="store_true", help="print one JSON object instead of text")
    return parser


def valid_email(email: str) -> str:
    email = (email or "").strip()
    if not EMAIL_RE.match(email):
        raise InitError(f"not an email address: {email!r}")
    lowered = email.lower()
    if lowered.endswith("@example.com") or "your-email" in lowered:
        raise InitError("use your real contact email, not the placeholder")
    return email


def valid_app_name(name: str) -> str:
    name = (name or "").strip()
    if not APP_NAME_RE.match(name):
        raise InitError("app name: letters, digits, spaces and . _ / - only, at most 60 characters")
    return name


def _resolve_home(raw: str | None) -> Path:
    if raw:
        return Path(raw).expanduser().resolve()
    try:
        return common.home()
    except common.ToolError as exc:
        raise InitError(exc.detail) from exc


def _ask(prompt: Callable[[str], str], question: str, check: Callable[[str], str], default: str = "") -> str:
    for _ in range(3):
        try:
            answer = prompt(question).strip() or default
        except EOFError as exc:
            raise InitError("no answer (stdin closed); use --non-interactive with flags") from exc
        try:
            return check(answer)
        except InitError as exc:
            print(f"  {exc}", file=sys.stderr)
    raise InitError("no valid answer after 3 tries")


def _updated_lines(path: Path, updates: dict[str, str | None]) -> tuple[list[str], dict[str, tuple[str | None, str | None]]]:
    """The file's lines with `updates` applied (None removes the key), and {key: (old, new)} for real changes."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    current = common.read_config_env(path)
    changes = {k: (current.get(k) or None, v) for k, v in updates.items() if (current.get(k) or None) != v}
    out: list[str] = []
    done: set[str] = set()
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if key in updates:
            if updates[key] is not None and key not in done:
                out.append(f"{key}={_quote(updates[key])}")
            done.add(key)
            continue
        out.append(line)
    for key, value in updates.items():
        if key not in done and value is not None:
            out.append(f"{key}={_quote(value)}")
    return out, changes


def _quote(value: str) -> str:
    return f'"{value}"' if any(c.isspace() for c in value) else value


def write_private(path: Path, lines: list[str]) -> None:
    """Atomic write with mode 0600 (the file holds a contact email, and maybe tokens added later)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".env")
    try:
        os.chmod(tmp, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
    os.chmod(path, 0o600)


HEADER = ["# Stock Desk configuration, written by `stockdesk init`. KEY=VALUE lines; environment variables win.",
          "# SEC_USER_AGENT: app name plus your contact email, required by SEC's fair-access policy."]


def run(args: argparse.Namespace, prompt: Callable[[str], str] = input) -> dict:
    interactive = not args.non_interactive
    target = _resolve_home(args.home)
    default = common.default_home()

    if args.sec_email:
        email = valid_email(args.sec_email)
    elif interactive:
        print(WHY_EMAIL)
        email = _ask(prompt, "Contact email for SEC requests: ", valid_email)
    else:
        raise InitError("--sec-email is required with --non-interactive")
    if args.app_name:
        app = valid_app_name(args.app_name)
    elif interactive and not args.sec_email:
        app = _ask(prompt, f"App name [{DEFAULT_APP_NAME}]: ", valid_app_name, DEFAULT_APP_NAME)
    else:
        app = DEFAULT_APP_NAME

    # Plan every write first, so a refusal leaves nothing half-done.
    plans: list[tuple[Path, list[str], dict]] = []
    config_env = target / CONFIG_FILE
    home_updates: dict[str, str | None] = {SEC_UA_ENV: f"{app} {email}"}
    if target == default:  # ~/.stockdesk is both the home and the pointer: it must not point elsewhere
        home_updates[HOME_ENV] = None
    lines, changes = _updated_lines(config_env, home_updates)
    if not config_env.is_file():
        lines = HEADER + lines
    plans.append((config_env, lines, changes))
    if target != default:
        pointer = default / CONFIG_FILE
        p_lines, p_changes = _updated_lines(pointer, {HOME_ENV: str(target)})
        plans.append((pointer, p_lines, p_changes))

    refused = [(path, changes) for path, _, changes in plans if path.is_file() and changes and not args.force]
    if refused:
        detail = "; ".join(f"{path} exists and would change {_describe(changes)}" for path, changes in refused)
        raise InitError(f"{detail}. Nothing was written; rerun with --force to apply")

    created = []
    for sub in ("", "evidence", "cache", "config"):
        folder = target / sub
        if not folder.is_dir():
            folder.mkdir(parents=True, exist_ok=True)
            created.append(str(folder))
    written = {}
    for path, lines, changes in plans:
        if changes or not path.is_file():
            write_private(path, lines)
            written[str(path)] = {k: {"old": old, "new": new} for k, (old, new) in changes.items()}

    copied, skipped = [], []
    if args.copy_config:
        for name in CONFIG_NAMES:
            dest = target / "config" / name
            if dest.is_file() and not args.force:
                skipped.append(str(dest))
                continue
            with common.bundled("config", name).open("rb") as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
            copied.append(str(dest))

    warnings = []
    env_home = os.environ.get(HOME_ENV, "").strip()
    if env_home and Path(env_home).expanduser() != target:
        warnings.append(f"the STOCKDESK_HOME environment variable ({env_home}) overrides {target} in this shell")
    return {"ok": True, "home": str(target), "config_env": str(config_env), "sec_user_agent": f"{app} {email}",
            "created": created, "written": written, "copied": copied, "skipped": skipped,
            "warnings": warnings, "next": list(NEXT_STEPS)}


def _describe(changes: dict) -> str:
    return ", ".join(f"{k}: {old!r} -> {new!r}" for k, (old, new) in changes.items())


def _print_human(result: dict) -> None:
    print(f"Stock Desk home: {result['home']}")
    for folder in result["created"]:
        print(f"  created {folder}")
    for path, changes in result["written"].items():
        print(f"  wrote {path} (mode 0600)")
        for key, change in changes.items():
            print(f"    {key}: {change['old']!r} -> {change['new']!r}")
    if not result["written"]:
        print(f"  {result['config_env']} already up to date")
    for path in result["copied"]:
        print(f"  copied {path} (edit it to change peers, sector ETFs or news names)")
    for path in result["skipped"]:
        print(f"  kept {path} (exists; --force replaces it with the bundled copy)")
    for warning in result["warnings"]:
        print(f"WARN: {warning}")
    print("Next:")
    for step in result["next"]:
        print(f"  {step}")


def main(argv: Sequence[str] | None = None, prompt: Callable[[str], str] = input) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    want_json = "--json" in argv
    try:
        result = run(_parser().parse_args(argv), prompt)
    except InitError as exc:
        if want_json:
            print(json.dumps({"ok": False, "error": "bad_input", "detail": str(exc)}))
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 1
    except SystemExit as exc:  # --help
        return int(exc.code or 0)
    if want_json:
        print(json.dumps(result))
    else:
        _print_human(result)
    return 0
