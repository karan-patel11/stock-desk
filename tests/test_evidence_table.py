from __future__ import annotations

import json

import pytest

from stockdesk import common
from stockdesk import evidence_table
from stockdesk.common import ToolError


@pytest.fixture
def ledger(run_id):
    def put(**kw):
        base = dict(tool="t.py", fact="f", value=1, unit="USD", period="2026-Q3", source="s",
                    url="https://example.com/a", locator="l", source_tier="T1")
        base.update(kw)
        return common.write_evidence(run_id, **base)["id"]
    ids = {
        "rev": put(fact="Revenue, NKE", value=11213000000, source="SEC EDGAR companyfacts, 10-Q"),
        "close": put(tool="tech.py", fact="Last close (NKE)", value=38.59, period="2026-11-06",
                     source="Yahoo Finance via yfinance (unofficial, disclosed): daily bars", source_tier="T2"),
        "pipe": put(fact="Title with | pipe\nand newline", value="x" * 300, unit="text", url="none supplied",
                    source_tier="unrated"),
    }
    ids["growth"] = put(fact="Revenue growth", value=0.0814, unit="ratio", derived_from=[ids["rev"], ids["close"]])
    return run_id, ids


def table(run):
    _, evidence, data = evidence_table.main(["--run", run])
    assert evidence == []
    return data


def row_for(markdown, evidence_id):
    return next(line for line in markdown.splitlines() if line.startswith(f"| {evidence_id} |"))


def test_columns_rows_and_values(ledger):
    run, ids = ledger
    data = table(run)
    lines = data["markdown"].splitlines()
    assert lines[0] == "| ID | Fact | Value (unit) | Period | Source | Tier | Link | Verified |"
    assert len(lines) == 2 + 4 and data["entries"] == 4
    rev = row_for(data["markdown"], ids["rev"])
    assert "| 11213000000 (USD) |" in rev and "| T1 |" in rev and "[link](<https://example.com/a>)" in rev
    close = row_for(data["markdown"], ids["close"])
    assert "| 38.59 (USD) |" in close and "| T2 |" in close and "unofficial, disclosed" in close
    assert "| T2 |" in row_for(data["markdown"], ids["growth"])  # derived: weakest input tier


def test_cells_are_escaped_and_shortened(ledger):
    run, ids = ledger
    row = row_for(table(run)["markdown"], ids["pipe"])
    assert "Title with \\| pipe and newline" in row and "…" in row and "| none supplied |" in row
    assert len(row.split(" | ")) == 8  # the escaped pipe did not add a column


def test_verified_column_uses_latest_record(ledger):
    run, ids = ledger
    common.append_verification(run, ids["rev"], "11.2B", "FAIL", "x")
    common.append_verification(run, ids["rev"], "11.213B", "PASS", "x")
    common.append_verification(run, ids["close"], "40", "FAIL", "x")
    data = table(run)
    assert row_for(data["markdown"], ids["rev"]).endswith("| PASS |")
    assert row_for(data["markdown"], ids["close"]).endswith("| FAIL |")
    assert row_for(data["markdown"], ids["growth"]).endswith("| not checked |")
    assert data["citations"] == "1/2" and data["uncorrected"] == [ids["close"]]


def test_news_weight_and_counted(run_id):
    path = common.evidence_root() / run_id
    common.write_evidence(run_id, tool="news.py", fact="Article tone: A", value=-3.0, unit="gdelt_tone",
                          period="2026-11-01", source="reuters.com", url="https://reuters.com/a", locator="l",
                          source_tier="T3")
    entry = json.loads((path / "E1.json").read_text())
    entry.update({"weight": 1.0, "counted": True, "not_counted_reason": None})
    (path / "E1.json").write_text(json.dumps(entry))
    entry2 = {**entry, "id": "E2", "source_tier": "T4", "weight": 0.4, "counted": False,
              "not_counted_reason": "duplicate_of:E1"}
    (path / "E2.json").write_text(json.dumps(entry2))
    md = table(run_id)["markdown"]
    assert "| T3 · weight 1.0 · counted |" in row_for(md, "E1")
    assert "| T4 · weight 0.4 · not counted (duplicate_of:E1) |" in row_for(md, "E2")


def test_old_entry_without_tier(run_id):
    (common.evidence_root() / run_id / "E1.json").write_text(json.dumps(
        {"id": "E1", "fact": "old", "value": 1, "unit": "USD", "period": "p", "source": "s", "url": "u"}))
    assert "| not recorded |" in row_for(table(run_id)["markdown"], "E1")


def test_empty_run_is_no_data(run_id):
    with pytest.raises(ToolError) as err:
        table(run_id)
    assert err.value.code == "no_data"


def test_bad_run_is_bad_input(run_id):
    with pytest.raises(ToolError) as err:
        evidence_table.main(["--run", "nonsense"])
    assert err.value.code == "bad_input"
