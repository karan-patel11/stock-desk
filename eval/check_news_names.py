#!/usr/bin/env python3
"""check_news_names.py [--home PATH]

Confirms news.py resolves a news name for every Phase 4 batch ticker, WITHOUT contacting GDELT: it calls
news.company_name() (the lookup news.py --ticker uses) with all network access blocked, and prints the exact
query each ticker would send. ZZZQ, the invalid-ticker run, must have no name (bad_input).

Default: checks eval/config/news_names.json in a throwaway home. --home ~/.stockdesk checks the installed override
instead (read-only) and that it is byte-identical to eval/config/news_names.json.
Exit 0 only if every check passes.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import socket
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from stockdesk import common, news  # noqa: E402
from stockdesk.common import ToolError  # noqa: E402

OVERRIDE = HERE / "config" / "news_names.json"
BATCH = ["NKE", "JNJ", "CVX", "JPM", "CAT", "NNE", "PG", "FIG", "NVDA", "BABA", "GOOGL", "XOM"]
NO_NAME = ["ZZZQ"]


def block_network() -> None:
    def refuse(*args, **kwargs):
        raise RuntimeError("network blocked: this check must not contact GDELT")
    socket.socket.connect = refuse          # type: ignore[method-assign]
    socket.create_connection = refuse       # type: ignore[assignment]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(home: Path) -> list[str]:
    os.environ["STOCKDESK_HOME"] = str(home)
    problems = []
    installed = home / "config" / "news_names.json"
    print(f"config: {installed}")
    if not installed.is_file():
        return [f"no override at {installed}: the shipped list (10 names) would be used"]
    if sha(installed) != sha(OVERRIDE):
        problems.append(f"{installed} differs from eval/config/news_names.json (sha256 {sha(installed)[:12]} vs "
                        f"{sha(OVERRIDE)[:12]})")
    else:
        print(f"identical to eval/config/news_names.json (sha256 {sha(OVERRIDE)[:12]})")
    for ticker in BATCH:
        try:
            name = news.company_name(ticker)
            print(f"  ok  {ticker:6} -> {news.QUERY_TEMPLATE.format(name=name)}")
        except ToolError as exc:
            problems.append(f"{ticker}: {exc.code}: {exc.detail}")
    for ticker in NO_NAME:
        try:
            name = news.company_name(ticker)
            problems.append(f"{ticker} has a name ({name!r}) but must have none")
        except ToolError as exc:
            print(f"  ok  {ticker:6} -> {exc.code} (expected: no name for the invalid-ticker run)")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--home", type=Path, default=None, help="check this STOCKDESK_HOME's installed override")
    args = parser.parse_args(argv)
    block_network()
    if args.home:
        problems = check(args.home.expanduser())
    else:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "config").mkdir()
            shutil.copy2(OVERRIDE, Path(tmp) / "config" / "news_names.json")
            problems = check(Path(tmp))
    for problem in problems:
        print(f"FAIL {problem}")
    print("PASS: every batch ticker resolves; GDELT not contacted" if not problems else f"{len(problems)} problem(s)")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
