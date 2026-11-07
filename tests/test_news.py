from __future__ import annotations

import json
from datetime import timedelta

import pytest
import requests

import common
import news
from common import ToolError

RATE_TEXT = "Please limit requests to one every 5 seconds or contact kalev.leetaru5@gmail.com for assistance."


class Resp:
    def __init__(self, text, status=200):
        self.text, self.status_code, self.headers = text, status, {}


def article(n, title, url=None, seen=None, domain="example.com"):
    return {"url": url or f"https://{domain}/story-{n}", "title": title,
            "seendate": seen or f"2026110{n}T120000Z", "domain": domain, "language": "English",
            "sourcecountry": "United States"}


ARTICLES = [
    article(4, "Acme earnings beat estimates as tariffs weigh"),
    article(3, "Acme tariffs hit margins, analysts say"),
    article(3, "Duplicate url should be dropped", url="https://example.com/story-3"),
    {"url": "https://example.com/no-title", "title": "", "seendate": "20261102T000000Z"},
    {"url": "ftp://example.com/bad-scheme", "title": "Bad scheme", "seendate": "20261102T000000Z"},
    article(2, "Acme supplier tariffs worry investors"),
]
TONE = {"timeline": [{"series": "Average Tone", "data": [
    {"date": "20261101T000000Z", "value": -1.0}, {"date": "20261102T000000Z", "value": -2.0},
    {"date": "20261103T000000Z", "value": -3.0}]}]}


@pytest.fixture
def gdelt(monkeypatch):
    calls = []
    state = {"articles": json.dumps({"articles": ARTICLES}), "tone": json.dumps(TONE),
             "tone_status": 200, "articles_status": 200}

    def fake_get(url, headers=None, timeout=None):
        calls.append(url)
        if "mode=artlist" in url:
            return Resp(state["articles"], state["articles_status"])
        if "mode=timelinetone" in url:
            return Resp(state["tone"], state["tone_status"])
        return Resp("unexpected", 404)

    monkeypatch.setattr(common, "_requests_get", fake_get)
    return calls, state


def test_happy_path(gdelt, run_id):
    calls, _ = gdelt
    run, ids, data = news.main(["Acme Corp", "--days", "14"])
    assert run == run_id
    titles = [a["title"] for a in data["articles"]]
    assert titles == ["Acme earnings beat estimates as tariffs weigh", "Acme tariffs hit margins, analysts say",
                      "Acme supplier tariffs worry investors"]  # duplicate URL, empty title, bad scheme dropped
    first = common.read_evidence(run, data["articles"][0]["id"])
    assert first["url"] == "https://example.com/story-4" and first["period"] == "2026-11-04"
    assert first["unit"] == "text" and first["tool"] == "news.py"
    tone = common.read_evidence(run, data["average_tone"]["id"])
    assert tone["value"] == -2.0 and tone["period"] == "2026-11-01/2026-11-03"
    kw = data["keywords"]
    assert kw["words"][0] == {"word": "tariffs", "count": 3}   # "acme"/"corp" are query words
    kw_entry = common.read_evidence(run, kw["id"])
    assert kw_entry["derived_from"] == [a["id"] for a in data["articles"]]
    assert data["unavailable"] == []
    assert set(ids) == {a["id"] for a in data["articles"]} | {data["average_tone"]["id"], kw["id"]}
    assert any("timespan=14d" in c for c in calls)


def test_requests_are_paced_for_gdelt(gdelt, run_id, monkeypatch):
    waits = []
    monkeypatch.setattr(common, "_sleep", waits.append)
    news.main(["Acme Corp"])
    assert any(0 < w <= news.GDELT_INTERVAL for w in waits)


def test_second_call_is_served_from_cache(gdelt, run_id):
    calls, _ = gdelt
    _, _, first = news.main(["Acme Corp"])
    count = len(calls)
    _, _, second = news.main(["Acme Corp"])
    assert len(calls) == count
    assert first["from_cache"] is False and second["from_cache"] is True


def test_rate_limit_text_is_an_error_and_never_cached(gdelt, run_id):
    calls, state = gdelt
    state["articles"] = RATE_TEXT
    with pytest.raises(ToolError) as err:
        news.main(["Acme Corp"])
    assert err.value.code == "rate_limited"
    state["articles"] = json.dumps({"articles": ARTICLES})
    _, _, data = news.main(["Acme Corp"])  # would fail if the bad body had been cached
    assert len(data["articles"]) == 3


def test_non_json_body_is_source_unavailable(gdelt, run_id):
    _, state = gdelt
    state["articles"] = "<html>gateway</html>"
    with pytest.raises(ToolError) as err:
        news.main(["Acme Corp"])
    assert err.value.code == "source_unavailable"


@pytest.mark.parametrize("body", ["", "{}", json.dumps({"articles": []})])
def test_no_articles_is_no_data(gdelt, run_id, body):
    _, state = gdelt
    state["articles"] = body
    with pytest.raises(ToolError) as err:
        news.main(["Acme Corp"])
    assert err.value.code == "no_data"


def test_unexpected_tone_shape_is_listed_not_guessed(gdelt, run_id):
    _, state = gdelt
    state["tone"] = json.dumps({"timeline": []})
    _, _, data = news.main(["Acme Corp"])
    assert data["average_tone"] is None
    assert data["unavailable"][0]["metric"] == "average_tone"
    assert len(data["articles"]) == 3


def test_tone_request_failure_keeps_articles(gdelt, run_id):
    _, state = gdelt
    state["tone_status"] = 429
    _, _, data = news.main(["Acme Corp"])
    assert data["average_tone"] is None
    assert data["unavailable"][0]["reason"].startswith("rate_limited")


def test_no_repeated_words_means_keywords_unavailable(gdelt, run_id):
    _, state = gdelt
    state["articles"] = json.dumps({"articles": [article(4, "Alpha beta gamma"), article(3, "Delta epsilon zeta")]})
    _, _, data = news.main(["Acme Corp"])
    assert data["keywords"] is None
    assert {u["metric"] for u in data["unavailable"]} == {"keywords"}


def test_article_cap(gdelt, run_id):
    _, state = gdelt
    many = [article(1, f"Story number {i} about widgets", url=f"https://example.com/s{i}") for i in range(30)]
    state["articles"] = json.dumps({"articles": many})
    _, _, data = news.main(["Acme Corp"])
    assert len(data["articles"]) == news.MAX_ARTICLES


@pytest.mark.parametrize("argv", [["Acme", "--days", "0"], ["Acme", "--days", "91"], ["A"], ["  "]])
def test_bad_input(gdelt, run_id, argv):
    with pytest.raises(ToolError) as err:
        news.main(argv)
    assert err.value.code == "bad_input"


def test_cli_prints_only_json(gdelt, run_id, capsys):
    code = common.run_cli(news.main, ["Acme Corp"])
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert code == 0 and payload["ok"] is True and payload["run"] == run_id
    assert out.count("\n") == 1


def test_network_down_is_source_unavailable(monkeypatch, run_id):
    def down(*a, **k):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(common, "_requests_get", down)
    with pytest.raises(ToolError) as err:
        news.main(["Acme Corp"])
    assert err.value.code == "source_unavailable"


def _age_cache(home, seconds):
    """Make every cached response look `seconds` old."""
    stamp = common.utc_iso(common.utc_now() - timedelta(seconds=seconds))
    for path in (home / "cache").glob("*.json"):
        record = json.loads(path.read_text(encoding="utf-8"))
        record["fetched_at"] = stamp
        path.write_text(json.dumps(record), encoding="utf-8")


def test_news_cache_ttl_default_override_and_global_ignored(gdelt, run_id, monkeypatch):
    seen = []
    real = common.http_get
    monkeypatch.setattr(common, "http_get", lambda *a, **k: (seen.append(k["ttl"]), real(*a, **k))[1])
    monkeypatch.setenv("STOCKDESK_CACHE_TTL", "5")       # the global setting must not reach news
    news.main(["Acme Corp"])
    monkeypatch.setenv("STOCKDESK_NEWS_CACHE_TTL", "86400")
    news.main(["Acme Corp"])
    assert seen == [3600.0, 3600.0, 86400.0, 86400.0]


def test_long_news_ttl_serves_a_warm_cache_and_default_refetches(gdelt, run_id, monkeypatch, _isolated_home):
    calls, _ = gdelt
    news.main(["Acme Corp"])
    warmed = len(calls)
    _age_cache(_isolated_home, 2 * 3600)
    monkeypatch.setenv("STOCKDESK_NEWS_CACHE_TTL", "86400")
    _, _, data = news.main(["Acme Corp"])
    assert len(calls) == warmed and data["articles"]      # served from the 2-hour-old cache
    monkeypatch.delenv("STOCKDESK_NEWS_CACHE_TTL")
    news.main(["Acme Corp"])
    assert len(calls) > warmed                            # default one hour: fetched again


@pytest.mark.parametrize("value", ["abc", "0", "-5", "nan", "inf"])
def test_bad_news_cache_ttl_is_an_error_before_any_request(gdelt, run_id, monkeypatch, value):
    calls, _ = gdelt
    monkeypatch.setenv("STOCKDESK_NEWS_CACHE_TTL", value)
    with pytest.raises(ToolError) as err:
        news.main(["Acme Corp"])
    assert err.value.code == "bad_input" and "STOCKDESK_NEWS_CACHE_TTL" in err.value.detail
    assert calls == []


def test_http_429_is_rate_limited_without_retry(gdelt, run_id):
    calls, state = gdelt
    state["articles_status"] = 429
    with pytest.raises(ToolError) as err:
        news.main(["Acme Corp"])
    assert err.value.code == "rate_limited"
    assert len(calls) == 1  # every refused request restarts GDELT's block, so it is never retried


def test_rate_limit_body_is_not_retried(gdelt, run_id):
    calls, state = gdelt
    state["articles"] = RATE_TEXT
    with pytest.raises(ToolError):
        news.main(["Acme Corp"])
    assert len(calls) == 1


def test_pacing_holds_across_processes(gdelt, run_id, monkeypatch):
    """A second tool process (simulated: in-process memory cleared) still waits for the first one's request."""
    news.main(["Acme Corp"])
    common._last_request.clear()
    waits = []
    monkeypatch.setattr(common, "_sleep", waits.append)
    news.main(["Other Query"])
    assert waits and all(0 < w <= news.GDELT_INTERVAL for w in waits)
    assert news.GDELT_INTERVAL >= 5.5


def test_news_entries_are_unrated_until_tiers_apply(gdelt, run_id):
    run, ids, _ = news.main(["Acme Corp"])
    assert {common.read_evidence(run, i)["source_tier"] for i in ids} == {"unrated"}



def test_cached_response_is_disclosed_with_fetched_at(gdelt, run_id, monkeypatch):
    calls, _ = gdelt
    fresh = news.main(["Acme Corp"])[2]
    assert fresh["cached"] is False and fresh["from_cache"] is False
    assert [r["mode"] for r in fresh["responses"]] == ["artlist", "timelinetone"]
    first_fetch = fresh["fetched_at"]
    count = len(calls)
    later = news.main(["Acme Corp"])[2]
    assert len(calls) == count                                   # no new request
    assert later["cached"] is True and later["fetched_at"] == first_fetch
    assert all(r["cached"] for r in later["responses"])
    for entry_id in [a["id"] for a in later["articles"]]:
        assert common.read_evidence(run_id, entry_id)["retrieved_at"] == first_fetch


def test_partly_cached_still_says_cached(gdelt, run_id):
    calls, state = gdelt
    state["tone_status"] = 500                                   # tone fails, articles get cached
    news.main(["Acme Corp"])
    state["tone_status"] = 200
    data = news.main(["Acme Corp"])[2]
    assert data["cached"] is True and data["from_cache"] is False
    assert {r["mode"]: r["cached"] for r in data["responses"]} == {"artlist": True, "timelinetone": False}


def test_cache_ttl_hours(gdelt, run_id, monkeypatch, _isolated_home):
    monkeypatch.setenv("STOCKDESK_CACHE_TTL_HOURS", "24")
    assert news.news_cache_ttl() == 86400.0
    monkeypatch.setenv("STOCKDESK_NEWS_CACHE_TTL", "600")        # seconds setting wins
    assert news.news_cache_ttl() == 600.0
    monkeypatch.delenv("STOCKDESK_NEWS_CACHE_TTL")
    calls, _ = gdelt
    news.main(["Acme Corp"])
    warmed = len(calls)
    _age_cache(_isolated_home, 20 * 3600)                        # 20 hours old, inside 24 hours
    assert news.main(["Acme Corp"])[2]["cached"] is True and len(calls) == warmed
    for bad in ("0", "-1", "a day", "nan"):
        monkeypatch.setenv("STOCKDESK_CACHE_TTL_HOURS", bad)
        with pytest.raises(ToolError) as err:
            news.news_cache_ttl()
        assert err.value.code == "bad_input"



# ---------------- --ticker: the query is built from config, never typed ----------------

def test_ticker_builds_the_fixed_query(gdelt, run_id):
    calls, _ = gdelt
    _, _, data = news.main(["--ticker", "nke", "--days", "90"])
    assert data["query"] == "Nike (earnings OR shares OR guidance) sourcelang:english"
    assert data["company_name"] == "Nike"
    assert all("query=Nike+%28earnings+OR+shares+OR+guidance%29+sourcelang%3Aenglish" in c for c in calls)
    assert all("timespan=90d" in c for c in calls)


def test_ticker_and_the_same_typed_query_share_one_cache_entry(gdelt, run_id):
    calls, _ = gdelt
    news.main(["--ticker", "NKE", "--days", "90"])
    count = len(calls)
    _, _, typed = news.main(["Nike (earnings OR shares OR guidance) sourcelang:english", "--days", "90"])
    assert len(calls) == count and typed["cached"] is True
    _, _, other = news.main(["NIKE (earnings OR shares OR guidance) sourcelang:english", "--days", "90"])
    assert other["cached"] is False  # any other spelling is a different cache entry


def test_names_are_read_from_config(gdelt, run_id, _isolated_home):
    (_isolated_home / "config" / "news_names.json").write_text(json.dumps({"ZZZ": "Zed Holdings"}))
    _, _, data = news.main(["--ticker", "ZZZ"])
    assert data["query"].startswith("Zed Holdings (earnings")


@pytest.mark.parametrize("names,ticker", [
    ({"NKE": "Nike"}, "ZZZ"),                 # not configured
    ({"NKE": ""}, "NKE"),
    ({"NKE": '"Nike"'}, "NKE"),               # quote marks
    ({"NKE": "Nike  Inc"}, "NKE"),            # double space
])
def test_missing_or_bad_name_is_bad_input(gdelt, run_id, _isolated_home, names, ticker):
    (_isolated_home / "config" / "news_names.json").write_text(json.dumps(names))
    with pytest.raises(ToolError) as err:
        news.main(["--ticker", ticker])
    assert err.value.code == "bad_input"


@pytest.mark.parametrize("argv", [[], ["Nike", "--ticker", "NKE"]])
def test_query_or_ticker_exactly_one(gdelt, run_id, argv):
    with pytest.raises(ToolError) as err:
        news.main(argv)
    assert err.value.code == "bad_input"
