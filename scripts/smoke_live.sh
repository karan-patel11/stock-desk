#!/usr/bin/env bash
# Runs every data tool once against LIVE sources and prints a one-line summary per tool.
# Usage: scripts/smoke_live.sh [TICKER] ["Company name"] [event-dates-comma-separated]
# Needs: pip install -r requirements.txt, and SEC_USER_AGENT set in .env (your real contact email).
# Precedent is skipped unless you pass event dates you have verified from an opened source.
set -u
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"
EVHOME="${STOCKDESK_HOME:-$(pwd)}"
TICKER="${1:-NKE}"
NAME="${2:-Nike}"
DATES="${3:-}"

summarize() {  # reads one JSON object on stdin
  "$PY" -c '
import json, sys
raw = sys.stdin.read()
try:
    d = json.loads(raw)
except Exception:
    print("NOT JSON:", raw[:200].replace("\n", " ")); sys.exit(1)
if d.get("ok"):
    data = d.get("data", {})
    gaps = data.get("unavailable") or []
    print("ok  evidence=%d  unavailable=%s" % (len(d.get("evidence", [])), json.dumps(gaps)[:300]))
else:
    print("FAIL %s: %s" % (d.get("error"), d.get("detail")))
    sys.exit(1)'
}

echo "== round.py start $TICKER"
START="$("$PY" tools/round.py start "$TICKER")"; echo "$START" | summarize || exit 1
RUN="$(echo "$START" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["run"])')"
echo "run: $RUN"
FAILED=0
run_tool() {
  echo "== $*"
  "$PY" "$@" --run "$RUN" | summarize || FAILED=1
}
run_tool tools/fund.py "$TICKER" --quarters 12
run_tool tools/tech.py "$TICKER" --lookback 2y
run_tool tools/news.py "$NAME" --days 30
if [ -n "$DATES" ]; then run_tool tools/precedent.py "$TICKER" --dates "$DATES" --windows 5,30,90,250; else echo "== precedent.py skipped (pass verified event dates as the 3rd argument)"; fi
echo "== verify.py (E1 must exist and match itself)"
VAL="$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["value"])' "$EVHOME/evidence/$RUN/E1.json" 2>/dev/null || true)"
if [ -n "$VAL" ]; then "$PY" tools/verify.py E1 --value "$VAL" --run "$RUN" | summarize || FAILED=1; fi
"$PY" tools/round.py end --run "$RUN" >/dev/null 2>&1 || true
echo "Evidence files: $EVHOME/evidence/$RUN/  (open a few and check the url and locator fields by hand)"
exit $FAILED
