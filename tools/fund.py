#!/usr/bin/env python3
"""fund.py TICKER [--quarters 8] [--run RUN]

Fundamentals from SEC EDGAR XBRL (companyfacts): revenue, gross profit, operating income,
net income, diluted EPS and total debt per quarter, plus derived YoY growth, margins and
margin changes, the SIC code, configured peers and the sector ETF.

Rules this tool enforces:
- XBRL never reports Q4 on its own. For additive flow metrics Q4 is DERIVED as the 10-K fiscal
  year minus the 10-Q nine-month YTD; both inputs are written to the ledger and the Q4 entry
  lists them in derived_from. EPS is not additive, so a Q4 EPS is never derived.
- Facts are deduplicated per period, keeping the latest filing. Amendments (10-K/A, 10-Q/A) are ignored.
- Anything missing or undefined (no tag, prior value <= 0, no peers configured) is listed in
  data.unavailable. Nothing is guessed or interpolated.
- Freshness: a metric whose latest quarterly value ended more than STOCKDESK_MAX_FUND_AGE_DAYS (default 200)
  days before today (UTC) is dropped and listed as "latest quarterly value ends <date>; stale". Annual values
  are never substituted. If no metric is fresh, the tool returns no_data. (Example: JPM's quarterly
  us-gaap:Revenues stops in 2014; without this check those quarters were reported as the latest.)
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Sequence

import common
from common import ToolError

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SEC_INTERVAL = 0.15  # seconds between SEC requests; SEC's limit is 10 per second
FORMS = ("10-Q", "10-K")
MAX_AGE_ENV = "STOCKDESK_MAX_FUND_AGE_DAYS"
DEFAULT_MAX_AGE_DAYS = 200

# key, label, ledger unit, SEC unit, kind, us-gaap tags in priority order
METRICS = [
    ("revenue", "Revenue", "USD", "USD", "flow", [
        "RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
        "RevenueFromContractWithCustomerIncludingAssessedTax"]),
    ("gross_profit", "Gross profit", "USD", "USD", "flow", ["GrossProfit"]),
    ("operating_income", "Operating income", "USD", "USD", "flow", ["OperatingIncomeLoss"]),
    ("net_income", "Net income", "USD", "USD", "flow", ["NetIncomeLoss"]),
    ("eps_diluted", "Diluted EPS", "USD/share", "USD/shares", "flow_nonadditive", ["EarningsPerShareDiluted"]),
    ("total_debt", "Total debt", "USD", "USD", "instant", ["LongTermDebt", "DebtLongtermAndShorttermCombinedAmount"]),
]
# When no combined debt tag exists for a balance-sheet date, total debt is derived as the sum of these
# two instants (filers such as Nike tag LongTermDebt only in the 10-K but split it every quarter).
DEBT_PARTS = ("LongTermDebtCurrent", "LongTermDebtNoncurrent")
GROWTH_KEYS = ("revenue", "gross_profit", "operating_income", "net_income", "eps_diluted")
MARGINS = (("gross_margin", "Gross margin", "gross_profit"),
           ("operating_margin", "Operating margin", "operating_income"),
           ("net_margin", "Net margin", "net_income"))


@dataclass(frozen=True)
class Fact:
    start: str | None
    end: str
    val: float
    accn: str
    form: str
    filed: str
    tag: str


@dataclass
class Period:
    start: str | None
    end: str
    val: float
    tag: str
    accn: str
    form: str
    derived: bool = False
    inputs: tuple[Fact, Fact] | None = None  # (fiscal year, nine-month YTD) for a derived Q4


def _days(later: str, earlier: str) -> int:
    return (datetime.strptime(later, "%Y-%m-%d") - datetime.strptime(earlier, "%Y-%m-%d")).days


def _json(text: str, what: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ToolError("source_unavailable", f"{what}: response was not JSON") from exc


def resolve_cik(ticker: str) -> tuple[str, str]:
    result = common.http_get(TICKERS_URL, sec=True, ttl=7 * 86400, min_interval=SEC_INTERVAL)
    table = _json(result.text, "SEC ticker map")
    wanted = ticker.upper()
    for row in table.values():
        if isinstance(row, dict) and str(row.get("ticker", "")).upper() == wanted:
            return str(int(row["cik_str"])).zfill(10), str(row.get("title", ""))
    raise ToolError("no_data", f"{ticker} is not in the SEC ticker map")


def extract_facts(us_gaap: dict[str, Any], tag: str, sec_unit: str) -> list[Fact]:
    node = us_gaap.get(tag)
    if not node:
        return []
    facts = []
    for item in node.get("units", {}).get(sec_unit, []):
        if item.get("form") not in FORMS or "end" not in item or "val" not in item:
            continue
        if isinstance(item["val"], bool) or not isinstance(item["val"], (int, float)):
            continue
        facts.append(Fact(item.get("start"), item["end"], item["val"], str(item.get("accn", "")),
                          item["form"], str(item.get("filed", "")), tag))
    return facts


def dedupe(facts: list[Fact]) -> dict[tuple[str | None, str], Fact]:
    """One fact per (start, end): the latest filing wins (restated comparatives replace originals)."""
    best: dict[tuple[str | None, str], Fact] = {}
    for fact in facts:
        key = (fact.start, fact.end)
        current = best.get(key)
        if current is None or (fact.filed, fact.accn) > (current.filed, current.accn):
            best[key] = fact
    return best


def flow_periods(facts: list[Fact], additive: bool) -> dict[str, Period]:
    """Quarter periods keyed by end date; Q4 derived as FY minus nine-month YTD when additive."""
    quarters: dict[str, Period] = {}
    nine_month: dict[str, Fact] = {}
    fiscal_years: list[Fact] = []
    for (start, end), fact in dedupe(facts).items():
        if start is None:
            continue
        days = _days(end, start)
        if 80 <= days <= 100:
            quarters[end] = Period(start, end, fact.val, fact.tag, fact.accn, fact.form)
        elif 260 <= days <= 285:
            nine_month[start] = fact
        elif 350 <= days <= 380:
            fiscal_years.append(fact)
    if additive:
        for year in fiscal_years:
            if year.end in quarters:
                continue
            nine = nine_month.get(year.start or "")
            if nine is None or not 80 <= _days(year.end, nine.end) <= 100:
                continue
            q4_start = (datetime.strptime(nine.end, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
            quarters[year.end] = Period(q4_start, year.end, year.val - nine.val, year.tag, year.accn, year.form,
                                        derived=True, inputs=(year, nine))
    return quarters


def instant_periods(facts: list[Fact]) -> dict[str, Period]:
    best: dict[str, Fact] = {}
    for fact in facts:
        if fact.start is not None:
            continue
        current = best.get(fact.end)
        if current is None or (fact.filed, fact.accn) > (current.filed, current.accn):
            best[fact.end] = fact
    return {end: Period(None, end, f.val, f.tag, f.accn, f.form) for end, f in best.items()}


def collect_metric(us_gaap: dict[str, Any], tags: list[str], sec_unit: str, kind: str) -> tuple[dict[str, Period], list[str]]:
    """Merge tags in priority order: for each period end the highest-priority tag that has it wins."""
    merged: dict[str, Period] = {}
    used: list[str] = []
    for tag in tags:
        facts = extract_facts(us_gaap, tag, sec_unit)
        if not facts:
            continue
        periods = instant_periods(facts) if kind == "instant" else flow_periods(facts, kind == "flow")
        added = False
        for end, period in periods.items():
            if end not in merged:
                merged[end] = period
                added = True
        if added:
            used.append(tag)
    return merged, used


def max_age_days() -> int:
    raw = common.env(MAX_AGE_ENV)
    if not raw:
        return DEFAULT_MAX_AGE_DAYS
    try:
        days = int(raw)
    except ValueError:
        days = 0
    if days <= 0:
        raise ToolError("bad_input", f"{MAX_AGE_ENV} must be a positive whole number of days, got {raw!r}")
    return days


def main(argv: Sequence[str], today: date | None = None) -> tuple[str | None, list[str], dict[str, Any]]:
    parser = common.ContractParser(prog="fund.py", description="Fundamentals from SEC EDGAR XBRL.")
    parser.add_argument("ticker")
    parser.add_argument("--quarters", type=int, default=8, help="number of most recent quarters (1-12)")
    common.add_run_argument(parser)
    args = parser.parse_args(list(argv))
    ticker = common.normalize_ticker(args.ticker)
    if not 1 <= args.quarters <= 12:
        raise ToolError("bad_input", "--quarters must be between 1 and 12")
    run = common.resolve_run(args.run)
    max_age = max_age_days()
    today_text = (today or common.utc_now().date()).isoformat()
    common.user_agent(required=True)  # fail before any request if the SEC contact is not configured

    cik, name = resolve_cik(ticker)
    submissions = common.http_get(SUBMISSIONS_URL.format(cik=cik), sec=True, min_interval=SEC_INTERVAL)
    sub = _json(submissions.text, "SEC submissions")
    facts_url = FACTS_URL.format(cik=cik)
    facts_result = common.http_get(facts_url, sec=True, min_interval=SEC_INTERVAL)
    facts_doc = _json(facts_result.text, "SEC companyfacts")
    us_gaap = facts_doc.get("facts", {}).get("us-gaap")
    if not us_gaap:
        raise ToolError("no_data", f"{ticker} has no us-gaap XBRL facts (foreign filer or no XBRL)")
    retrieved_at = facts_result.fetched_at
    sub_url = SUBMISSIONS_URL.format(cik=cik)

    ids: list[str] = []
    unavailable: list[dict[str, str]] = []

    def record(fact: str, value: Any, unit: str, period: str, source: str, url: str, locator: str,
               derived_from: list[str] | None = None, when: str | None = None, tier: str = "T1") -> str:
        entry = common.write_evidence(run, tool="fund.py", fact=fact, value=value, unit=unit, period=period,
                                      source=source, url=url, locator=locator, derived_from=derived_from,
                                      source_tier=tier,
                                      retrieved_at=when or retrieved_at)
        ids.append(entry["id"])
        return entry["id"]

    # ---- company facts that are not quarterly ----
    sic = sub.get("sic")
    sic_id = fye_id = None
    if sic:
        sic_id = record(f"SIC code, {ticker}", int(sic), "code", submissions.fetched_at[:10],
                        "SEC EDGAR submissions", sub_url, f"sic={sic} ({sub.get('sicDescription', '')})",
                        when=submissions.fetched_at)
    else:
        unavailable.append({"metric": "sic", "reason": "no SIC code in SEC submissions"})
    if sub.get("fiscalYearEnd"):
        fye_id = record(f"Fiscal year end (MMDD), {ticker}", str(sub["fiscalYearEnd"]), "MMDD",
                        submissions.fetched_at[:10], "SEC EDGAR submissions", sub_url,
                        f"fiscalYearEnd={sub['fiscalYearEnd']}", when=submissions.fetched_at)

    peers_cfg = common.load_config("peers.json")
    peers = peers_cfg.get(ticker)
    peers_id = None
    if isinstance(peers, list) and peers:
        peers_id = record(f"Configured peers, {ticker}", ",".join(peers), "tickers", retrieved_at[:10],
                          "config/peers.json (curated)", "config/peers.json", f"peers[{ticker}]", when=retrieved_at,
                          tier="unrated")  # our curated config, not an SEC fact
    else:
        peers = []
        unavailable.append({"metric": "peers", "reason": f"no peers configured for {ticker} in config/peers.json"})

    etf_cfg = common.load_config("sector_etf.json")
    etf = (etf_cfg.get("overrides") or {}).get(ticker)
    if not etf and sic:
        for rule in etf_cfg.get("sic_ranges") or []:
            if rule["min"] <= int(sic) <= rule["max"]:
                etf = rule["etf"]
                break
    etf_id = None
    if etf:
        etf_id = record(f"Sector ETF, {ticker}", etf, "ticker", retrieved_at[:10], "config/sector_etf.json (curated)",
                        "config/sector_etf.json", f"overrides[{ticker}]", when=retrieved_at,
                        tier="unrated")  # our curated config, not an SEC fact
    else:
        unavailable.append({"metric": "sector_etf", "reason": f"no ETF mapping for {ticker}; pass --etf to precedent.py"})

    # ---- quarterly facts ----
    collected: dict[str, dict[str, Period]] = {}
    tags_used: dict[str, list[str]] = {}
    debt_parts = {tag: instant_periods(extract_facts(us_gaap, tag, "USD")) for tag in DEBT_PARTS}
    for key, label, _unit, sec_unit, kind, tags in METRICS:
        periods, used = collect_metric(us_gaap, tags, sec_unit, kind)
        if not periods and key == "total_debt" and all(debt_parts.values()):
            collected[key] = {}  # every date falls back to the derived sum below
            tags_used[key] = list(DEBT_PARTS)
            continue
        if not periods:
            unavailable.append({"metric": key, "reason": f"no us-gaap tag with {sec_unit} 10-Q/10-K facts among {', '.join(tags)}"})
            continue
        collected[key] = periods
        tags_used[key] = used

    if "revenue" not in collected:
        raise ToolError("no_data", f"no quarterly revenue found for {ticker}")

    # ---- freshness: drop any metric whose latest quarterly value is too old ----
    for key in list(collected):
        if collected[key]:
            latest = max(collected[key])
        else:  # total debt built from its two parts: the latest date both parts have
            common_ends = set.intersection(*(set(p) for p in debt_parts.values()))
            latest = max(common_ends) if common_ends else None
        if latest is None:
            continue
        if _days(today_text, latest) > max_age:
            unavailable.append({"metric": key, "reason": f"latest quarterly value ends {latest}; stale"})
            del collected[key]
            tags_used.pop(key, None)

    if not collected:
        reasons = "; ".join(f"{u['metric']}: {u['reason']}" for u in unavailable if u["metric"] in {m[0] for m in METRICS})
        raise ToolError("no_data", f"no fresh quarterly data for {ticker} ({reasons or 'no metrics found'})")
    if "revenue" in collected:
        ends = sorted(collected["revenue"])[-args.quarters:]
    else:  # revenue stale or missing: use the quarters the fresh flow metrics have
        flow_keys = [m[0] for m in METRICS if m[4] != "instant" and m[0] in collected]
        pool = set().union(*(collected[k] for k in flow_keys)) if flow_keys else set().union(
            *(collected[k] for k in collected if collected[k]))
        if not pool:
            raise ToolError("no_data", f"no fresh quarterly data for {ticker}")
        ends = sorted(pool)[-args.quarters:]
    labels = {key: (label, unit) for key, label, unit, *_ in METRICS}

    input_ids: dict[tuple[str, str, str | None], str] = {}

    def record_input(key: str, fact: Fact, what: str) -> str:
        cache_key = (key, fact.end, fact.start)
        if cache_key not in input_ids:
            label, unit = labels[key]
            input_ids[cache_key] = record(
                f"{label}, {ticker} {what} ended {fact.end}", fact.val, unit, f"{fact.start}/{fact.end}",
                f"SEC EDGAR companyfacts, {fact.form}", facts_url, f"us-gaap:{fact.tag}, accn {fact.accn}")
        return input_ids[cache_key]

    raw_ids: dict[tuple[str, str], str] = {}
    raw_values: dict[tuple[str, str], float] = {}
    quarter_rows: dict[str, dict[str, Any]] = {end: {"end": end, "metrics": {}, "yoy": {}, "margins": {}, "margin_change": {}} for end in ends}

    for end in ends:
        for key, label, unit, _sec, kind, _tags in METRICS:
            periods = collected.get(key)
            if periods is None:
                continue
            period = periods.get(end)
            if period is None and key == "total_debt" and all(end in p for p in debt_parts.values()):
                parts = [debt_parts[tag][end] for tag in DEBT_PARTS]
                part_ids = [record(f"{tag}, {ticker} at {end}", part.val, unit, end,
                                   f"SEC EDGAR companyfacts, {part.form}", facts_url, f"us-gaap:{tag}, accn {part.accn}")
                            for tag, part in zip(DEBT_PARTS, parts)]
                total = sum(part.val for part in parts)
                tags_used.setdefault(key, [])
                tags_used[key] += [tag for tag in DEBT_PARTS if tag not in tags_used[key]]
                evidence_id = record(
                    f"{label}, {ticker} at {end} (derived: current + noncurrent long-term debt)", total, unit, end,
                    "SEC EDGAR companyfacts (derived)", facts_url, " + ".join(f"us-gaap:{tag}" for tag in DEBT_PARTS),
                    derived_from=part_ids)
                raw_ids[(key, end)] = evidence_id
                raw_values[(key, end)] = total
                quarter_rows[end]["metrics"][key] = {"id": evidence_id, "value": total, "derived_q4": False,
                                                     "derived_from_parts": list(DEBT_PARTS)}
                continue
            if period is None:
                reason = "Q4 EPS is not derivable (EPS is not additive)" if key == "eps_diluted" else "no value for this period"
                unavailable.append({"metric": f"{key}@{end}", "reason": reason})
                continue
            if period.derived and period.inputs:
                fy_id = record_input(key, period.inputs[0], "fiscal year")
                nine_id = record_input(key, period.inputs[1], "nine months")
                evidence_id = record(
                    f"{label}, {ticker} quarter ended {end} (derived Q4 = fiscal year minus nine months)",
                    period.val, unit, f"{period.start}/{end}",
                    "SEC EDGAR companyfacts (derived: 10-K fiscal year minus 10-Q nine-month YTD)", facts_url,
                    f"us-gaap:{period.tag}, FY accn {period.inputs[0].accn} minus 9M accn {period.inputs[1].accn}",
                    derived_from=[fy_id, nine_id])
            else:
                evidence_id = record(
                    f"{label}, {ticker} {'at' if kind == 'instant' else 'quarter ended'} {end}",
                    period.val, unit, end if kind == "instant" else f"{period.start}/{end}",
                    f"SEC EDGAR companyfacts, {period.form}", facts_url, f"us-gaap:{period.tag}, accn {period.accn}")
            raw_ids[(key, end)] = evidence_id
            raw_values[(key, end)] = period.val
            quarter_rows[end]["metrics"][key] = {"id": evidence_id, "value": period.val, "derived_q4": period.derived}

    def prior_year_end(end: str) -> str | None:
        for candidate in ends:
            if 350 <= _days(end, candidate) <= 380:
                return candidate
        return None

    def quarter_start(end: str) -> str | None:
        for key in ("revenue", "gross_profit", "operating_income", "net_income", "eps_diluted"):
            if end in collected.get(key, {}):
                return collected[key][end].start
        return None

    def derive(fact: str, value: float, unit: str, end: str, formula: str, parents: list[str]) -> dict[str, Any]:
        period = f"{quarter_start(end)}/{end}"
        evidence_id = record(fact, round(value, 6), unit, period, "Derived by fund.py from ledger entries", facts_url,
                             formula, derived_from=parents)
        return {"id": evidence_id, "value": round(value, 6)}

    margin_ids: dict[tuple[str, str], tuple[str, float]] = {}
    for end in ends:
        revenue = raw_values.get(("revenue", end))
        for margin_key, label, numerator in MARGINS:
            value = raw_values.get((numerator, end))
            if value is None or revenue is None:
                continue
            if revenue <= 0:
                unavailable.append({"metric": f"{margin_key}@{end}", "reason": "revenue <= 0; margin undefined"})
                continue
            row = derive(f"{label}, {ticker} quarter ended {end}", value / revenue, "ratio", end,
                         f"{numerator} / revenue", [raw_ids[(numerator, end)], raw_ids[("revenue", end)]])
            quarter_rows[end]["margins"][margin_key] = row
            margin_ids[(margin_key, end)] = (row["id"], row["value"])

    for end in ends:
        prior = prior_year_end(end)
        if prior is None:
            continue
        for key in GROWTH_KEYS:
            current, before = raw_values.get((key, end)), raw_values.get((key, prior))
            if current is None or before is None:
                continue
            if before <= 0:
                unavailable.append({"metric": f"{key}_yoy@{end}", "reason": f"prior-year value {before} is not positive; growth undefined"})
                continue
            label = labels[key][0]
            quarter_rows[end]["yoy"][key] = derive(
                f"{label} growth YoY, {ticker} quarter ended {end} vs {prior}", current / before - 1, "ratio", end,
                "current / prior-year quarter - 1", [raw_ids[(key, end)], raw_ids[(key, prior)]])
        for margin_key, label, _numerator in MARGINS:
            now, then = margin_ids.get((margin_key, end)), margin_ids.get((margin_key, prior))
            if now is None or then is None:
                continue
            quarter_rows[end]["margin_change"][margin_key] = derive(
                f"{label} change YoY, {ticker} quarter ended {end} vs {prior}", now[1] - then[1], "ratio", end,
                "margin - prior-year margin (percentage points as a fraction)", [now[0], then[0]])

    if len(ends) < 5:
        unavailable.append({"metric": "yoy", "reason": f"only {len(ends)} quarters selected; YoY needs a prior-year quarter in the window"})

    data = {
        "ticker": ticker, "cik": cik, "name": name or sub.get("name", ""),
        "sic": sic, "sic_description": sub.get("sicDescription"), "sic_id": sic_id,
        "fiscal_year_end": sub.get("fiscalYearEnd"), "fiscal_year_end_id": fye_id,
        "latest_quarter_end": ends[-1], "as_of": today_text, "max_age_days": max_age, "retrieved_at": retrieved_at, "tags_used": tags_used,
        "peers": peers, "peers_id": peers_id, "sector_etf": etf, "sector_etf_id": etf_id,
        "quarters": [quarter_rows[end] for end in ends], "unavailable": unavailable,
    }
    return run, ids, data


if __name__ == "__main__":
    sys.exit(common.run_cli(main))
