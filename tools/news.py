#!/usr/bin/env python3
"""news.py "QUERY" [--days 30] [--run RUN]
news.py --ticker TICKER [--days 30] [--run RUN]

With --ticker the query is built here, never typed by an agent: the company name from config/news_names.json
in QUERY_TEMPLATE. The same ticker always gives the same text, so the desk's call and scripts/warm_demo.sh
use the same cache entry. A ticker with no configured name is bad_input.

Recent headlines from the GDELT DOC 2.0 API: up to 20 articles (title, date, domain, URL),
the average tone over the window, and the most repeated words in the titles.

Honest limits, built in:
- GDELT allows one request every 5 seconds, so requests are paced 6 seconds apart (across processes, via a
  locked timestamp file in cache/pace/) and cached for an hour (STOCKDESK_NEWS_CACHE_TTL overrides this;
  STOCKDESK_CACHE_TTL does not apply to news). HTTP 429 or a rate-limit body returns rate_limited at once,
  without retrying: every refused request restarts GDELT's block.
  A 200 response whose body is a rate-limit message is never cached. data.from_cache is true only when
  every GDELT response used came from the cache. data.cached is true when ANY did, data.fetched_at is when the
  oldest response used was fetched, and data.responses lists each request's cached flag and fetched_at.
  Cache: <STOCKDESK_HOME>/cache/<sha256 of "GET " + the full request URL>.json, so the key is the exact query
  text and --days. STOCKDESK_CACHE_TTL_HOURS (hours) sets reuse for news; STOCKDESK_NEWS_CACHE_TTL (seconds) wins.
- GDELT indexes roughly the last 3 months, so --days is capped at 90.
- GDELT returns headlines only. Anyone citing what an article SAYS must open it first.
- Average tone is a second request (timelinetone). If that request fails or has an unexpected
  shape it is listed in data.unavailable; the articles are still returned.
- Keywords are counted locally from the returned titles (no GDELT keyword endpoint is assumed).
"""
from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter
from typing import Any, Sequence

import common
from common import ToolError

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_INTERVAL = 6.0  # GDELT allows 1 request per 5 s; at least 5.5 s is required, kept across processes
GDELT_ATTEMPTS = 3     # retries cover network and 5xx errors only; a rate limit fails at once
GDELT_RATE_LIMIT_WAIT = 15.0
CACHE_TTL = 3600.0
CACHE_TTL_ENV = "STOCKDESK_NEWS_CACHE_TTL"        # seconds; wins when set
CACHE_TTL_HOURS_ENV = "STOCKDESK_CACHE_TTL_HOURS"  # hours; news.py only (other tools: STOCKDESK_CACHE_TTL)
MAX_ARTICLES = 20
SOURCE = "GDELT DOC 2.0"
QUERY_TEMPLATE = "{name} (earnings OR shares OR guidance) sourcelang:english"
NAMES_CONFIG = "news_names.json"
STOPWORDS = frozenset("""
about after again against also amid been before being between both could does doing down during each
from further have having here into just like more most much only other over said says same shares share
should some stock stocks such than that their them then there these they this those through under until
very what when where which while will with would your inc corp company news today year years week
""".split())


def news_cache_ttl() -> float:
    """Seconds a GDELT response is reused: STOCKDESK_NEWS_CACHE_TTL (seconds), else STOCKDESK_CACHE_TTL_HOURS
    (hours), else one hour.

    Kept apart from STOCKDESK_CACHE_TTL on purpose. On demo day, set it high (for example 24 hours)
    and warm the cache with the sentiment agent's exact query. A bad value is an error, not ignored.
    """
    raw = common.env(CACHE_TTL_ENV)
    if not raw:
        hours_raw = common.env(CACHE_TTL_HOURS_ENV)
        if not hours_raw:
            return CACHE_TTL
        try:
            hours = float(hours_raw)
        except ValueError:
            hours = math.nan
        if not math.isfinite(hours) or hours <= 0:
            raise ToolError("bad_input", f"{CACHE_TTL_HOURS_ENV} must be a positive number of hours, got {hours_raw!r}")
        return hours * 3600.0
    try:
        seconds = float(raw)
    except ValueError:
        seconds = math.nan
    if not math.isfinite(seconds) or seconds <= 0:
        raise ToolError("bad_input", f"{CACHE_TTL_ENV} must be a positive number of seconds, got {raw!r}")
    return seconds


def _validate_body(text: str) -> None:
    stripped = text.strip()
    if stripped.lower().startswith("please limit requests"):
        raise ToolError("rate_limited", "GDELT asked for one request every 5 seconds")
    if stripped == "":
        return  # an empty body means no matches; handled by the caller
    try:
        json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ToolError("source_unavailable", f"GDELT returned a non-JSON body: {stripped[:80]!r}") from exc


def _date_from_seen(seendate: str) -> str | None:
    digits = re.match(r"(\d{4})(\d{2})(\d{2})", seendate or "")
    return f"{digits.group(1)}-{digits.group(2)}-{digits.group(3)}" if digits else None


def parse_articles(text: str) -> list[dict[str, str]]:
    body = json.loads(text) if text.strip() else {}
    articles: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in body.get("articles", []) if isinstance(body, dict) else []:
        url, title = str(item.get("url", "")).strip(), str(item.get("title", "")).strip()
        date = _date_from_seen(str(item.get("seendate", "")))
        if not url.startswith(("http://", "https://")) or not title or not date or url in seen:
            continue
        seen.add(url)
        articles.append({
            "title": title, "url": url, "date": date, "domain": str(item.get("domain", "")).strip(),
            "seendate": str(item.get("seendate", "")), "language": str(item.get("language", "")).strip(),
            "country": str(item.get("sourcecountry", "")).strip(),
        })
        if len(articles) == MAX_ARTICLES:
            break
    return articles


def parse_tone(text: str) -> tuple[float, int, str, str]:
    """(mean daily tone, number of points, first date, last date). Raises ValueError on any surprise."""
    body = json.loads(text)
    series = body["timeline"][0]["data"]
    points = [(str(p["date"]), float(p["value"])) for p in series]
    if not points:
        raise ValueError("timeline has no points")
    values = [v for _, v in points]
    first, last = _date_from_seen(points[0][0]), _date_from_seen(points[-1][0])
    if not first or not last:
        raise ValueError("unparseable timeline dates")
    return sum(values) / len(values), len(values), first, last


def top_keywords(titles: list[str], exclude: set[str], limit: int = 10) -> list[tuple[str, int]]:
    counts: Counter[str] = Counter()
    for title in titles:
        words = {w for w in re.findall(r"[a-z]{4,}", title.lower()) if w not in STOPWORDS and w not in exclude}
        counts.update(words)  # each word counts once per title
    ranked = sorted(((w, c) for w, c in counts.items() if c >= 2), key=lambda pair: (-pair[1], pair[0]))
    return ranked[:limit]


def company_name(ticker: str) -> str:
    """The configured news name for a ticker, used verbatim. Missing or malformed: bad_input, never a guess."""
    names = common.load_config(NAMES_CONFIG)
    name = names.get(ticker)
    if not isinstance(name, str) or not name.strip():
        raise ToolError("bad_input", f"no news name for {ticker} in config/{NAMES_CONFIG}; add one before analyzing")
    if name != " ".join(name.split()) or '"' in name or not 2 <= len(name) <= 60:
        raise ToolError("bad_input", f"config/{NAMES_CONFIG}: name for {ticker} must be 2-60 characters, "
                                     "single-spaced, with no quote marks")
    return name


def main(argv: Sequence[str]) -> tuple[str | None, list[str], dict[str, Any]]:
    parser = common.ContractParser(prog="news.py", description="Recent headlines and tone from GDELT.")
    parser.add_argument("query", nargs="?", default=None)
    parser.add_argument("--ticker", default=None, help="build the query from config/news_names.json")
    parser.add_argument("--days", type=int, default=30, help="look-back window, 1-90 days")
    common.add_run_argument(parser)
    args = parser.parse_args(list(argv))
    if (args.query is None) == (args.ticker is None):
        raise ToolError("bad_input", "give exactly one of: QUERY or --ticker TICKER")
    name = None
    if args.ticker is not None:
        name = company_name(common.normalize_ticker(args.ticker))
        query = QUERY_TEMPLATE.format(name=name)
    else:
        query = " ".join(args.query.split())
    if not 2 <= len(query) <= 200:
        raise ToolError("bad_input", "query must be 2-200 characters")
    if not 1 <= args.days <= 90:
        raise ToolError("bad_input", "--days must be between 1 and 90 (GDELT indexes about 3 months)")
    ttl = news_cache_ttl()
    run = common.resolve_run(args.run)

    base = {"query": query, "format": "json", "timespan": f"{args.days}d"}
    articles_result = common.http_get(
        GDELT_URL, params={**base, "mode": "artlist", "maxrecords": MAX_ARTICLES, "sort": "datedesc"},
        ttl=ttl, min_interval=GDELT_INTERVAL, attempts=GDELT_ATTEMPTS,
        rate_limit_wait=GDELT_RATE_LIMIT_WAIT, retry_rate_limited=False, validate=_validate_body)
    articles = parse_articles(articles_result.text)
    if not articles:
        raise ToolError("no_data", f"GDELT returned no articles for {query!r} in the last {args.days} days")
    retrieved_at = articles_result.fetched_at

    ids: list[str] = []
    unavailable: list[dict[str, str]] = []
    article_rows: list[dict[str, str]] = []
    for article in articles:
        entry = common.write_evidence(
            run, tool="news.py", fact=f"News article: {article['title']}", value=article["title"], unit="text",
            period=article["date"], source=f"{SOURCE} (headline from {article['domain'] or 'unknown domain'})",
            url=article["url"],
            locator=f"artlist seendate {article['seendate']}; country {article['country']}; language {article['language']}",
            retrieved_at=retrieved_at, source_tier="unrated")  # tiers not applied yet (Phase 2)
        ids.append(entry["id"])
        article_rows.append({"id": entry["id"], "title": article["title"], "date": article["date"],
                             "domain": article["domain"], "url": article["url"]})

    tone_row = None
    from_cache = [articles_result.from_cache]
    responses = [{"mode": "artlist", "cached": articles_result.from_cache, "fetched_at": articles_result.fetched_at}]
    try:
        tone_result = common.http_get(
            GDELT_URL, params={**base, "mode": "timelinetone"}, ttl=ttl,
            min_interval=GDELT_INTERVAL, attempts=GDELT_ATTEMPTS,
            rate_limit_wait=GDELT_RATE_LIMIT_WAIT, retry_rate_limited=False, validate=_validate_body)
        from_cache.append(tone_result.from_cache)
        responses.append({"mode": "timelinetone", "cached": tone_result.from_cache, "fetched_at": tone_result.fetched_at})
        mean_tone, points, first, last = parse_tone(tone_result.text)
        entry = common.write_evidence(
            run, tool="news.py", fact=f"Average news tone, query {query!r}, last {args.days} days",
            value=round(mean_tone, 4), unit="tone", period=f"{first}/{last}",
            source=f"{SOURCE} timelinetone (mean of {points} daily average-tone points)",
            url=tone_result.url, locator=f"mode=timelinetone, timespan={args.days}d",
            retrieved_at=tone_result.fetched_at, source_tier="unrated")  # GDELT aggregate over all domains
        ids.append(entry["id"])
        tone_row = {"id": entry["id"], "value": entry["value"], "points": points}
    except ToolError as exc:
        unavailable.append({"metric": "average_tone", "reason": f"{exc.code}: {exc.detail}"})
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        unavailable.append({"metric": "average_tone", "reason": f"unexpected timelinetone response ({type(exc).__name__})"})

    query_words = set(re.findall(r"[a-z]{4,}", query.lower()))
    keywords = top_keywords([a["title"] for a in articles], query_words)
    keywords_row = None
    if keywords:
        entry = common.write_evidence(
            run, tool="news.py", fact=f"Most repeated title words, query {query!r} ({len(articles)} headlines)",
            value=", ".join(f"{w}:{c}" for w, c in keywords), unit="word:count",
            period=f"{articles[-1]['date']}/{articles[0]['date']}",
            source="Derived by news.py from the returned headlines", url=articles_result.url,
            locator="words of 4+ letters, once per title, query words and stopwords removed",
            derived_from=[r["id"] for r in article_rows], retrieved_at=retrieved_at)
        ids.append(entry["id"])
        keywords_row = {"id": entry["id"], "words": [{"word": w, "count": c} for w, c in keywords]}
    else:
        unavailable.append({"metric": "keywords", "reason": "no word appears in two or more titles"})

    data = {
        "query": query, "company_name": name, "days": args.days, "retrieved_at": retrieved_at, "articles": article_rows,
        "average_tone": tone_row, "keywords": keywords_row, "unavailable": unavailable,
        "from_cache": all(from_cache),  # true only if every GDELT response used came from the local cache
        "cached": any(from_cache),      # true if ANY response used came from the cache: disclose it
        "fetched_at": min(r["fetched_at"] for r in responses),  # when the oldest response used was fetched
        "responses": responses,
        "note": "GDELT returns headlines only. Open an article before citing what it says.",
    }
    return run, ids, data


if __name__ == "__main__":
    sys.exit(common.run_cli(main))
