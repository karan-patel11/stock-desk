"""Generates the SYNTHETIC SEC fixtures used by tests/test_fund.py.

These files are shaped like SEC responses (company_tickers.json, submissions, companyfacts)
but every number is invented for a fictional company, TSTCO, so tests can assert exact values.
They are NOT recorded API responses. Run once: python3 tests/fixtures/build_synthetic.py
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).parent
CIK = 1234567
SHARES = 100_000_000

# fiscal year (ends May 31) -> (quarter revenues in $M, gross margin by quarter)
REVENUE = {2024: [900, 950, 1000, 1050], 2025: [1000, 1100, 1200, 1300],
           2026: [1080, 1180, 1260, 1400], 2027: [1166.4]}
GROSS = {2024: [.40] * 4, 2025: [.40] * 4, 2026: [.40, .40, .40, .39], 2027: [.38]}
OPER = {2024: [.10] * 4, 2025: [.10] * 4, 2026: [.10] * 4, 2027: [.11]}
NET = {2024: [.075] * 4, 2025: [.075] * 4, 2026: [.075] * 4, 2027: [.08]}
DEBT = {2024: [500, 505, 510, 515], 2025: [520, 525, 530, 535], 2026: [540, 545, 550, 555], 2027: [560]}


def quarter_bounds(fy: int, q: int) -> tuple[date, date]:
    start_year = fy - 1
    starts = [date(start_year, 6, 1), date(start_year, 9, 1), date(start_year, 12, 1), date(fy, 3, 1)]
    ends = [date(start_year, 8, 31), date(start_year, 11, 30), date(fy, 2, 28 if fy % 4 else 29), date(fy, 5, 31)]
    return starts[q], ends[q]


def accn(fy: int, q: int) -> str:
    return f"0001234567-{(fy - 1) % 100:02d}-{(q + 1) * 111:06d}"


def filed(end: date, extra: int = 35) -> str:
    return (end + timedelta(days=extra)).isoformat()


def flow(values: dict[int, list[float]], scale: float = 1e6, as_int: bool = True) -> list[dict]:
    out = []
    for fy, quarters in values.items():
        cumulative = 0.0
        fy_start = quarter_bounds(fy, 0)[0]
        for q, raw in enumerate(quarters):
            value = raw * scale
            value = int(round(value)) if as_int else round(value, 4)
            start, end = quarter_bounds(fy, q)
            cumulative += value
            base = {"accn": accn(fy, q), "fy": fy, "form": "10-Q", "filed": filed(end)}
            out.append({"start": start.isoformat(), "end": end.isoformat(), "val": value, "fp": f"Q{q + 1}", **base})
            if q == 1:  # six-month YTD reported in the Q2 10-Q
                out.append({"start": fy_start.isoformat(), "end": end.isoformat(), "val": cumulative, "fp": "Q2", **base})
            if q == 2:  # nine-month YTD reported in the Q3 10-Q
                out.append({"start": fy_start.isoformat(), "end": end.isoformat(), "val": cumulative, "fp": "Q3", **base})
            if q == 3:  # fiscal year reported in the 10-K (no stand-alone Q4)
                out.pop()
                out.append({"start": fy_start.isoformat(), "end": end.isoformat(), "val": cumulative, "fp": "FY",
                            "accn": accn(fy, 3), "fy": fy, "form": "10-K", "filed": filed(end, 50)})
        # comparatives: next year's 10-Q repeats each quarter later (same value), as real filings do
    comparatives = []
    for entry in out:
        if entry["form"] == "10-Q" and entry["fp"] == "Q1" and entry["fy"] < 2027:
            later = dict(entry)
            later["accn"] = entry["accn"].replace("-", "-9", 1)[:19]
            later["filed"] = (date.fromisoformat(entry["filed"]) + timedelta(days=365)).isoformat()
            comparatives.append(later)
    return out + comparatives


def margin_series(rev: dict, margin: dict) -> dict[int, list[float]]:
    return {fy: [r * m for r, m in zip(rev[fy], margin[fy])] for fy in rev}


def instants(values: dict[int, list[float]]) -> list[dict]:
    out = []
    for fy, quarters in values.items():
        for q, raw in enumerate(quarters):
            _, end = quarter_bounds(fy, q)
            out.append({"end": end.isoformat(), "val": int(raw * 1e6), "accn": accn(fy, q), "fy": fy,
                        "form": "10-K" if q == 3 else "10-Q", "filed": filed(end)})
    return out


def eps_series() -> list[dict]:
    net = margin_series(REVENUE, NET)
    values = {fy: [round(v * 1e6 / SHARES, 4) for v in quarters] for fy, quarters in net.items()}
    return flow(values, scale=1.0, as_int=False)


def build() -> None:
    rev_old = {fy: v for fy, v in REVENUE.items() if fy <= 2025}
    rev_new = {fy: v for fy, v in REVENUE.items() if fy >= 2026}
    facts = {
        "SalesRevenueNet": {"label": "Sales Revenue, Net", "units": {"USD": flow(rev_old)}},
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"label": "Revenue", "units": {"USD": flow(rev_new)}},
        "GrossProfit": {"label": "Gross Profit", "units": {"USD": flow(margin_series(REVENUE, GROSS))}},
        "OperatingIncomeLoss": {"label": "Operating Income", "units": {"USD": flow(margin_series(REVENUE, OPER))}},
        "NetIncomeLoss": {"label": "Net Income", "units": {"USD": flow(margin_series(REVENUE, NET))}},
        "EarningsPerShareDiluted": {"label": "EPS diluted", "units": {"USD/shares": eps_series()}},
        "LongTermDebt": {"label": "Long-term debt", "units": {"USD": instants(DEBT)}},
    }
    note = "SYNTHETIC fixture for fictional company TSTCO; not a recorded SEC response."
    (HERE / "synthetic_company_tickers.json").write_text(json.dumps({
        "_note": note,
        "0": {"cik_str": CIK, "ticker": "TSTCO", "title": "Test Footwear Co"},
        "1": {"cik_str": 7654321, "ticker": "OTHER", "title": "Other Corp"},
    }, indent=1))
    (HERE / "synthetic_submissions_tstco.json").write_text(json.dumps({
        "_note": note, "cik": str(CIK), "name": "Test Footwear Co", "sic": "3021",
        "sicDescription": "Rubber & Plastics Footwear", "fiscalYearEnd": "0531", "tickers": ["TSTCO"],
    }, indent=1))
    (HERE / "synthetic_companyfacts_tstco.json").write_text(json.dumps({
        "_note": note, "cik": CIK, "entityName": "Test Footwear Co", "facts": {"us-gaap": facts},
    }, indent=1))
    print("wrote synthetic fixtures")


if __name__ == "__main__":
    build()
