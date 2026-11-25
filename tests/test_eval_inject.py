"""eval/inject.py: deterministic for a seed, one change per variant, correct labels."""
from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

from stockdesk import common, verify

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "eval"))
import inject  # noqa: E402

TEXT = ("[FUNDAMENTAL] TSTCO · round 1\n"
        "• Revenue $12.43B [E1]; growth 8.14% [E2].\n"
        "• Close 61.42 [E3], volume 1.83x [E4].\n"
        "Gaps: none.\n")
LEDGER = {
    "E1": {"id": "E1", "fact": "Revenue", "value": 12_430_000_000, "unit": "USD"},
    "E2": {"id": "E2", "fact": "Revenue growth YoY", "value": 0.0814, "unit": "ratio"},
    "E3": {"id": "E3", "fact": "Close", "value": 61.42, "unit": "USD"},
    "E4": {"id": "E4", "fact": "Volume vs 20-day average", "value": 1.83, "unit": "x"},
    "E5": {"id": "E5", "fact": "SMA200", "value": 99.0, "unit": "USD"},
    "E6": {"id": "E6", "fact": "Previous close", "value": 61.42, "unit": "USD"},   # twin of E3
}
KINDS = [k for k in inject.TYPES]


def variant(kind, seed=7):
    return inject.make_variant(kind, TEXT, LEDGER, random.Random(f"{seed}:{kind}"))


def edit(old: str, new: str) -> tuple[str, str]:
    """The single differing span between two strings (common prefix and suffix removed)."""
    p = 0
    while p < min(len(old), len(new)) and old[p] == new[p]:
        p += 1
    s = 0
    while s < min(len(old), len(new)) - p and old[len(old) - 1 - s] == new[len(new) - 1 - s]:
        s += 1
    return old[p:len(old) - s], new[p:len(new) - s]


@pytest.mark.parametrize("kind", KINDS)
def test_deterministic_for_a_seed(kind):
    assert variant(kind) == variant(kind)


def test_different_seeds_can_differ():
    outs = {variant("off_small", seed)[0] for seed in range(10)}
    assert len(outs) > 1


@pytest.mark.parametrize("kind", [k for k in KINDS if k != "clean"])
def test_exactly_one_change(kind):
    new_text, at, _, _ = variant(kind)
    old_lines, new_lines = TEXT.splitlines(), new_text.splitlines()
    import difflib
    ops = [op for op in difflib.SequenceMatcher(None, old_lines, new_lines).get_opcodes() if op[0] != "equal"]
    assert len(ops) == 1, ops
    tag, i1, i2, j1, j2 = ops[0]
    if kind == "uncited":
        assert tag == "insert" and j2 - j1 == 1 and new_lines[at] == new_lines[j1]
    else:
        assert tag == "replace" and i2 - i1 == 1 and j2 - j1 == 1 and at == i1
        old_span, new_span = edit(old_lines[i1], new_lines[j1])
        # one contiguous edit: a figure, an E-id's digits, or an appended sentence
        assert len(old_span) <= len("12.43B") and (old_span or kind == "advice")


def test_clean_is_unchanged():
    assert variant("clean")[0] == TEXT


def changed_tokens(kind):
    new_text, at, label, note = variant(kind)
    old, new = TEXT.splitlines()[at], new_text.splitlines()[at]
    figs_old = {f.token for f in inject.figures(TEXT, LEDGER) if f.line == at}
    return old, new, label, note, figs_old


@pytest.mark.parametrize("kind,low,high", [("off_small", 0.02, 0.05), ("off_large", 0.10, 0.50)])
def test_offsets_move_a_figure_by_the_labelled_amount_and_break_the_match(kind, low, high):
    new_text, at, _, _ = variant(kind)
    before = {f.token: f for f in inject.figures(TEXT, LEDGER)}
    after = {f.token for f in inject.figures(new_text, LEDGER)}
    gone = [t for t in before if t not in after]
    assert len(gone) == 1
    old_line, new_line = TEXT.splitlines()[at], new_text.splitlines()[at]
    old_span, new_span = edit(old_line, new_line)
    figure = before[gone[0]]
    new_token = new_line[figure.start:figure.end + len(new_line) - len(old_line)]
    q_old, q_new = verify.parse_quantity(figure.token), verify.parse_quantity(new_token)
    rel = abs(q_new.value - q_old.value) / abs(q_old.value)
    assert low - 0.006 <= rel <= high + 0.006        # display rounding can nudge the realised move slightly
    assert not inject.still_passes(new_token, figure, LEDGER, figure.cited)


def test_unit_swap_changes_only_the_suffix():
    new_text, at, _, _ = variant("unit_swap")
    old_span, new_span = edit(TEXT.splitlines()[at], new_text.splitlines()[at])
    assert {old_span, new_span} <= {"%", "", "B", "M"} and old_span != new_span


def test_wrong_id_points_at_another_existing_entry():
    new_text, at, label, note = variant("wrong_id")
    old_id, new_id = note.split("; ")[0].split(" -> ")
    assert new_id in LEDGER and new_id != old_id and new_id not in inject.cited_ids(TEXT.splitlines()[at])
    assert label in ("", "wrong_id_similar")


def test_wrong_id_similar_uses_a_twin_entry():
    new_text, at, label, note = variant("wrong_id_similar")
    assert label == "wrong_id_similar" and "E3 -> E6" in note   # the only figure with a twin


def test_missing_id_points_outside_the_ledger():
    new_text, at, _, note = variant("missing_id")
    new_id = note.split(" -> ")[1].split(" ")[0]
    assert new_id not in LEDGER and new_id in inject.cited_ids(new_text.splitlines()[at])


def test_uncited_line_has_a_claim_and_no_citation():
    new_text, at, _, _ = variant("uncited")
    line = new_text.splitlines()[at]
    assert not inject.cited_ids(line) and inject.verify._NUM_IN_TEXT.search(line)


def test_advice_appends_one_banned_phrase():
    new_text, at, _, _ = variant("advice")
    assert len(verify.advice_matches(new_text)) == 1 and not verify.advice_matches(TEXT)


def test_legit_round_is_coarser_and_still_matches():
    new_text, at, _, _ = variant("legit_round")
    old_span, new_span = edit(TEXT.splitlines()[at], new_text.splitlines()[at])
    assert len(new_span) < len(old_span)                     # one decimal fewer
    after = inject.figures(new_text, LEDGER)
    assert len(after) == len(inject.figures(TEXT, LEDGER))   # every figure still matches its cited entry


def test_not_applicable_without_cited_figures():
    plain = "[SENTIMENT] TSTCO\nTone: no data.\n"
    for kind in ("off_small", "off_large", "unit_swap", "wrong_id", "wrong_id_similar", "missing_id", "legit_round"):
        assert inject.make_variant(kind, plain, LEDGER, random.Random(1)) is None


# ---------------- end to end on a synthetic run, through verify --text-file ----------------

@pytest.fixture
def synthetic_root():
    run = "r-20990101-01"
    run_dir = common.evidence_root() / run
    (run_dir / "reports").mkdir(parents=True)
    for eid in sorted(LEDGER, key=lambda i: int(i[1:])):
        e = LEDGER[eid]
        common.write_evidence(run, tool="t.py", fact=e["fact"], value=e["value"], unit=e["unit"], period="p",
                              source="s", url="https://x", locator="l", source_tier="T1")
    (run_dir / "reports" / "fundamental-r1.txt").write_text(TEXT, encoding="utf-8")
    return common.evidence_root()


def test_generate_labels_and_results(synthetic_root):
    snapshot = {p: p.read_bytes() for p in synthetic_root.rglob("*") if p.is_file()}
    rows = inject.generate([synthetic_root], seed=7)
    assert {p: p.read_bytes() for p in synthetic_root.rglob("*") if p.is_file()} == snapshot   # never writes a real run
    assert inject.generate([synthetic_root], seed=7) == rows
    by_type = {r["type"]: r for r in rows}
    assert set(by_type) == set(inject.TYPES)
    for kind in inject.FAULTS:
        assert by_type[kind]["expected"] == "FAIL" and by_type[kind]["actual"] == "FAIL"
        assert by_type[kind]["fault_flagged"] == "yes"
    for kind in inject.BENIGN:
        assert by_type[kind]["expected"] == "PASS" and by_type[kind]["actual"] == "PASS"
    # verify can't tell twin entries apart: recorded, not hidden
    assert by_type["wrong_id_similar"]["actual"] == "PASS"
