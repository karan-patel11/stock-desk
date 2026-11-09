"""stockdesk: one command, one subcommand per tool.

  stockdesk fund|tech|news|precedent|verify|round|confidence|evidence-table ARGS
  stockdesk --version

Each tool subcommand takes exactly the arguments of the old tools/<name>.py script and keeps its CLI contract:
one JSON object on stdout, exit 0 {"ok": true, ...} or exit 1 {"ok": false, "error": ..., "detail": ...},
logs on stderr. An unknown subcommand is a bad_input error under the same contract.
"""
from __future__ import annotations

import argparse
import importlib
import sys
from typing import Sequence

from . import __version__, common

# subcommand -> module in this package. Each module has main(argv) -> (run, evidence_ids, data).
DATA_TOOLS = {
    "fund": "fund",
    "tech": "tech",
    "news": "news",
    "precedent": "precedent",
    "verify": "verify",
    "round": "round",
    "confidence": "confidence",
    "evidence-table": "evidence_table",
}
# subcommand -> module with main(argv) -> exit code. Human-readable output, not the data-tool contract.
SETUP_COMMANDS = {"init": "init", "doctor": "doctor", "template": "template"}


def _parser() -> argparse.ArgumentParser:
    commands = list(DATA_TOOLS) + list(SETUP_COMMANDS)
    parser = common.ContractParser(
        prog="stockdesk",
        description="Stock Desk research tools. Research only, not financial advice.",
        epilog="Run 'stockdesk <command> --help' for a command's arguments.",
    )
    parser.add_argument("--version", action="version", version=f"stockdesk {__version__}")
    parser.add_argument("command", metavar="command", help="one of: " + ", ".join(commands))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    head, rest = args[:1], args[1:]
    known = list(DATA_TOOLS) + list(SETUP_COMMANDS)
    try:
        # Only the first token is parsed here; everything after it belongs to the subcommand.
        command = _parser().parse_args(head).command
        if command not in known:
            raise common.ToolError("bad_input", f"unknown command {command!r}; expected one of: {', '.join(known)}")
    except common.ToolError as exc:
        if not head:
            exc = common.ToolError("bad_input", f"missing command; expected one of: {', '.join(known)}")
        elif head[0].startswith("-"):
            exc = common.ToolError("bad_input", f"unrecognized arguments: {head[0]}; expected a command first "
                                                f"({', '.join(known)}) or --version")
        common.emit_error(exc.code, exc.detail)
        return 1
    except SystemExit as exc:  # --help / --version
        return int(exc.code or 0)
    if command in SETUP_COMMANDS:
        module = importlib.import_module(f".{SETUP_COMMANDS[command]}", __package__)
        return module.main(rest)
    module = importlib.import_module(f".{DATA_TOOLS[command]}", __package__)
    return common.run_cli(module.main, rest)


if __name__ == "__main__":
    sys.exit(main())
