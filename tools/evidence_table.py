#!/usr/bin/env python3
"""evidence_table.py --run RUN

Every evidence entry in the run as one markdown table, for the verdict document:
ID | Fact | Value (unit) | Period | Source | Tier | Link | Verified

- Values are printed exactly as stored; nothing is rounded or recomputed. Long text values are shortened.
- Verified is the latest result in evidence/<run>/verifications.jsonl, or "not checked".
- News entries that carry weight / counted fields show them in the Tier column.
- An entry written before source tiers existed shows "not recorded" as its tier.
"""
from __future__ import annotations

import sys
from typing import Any, Sequence

import common
from common import ToolError

COLUMNS = ("ID", "Fact", "Value (unit)", "Period", "Source", "Tier", "Link", "Verified")
MAX_TEXT = 120


def cell(value: Any) -> str:
    text = " ".join(str(value).split())  # no newlines inside a table row
    if len(text) > MAX_TEXT:
        text = text[:MAX_TEXT - 1] + "…"
    return text.replace("|", "\\|")


def tier_cell(entry: dict[str, Any]) -> str:
    parts = [entry.get("source_tier") or "not recorded"]
    if "weight" in entry:
        parts.append(f"weight {entry['weight']}")
    if "counted" in entry:
        reason = entry.get("not_counted_reason")
        parts.append("counted" if entry["counted"] else f"not counted ({reason})" if reason else "not counted")
    return cell(" · ".join(str(p) for p in parts))


def link_cell(url: Any) -> str:
    url = str(url or "")
    if url.startswith(("http://", "https://")):
        return f"[link](<{url.replace('>', '%3E')}>)"
    return cell(url) if url else "none"


def verified_cell(record: dict[str, Any] | None) -> str:
    return record["result"] if record else "not checked"


def main(argv: Sequence[str]) -> tuple[str | None, list[str], dict[str, Any]]:
    parser = common.ContractParser(prog="evidence_table.py", description="Markdown table of a run's evidence.")
    common.add_run_argument(parser)
    args = parser.parse_args(list(argv))
    if not args.run:
        raise ToolError("bad_input", "--run is required")
    run = common.resolve_run(args.run)
    entries = common.list_evidence(run)
    if not entries:
        raise ToolError("no_data", f"run {run} has no evidence entries")
    latest = common.latest_verifications(run)

    lines = ["| " + " | ".join(COLUMNS) + " |", "|" + "---|" * len(COLUMNS)]
    for entry in entries:
        unit = entry.get("unit")
        value = f"{cell(entry.get('value'))} ({cell(unit)})" if unit else cell(entry.get("value"))
        row = [entry["id"], cell(entry.get("fact", "")), value, cell(entry.get("period", "")),
               cell(entry.get("source", "")), tier_cell(entry), link_cell(entry.get("url")),
               verified_cell(latest.get(entry["id"]))]
        lines.append("| " + " | ".join(row) + " |")
    citations = common.citation_summary(run)
    data = {"markdown": "\n".join(lines) + "\n", "entries": len(entries), "citations": citations["display"],
            "uncorrected": citations["uncorrected"]}
    return run, [], data


if __name__ == "__main__":
    sys.exit(common.run_cli(main))
