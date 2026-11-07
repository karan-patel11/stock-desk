#!/usr/bin/env python3
"""verify.py: check numbers against the evidence ledger.

Single check:  verify.py E12 --value 8.1% [--tol 0.005] [--run RUN]
Withdrawal:    verify.py E12 --withdraw [--run RUN]           (an analyst withdrew the claim citing E12)
Report check:  verify.py --text-file report.txt [--run RUN]     (use - for stdin)
               verify.py --text "report text" [--run RUN]

Every check is appended to evidence/<run>/verifications.jsonl (one line per evidence ID checked:
id, claimed, result PASS|FAIL|WITHDRAWN, detail, checked_at). Evidence entries are never changed.
In report mode the PASS lines are written before the FAIL lines, so a failed number in a report is
never hidden by another number citing the same ID. When a line cites several IDs, a failed number is
logged against the cited IDs that no other number on that line matched (all of them if none qualifies). Uncited numbers have no ID and are not logged;
they are still returned in data.uncited. data.citations is the run's pass rate after this check.

Advice-word scan (report mode only): whole-word or whole-phrase, case-insensitive matches of buy, sell,
"price target(s)", "good to buy", "strong buy", "should hold", guaranteed, guarantee(s) make the report FAIL,
naming each phrase. Not matched: sell-off, selloff, buyback, buy-back, sellers, buyers, or "hold" on its own.
Each report scan is logged once as id ADVICE (PASS or FAIL); ADVICE never counts in the citation pass rate.

Matching rules (all done in code, never by an LLM):
- The given figure is normalized: 8.1% -> 0.081, 2.0 pts -> 0.02, 12.4B -> 12.4e9.
- A bare number is compared as written. 8.1 is NOT treated as 8.1%.
- Default tolerance is the rounding error implied by the figure as displayed
  (12.4B allows +/-0.05B). --tol adds a relative tolerance on the stored value.
- A missing ID is FAIL with reason not_found.
Both PASS and FAIL are normal results (exit 0); look at data.result.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import common
from common import ToolError

_MULTIPLIER = {"b": 1e9, "bn": 1e9, "m": 1e6, "mm": 1e6, "k": 1e3, "t": 1e12}
_QTY = re.compile(
    r"^\s*(?P<sign>[+\-−]?)\s*\$?\s*(?P<num>\d[\d,]*(?:\.\d+)?|\.\d+)\s*"
    r"(?P<suf>%|ppt|pts?|pp|x|×|bn|mm|[bmkt])?\s*$",
    re.IGNORECASE,
)
_SUFFIX = (
    r"(?P<suf>%|\s?(?:ppt|pts?|pp)\b|\s?[x×](?![A-Za-z0-9])|(?:bn|mm|[bmktBMKT])(?![A-Za-z0-9]))"
)
_NUM_IN_TEXT = re.compile(
    rf"(?<![\w.])(?P<sign>[+\-−])?\$?(?P<num>\d[\d,]*(?:\.\d+)?){_SUFFIX}?"
)
_CITE = re.compile(r"\[\s*(E\d+(?:\s*[,;/]\s*E\d+)*)\s*\]")
_IGNORE = [
    re.compile(r"\br-\d{8}-\d+\b"),
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(r"\bFY\s?\d{2,4}\b", re.IGNORECASE),
    re.compile(r"\bQ[1-4]\b", re.IGNORECASE),
    re.compile(r"\b(?:19|20)\d{2}\b"),
    re.compile(r"\b\d+\s*/\s*\d+\b"),
    re.compile(r"\b(?:SMA|EMA|RSI|ATR)\s?\(?\d+\)?", re.IGNORECASE),
    re.compile(r"\b\d+[- ](?:day|week|month|year|session|trading)s?\b", re.IGNORECASE),
    re.compile(r"\b\d+\s*(?:words?|events?|analysts?|rounds?)\b", re.IGNORECASE),
]
# Longest phrases first, so "good to buy" is reported as itself, not as "buy". A hyphen or letter on either side
# means a different word (sell-off, buyback, buy-back, sellers), so it does not match.
_ADVICE = re.compile(
    r"(?<![\w-])(good\s+to\s+buy|strong\s+buy|price\s+targets?|should\s+hold|guaranteed|guarantees?|buy|sell)(?![\w-])",
    re.IGNORECASE,
)
_NEGATIVE_WORD = re.compile(
    r"\b(?:down|decline[ds]?|declining|fell|fall(?:s|ing)?|drop(?:s|ped|ping)?|decrease[ds]?|"
    r"contract(?:s|ed|ion)?|shrank|shrink(?:s|ing)?|lower|cut|slid|slipped|lost)\b",
    re.IGNORECASE,
)


@dataclass
class Quantity:
    value: float      # normalized (8.1% -> 0.081)
    half_ulp: float   # half the last displayed digit, in normalized units
    kind: str         # ratio | multiple | scaled | plain
    text: str


def parse_quantity(text: str) -> Quantity:
    match = _QTY.match(text or "")
    if not match:
        raise ToolError("bad_input", f"cannot parse a number from {text!r}")
    digits = match.group("num").replace(",", "")
    decimals = len(digits.split(".")[1]) if "." in digits else 0
    suffix = (match.group("suf") or "").lower()
    if suffix in ("%", "pt", "pts", "pp", "ppt"):
        scale, kind = 0.01, "ratio"
    elif suffix in ("x", "×"):
        scale, kind = 1.0, "multiple"
    elif suffix in _MULTIPLIER:
        scale, kind = _MULTIPLIER[suffix], "scaled"
    else:
        scale, kind = 1.0, "plain"
    sign = -1.0 if match.group("sign") in ("-", "−") else 1.0
    return Quantity(sign * float(digits) * scale, 0.5 * 10 ** (-decimals) * scale, kind, text.strip())


def _unit_mismatch(quantity: Quantity, stored_unit: str | None) -> str | None:
    if quantity.kind == "ratio" and stored_unit != "ratio":
        return f"unit_mismatch: given a percent/points figure but stored unit is {stored_unit!r}"
    if quantity.kind == "multiple" and stored_unit != "x":
        return f"unit_mismatch: given a multiple (x) but stored unit is {stored_unit!r}"
    if quantity.kind == "scaled" and stored_unit in ("ratio", "x", "index"):
        return f"unit_mismatch: given a scaled amount but stored unit is {stored_unit!r}"
    return None


def _allowed(quantity: Quantity, stored: float, tol: float | None) -> float:
    allowed = quantity.half_ulp
    if tol is not None:
        allowed = max(allowed, tol * abs(stored))
    return allowed + abs(stored) * 1e-9 + 1e-12


def _matches(quantity: Quantity, entry: dict[str, Any], tol: float | None, sign: float = 1.0) -> tuple[bool, str | None]:
    stored = entry.get("value")
    if isinstance(stored, bool) or not isinstance(stored, (int, float)):
        return False, "stored_value_not_numeric"
    mismatch = _unit_mismatch(quantity, entry.get("unit"))
    if mismatch:
        return False, mismatch
    ok = abs(sign * quantity.value - stored) <= _allowed(quantity, float(stored), tol)
    return ok, None if ok else "value_differs"


def verify_single(run: str, evidence_id: str, value: str, tol: float | None) -> tuple[list[str], dict[str, Any]]:
    quantity = parse_quantity(value)
    entry = common.read_evidence(run, evidence_id)
    if entry is None:
        common.append_verification(run, evidence_id, value, "FAIL", "not_found: no such evidence ID in this run")
        return [], {"result": "FAIL", "reason": "not_found", "id": evidence_id, "given": value}
    ok, reason = _matches(quantity, entry, tol)
    stored = entry["value"]
    common.append_verification(
        run, evidence_id, value, "PASS" if ok else "FAIL",
        f"matches stored {stored} {entry['unit']}" if ok else f"{reason}: stored {stored} {entry['unit']}")
    return [evidence_id], {
        "result": "PASS" if ok else "FAIL",
        "reason": None if ok else reason,
        "id": evidence_id,
        "given": value,
        "given_normalized": quantity.value,
        "stored_value": stored,
        "unit": entry["unit"],
        "fact": entry["fact"],
        "source": entry["source"],
        "tolerance_abs": _allowed(quantity, float(stored), tol) if isinstance(stored, (int, float)) else None,
    }


def _mask(line: str) -> str:
    for pattern in _IGNORE:
        line = pattern.sub(lambda m: " " * len(m.group(0)), line)
    return line


def _looks_like_claim(digits: str, has_suffix: bool) -> bool:
    if has_suffix:
        return True
    clean = digits.replace(",", "")
    return "." in clean or float(clean) >= 1000


def advice_matches(text: str) -> list[dict[str, str]]:
    found = []
    for raw_line in text.splitlines():
        for match in _ADVICE.finditer(raw_line):
            found.append({"phrase": " ".join(match.group(1).lower().split()), "line": raw_line.strip()})
    return found


def verify_report(run: str, text: str, tol: float | None) -> tuple[list[str], dict[str, Any]]:
    passes: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    uncited: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    cited_all: list[str] = []
    entries: dict[str, dict[str, Any] | None] = {}

    def entry_for(evidence_id: str) -> dict[str, Any] | None:
        if evidence_id not in entries:
            entries[evidence_id] = common.read_evidence(run, evidence_id)
        return entries[evidence_id]

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        cited: list[str] = []
        for group in _CITE.findall(line):
            for evidence_id in re.findall(r"E\d+", group):
                if evidence_id not in cited:
                    cited.append(evidence_id)
        for evidence_id in cited:
            if evidence_id not in cited_all:
                cited_all.append(evidence_id)
        scan = _mask(_CITE.sub(lambda m: " " * len(m.group(0)), line))
        line_matched: set[str] = set()
        line_failures: list[dict[str, Any]] = []
        for match in _NUM_IN_TEXT.finditer(scan):
            digits = match.group("num")
            if not _looks_like_claim(digits, bool(match.group("suf"))):
                continue
            token = match.group(0).strip()
            try:
                quantity = parse_quantity(token)
            except ToolError:
                continue
            prefix = scan[max(0, match.start() - 24):match.start()]
            explicit_sign = bool(match.group("sign"))
            directional = (not explicit_sign) and bool(_NEGATIVE_WORD.search(prefix))
            if not cited:
                uncited.append({"number": token, "line": line})
                continue
            found = [e for e in (entry_for(i) for i in cited) if e is not None]
            matched_id = None
            note = None
            for candidate in found:
                if directional:
                    ok_neg, _ = _matches(quantity, candidate, tol, sign=-1.0)
                    if ok_neg:
                        matched_id = candidate["id"]
                        break
                ok, _ = _matches(quantity, candidate, tol)
                if ok:
                    matched_id = candidate["id"]
                    if directional:
                        note = "text says the figure fell but the stored value is positive"
                    break
            if matched_id:
                line_matched.add(matched_id)
                passes.append({"number": token, "id": matched_id})
                if note:
                    warnings.append({"number": token, "line": line, "id": matched_id, "warning": note})
            else:
                line_failures.append({
                    "number": token,
                    "line": line,
                    "cited": cited,
                    "reason": "no cited ID holds this value" if found else "cited IDs not found",
                    "stored": [{"id": e["id"], "value": e["value"], "unit": e["unit"], "fact": e["fact"]} for e in found],
                })
        for item in line_failures:
            # Blame the cited IDs that no other number on this line matched; if none, blame them all.
            item["blamed"] = [i for i in item["cited"] if i not in line_matched] or list(item["cited"])
        failures.extend(line_failures)

    missing = [i for i in cited_all if entry_for(i) is None]
    advice = advice_matches(text)
    result = "FAIL" if (failures or uncited or missing or advice) else "PASS"
    # Log: passes first, then failures, so a failure is the latest record for its ID.
    for item in passes:
        stored = entries[item["id"]]
        common.append_verification(run, item["id"], item["number"], "PASS",
                                   f"report: matches stored {stored['value']} {stored['unit']}")
    for item in failures:
        for evidence_id in item["blamed"]:
            stored = entries.get(evidence_id)
            if stored is None:
                continue  # logged once below as not_found
            common.append_verification(run, evidence_id, item["number"], "FAIL",
                                       f"report: {item['reason']}; stored {stored['value']} {stored['unit']}")
    for evidence_id in missing:
        common.append_verification(run, evidence_id, None, "FAIL", "report: not_found: no such evidence ID in this run")
    phrases = sorted({m["phrase"] for m in advice})
    common.append_verification(run, common.ADVICE_ID, phrases or None, "FAIL" if advice else "PASS",
                               ("advice words: " + "; ".join(f"{m['phrase']!r} in: {m['line']}" for m in advice))
                               if advice else "report: no advice words")
    found_ids = [i for i in cited_all if entries.get(i) is not None]
    return found_ids, {
        "result": result,
        "checked": len(passes) + len(failures),
        "passed": passes,
        "failed": failures,
        "uncited": uncited,
        "missing_ids": missing,
        "advice": {"result": "FAIL" if advice else "PASS", "matches": advice},
        "warnings": warnings,
    }


def _read_text(args) -> str:
    if args.text is not None:
        return args.text
    if args.text_file == "-":
        return sys.stdin.read()
    path = Path(args.text_file)
    if not path.is_file():
        raise ToolError("bad_input", f"report file not found: {args.text_file}")
    return path.read_text(encoding="utf-8")


def main(argv: Sequence[str]) -> tuple[str | None, list[str], dict[str, Any]]:
    parser = common.ContractParser(prog="verify.py", description="Verify numbers against the evidence ledger.")
    parser.add_argument("evidence_id", nargs="?", help="e.g. E12 (single check; needs --value)")
    parser.add_argument("--value", help="figure to check, e.g. 8.1%% or 12.4B or 0.081")
    parser.add_argument("--withdraw", action="store_true", help="record that the claim citing EVIDENCE_ID was withdrawn")
    parser.add_argument("--tol", type=float, default=None, help="extra relative tolerance on the stored value, e.g. 0.005")
    parser.add_argument("--text", default=None, help="report text to check")
    parser.add_argument("--text-file", default=None, help="file with report text, or - for stdin")
    common.add_run_argument(parser)
    args = parser.parse_args(list(argv))
    modes = [args.evidence_id is not None, args.text is not None, args.text_file is not None]
    if sum(modes) != 1:
        raise ToolError("bad_input", "give exactly one of: EVIDENCE_ID with --value, --text, or --text-file")
    if args.tol is not None and not (0 <= args.tol < 1):
        raise ToolError("bad_input", "--tol must be between 0 and 1")
    if args.withdraw and (args.evidence_id is None or args.value is not None or args.tol is not None):
        raise ToolError("bad_input", "--withdraw takes an EVIDENCE_ID only (no --value, --tol, --text)")
    run = common.resolve_run(args.run)
    if args.withdraw:
        evidence_id = args.evidence_id.strip()
        record = common.append_verification(run, evidence_id, None, "WITHDRAWN", "claim withdrawn by the analyst")
        evidence = [evidence_id] if common.read_evidence(run, evidence_id) else []
        data = {"result": "WITHDRAWN", "id": evidence_id, "checked_at": record["checked_at"]}
    elif args.evidence_id is not None:
        if args.value is None:
            raise ToolError("bad_input", "a single check needs --value")
        evidence, data = verify_single(run, args.evidence_id.strip(), args.value, args.tol)
    else:
        evidence, data = verify_report(run, _read_text(args), args.tol)
    data["citations"] = common.citation_summary(run)
    return run, evidence, data


if __name__ == "__main__":
    sys.exit(common.run_cli(main))
