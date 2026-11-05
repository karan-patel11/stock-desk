# Stock Desk

A research desk for small investment teams, built on [Switch](https://github.com/sandbox-quantum/switch) for the
WeMakeDevs "Flip the Switch" hackathon (Track 01, Best Business Workflow).

Type `@desk-chief analyze NKE` in a Slack channel. Three analyst agents (fundamental, technical, sentiment) report with
cited evidence IDs. The chief agent checks every cited number against an evidence ledger, cross-examines the analysts
(two rounds at most), orders a precedent check, and posts a verdict that is saved in the room. Humans can interrupt at any time.

**Research only, not financial advice.** The desk never says buy or sell and never gives price targets.

## How it fits together

```
Slack channel  ->  Switch room  ->  4 Claude Code agents  ->  Python tools  ->  evidence ledger
(humans)           (instructions,   desk-chief                fund tech news     evidence/<run>/E<n>.json
                    saved verdicts)  desk-fundamental          precedent verify
                                     desk-technical            round
                                     desk-sentiment
```

Agents reason and talk. Python does every calculation and writes the evidence the agents cite. `verify.py` and
`round.py` enforce the rules in code (number matching, the two-round cap), not in prompts.

## What has and has not been verified

| Item | State |
|---|---|
| All tools, ledger, verify, round cap, template builder | 138 offline tests pass (`pytest`, networking disabled) |
| SEC parsing (`fund.py`) | Tested against **synthetic** fixtures for a fictional company (`tests/fixtures/build_synthetic.py`), not recorded SEC responses |
| Live data (SEC, Yahoo, GDELT) | **Not run during the build** (the build sandbox had no access). Run `scripts/smoke_live.sh` once and fix surprises before the demo |
| Switch template fields | Taken from the Switch docs quoted in the project context. The `params:` block and `{param}` substitution inside instructions are **unverified**; see the top of `switch/desk-team.skeleton` |
| Slack setup through Switch | **Unverified**, follow Switch's own Slack bridge guide |

## Setup (about 10 minutes, excluding Slack)

```bash
git clone <this repo> && cd stock-desk
python3 -m venv .venv && source .venv/bin/activate      # Python 3.11+
pip install -r requirements.txt
cp .env.example .env
# edit .env: set SEC_USER_AGENT to "StockDesk Your Name your-real-email@example.com"
# (SEC requires a real contact; the tools refuse the placeholder). Leave STOCKDESK_HOME empty to use this folder.
pytest                                                  # must pass offline
scripts/smoke_live.sh NKE Nike                          # live run of every tool; read the output
```

`STOCKDESK_HOME` must be the absolute path of this repo on the machine that runs the agents. All agents share
`evidence/` and `cache/` through it. Dependencies: requests, pandas, yfinance, pytest. (`pyyaml` is optional and only
used by `scripts/build_template.py` to validate YAML.)

## Switch and Slack setup

`docs/stage0.md` is the step-by-step runbook, with every step cited to the Switch docs.

1. Run a Switch server. Fastest for one person: Switch Console's **Run a server on this computer** (Switch docs,
   `getting-started/add-a-server.md`). The agents run on the machine where this repo lives and need the venv above.
   The Switch repository has no Railway template.
2. Connect Slack to Switch with Switch's Slack guide (`deploy/messaging-apps/slack.md`, Socket Mode, no public address
   needed). Slack is the Stage 0 bridge; Docker is not needed for it. Note the **Name** you give the connection: the
   templates' **Messaging app** param asks for it. The built-in Mattermost (needs Docker) is the documented fallback
   only; pick its connection for the same param instead.
3. **Stage 0, do this before anything else.** Load `switch/mention-test.template.yaml` in the Console and pick the
   Slack connection. Pass criteria:
   - [ ] Kickoff wakes s0-chief
   - [ ] s0-chief mentions s0-technical, s0-technical replies, and the reply wakes s0-chief (`MENTION TEST PASSED`)
   - [ ] Everything stays in one thread
   - [ ] You post a message mid-thread and s0-chief reacts to it
   - [ ] A room document created by an agent is still there after a second run (verdict memory depends on this)

   If the first two fail, nothing else matters: fix addressing or the bridge first. Agents wake only on a mention by
   routing name. Slack completes agent names only on a paid plan with user-group permission (Switch's Slack guide);
   otherwise type them in full, because a typo looks like silence.
4. Build and load the desk: `python3 scripts/build_template.py`, then load `switch/desk-team.template.yaml` with params
   `ticker`, `stockdesk_home` (absolute path), `python` (the venv interpreter, for example `/abs/path/.venv/bin/python`)
   and `bridge`. The kickoff posts `@desk-chief analyze <ticker>`.

## Commands

All tools print one JSON object on stdout (`{"ok":true,"run":...,"evidence":[...],"data":{...}}` or
`{"ok":false,"error":...,"detail":...}`, exit 1). Error codes: `no_data`, `source_unavailable`, `bad_input`, `rate_limited`.
`--run` defaults to the current run.

```bash
python tools/round.py start NKE | status | next | end
python tools/fund.py NKE [--quarters 8]          # SEC XBRL: revenue, margins, EPS, debt, YoY (derived)
python tools/tech.py NKE [--lookback 1y]         # SMA50/200, cross, RSI(14), ATR(14), volume ratio, 52-week range
python tools/news.py "Nike" [--days 30]          # GDELT headlines, average tone, repeated title words
python tools/precedent.py NKE --dates 2024-06-27,2024-12-19 [--etf XLY] [--windows 5,30] [--urls U1,U2]   # example dates; use ones you have verified
python tools/verify.py E12 --value 8.1%          # or --text-file report.txt to scan a whole report
python scripts/build_template.py [--check]
```

## Demo day

GDELT often rate limits for minutes at a time, and a refused call means a sentiment error in the thread. Warm the cache
first:

```bash
# in .env: STOCKDESK_NEWS_CACHE_TTL=86400
scripts/warm_demo.sh NKE Nike
```

`warm_demo.sh` starts a throwaway run (the desk starts its own) and runs the sentiment agent's exact `news.py` query,
always fetching fresh; a test fails if the script and `agents/sentiment.md` differ. **The Company argument must be the
brand name in the form the agent searches:** the common brand name with no corporate suffix (Inc, Corp, Ltd, Co),
capitalized as normally written, for example Nike, Apple, Microsoft. The cache matches exact text, so `"Nike Inc"` or
`NIKE` would warm an entry the agent never reads. If you give the desk a company name yourself, write it the same way:
the agent searches a given name as written. If GDELT refuses, the script exits 1 and leaves the cache as it was; wait a
few minutes and run it again. The evidence still records the original `retrieved_at`, so the age of the headlines stays
visible. Clear the variable after the demo.

## Design decisions worth knowing

- **Fail closed.** Missing data is an error or an entry in `data.unavailable`, never a guess. There is no stale-cache fallback
  and no second price source. Stale prices (more than 7 days old, `STOCKDESK_MAX_STALE_DAYS`) are an error.
- **Q4 is derived** as fiscal year minus nine-month YTD, with both inputs written to the ledger and listed in `derived_from`.
  Q4 EPS is never derived. Amended filings (10-K/A, 10-Q/A) are ignored.
- **verify.py** normalizes units (`8.1%`, `2.0 pts`, `1.8x`, `12.4B`). A bare number is compared as written. Default
  tolerance is the rounding the displayed figure implies; `--tol` adds a relative tolerance.
- **Precedent convention**: day 0 is the first session on or after the event, base is the prior close, a window of N is the
  close N sessions after base. Excess return is stock minus sector ETF, both total-return adjusted. Fewer than 3 events sets
  `small_sample`. Every event needs a source URL that the sentiment agent actually opened.
- **News** is headlines only (GDELT, roughly the last 3 months, one request per 5 seconds). The sentiment agent may only
  describe an article it opened. Responses are cached for an hour; `STOCKDESK_NEWS_CACHE_TTL` (seconds) overrides that,
  and the global `STOCKDESK_CACHE_TTL` does not apply to news. There is still no stale fallback: an expired entry is
  fetched again, and if GDELT refuses, the tool returns an error.
- `config/peers.json` and `config/sector_etf.json` are small curated lists for demo tickers. An unmapped ticker needs `--etf`.
  Review them before relying on them.

## Data sources and disclosures

SEC EDGAR (needs `SEC_USER_AGENT`, under 10 requests per second), GDELT DOC 2.0, and daily prices through
**yfinance, an unofficial Yahoo Finance client** that can be rate limited or change without notice. Stooq was dropped as a
fallback because it now requires an API key. This is a hackathon project, not a data product.

## Layout

```
agents/            instruction files, source of truth for the 4 agents (max 60 lines each)
switch/            desk-team.skeleton -> desk-team.template.yaml (generated), mention-test.template.yaml
tools/             common fund tech news precedent verify round
config/            peers.json sector_etf.json
scripts/           build_template.py smoke_live.sh warm_demo.sh
tests/             offline tests and synthetic fixtures
evidence/ cache/   generated, gitignored
```
