# Stock Desk

**Every number cited. Every claim checked.**

A research desk for small investment teams that runs inside the Slack channel they already use. One message starts
it. Four AI agents split the work, argue it out in a thread, and every figure is checked against an evidence ledger
in code before a verdict reaches the team. Built on [Switch](https://github.com/sandbox-quantum/switch) for the
WeMakeDevs "Flip the Switch" hackathon, **Track 01: Best Business Workflow**.

> ### ▶ Watch a complete run in Slack
>
> **[See Stock Desk run end to end in Slack (video)](https://www.loom.com/share/a064d6c7b1764cb2a510fd8570291bf1)**
>
> One `@desk-chief analyze` message, the agents' debate in the thread, the citation checks, and the verdict card,
> recorded live. This is the fastest way to see how it looks and behaves.

**[Live site](https://karan-patel11.github.io/stock-desk/)** · **[Watch a full Slack run](https://www.loom.com/share/a064d6c7b1764cb2a510fd8570291bf1)** ·
**[Written record of a real run](docs/desk-run-nke-2.md)** · **[Decisions and known limits](docs/DECISIONS.md)**

> Research only, not financial advice. Outlooks are Bullish, Bearish or Neutral. The desk never says buy or sell and
> never gives price targets.

## The problem

A small investment team starts the day with the same chore: pull the latest filings, check the price trend, skim the
news, then argue about it in chat. The numbers get copied by hand from a dozen tabs, the reasoning is lost in the
scroll, and nobody can say later where "revenue down 4%" came from.

AI assistants make this faster and worse at the same time. They write a confident summary in seconds, and some of
its numbers are invented. A team cannot act on research it cannot check.

## The workflow

Stock Desk turns that morning routine into one auditable workflow, run by people and agents together in one Slack
channel.

| Step | Who | What happens | Where the team sees it |
|---|---|---|---|
| 1. Ask | An analyst | Types `@desk-chief analyze NKE` | The channel |
| 2. Set the goal | desk-chief and the analyst | The chief asks: 1–4 weeks, 3–6 months, 1–3 years, or all. The analyst replies `@desk-chief 2` | The run's thread |
| 3. Brief the specialists | desk-chief | One message gives three agents a scoped brief: fundamentals from SEC filings, technicals from prices, sentiment from news | The thread |
| 4. Gather evidence | The three analysts | Each runs one Python tool. The tool writes every fact to an evidence ledger with its source, tier and link (E1, E2 …) | The ledger, on the host machine |
| 5. Check every number | desk-chief, using `verify.py` | Each report is checked line by line against the ledger. A wrong number goes back to the analyst who wrote it, to be corrected or withdrawn | The thread |
| 6. Cross-examine | desk-chief | Up to two rounds of targeted questions, then a precedent check: how the stock moved after past comparable events | The thread |
| 7. Decide | desk-chief, using `confidence.py` | An outlook for each time horizon, with a confidence level set by a fixed rule, not by the model | A verdict card in the channel |
| 8. Keep the record | Switch | The card and the full evidence table are saved as a room document. The next run on the same ticker quotes it | The room's documents |

People stay in charge the whole time. Anyone in the room can type `@desk-chief explain E159` to see where a number
came from, `ask technical: …` to question one analyst, `pause`, or `verdict now`. Any other message posted during a
run is treated as new evidence.

## What the team gets

- **Research they can check.** In the run below, 28 of 28 citations were verified against the ledger, with 54 checks
  logged and none failed. Each fact links to its SEC filing or price history.
- **Mistakes caught before they spread.** In an earlier run the sentiment agent quoted "17%" straight from a headline.
  No tool had measured it, so the verifier failed it and sent it back, and the agent corrected the report.
- **A decision in minutes, not a morning.** The full run, two rounds included, took about 7 minutes.
- **Confidence they can trust.** High confidence needs the key analysts to agree, every citation to pass and at least
  three precedents. Missing data lowers it. The rule is in `tools/confidence.py` and the chief cannot override it.
- **An audit trail.** Every fact, every check and every correction is kept: the evidence ledger, the verification log
  and the saved verdict. Nothing is overwritten.
- **Honest gaps.** When a source fails, the desk says "no data" and lowers confidence. When news was refused during the
  run below, long-term confidence dropped to low instead of the desk guessing a mood.

## A real run: NKE, 7 November 2026

| | |
|---|---|
| Goal | Medium term (3–6 months) |
| Verdict | **Bearish, confidence high.** Revenue fell 4.3259% year over year (SEC filing, tier T1) [E159]. The close of 38.59 is below the 200-day average of 45.41 (price data, tier T2) [E165, E167]. After 5 past comparable reports, NKE trailed its sector by 0.085416 over 90 sessions [E366] |
| Other horizons | Short term (1–4 weeks): Neutral, high. Long term (1–3 years): Neutral, low (sentiment: no data) |
| Citations verified | 28/28 |
| Evidence entries | 369, each with source, tier, link and retrieval time |
| Time | About 7 minutes |

**▶ [Watch this kind of run in Slack, start to finish (video)](https://www.loom.com/share/a064d6c7b1764cb2a510fd8570291bf1)**

The full thread, the checks and what went wrong are in [`docs/desk-run-nke-2.md`](docs/desk-run-nke-2.md).

## Why it runs on Switch

Switch is not a wrapper here; the workflow is made of it.

- **Routing by mention.** `@desk-chief` wakes exactly one agent. The chief briefs three analysts in one message, and
  each reply wakes the chief again. Analysts answer only the chief.
- **One thread per run.** Reports, challenges, corrections and round two stay in the run's thread. Only the verdict
  card is posted to the channel.
- **Memory in room documents.** Each verdict is saved in the room. The next run on the same ticker finds it and quotes
  it first, so the team sees how the view changed.
- **Shared rules.** The room's instructions reach every agent that joins: cite every number, no advice, two rounds.
- **Operable from chat.** `!reset`, `!list-documents` and aliases work without leaving Slack.

Without the room there is no desk: no routing between agents, no shared thread, no memory between runs.

## How it is built

```
Slack channel  ->  Switch room  ->  4 Claude Code agents  ->  Python tools  ->  evidence ledger
(the team)         (routing,        desk-chief                fund.py           evidence/<run>/E<n>.json
                    threads,         desk-fundamental          tech.py           verifications.jsonl
                    saved verdicts)  desk-technical            news.py           confidence.json
                                     desk-sentiment            precedent.py
                                                               verify.py, confidence.py, round.py
```

Agents reason and talk. Python does every calculation and writes the evidence the agents cite. `verify.py`,
`confidence.py` and `round.py` (the two-round cap) enforce the rules in code, not in prompts. 281 offline tests cover
them.

## Set it up and use it

Want to see it first? [Watch a full Slack run](https://www.loom.com/share/a064d6c7b1764cb2a510fd8570291bf1).
To run it yourself, plan for about 10 minutes plus the Slack connection.

**You need**

- Python 3.11 or newer
- [Switch Console](https://github.com/sandbox-quantum/switch) (it runs on macOS; Windows and Linux builds are early access)
- A Slack workspace you can add an app to. No Slack? Switch's built-in Mattermost (needs Docker) is the documented fallback.
- Claude Code installed and signed in, because the four agents run as Claude Code sessions
- A real contact email for SEC's required User-Agent (SEC rejects placeholders, and so do the tools)

**1. Get the code and check it works**

```bash
git clone https://github.com/karan-patel11/stock-desk.git && cd stock-desk
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && pytest -q          # 281 tests, offline
cp .env.example .env
```

Open `.env` and set `SEC_USER_AGENT` to `StockDesk Your Name your-real-email@example.com`. Leave `STOCKDESK_HOME`
empty to use this folder. Then run one live call to every data source and read the output:

```bash
scripts/smoke_live.sh NKE
```

**2. Start Switch and connect Slack.** Run a Switch server from Switch Console (**Run a server on this computer**),
then connect your Slack workspace with Switch's Slack guide. Note the connection's **Name**; you will need it next.
Step-by-step with doc references: [Switch and Slack setup](#switch-and-slack-setup) and `docs/stage0.md`.

**3. Load the desk.** Build and load the template:

```bash
python3 scripts/build_template.py
```

In Switch Console, load `switch/desk-team.template.yaml` and fill in the params: `ticker` (for example NKE),
`stockdesk_home` (the absolute path of this folder), `python` (the absolute path of `.venv/bin/python`) and `bridge`
(your Slack connection's name). This creates the four agents and the room.

**4. Check each agent's instructions.** On Switch Console 0.40.1 the `{python}` and `{stockdesk_home}` placeholders
can stay as literal text. Open each desk agent (**Your Agents → the agent → Agent settings**). If its instructions
still contain them, paste the filled-in text and save. The exact command is in
[Switch and Slack setup](#switch-and-slack-setup), step 5. If the agents run commands with a literal `{python}` in them, this is why.

**5. Reset the agents, then run it.** In your Slack channel, send each of these as its own plain message:
`!reset @desk-chief`, `!reset @desk-fundamental`, `!reset @desk-technical`, `!reset @desk-sentiment`. Each replies that
it reset. Then:

```
@desk-chief analyze NKE
```

**Using it**

1. The chief asks for your goal. Reply with `@desk-chief 1` (1–4 weeks), `2` (3–6 months), `3` (1–3 years), or `all`.
   To skip the question, name the goal up front: `@desk-chief analyze NKE medium, focus on debt`.
2. Watch the run's thread: three analyst reports, the chief's citation checks and cross-examination, then the verdict
   card in the channel. A full run takes about 7 minutes.
3. Question anything while it runs:

| Say this | To do this |
|---|---|
| `@desk-chief explain E159` | See where one number came from, its source and tier, and whether it passed |
| `@desk-chief evidence` | Post the full evidence table for the run |
| `@desk-chief ask technical: <question>` | Put a question to one analyst |
| `@desk-chief pause` / `resume` | Hold or continue the run |
| `@desk-chief verdict now` | Skip to the verdict |

4. Find the saved verdict and evidence table in the room's documents. The next run on the same ticker reads it first.

**If something goes wrong**

- **Silence after you mention an agent:** agents wake only on their exact name, and Slack does not autocomplete them on
  free plans. Type the full name, and check for typos.
- **Agents answer only you:** by default each agent answers only its owner. To let teammates use the desk, change
  "Who can talk to your agent" on all four agents (step 7 in [Switch and Slack setup](#switch-and-slack-setup)). Do this
  only in a channel you trust, because anyone who can address the agents can start tool runs on the host machine.
- **Sentiment says "no data":** the news source (GDELT) rate limits hard. Warm its cache before a demo with
  `scripts/warm_demo.sh NKE` (see [Demo day](#demo-day)). The desk will report the gap and lower confidence instead of
  guessing.
- **A ticker is rejected:** `config/news_names.json` needs a common brand name for it, and `--etf` is needed for tickers
  missing from `config/sector_etf.json`. Banks and insurers are not supported yet (see `docs/DECISIONS.md`).

---

# Technical reference

## Horizons

| | Short | Medium | Long |
|---|---|---|---|
| Period | 1–4 weeks | 3–6 months | 1–3 years |
| Evidence emphasized | technical momentum, 14-day news | earnings trend, guidance, 200-day trend, 30-day news | multi-year revenue, margins, debt; 90-day news for structural risks only |
| Precedent window | 5 trading days | 30 and 90 trading days | 250 trading days |
| Analysts that must agree for "high" | technical | fundamental and technical | fundamental |
| Highest confidence | high | high | medium |

The tools run once per analysis with the widest settings (`fund.py --quarters 12`, `tech.py --lookback 2y`,
`news.py --days 90`, `precedent.py --windows 5,30,90,250`). Every horizon reads the same evidence. The goal only picks
which horizon is the headline (`all` means medium).

## Sentiment

Sentiment reports one number: GDELT's average tone over the last 90 days for the company's query, labelled
**"unweighted, tiers not applied"**. It covers every matching article from every outlet, including off-topic ones.
It is not weighted by source and not de-duplicated, and it gives no 14- or 30-day window. So:

- short and medium get `not_measured` from sentiment. This is not a penalty: confidence.py only adds the reason
  "sentiment: not measured for <horizon> (interim mode)". A failed or refused news call is still "no data" and still
  lowers confidence by one level;
- long reads the 90-day tone: at or below -1.0 negative, at or above +1.0 positive, otherwise neutral.

News tone can only lower confidence, never raise it. Tone weighted by source tier was designed but is **deferred**:
it needs a tone for every article, and GDELT does not provide one. Its ToneChart lists only about 29% of articles, in
whole-number tone bins (`docs/DECISIONS.md`, Sentiment). The sentiment agent still cites individual headlines by
evidence ID, and may describe an article only after opening it.

**Research only, not financial advice.** The desk never says buy or sell and never gives price targets.

## What has and has not been verified

| Item | State |
|---|---|
| All tools, ledger, verify, confidence, evidence table, round cap, narrator, template builder | 281 offline tests pass (`pytest`, networking disabled) |
| SEC parsing (`fund.py`) | Tested against **synthetic** fixtures for a fictional company (`tests/fixtures/build_synthetic.py`), not recorded SEC responses |
| Live data (SEC, Yahoo, GDELT) | Every tool passed live on 2026-11-06; SEC, Yahoo, precedent, verify, confidence and evidence table re-run live on 2026-11-07 (GDELT refused that day) |
| Switch template and Slack | Stage 0 and two full NKE desk runs passed on Slack on 2026-11-05 (`docs/stage0-results.md`, `docs/desk-run-nke.md`) |
| New rules in Slack (goal, horizons, confidence tool, card) | One full NKE run on 2026-11-07: 28/28 citations, confidence as computed by `confidence.py`, saved verdict uses T1/T2/unrated (`docs/desk-run-nke-2.md`). Agent instructions were pasted into Switch Console, not loaded from the template |
| Room commands | `explain E159` and `evidence` tested in Slack on 2026-11-07. `ask`, `pause` / `resume` and a mid-run interrupt not yet tested |
| Voice | Not shown working. Wispr Flow dictation needs no code; `scripts/narrator.py` is tested offline only (no Slack token was configured) |

## Setup (about 10 minutes, excluding Slack)

```bash
git clone https://github.com/karan-patel11/stock-desk.git && cd stock-desk
python3 -m venv .venv && source .venv/bin/activate      # Python 3.11+
pip install -r requirements.txt
cp .env.example .env
# edit .env: set SEC_USER_AGENT to "StockDesk Your Name your-real-email@example.com"
# (SEC requires a real contact; the tools refuse the placeholder). Leave STOCKDESK_HOME empty to use this folder.
pytest                                                  # must pass offline
scripts/smoke_live.sh NKE                               # live run of every tool; read the output
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
3. **Stage 0 (optional sanity check).** Load `switch/mention-test.template.yaml` in the Console and pick the
   Slack connection. Pass criteria:
   - [ ] Kickoff wakes s0-chief
   - [ ] s0-chief mentions s0-technical, s0-technical replies, and the reply wakes s0-chief (`MENTION TEST PASSED`)
   - [ ] Everything stays in one thread
   - [ ] You post a message mid-thread and s0-chief reacts to it
   - [ ] A room document created by an agent is still there after a second run (verdict memory depends on this)

   If the first two fail, nothing else matters: fix addressing or the bridge first. Agents wake only on a mention by
   routing name. Slack completes agent names only on a paid plan with user-group permission (Switch's Slack guide);
   otherwise type them in full, because a typo looks like silence.
4. Build and load the desk: `python3 scripts/build_template.py` (it rebuilds the template from `agents/*.md`), then load
   `switch/desk-team.template.yaml` with params
   `ticker`, `stockdesk_home` (absolute path), `python` (the venv interpreter, for example `/abs/path/.venv/bin/python`)
   and `bridge`. The kickoff posts `@desk-chief analyze <ticker>`, so the first run starts as soon as the room exists.
5. **Check each agent's instructions, and fix them if needed.** On our server (Switch Console 0.40.1) the template's
   `{python}` and `{stockdesk_home}` placeholders stayed as literal text inside the agents' instructions, although
   `docs/TEMPLATES.md` says every string is filled in. Open each desk agent in Switch Console (**Your Agents → the agent
   → Agent settings**). If its **Agent instructions** still contain `{python}` or `{stockdesk_home}`, put the filled-in
   text on the clipboard from the repo folder, select all in the box, paste and **Save**. For desk-chief:
   ```bash
   python3 -c 'import sys; t = open(f"agents/{sys.argv[1]}.md").read(); print(t.replace("$STOCKDESK_HOME", sys.argv[2]).replace("$STOCKDESK_PY", sys.argv[3]), end="")' chief "$(pwd)" "$(pwd)/.venv/bin/python" | pbcopy
   ```
   Repeat with `fundamental`, `technical` and `sentiment` in place of `chief`. On Linux, use `xclip -selection
   clipboard` instead of `pbcopy`.
6. In the Slack channel, send each of these as its own plain message (not bulleted, not code-formatted):
   `!reset @desk-chief`, `!reset @desk-fundamental`, `!reset @desk-technical`, `!reset @desk-sentiment`. Each agent
   replies that it reset. Then start a run with `@desk-chief analyze NKE` and answer the goal question with, for
   example, `@desk-chief 2`. `docs/desk-run-nke-2.md` shows a complete run.
7. **Let teammates use it (optional).** Each agent answers only its owner by default (Agent settings, "Who can talk to
   your agent: Me and my agents"). For a team, change that setting on all four desk agents so people in the room can
   address them. Anyone who can address the agents can start tool runs on the host machine, so do this only in a
   channel you trust. The template's room alias makes `@chief` work too; if it is missing, type
   `!set-alias @desk-chief @chief` in the channel.

## Commands

All tools print one JSON object on stdout (`{"ok":true,"run":...,"evidence":[...],"data":{...}}` or
`{"ok":false,"error":...,"detail":...}`, exit 1). Error codes: `no_data`, `source_unavailable`, `bad_input`, `rate_limited`.
`--run` defaults to the current run.

```bash
python tools/round.py start NKE [--goal short|medium|long|all] | goal G | status | next | end
python tools/fund.py NKE [--quarters 12]         # SEC XBRL: revenue, margins, EPS, debt, YoY (derived)
python tools/tech.py NKE [--lookback 2y]         # SMA50/200, cross, RSI(14), ATR(14), volume ratio, 52-week range
python tools/news.py --ticker NKE [--days 90]    # GDELT headlines, average tone, title words (name from config)
python tools/precedent.py NKE --dates 2024-06-27,2024-12-19 [--etf XLY] [--windows 5,30,90,250] [--urls U1,U2]   # example dates; use ones you have verified
python tools/verify.py E12 --value 8.1%          # or --text-file report.txt to scan a whole report
python tools/verify.py E12 --withdraw            # record that the analyst withdrew the claim citing E12
python tools/confidence.py --run RUN --horizon medium --direction bullish --fund bullish --tech neutral --sent no_data
python tools/evidence_table.py --run RUN         # markdown table of every evidence entry, for the verdict doc
python scripts/build_template.py [--check]
```

## In the room

Commands for desk-chief (or `@chief` where the room alias is set), any time during a run:

| Command | What it does |
|---|---|
| `@desk-chief analyze NKE [short\|medium\|long\|all] [, focus on <topic>]` | Start a run; the focus goes to the analyst that owns it |
| `@desk-chief explain E12` | What fact E12 is, its value, source and tier, whether it passed, who cited it |
| `@desk-chief evidence` | The evidence table for the current run |
| `@desk-chief ask technical: <question>` | Forwards the question to that analyst and posts the answer |
| `@desk-chief verdict now` | Skip to the verdict |
| `@desk-chief pause` / `resume` | Hold or continue the run |

Every agent message ends with one line starting with 🔊: a plain-English summary of at most 25 words, with no evidence IDs.

## Voice

Dictate into Slack with Wispr Flow (or any dictation tool); no integration is needed. Add `desk-chief`,
`desk-fundamental`, `desk-technical` and `desk-sentiment` to Wispr's dictionary: agents wake only on their exact name,
so a misspelled name means silence. Where the room alias is set, `@chief` also reaches desk-chief.

### Narrator (optional)

`scripts/narrator.py` reads the desk channel aloud: only the lines that start with 🔊, each once, in posting order, and
only messages posted after it started. It is read-only. It calls only `conversations.history` and
`conversations.replies`, never posts, and never talks to the agents, so it does not bypass Switch.

```bash
# in .env: SLACK_BOT_TOKEN (xoxb-..., scope channels:history; the app must be in the channel) and SLACK_CHANNEL_ID
python3 scripts/narrator.py --dry-run --once     # check the settings: prints instead of speaking
python3 scripts/narrator.py                      # speaks with say (macOS) or espeak (Linux); Ctrl-C to stop
```

If neither `say` nor `espeak` is installed it stops with an error. It polls every 4 seconds (`--interval`) and backs off
when Slack rate limits it. Start it before `@desk-chief analyze`, or within 2 hours of the run's first message
(`--lookback-min`), so it finds the run's thread.

## Demo day

GDELT rate limits hard: on 2026-11-07 it refused this machine for more than two hours after a few requests, and a refused call means sentiment reports no data. Warm the cache
first:

```bash
# in .env: STOCKDESK_CACHE_TTL_HOURS=24   (or STOCKDESK_NEWS_CACHE_TTL=86400)
scripts/warm_demo.sh NKE
```

`warm_demo.sh` starts a throwaway run (the desk starts its own) and makes the sentiment agent's exact call,
`news.py --ticker NKE --days 90`, always fetching fresh. Neither the agent nor the script types the query:
`news.py --ticker` builds it from the fixed name in `config/news_names.json`
(`Nike (earnings OR shares OR guidance) sourcelang:english`), so both produce the same request and hit the same cache
entry. A test fails if the script's call and `agents/sentiment.md` differ. To analyze a ticker that is not in
`config/news_names.json`, add its common brand name first; otherwise `news.py` returns bad_input. If GDELT refuses,
the script exits 1 and leaves the cache as it was; wait at least an hour (refusals keep the block going) and run it
again. A cached answer is disclosed: the sentiment report says "News cached, fetched <time>", and the evidence keeps
the original `retrieved_at`. Clear the variable after the demo.

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
  describe an article it opened. Responses are cached in `cache/` under a hash of the full request URL (so the exact
  query text and `--days`) and reused for an hour. `STOCKDESK_CACHE_TTL_HOURS` (hours) or `STOCKDESK_NEWS_CACHE_TTL`
  (seconds, wins if both are set) changes that; the global `STOCKDESK_CACHE_TTL` does not apply to news. A reused
  response is disclosed: `data.cached` is true, `data.fetched_at` says when it was fetched, and every evidence entry
  keeps that original `retrieved_at`. There is still no stale fallback: an expired entry is
  fetched again, and if GDELT refuses, the tool returns an error.
- `config/peers.json` and `config/sector_etf.json` are small curated lists for demo tickers. An unmapped ticker needs `--etf`.
  Review them before relying on them.

## Verification log

`verify.py` never edits an evidence entry. Every check appends one line to `evidence/<run>/verifications.jsonl`:
`{"id", "claimed", "result": "PASS"|"FAIL"|"WITHDRAWN", "detail", "checked_at"}`. The latest line per evidence ID wins,
so a FAIL followed by a PASS (corrected figure) or WITHDRAWN (claim dropped) counts as corrected.

**Citation pass rate** ("Citations verified: 14/14"): among the evidence IDs with at least one check, leaving out those
whose latest result is WITHDRAWN, the share whose latest result is PASS. An **uncorrected failure** is an ID whose latest
result is FAIL.

## How confidence works

Confidence is a label (low, medium, high) computed by `tools/confidence.py` from fixed rules. No model decides it, and the
chief may not set or change it. There are no percentages.

1. Every horizon starts at **medium**.
2. It drops one level for each of these: an analyst had no data (sentiment "not measured" does not count); the precedent check found fewer than 3 past events for
   that horizon's window; no precedent check was run; a cited number failed verification and was not corrected; the news
   tone points the other way from the outlook (only when the outlook is bullish or bearish).
3. It becomes **high** only if nothing above applied, every checked citation passed, and the analysts that matter most
   for that horizon agree with the outlook: technical for short term, fundamental and technical for medium term,
   fundamental for long term.
4. Long term is capped at **medium**: the desk only has about 3 years of filings and no valuation data.

News tone can only lower confidence, never raise it. The analysts' stances are passed in; precedent counts and the
verification results are read from the run's own ledger.

## Source tiers

Every evidence entry has a `source_tier`, strongest first:

| Tier | Meaning | Written by |
|---|---|---|
| T1 | Regulatory or primary: legally accountable filings (SEC EDGAR) | `fund.py` |
| T2 | Market data: Yahoo Finance via yfinance (unofficial, disclosed). Never called official | `tech.py`, `precedent.py` |
| T3 | News: original reporting with named editors and a public corrections policy | not applied (deferred) |
| T4 | News: mostly syndicated, aggregated or contributor content, or narrow trade press | not applied (deferred) |
| company_statement | Issued by the company itself: used for event dates, never for sentiment | not applied (deferred) |
| excluded | Opinion, promotional, user-generated or auto-generated content, and all social media | not applied (deferred) |
| unrated | Anything not on a list, plus our own curated config (peers, sector ETF) and caller-supplied event dates | several |

A derived entry (growth, margins, ratios, excess returns) takes the **weakest** tier among its inputs. A precedent excess
return is therefore `unrated`, because one input is the event date the sentiment agent read on a web page. News tiers
are not applied (see Sentiment), so every `news.py` entry is `unrated`.

The T3/T4 definitions above are **our curated judgment, not an industry standard**. No news domain lists ship with the
repo while tier weighting is deferred. Entries written before tiers existed have no `source_tier`; they are never
rewritten, and they show as "not recorded".

## Our audit

Checking the fundamental guardrails against live SEC data (2026-11-07), `fund.py --quarters 12` for JPM returned
quarters from 2012 to 2014 as the "latest 12". JPM stopped reporting quarterly `us-gaap:Revenues` after 2014 and
now reports quarterly revenue only as `RevenuesNetOfInterestExpense`, a tag the tool does not read. Nothing flagged
the 12-year-old figures. `fund.py` now checks freshness for each metric: if a metric's latest quarterly value ended
more than 200 days ago (`STOCKDESK_MAX_FUND_AGE_DAYS`), that metric is no_data, marked "stale", and never filled
from annual values. Banks and insurers remain unsupported (`docs/DECISIONS.md`, Known limitations).

## Data sources and disclosures

- **SEC EDGAR** (needs `SEC_USER_AGENT`, under 10 requests per second).
- **Daily prices through yfinance, an unofficial Yahoo Finance client** that can be rate limited or change without notice.
  Stooq was dropped as a fallback because it now requires an API key.
- **GDELT DOC 2.0** is a metadata index of news articles (headlines, URLs, tone), not the articles themselves. It updates
  about every 15 minutes, covers roughly the last 3 months, and allows one request per 5 seconds. The tools space GDELT
  calls at least 6 seconds apart, across processes, cache them, and return `rate_limited` at once on a refusal: retrying
  only lengthens the block (seen live: more than two hours).

This is a hackathon project, not a data product.

## Layout

```
agents/            instruction files, source of truth for the 4 agents (chief max 80 lines, analysts max 60)
switch/            desk-team.skeleton -> desk-team.template.yaml (generated), mention-test.template.yaml
tools/             common fund tech news precedent verify round confidence evidence_table
config/            peers.json sector_etf.json news_names.json
scripts/           build_template.py smoke_live.sh warm_demo.sh narrator.py
docs/              DECISIONS.md, Stage 0 runbook and results, desk run records, site/ (presentation page)
tests/             offline tests and synthetic fixtures
evidence/ cache/   generated, gitignored
```
