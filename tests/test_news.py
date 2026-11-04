from __future__ import annotations

import json

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
    news.main(["Acme Corp"])
    count = len(calls)
    news.main(["Acme Corp"])
    assert len(calls) == count


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
