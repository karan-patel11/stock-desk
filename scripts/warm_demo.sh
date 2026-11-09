#!/usr/bin/env bash
# Warms the news cache for a demo with the exact call the sentiment agent makes (agents/sentiment.md, JOB 1 step 2).
# Usage: scripts/warm_demo.sh TICKER      for example: scripts/warm_demo.sh NKE
# news.py --ticker builds the query from config/news_names.json, so this and the agent produce the same request text
# and the same cache entry. Set STOCKDESK_CACHE_TTL_HOURS=24 in .env first, or the warm cache lasts one hour.
# tests/test_agents_and_template.py fails if the news.py call below and the one in agents/sentiment.md differ.
set -u
cd "$(dirname "$0")/.."
if [ $# -ne 1 ] || [ -z "$1" ]; then
  cat >&2 <<'USAGE'
usage: scripts/warm_demo.sh TICKER      for example: scripts/warm_demo.sh NKE
The company name comes from config/news_names.json, the same place the sentiment agent's call reads it.
USAGE
  exit 2
fi
TICKER="$1"
if [ -n "${PYTHON:-}" ]; then PY="$PYTHON"; elif [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY=python3; fi

TTL="$("$PY" -c 'import sys; sys.path.insert(0, "src"); from stockdesk import news; print(int(news.news_cache_ttl()))')" || exit 1
echo "news cache TTL for the demo: ${TTL}s"
if [ "$TTL" -le 3600 ]; then echo "warning: set STOCKDESK_CACHE_TTL_HOURS=24 in .env or this cache expires in an hour" >&2; fi

START="$("$PY" tools/round.py start "$TICKER")" || { echo "$START"; exit 1; }
RUN="$(echo "$START" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["run"])')" || exit 1
echo "warm-up run: $RUN (throwaway; the desk starts its own)"

# STOCKDESK_NEWS_CACHE_TTL=1 for this call only: always fetch fresh, so an older entry is replaced, not reused.
# If GDELT refuses, the tool errors and any older cache entry is left as it was.
OUT="$(STOCKDESK_NEWS_CACHE_TTL=1 "$PY" tools/news.py --ticker "$TICKER" --days 90 --run "$RUN")"
STATUS=$?
"$PY" tools/round.py end --run "$RUN" >/dev/null 2>&1 || true
echo "$OUT" | "$PY" -c '
import json, sys
d = json.loads(sys.stdin.read())
if not d.get("ok"):
    hint = " (wait a few minutes; GDELT blocks for a while after refusals)" if d.get("error") == "rate_limited" else ""
    print("FAIL %s: %s%s" % (d.get("error"), d.get("detail"), hint)); sys.exit(1)
data = d["data"]
print("ok  query=%r  articles=%d  fetched_at=%s  cached=%s" % (
    data["query"], len(data["articles"]), data["fetched_at"], data["cached"]))
print("unavailable: %s" % json.dumps(data["unavailable"]))' || exit 1
exit $STATUS
