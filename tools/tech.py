#!/usr/bin/env python3
"""tech.py TICKER [--lookback 1y] [--run RUN]

Technical facts from daily bars: last close, SMA50, SMA200, latest SMA50/SMA200 cross,
RSI(14), volume vs the prior 20 sessions, 52-week high/low, ATR(14).

Definitions (documented so evidence entries are auditable):
- Prices are RAW (auto_adjust=False), so "last close" equals the quoted price.
- SMA: simple mean of the last N closes.
- RSI(14) and ATR(14): Wilder smoothing, seeded with the simple mean of the first 14 values.
- Volume ratio: latest volume divided by the mean of the 20 sessions BEFORE it.
- 52-week range: highest high and lowest low over the 365 days ending at the last bar.
Metrics that cannot be computed are listed in data.unavailable with the reason.
"""
from __future__ import annotations

import sys
from datetime import date, datetime
from typing import Any, Sequence

import numpy as np
import pandas as pd

import common
from common import ToolError

LOOKBACKS = ("6mo", "1y", "2y", "5y")
SOURCE = "Yahoo Finance via yfinance (unofficial, disclosed): daily bars"


# ---------------- indicators (pure functions) ----------------

def sma(close: pd.Series, window: int) -> pd.Series:
    return close.rolling(window).mean()


def _rsi_value(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else float("nan")
    return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder RSI. First value at position `period`, seeded with simple means."""
    values = close.to_numpy(dtype=float)
    out = np.full(len(values), np.nan)
    if len(values) <= period:
        return pd.Series(out, index=close.index)
    changes = np.diff(values)
    gains = np.where(changes > 0, changes, 0.0)
    losses = np.where(changes < 0, -changes, 0.0)
    avg_gain = gains[:period].mean()
    avg_loss = losses[:period].mean()
    out[period] = _rsi_value(avg_gain, avg_loss)
    for i in range(period, len(changes)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        out[i + 1] = _rsi_value(avg_gain, avg_loss)
    return pd.Series(out, index=close.index)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder ATR. True range starts at the second bar; first ATR is the mean of `period` TRs."""
    h, l, c = (s.to_numpy(dtype=float) for s in (high, low, close))
    out = np.full(len(c), np.nan)
    if len(c) <= period:
        return pd.Series(out, index=close.index)
    tr = np.full(len(c), np.nan)
    for i in range(1, len(c)):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    out[period] = tr[1:period + 1].mean()
    for i in range(period + 1, len(c)):
        out[i] = (out[i - 1] * (period - 1) + tr[i]) / period
    return pd.Series(out, index=close.index)


def latest_cross(fast: pd.Series, slow: pd.Series) -> tuple[str, str] | None:
    """Most recent sign change of fast - slow: ('golden'|'death', date). Exact zeros are skipped."""
    diff = (fast - slow).dropna()
    signs = np.sign(diff.to_numpy(dtype=float))
    last_sign = 0.0
    cross = None
    for position, sign in enumerate(signs):
        if sign == 0:
            continue
        if last_sign != 0 and sign != last_sign:
            cross = ("golden" if sign > 0 else "death", str(diff.index[position]))
        last_sign = sign
    return cross


def volume_ratio(volume: pd.Series, window: int = 20) -> tuple[float, float, float] | None:
    """(latest volume, mean of prior `window` sessions, ratio) or None if not computable."""
    if len(volume) < window + 1:
        return None
    latest = float(volume.iloc[-1])
    average = float(volume.iloc[-(window + 1):-1].mean())
    if average <= 0:
        return None
    return latest, average, latest / average


# ---------------- tool ----------------

def _days_between(a: str, b: str) -> int:
    return (datetime.strptime(a, "%Y-%m-%d") - datetime.strptime(b, "%Y-%m-%d")).days


def main(argv: Sequence[str], today: date | None = None) -> tuple[str | None, list[str], dict[str, Any]]:
    parser = common.ContractParser(prog="tech.py", description="Technical indicators from daily bars.")
    parser.add_argument("ticker")
    parser.add_argument("--lookback", default="1y", help="one of " + ", ".join(LOOKBACKS))
    common.add_run_argument(parser)
    args = parser.parse_args(list(argv))
    ticker = common.normalize_ticker(args.ticker)
    if args.lookback not in LOOKBACKS:
        raise ToolError("bad_input", f"--lookback must be one of {', '.join(LOOKBACKS)}")
    run = common.resolve_run(args.run)

    frame, retrieved_at = common.fetch_prices(ticker, period=args.lookback, auto_adjust=False)
    frame = frame.sort_index()
    bars = len(frame)
    first_date, last_date = str(frame.index[0]), str(frame.index[-1])

    today_text = (today or common.utc_now().date()).isoformat()
    max_stale = int(common.env("STOCKDESK_MAX_STALE_DAYS", "7") or 7)
    age = _days_between(today_text, last_date)
    if age > max_stale:
        raise ToolError("source_unavailable", f"latest bar for {ticker} is {last_date}, {age} days old; refusing stale data")

    close, high, low, volume = frame["Close"], frame["High"], frame["Low"], frame["Volume"]
    url = f"https://finance.yahoo.com/quote/{ticker}/history/"
    base_locator = f"daily bars {first_date}..{last_date}, auto_adjust=False"
    ids: list[str] = []
    metrics: dict[str, dict[str, Any]] = {}
    unavailable: list[dict[str, str]] = []

    def record(key: str, fact: str, value: Any, unit: str, period: str, definition: str,
               derived_from: list[str] | None = None) -> str:
        entry = common.write_evidence(
            run, tool="tech.py", fact=f"{fact} ({ticker})", value=round(common.plain(value), 6) if isinstance(value, (int, float, np.floating, np.integer)) else value,
            unit=unit, period=period, source=SOURCE, url=url,
            locator=f"{base_locator}; {definition}", derived_from=derived_from, retrieved_at=retrieved_at,
            source_tier="T2",
        )
        ids.append(entry["id"])
        metrics[key] = {"id": entry["id"], "value": entry["value"], "unit": unit}
        return entry["id"]

    last_close = float(close.iloc[-1])
    record("last_close", "Last close", last_close, "USD", last_date, "raw close of the latest bar")

    sma_series: dict[int, pd.Series] = {}
    for window in (50, 200):
        key = f"sma{window}"
        if bars < window:
            unavailable.append({"metric": key, "reason": f"need {window} bars, have {bars}"})
            continue
        sma_series[window] = sma(close, window)
        start = str(frame.index[-window])
        record(key, f"SMA{window}", float(sma_series[window].iloc[-1]), "USD", f"{start}/{last_date}",
               f"simple mean of the last {window} closes")

    if 50 in sma_series and 200 in sma_series:
        cross = latest_cross(sma_series[50], sma_series[200])
        derived = [metrics["sma50"]["id"], metrics["sma200"]["id"]]
        if cross is None:
            record("cross", "Latest SMA50/SMA200 cross", "none", "event", f"{first_date}/{last_date}",
                   "no sign change of SMA50-SMA200 inside the available window", derived)
        else:
            kind, cross_date = cross
            direction = "above" if kind == "golden" else "below"
            record("cross", f"Latest SMA50/SMA200 cross ({kind} = SMA50 crossed {direction} SMA200)", kind, "event",
                   cross_date, "last sign change of SMA50-SMA200", derived)
    else:
        unavailable.append({"metric": "cross", "reason": "needs both SMA50 and SMA200"})

    rsi_value = rsi(close, 14).iloc[-1] if bars > 14 else float("nan")
    if np.isfinite(rsi_value):
        record("rsi14", "RSI(14)", float(rsi_value), "index", f"{first_date}/{last_date}",
               "Wilder smoothing, seeded with the mean of the first 14 changes")
    else:
        unavailable.append({"metric": "rsi14", "reason": "not enough bars or no price movement"})

    ratio = volume_ratio(volume, 20)
    if ratio is None:
        unavailable.append({"metric": "volume_ratio", "reason": "need 21 bars with non-zero average volume"})
    else:
        latest_volume, average_volume, value = ratio
        window_start = str(frame.index[-21])
        v_id = record("volume_latest", "Latest volume", latest_volume, "shares", last_date, "volume of the latest bar")
        a_id = record("volume_avg20", "Average volume, prior 20 sessions", average_volume, "shares",
                      f"{window_start}/{str(frame.index[-2])}", "mean volume of the 20 sessions before the latest bar")
        record("volume_ratio", "Volume vs 20-day average", value, "x", last_date,
               "latest volume / mean of the prior 20 sessions", [v_id, a_id])

    if _days_between(last_date, first_date) < 340:
        unavailable.append({"metric": "range_52w", "reason": f"history covers only {_days_between(last_date, first_date)} days"})
    else:
        cutoff = (datetime.strptime(last_date, "%Y-%m-%d") - pd.Timedelta(days=365)).strftime("%Y-%m-%d")
        window = frame[frame.index >= cutoff]
        record("high_52w", "52-week high", float(window["High"].max()), "USD", f"{window.index[0]}/{last_date}",
               "highest daily high in the 365 days ending at the last bar")
        record("low_52w", "52-week low", float(window["Low"].min()), "USD", f"{window.index[0]}/{last_date}",
               "lowest daily low in the 365 days ending at the last bar")

    atr_value = atr(high, low, close, 14).iloc[-1] if bars > 14 else float("nan")
    if np.isfinite(atr_value):
        record("atr14", "ATR(14)", float(atr_value), "USD", f"{first_date}/{last_date}",
               "Wilder smoothing of true range, seeded with the mean of the first 14 true ranges")
    else:
        unavailable.append({"metric": "atr14", "reason": "not enough bars"})

    data = {
        "ticker": ticker, "as_of": last_date, "bars": bars, "lookback": args.lookback,
        "retrieved_at": retrieved_at, "metrics": metrics, "unavailable": unavailable,
    }
    return run, ids, data


if __name__ == "__main__":
    sys.exit(common.run_cli(main))
