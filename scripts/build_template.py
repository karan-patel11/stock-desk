#!/usr/bin/env python3
"""Build switch/desk-team.template.yaml from switch/desk-team.skeleton and agents/*.md.

  python3 scripts/build_template.py            write the template
  python3 scripts/build_template.py --check    exit 1 if the checked-in template is out of date

The agent files are the source of truth. This script:
- replaces $STOCKDESK_HOME with the template param {stockdesk_home} and $STOCKDESK_PY with {python},
- refuses any other curly brace in an agent file (Switch would read it as a template placeholder),
- indents each file under its instructions: block,
- validates the result as YAML if PyYAML is installed (optional; not a project dependency),
- prints the fields that are not confirmed against Switch so nobody mistakes them for verified.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKELETON = ROOT / "switch" / "desk-team.skeleton"
OUTPUT = ROOT / "switch" / "desk-team.template.yaml"
AGENTS = ROOT / "agents"
MARKER = re.compile(r"^(?P<indent>[ ]*)@@INSTRUCTIONS:(?P<name>[a-z]+)@@[ ]*$")
SUBSTITUTIONS = (("$STOCKDESK_HOME", "{stockdesk_home}"), ("$STOCKDESK_PY", "{python}"))
MAX_LINES = 60
UNVERIFIED = (
    "params: block shape (name/type/description/default)",
    "{param} substitution inside instructions: and docs: text",
    "upper-case ticker in the room name desk-{ticker}",
)


def agent_text(name: str) -> str:
    path = AGENTS / f"{name}.md"
    if not path.is_file():
        raise SystemExit(f"missing agent file: {path}")
    text = path.read_text(encoding="utf-8")
    lines = text.rstrip("\n").splitlines()
    if len(lines) > MAX_LINES:
        raise SystemExit(f"{path.name} has {len(lines)} lines; the limit is {MAX_LINES}")
    if "\t" in text:
        raise SystemExit(f"{path.name} contains a tab character")
    for number, line in enumerate(lines, 1):
        if "{" in line or "}" in line:
            raise SystemExit(f"{path.name}:{number} contains a curly brace; Switch would treat it as a placeholder")
    for old, new in SUBSTITUTIONS:
        text = text.replace(old, new)
    if re.search(r"\$[A-Z_]{3,}", text):
        leftover = re.search(r"\$[A-Z_]{3,}", text).group(0)
        raise SystemExit(f"{path.name} uses an unknown variable {leftover}")
    return text.rstrip("\n")


def build() -> str:
    out: list[str] = []
    seen: set[str] = set()
    for line in SKELETON.read_text(encoding="utf-8").splitlines():
        match = MARKER.match(line)
        if not match:
            out.append(line)
            continue
        name = match.group("name")
        seen.add(name)
        pad = match.group("indent")
        out.extend((pad + body) if body else "" for body in agent_text(name).splitlines())
    expected = {"chief", "fundamental", "technical", "sentiment"}
    if seen != expected:
        raise SystemExit(f"skeleton must inject exactly {sorted(expected)}, found {sorted(seen)}")
    return "\n".join(out) + "\n"


def validate(text: str) -> str:
    try:
        import yaml  # optional
    except ImportError:
        return "PyYAML not installed: YAML syntax not validated (pip install pyyaml to check)"
    doc = yaml.safe_load(text)
    names = [a["name"] for a in doc["agents"]]
    assert names == ["desk-chief", "desk-fundamental", "desk-technical", "desk-sentiment"], names
    assert doc["room"]["agents"] == names
    assert doc["kickoff"].strip().startswith("@desk-chief analyze")
    for agent in doc["agents"]:
        assert agent["instructions"].strip(), agent["name"]
        assert agent["directory"].endswith(agent["name"]), agent["name"]
    return f"YAML parsed: {len(names)} agents, room {doc['room']['name']!r}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="fail if the checked-in template is stale")
    args = parser.parse_args()
    text = build()
    note = validate(text)
    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.is_file() else ""
        if current != text:
            print("switch/desk-team.template.yaml is out of date; run scripts/build_template.py", file=sys.stderr)
            return 1
        print("template is up to date; " + note)
    else:
        OUTPUT.write_text(text, encoding="utf-8")
        print(f"wrote {OUTPUT.relative_to(ROOT)}; {note}")
    print("UNVERIFIED against Switch (confirm in Console):")
    for item in UNVERIFIED:
        print(f"  - {item}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
