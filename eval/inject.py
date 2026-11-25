#!/usr/bin/env python3
"""inject.py --seed 7 [--root PATH ...] [--out eval/results]

Verifier fault injection (M8, eval/METRICS.md). For every reports/*.txt of every run that has an evidence ledger,
builds labelled variants that each make ONE change, then runs `verify --text-file` on each variant against a copy
of that run's ledger in a temporary STOCKDESK_HOME. Real runs are never written.

Types (expected verify result):
  off_small    a cited figure moved 2-5%, beyond its display rounding            FAIL
  off_large    a cited figure moved 10-50%                                       FAIL
  unit_swap    8.1% -> 8.1, 12.4B -> 12.4M (and back)                            FAIL
  wrong_id     the figure kept, its citation pointed at another existing E-id    FAIL
               (labelled wrong_id_similar when the figure still matches an entry cited on that line)
  wrong_id_similar  deliberate edge case: the citation pointed at another existing entry whose stored value
               also matches the figure. verify can't tell these apart; reported in its own row     FAIL
  missing_id   its citation pointed at an E-id that does not exist               FAIL
  uncited      a new plausible figure on its own line, no citation               FAIL
  advice       one banned phrase appended to a line                              FAIL
  legit_round  a figure re-displayed one decimal coarser, from the stored value   PASS
  clean        unchanged                                                         PASS

Writes <out>/injection.csv and <out>/injection.md. `actual` is verify's data.result. `fault_flagged` says whether
verify's output points at the injected change itself (a failed or uncited number on the changed line, the new
missing ID, or an advice match on the changed line), so a report that already failed can't count as a catch.
Stdlib plus this repo's stockdesk package.
"""
from __future__ import annotations

import argparse
import csv
import difflib
import random
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

from stockdesk import common, verify  # noqa: E402
from stockdesk.common import ToolError  # noqa: E402
from score_runs import RUN_DIR_RE, default_roots, read_json, temp_home  # noqa: E402

FAULTS = ("off_small", "off_large", "unit_swap", "wrong_id", "missing_id", "uncited", "advice")
BENIGN = ("legit_round", "clean")
PROBES = ("wrong_id_similar",)
TYPES = FAULTS + PROBES + BENIGN
EXPECTED = {**{t: "FAIL" for t in FAULTS}, "wrong_id_similar": "FAIL", **{t: "PASS" for t in BENIGN}}
UNIT_SWAP = {"%": "", "B": "M", "M": "B", "b": "m", "m": "b", "bn": "mm", "mm": "bn", "K": "M", "k": "m"}
_TOKEN = re.compile(r"^(?P<sign>[+\-−]?)(?P<dollar>\$?)(?P<num>\d[\d,]*(?:\.\d+)?)(?P<suf>.*)$")
UNCITED_TEMPLATES = [
    ("• Operating margin was {:.1f}% in the latest quarter.", 5, 40),
    ("• Free cash flow came to ${:.2f}B.", 0.5, 20),
    ("• The 52-week high was {:.2f}.", 20, 600),
    ("• Short interest is {:.1f}% of the float.", 0.5, 12),
]
ADVICE_SENTENCES = [
    "This looks like a strong buy.",
    "Now may be the time to buy.",
    "It is good to buy at this level.",
    "Holders should hold for now.",
    "A rebound is guaranteed.",
    "Some would sell here.",
    "The price target is unchanged.",
]
CSV_COLUMNS = ["variant", "run", "report", "type", "expected", "actual", "base_result", "fault_flagged",
               "line", "before", "after", "detail"]


@dataclass
class Figure:
    line: int          # index into text.splitlines()
    start: int         # span in that line
    end: int
    token: str
    quantity: Any
    matched: str       # the cited E-id this figure matches
    directional: bool
    cited: list[str]


# --------------------------------------------------------------------------- finding cited figures (as verify.py does)

def cited_ids(line: str) -> list[str]:
    ids: list[str] = []
    for group in verify._CITE.findall(line):
        for evidence_id in re.findall(r"E\d+", group):
            if evidence_id not in ids:
                ids.append(evidence_id)
    return ids


def matches(quantity: Any, entry: dict[str, Any] | None, directional: bool) -> bool:
    if entry is None:
        return False
    if directional and verify._matches(quantity, entry, None, sign=-1.0)[0]:
        return True
    return verify._matches(quantity, entry, None)[0]


def figures(text: str, ledger: dict[str, dict[str, Any]]) -> list[Figure]:
    """Numbers verify.py treats as claims, on cited lines, that match one of the line's cited entries."""
    found = []
    for index, raw in enumerate(text.splitlines()):
        cited = cited_ids(raw)
        if not cited:
            continue
        scan = verify._mask(verify._CITE.sub(lambda m: " " * len(m.group(0)), raw))
        for match in verify._NUM_IN_TEXT.finditer(scan):
            if not verify._looks_like_claim(match.group("num"), bool(match.group("suf"))):
                continue
            token = match.group(0).strip()
            try:
                quantity = verify.parse_quantity(token)
            except ToolError:
                continue
            prefix = scan[max(0, match.start() - 24):match.start()]
            directional = not match.group("sign") and bool(verify._NEGATIVE_WORD.search(prefix))
            hit = next((i for i in cited if matches(quantity, ledger.get(i), directional)), None)
            if hit:
                start = match.start() + (len(match.group(0)) - len(match.group(0).lstrip()))
                found.append(Figure(index, start, start + len(token), token, quantity, hit, directional, cited))
    return found


def fmt(value: float, decimals: int, commas: bool) -> str:
    return f"{value:,.{decimals}f}" if commas else f"{value:.{decimals}f}"


def parts(token: str) -> dict[str, str]:
    match = _TOKEN.match(token)
    if not match:
        raise ValueError(f"unparsed token {token!r}")
    return match.groupdict()


def still_passes(new_token: str, figure: Figure, ledger: dict[str, dict[str, Any]], cited: list[str]) -> bool:
    try:
        quantity = verify.parse_quantity(new_token)
    except ToolError:
        return False
    return any(matches(quantity, ledger.get(i), figure.directional) for i in cited)


# --------------------------------------------------------------------------- mutations: each returns (lines, line_index) or None

def replace_span(lines: list[str], figure: Figure, new: str) -> list[str]:
    out = list(lines)
    line = out[figure.line]
    out[figure.line] = line[:figure.start] + new + line[figure.end:]
    return out


def mutate_offset(lines, figs, ledger, rng, low, high):
    for figure in rng.sample(figs, len(figs)):
        p = parts(figure.token)
        decimals = len(p["num"].split(".")[1]) if "." in p["num"] else 0
        base = float(p["num"].replace(",", ""))
        for _ in range(20):
            factor = 1 + rng.choice((-1, 1)) * rng.uniform(low, high)
            new = p["sign"] + p["dollar"] + fmt(abs(base * factor), decimals, "," in p["num"]) + p["suf"]
            if new != figure.token and not still_passes(new, figure, ledger, figure.cited):
                return replace_span(lines, figure, new), figure.line, ""
    return None


def mutate_unit_swap(lines, figs, ledger, rng):
    for figure in rng.sample(figs, len(figs)):
        p = parts(figure.token)
        suffix = p["suf"].strip()
        if suffix not in UNIT_SWAP:
            continue
        new = p["sign"] + p["dollar"] + p["num"] + UNIT_SWAP[suffix]
        if new != figure.token and not still_passes(new, figure, ledger, figure.cited):
            return replace_span(lines, figure, new), figure.line, ""
    return None


def swap_citation(line: str, old: str, new: str) -> str | None:
    """Replace the single occurrence of ID `old` inside a citation bracket."""
    hits = [m for m in re.finditer(rf"\b{old}\b", line)
            if any(b.start() <= m.start() < b.end() for b in verify._CITE.finditer(line))]
    if len(hits) != 1:
        return None
    return line[:hits[0].start()] + new + line[hits[0].end():]


def mutate_wrong_id(lines, figs, ledger, rng):
    pool = sorted(ledger, key=lambda i: int(i[1:]))
    for figure in rng.sample(figs, len(figs)):
        others = [i for i in pool if i not in figure.cited]
        if not others:
            continue
        new_id = rng.choice(others)
        line = swap_citation(lines[figure.line], figure.matched, new_id)
        if line is None:
            continue
        out = list(lines)
        out[figure.line] = line
        still = [i for i in cited_ids(line)]
        similar = still_passes(figure.token, figure, ledger, still)
        note = f"{figure.matched} -> {new_id}"
        if similar:
            note += "; the figure still matches an entry cited on this line"
        return out, figure.line, ("wrong_id_similar" if similar else "") + "|" + note
    return None


def mutate_wrong_id_similar(lines, figs, ledger, rng):
    """Point the citation at another, uncited entry whose value also matches the figure, if one exists."""
    pool = sorted(ledger, key=lambda i: int(i[1:]))
    for figure in rng.sample(figs, len(figs)):
        twins = [i for i in pool if i not in figure.cited and matches(figure.quantity, ledger[i], figure.directional)]
        if not twins:
            continue
        new_id = rng.choice(twins)
        line = swap_citation(lines[figure.line], figure.matched, new_id)
        if line is None:
            continue
        out = list(lines)
        out[figure.line] = line
        return out, figure.line, (f"wrong_id_similar|{figure.matched} -> {new_id}; {figure.token} matches both "
                                  f"({ledger[figure.matched].get('fact')!r} / {ledger[new_id].get('fact')!r})")
    return None


def mutate_missing_id(lines, figs, ledger, rng):
    top = max((int(i[1:]) for i in ledger), default=0)
    for figure in rng.sample(figs, len(figs)):
        new_id = f"E{top + 1 + rng.randint(0, 99)}"
        line = swap_citation(lines[figure.line], figure.matched, new_id)
        if line is not None:
            out = list(lines)
            out[figure.line] = line
            return out, figure.line, f"|{figure.matched} -> {new_id} (not in ledger)"
    return None


def mutate_uncited(lines, rng):
    template, low, high = rng.choice(UNCITED_TEMPLATES)
    at = rng.randint(0, len(lines))
    return lines[:at] + [template.format(rng.uniform(low, high))] + lines[at:], at, ""


def mutate_advice(lines, rng):
    candidates = [i for i, line in enumerate(lines) if line.strip()]
    if not candidates:
        return None
    at = rng.choice(candidates)
    out = list(lines)
    out[at] = out[at].rstrip() + " " + rng.choice(ADVICE_SENTENCES)
    return out, at, ""


def mutate_legit_round(lines, figs, ledger, rng):
    for figure in rng.sample(figs, len(figs)):
        p = parts(figure.token)
        if "." not in p["num"]:
            continue
        decimals = len(p["num"].split(".")[1]) - 1
        shown = float(p["num"].replace(",", ""))
        scale = abs(figure.quantity.value) / shown if shown else 0
        stored = ledger[figure.matched].get("value")
        if not scale or not isinstance(stored, (int, float)) or isinstance(stored, bool):
            continue
        new_num = fmt(round(abs(stored) / scale, decimals), decimals, "," in p["num"])
        new = p["sign"] + p["dollar"] + new_num + p["suf"]
        claim = verify._looks_like_claim(new_num, bool(p["suf"].strip()))
        if new != figure.token and claim and still_passes(new, figure, ledger, [figure.matched]):
            return replace_span(lines, figure, new), figure.line, ""
    return None


def make_variant(kind: str, text: str, ledger: dict[str, dict[str, Any]], rng: random.Random):
    """(variant text, changed line index or None, label override, note) or None when not applicable."""
    lines = text.splitlines()
    figs = figures(text, ledger)
    if kind == "clean":
        return text, None, "", ""
    if kind in ("off_small", "off_large", "unit_swap", "wrong_id", "wrong_id_similar", "missing_id",
                "legit_round") and not figs:
        return None
    result = {
        "off_small": lambda: mutate_offset(lines, figs, ledger, rng, 0.02, 0.05),
        "off_large": lambda: mutate_offset(lines, figs, ledger, rng, 0.10, 0.50),
        "unit_swap": lambda: mutate_unit_swap(lines, figs, ledger, rng),
        "wrong_id": lambda: mutate_wrong_id(lines, figs, ledger, rng),
        "wrong_id_similar": lambda: mutate_wrong_id_similar(lines, figs, ledger, rng),
        "missing_id": lambda: mutate_missing_id(lines, figs, ledger, rng),
        "uncited": lambda: mutate_uncited(lines, rng),
        "advice": lambda: mutate_advice(lines, rng),
        "legit_round": lambda: mutate_legit_round(lines, figs, ledger, rng),
    }[kind]()
    if result is None:
        return None
    out, at, extra = result
    label, _, note = extra.partition("|") if "|" in extra else ("", "", extra)
    trailing = "\n" if text.endswith("\n") else ""
    return "\n".join(out) + trailing, at, label, note


# --------------------------------------------------------------------------- running verify on copies

def run_verify(run: str, name: str, text: str) -> dict[str, Any]:
    """verify --text-file on a variant, inside the current temp home (which holds a copy of the run's ledger)."""
    path = common.evidence_root() / run / "variants" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _, _, data = verify.main(["--text-file", str(path), "--run", run])
    return data


def describe(data: dict[str, Any]) -> str:
    bits = [f"{f['number']} {f['reason']} {f['cited']}" for f in data["failed"]]
    bits += [f"uncited {u['number']}" for u in data["uncited"]]
    bits += [f"missing {i}" for i in data["missing_ids"]]
    bits += [f"advice {m['phrase']!r}" for m in data["advice"]["matches"]]
    return "; ".join(bits)


def flagged(data: dict[str, Any], kind: str, changed: str | None, note: str) -> str:
    if kind in BENIGN or changed is None:
        return ""
    line = changed.strip()
    if kind == "missing_id":
        new_id = note.split("-> ")[-1].split(" ")[0]
        return "yes" if new_id in data["missing_ids"] else "no"
    if kind == "advice":
        return "yes" if any(m["line"] == line for m in data["advice"]["matches"]) else "no"
    hit = any(f["line"] == line for f in data["failed"]) or any(u["line"] == line for u in data["uncited"])
    return "yes" if hit else "no"


def corpus(roots: list[Path]) -> list[tuple[Path, Path]]:
    items = []
    for root in roots:
        for run_dir in sorted(p for p in root.iterdir() if p.is_dir() and RUN_DIR_RE.match(p.name)):
            if not any(run_dir.glob("E*.json")):
                continue
            for report in sorted((run_dir / "reports").glob("*.txt")) if (run_dir / "reports").is_dir() else []:
                items.append((run_dir, report))
    return items


def generate(roots: list[Path], seed: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    by_run: dict[Path, list[Path]] = {}
    for run_dir, report in corpus(roots):
        by_run.setdefault(run_dir, []).append(report)
    for run_dir, reports in by_run.items():
        run = run_dir.name
        ledger = {p.stem: read_json(p) for p in run_dir.glob("E*.json")}
        with temp_home() as home:
            copy = home / "evidence" / run
            copy.mkdir(parents=True)
            for entry in run_dir.glob("E*.json"):
                shutil.copy2(entry, copy / entry.name)
            for report in reports:
                text = report.read_text(encoding="utf-8")
                base = run_verify(run, f"{report.stem}__base.txt", text)
                for kind in TYPES:
                    rng = random.Random(f"{seed}:{run}:{report.name}:{kind}")
                    variant_id = f"{run}/{report.stem}/{kind}"
                    made = make_variant(kind, text, ledger, rng)
                    if made is None:
                        rows.append({"variant": variant_id, "run": run, "report": report.name, "type": kind,
                                     "expected": "n/a", "actual": "n/a", "base_result": base["result"],
                                     "fault_flagged": "", "line": "", "before": "", "after": "",
                                     "detail": "not applicable: no suitable figure"
                                               + (" (no other entry holds a matching value)"
                                                  if kind == "wrong_id_similar" and figures(text, ledger) else "")})
                        continue
                    new_text, at, label, note = made
                    label = label or kind
                    data = run_verify(run, f"{report.stem}__{kind}.txt", new_text)
                    old_lines, new_lines = text.splitlines(), new_text.splitlines()
                    before = ""
                    if at is not None and kind != "uncited":
                        before = old_lines[at]
                    after = new_lines[at] if at is not None else ""
                    detail = describe(data)
                    rows.append({"variant": variant_id, "run": run, "report": report.name, "type": label,
                                 "expected": EXPECTED[label], "actual": data["result"],
                                 "base_result": base["result"], "fault_flagged": flagged(data, kind, after or None, note),
                                 "line": "" if at is None else at + 1, "before": before, "after": after,
                                 "detail": (note + "; " if note else "") + detail})
    return rows


def verify_digest() -> str:
    import hashlib
    return hashlib.sha256(Path(verify.__file__).read_bytes()).hexdigest()


def k_of_n(k: int, n: int, zero_failures: bool) -> str:
    return f"{k}/{n}" + (f" (0 failures; 95% upper bound 3/{n})" if n and zero_failures else "")


def table(rows: list[dict[str, Any]]) -> str:
    out = ["| Type | Expected | Variants | As expected | Flagged at the injected change | Reports already failing | Not applicable |",
           "|---|---|---|---|---|---|---|"]
    for kind in FAULTS[:3] + ("wrong_id", "wrong_id_similar") + FAULTS[4:] + BENIGN:
        mine = [r for r in rows if r["type"] == kind and r["expected"] != "n/a"]
        na = sum(1 for r in rows if r["type"] == kind and r["expected"] == "n/a")
        ok = sum(1 for r in mine if r["actual"] == r["expected"])
        if kind in BENIGN:
            flag = "n/a"
        else:
            hits = sum(1 for r in mine if r["fault_flagged"] == "yes")
            flag = k_of_n(hits, len(mine), hits == len(mine))
        failing_base = sum(1 for r in mine if r["base_result"] == "FAIL")
        out.append(f"| {kind} | {EXPECTED[kind]} | {len(mine)} | {k_of_n(ok, len(mine), ok == len(mine))} | {flag} | "
                   f"{failing_base} | {na} |")
    return "\n".join(out)


def write_outputs(rows: list[dict[str, Any]], out: Path, seed: int) -> None:
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "injection.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    reports = sorted({(r["run"], r["report"], r["base_result"]) for r in rows})
    passing = {(run, rep) for run, rep, res in reports if res == "PASS"}
    clean_base = [r for r in rows if (r["run"], r["report"]) in passing]
    benign = [r for r in rows if r["type"] in BENIGN and r["expected"] != "n/a"]
    alarms = [r for r in benign if r["actual"] == "FAIL"]
    misses = [r for r in rows if r["expected"] == "FAIL" and r["actual"] == "PASS"]
    unflagged = [r for r in rows if r["fault_flagged"] == "no"]
    lines = [
        "# Verifier fault injection (M8)", "",
        f"Generated by `eval/inject.py --seed {seed}`. Definitions: `eval/METRICS.md` (M8). "
        f"verify.py sha256 {verify_digest()[:16]}.", "",
        f"Corpus: {len(reports)} report files from {len({r[0] for r in reports})} runs with a ledger. "
        f"Unchanged, {len(passing)}/{len(reports)} pass verify as saved.", "",
        "**As expected** = verify's result equals the expected result. For fault types that is the detection rate; "
        "for `clean` and `legit_round`, a FAIL is a false alarm. **Flagged at the injected change** = verify's "
        "output points at the changed line or ID, so a report that already failed can't count as a catch.", "",
        "## All reports", "", table(rows), "",
        "## Reports that pass verify unchanged", "", table(clean_base), "",
        f"## False alarms ({len(alarms)}/{len(benign)} clean and legit_round variants)", "",
    ]
    lines += [f"- `{r['variant']}` ({r['type']}): {r['detail']}" for r in alarms] or ["None."]
    lines += ["", f"## Missed faults ({len(misses)} variants expected FAIL that passed)", ""]
    lines += [f"- `{r['variant']}` ({r['type']}): line {r['line']}: `{r['after']}`; {r['detail']}" for r in misses] or ["None."]
    lines += ["", f"## Faults not flagged at the injected change ({len(unflagged)})", ""]
    lines += [f"- `{r['variant']}` ({r['type']}): line {r['line']}: `{r['after']}`; {r['detail']}" for r in unflagged] or ["None."]
    lines += ["", "## wrong_id_similar, hand-classified", ""] + similar_section(rows)
    (out / "injection.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


LABELS = HERE / "labels" / "wrong_id_similar.csv"


def similar_section(rows: list[dict[str, Any]]) -> list[str]:
    """Each wrong_id_similar variant was inspected by hand (eval/labels/wrong_id_similar.csv): a true equivalent
    (the two entries hold the same fact) is excluded from detection; a misattribution counts."""
    found = [r for r in rows if r["type"] == "wrong_id_similar" and r["expected"] != "n/a"]
    labels = {}
    if LABELS.is_file():
        with open(LABELS, encoding="utf-8") as handle:
            labels = {r["variant"]: r for r in csv.DictReader(handle)}
    out = [f"{len(found)} variants found. Labels: `eval/labels/wrong_id_similar.csv` (one person, by inspection).", ""]
    unlabelled = [r["variant"] for r in found if r["variant"] not in labels]
    for r in found:
        label = labels.get(r["variant"], {})
        out.append(f"- `{r['variant']}`: verify {r['actual']}; {label.get('class', 'UNLABELLED')}: "
                   f"{label.get('reason', r['detail'])}")
    mis = [r for r in found if labels.get(r["variant"], {}).get("class") == "misattribution"]
    eq = [r for r in found if labels.get(r["variant"], {}).get("class") == "equivalent"]
    caught = sum(1 for r in mis if r["actual"] == "FAIL")
    out += ["", f"Equivalent, excluded from detection: {len(eq)}/{len(found)}.",
            f"**Misattribution detection: {caught}/{len(mis)}.**"]
    if unlabelled:
        out.append(f"Unlabelled (not counted): {', '.join(unlabelled)}")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--root", action="append", type=Path)
    parser.add_argument("--out", type=Path, default=HERE / "results")
    args = parser.parse_args(argv)
    rows = generate(args.root or default_roots(), args.seed)
    write_outputs(rows, args.out, args.seed)
    print(f"{len(rows)} variants -> {args.out / 'injection.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
