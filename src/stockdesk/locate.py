"""Where the stockdesk executable is, so a generated Switch template can call it by absolute path.

Switch Console may start Claude Code sessions without the user's shell PATH, so a bare `stockdesk` in an agent's
instructions can fail. `stockdesk doctor` shows the command `stockdesk template` will embed.
"""
from __future__ import annotations

import shlex
import shutil
import sys
from pathlib import Path

NAMES = ("stockdesk", "stockdesk.exe")


def executable() -> tuple[list[str], str]:
    """(argv prefix that runs this stockdesk, how it was found). Never a relative path."""
    argv0 = sys.argv[0] if sys.argv else ""
    if argv0 and Path(argv0).name in NAMES:
        found = argv0 if ("/" in argv0 or "\\" in argv0) else shutil.which(argv0)
        if found and Path(found).is_file():
            return [str(Path(found).absolute())], "the running command (sys.argv[0])"
    sibling = Path(sys.executable).parent / ("stockdesk.exe" if sys.platform == "win32" else "stockdesk")
    if sibling.is_file():
        return [str(sibling.absolute())], "next to the running Python"
    found = shutil.which("stockdesk")
    if found:
        return [str(Path(found).absolute())], "PATH"
    return [str(Path(sys.executable).absolute()), "-m", "stockdesk"], "fallback: no stockdesk executable found"


def command_text(argv: list[str] | None = None) -> str:
    """The prefix as shell text, quoted when a path has spaces."""
    return " ".join(shlex.quote(part) for part in (argv or executable()[0]))
