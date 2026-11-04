#!/usr/bin/env python3
"""precedent.py TICKER --dates 2023-09-15,2024-03-21 [--etf XLY] [--windows 5,30] [--urls U1,U2] [--run RUN]

For each past event: the stock's return minus its sector ETF's return over each window, then the
mean across events. Uses total-return (adjusted) closes for both.

Convention (stored in every entry's locator so it is auditable):
- day 0 = the first trading session on or after the event date (weekend events roll forward).
- base = the close of the session BEFORE day 0.
- a window of N = the close N sessions after the base, i.e. N sessions starting with day 0.
- sessions are the dates present in BOTH price series.
An event whose window is not fully inside the price history is skipped for that window, with the reason.
small_sample is true when fewer than 3 events could be used. --urls (same order as --dates) are the
opened source pages for each event date; missing ones are reported in data.warnings.
"""
from __future__ import annotations

import sys
from bisect import bisect_left
from datetime import date, datetime, timedelta
from typing import Any, Sequence

import common
from common import ToolError

SOURCE = "Yahoo Finance daily bars via yfinance (unofficial), total-return adjusted (auto_adjust=True)"
MAX_EVENTS = 12
CONVENTION = ("day 0 = first session on/after the event date; base = close of the prior session; "
              "window N = close N sessions after the base; excess = stock return - ETF return")


def parse_list(raw: str, what: str) -> list[str]:
    items = [part.strip() for part in (raw or "").split(",") if part.strip()]
    if not items:
        raise ToolError("bad_input", f"{what} must not be empty")
    return items


def event_returns(stock, etf, event: str, window: int) -> dict[str, Any] | str:
    """Return the window's numbers, or a string explaining why this event/window cannot be used."""
    sessions = sorted(set(stock.index) & set(etf.index))
    day0 = bisect_left(sessions, event)
    if day0 >= len(sessions):
        return "event is after the last available session"
    if (datetime.strptime(sessions[day0], "%Y-%m-%d") - datetime.strptime(event, "%Y-%m-%d")).days > 7:
        return f"no trading session within 7 days after the event (next is {sessions[day0]})"
    base = day0 - 1
    if base < 0:
        return "no session before the event in the price history"
    end = base + window
    if end >= len(sessions):
        return f"window of {window} sessions is not complete in the price history"
    base_date, end_date = sessions[base], sessions[end]
    s0, s1 = float(stock.loc[base_date]), float(stock.loc[end_date])
    e0, e1 = float(etf.loc[base_date]), float(etf.loc[end_date])
    if s0 <= 0 or e0 <= 0:
        return "non-positive base price"
    stock_ret, etf_ret = s1 / s0 - 1, e1 / e0 - 1
    return {"day0": sessions[day0], "base_date": base_date, "end_date": end_date,
            "stock_return": stock_ret, "etf_return": etf_ret, "excess": stock_ret - etf_ret}


def main(argv: Sequence[str], today: date | None = None) -> tuple[str | None, list[str], dict[str, Any]]:
    parser = common.ContractParser(prog="precedent.py", description="Excess returns after past events.")
    parser.add_argument("ticker")
    parser.add_argument("--dates", required=True, help="comma-separated event dates, YYYY-MM-DD")
    parser.add_argument("--etf", default=None, help="sector ETF ticker (default: config/sector_etf.json)")
    parser.add_argument("--windows", default="5,30", help="comma-separated window lengths in sessions")
    parser.add_argument("--urls", default=None, help="comma-separated source URLs, same order as --dates")
    common.add_run_argument(parser)
    args = parser.parse_args(list(argv))
    ticker = common.normalize_ticker(args.ticker)
    run = common.resolve_run(args.run)
    today_text = (today or common.utc_now().date()).isoformat()

    dates = [common.parse_date(d) for d in parse_list(args.dates, "--dates")]
    if len(set(dates)) != len(dates):
        raise ToolError("bad_input", "--dates contains duplicates")
    if len(dates) > MAX_EVENTS:
        raise ToolError("bad_input", f"at most {MAX_EVENTS} events")
    if any(d > today_text for d in dates):
        raise ToolError("bad_input", "an event date is in the future")
    urls: list[str | None] = [None] * len(dates)
    if args.urls is not None:
        urls = parse_list(args.urls, "--urls")
        if len(urls) != len(dates):
            raise ToolError("bad_input", "--urls must have the same number of entries as --dates")
        if any(not u.startswith(("http://", "https://")) for u in urls):
            raise ToolError("bad_input", "every --urls entry must start with http:// or https://")
    try:
        windows = sorted({int(w) for w in parse_list(args.windows, "--windows")})
    except ValueError as exc:
        raise ToolError("bad_input", "--windows must be integers") from exc
    if any(not 1 <= w <= 120 for w in windows):
        raise ToolError("bad_input", "each window must be between 1 and 120 sessions")

    etf = (args.etf or (common.load_config("sector_etf.json").get("overrides") or {}).get(ticker) or "").strip().upper()
    if not etf:
        raise ToolError("bad_input", f"no ETF mapping for {ticker}; pass --etf (for example --etf XLY)")
    etf = common.normalize_ticker(etf)

    pairs = sorted(zip(dates, urls))
    start = (datetime.strptime(pairs[0][0], "%Y-%m-%d") - timedelta(days=14)).strftime("%Y-%m-%d")
    stock_frame, stock_at = common.fetch_prices(ticker, start=start, auto_adjust=True)
    etf_frame, etf_at = common.fetch_prices(etf, start=start, auto_adjust=True)
    stock_close, etf_close = stock_frame["Close"], etf_frame["Close"]
    retrieved_at = min(stock_at, etf_at)
    history = f"https://finance.yahoo.com/quote/{ticker}/history/"

    ids: list[str] = []
    warnings: list[str] = []
    events_out: list[dict[str, Any]] = []
    excess_by_window: dict[int, list[tuple[str, float]]] = {w: [] for w in windows}
    used_events: set[str] = set()

    def record(fact: str, value: Any, unit: str, period: str, source: str, url: str, locator: str,
               derived_from: list[str] | None = None) -> str:
        entry = common.write_evidence(run, tool="precedent.py", fact=fact, value=value, unit=unit, period=period,
                                      source=source, url=url, locator=locator, derived_from=derived_from,
                                      retrieved_at=retrieved_at)
        ids.append(entry["id"])
        return entry["id"]

    for event, url in pairs:
        if url is None:
            warnings.append(f"no source URL supplied for event {event}; the chief must not present it as sourced")
        event_id = record(f"Precedent event date for {ticker}", event, "date", event,
                          "Supplied by the caller from an opened source" if url else "Supplied by the caller (no source URL)",
                          url or "none supplied", "event date as given to precedent.py")
        row: dict[str, Any] = {"date": event, "id": event_id, "url": url, "windows": {}, "skipped": {}}
        for window in windows:
            result = event_returns(stock_close, etf_close, event, window)
            if isinstance(result, str):
                row["skipped"][str(window)] = result
                continue
            locator = f"{CONVENTION}; day0 {result['day0']}"
            period = f"{result['base_date']}/{result['end_date']}"
            s_id = record(f"{ticker} return, {window} sessions after {event}", round(result["stock_return"], 6),
                          "ratio", period, SOURCE, history, locator)
            e_id = record(f"{etf} return, {window} sessions after {event}", round(result["etf_return"], 6),
                          "ratio", period, SOURCE, f"https://finance.yahoo.com/quote/{etf}/history/", locator)
            x_id = record(f"Excess return of {ticker} vs {etf}, {window} sessions after {event}",
                          round(result["excess"], 6), "ratio", period, "Derived by precedent.py from ledger entries",
                          history, f"{locator}; excess = stock return - ETF return", derived_from=[s_id, e_id, event_id])
            row["windows"][str(window)] = {
                "stock_return": {"id": s_id, "value": round(result["stock_return"], 6)},
                "etf_return": {"id": e_id, "value": round(result["etf_return"], 6)},
                "excess": {"id": x_id, "value": round(result["excess"], 6)},
            }
            excess_by_window[window].append((x_id, result["excess"]))
            used_events.add(event)
        events_out.append(row)

    summary: dict[str, Any] = {}
    for window, items in excess_by_window.items():
        if not items:
            summary[str(window)] = {"n": 0, "mean_excess": None, "small_sample": True}
            warnings.append(f"no usable events for the {window}-session window")
            continue
        mean = sum(v for _, v in items) / len(items)
        parents = [i for i, _ in items]
        small = len(items) < 3
        mean_id = record(f"Mean excess return of {ticker} vs {etf}, {window} sessions, {len(items)} events"
                         + (" (small sample)" if small else ""), round(mean, 6), "ratio",
                         f"{pairs[0][0]}/{pairs[-1][0]}", "Derived by precedent.py from ledger entries", history,
                         "arithmetic mean of the excess returns", derived_from=parents)
        n_id = record(f"Events used, {window}-session window, {ticker}", len(items), "count",
                      f"{pairs[0][0]}/{pairs[-1][0]}", "Derived by precedent.py from ledger entries", history,
                      "count of events with a complete window", derived_from=parents)
        summary[str(window)] = {"n": len(items), "n_id": n_id, "small_sample": small,
                                "mean_excess": {"id": mean_id, "value": round(mean, 6)}}

    data = {
        "ticker": ticker, "etf": etf, "windows": windows, "convention": CONVENTION, "events": events_out,
        "summary": summary, "n_events_used": len(used_events), "small_sample": len(used_events) < 3,
        "warnings": warnings, "retrieved_at": retrieved_at,
    }
    return run, ids, data


if __name__ == "__main__":
    sys.exit(common.run_cli(main))
