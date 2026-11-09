# Decisions

Design decisions for Stock Desk, locked on 2026-11-06 and updated through 2026-11-07. Each section says what is
built, what is deferred and what is not done.

## Rules for every change

1. No number without evidence: every number shown comes from a tool and carries an evidence ID.
2. Fail closed: missing data is an explicit error or "no data", never a guess.
3. Research, not advice: outlooks are Bullish, Bearish or Neutral only. No buy/sell, no price targets, nothing
   "guaranteed". Every verdict ends with "Research only, not financial advice."
4. Switch stays central: agents talk only through the Switch room.
5. Reproducible: no hard-coded paths or secrets; configuration in `.env`.
6. Dependencies: requests, pandas, yfinance, pytest (PyYAML optional). Nothing else without asking.
7. pytest passes with networking disabled.
8. One feature per commit, never squashed.
9. CLI contract: one JSON object on stdout; error codes no_data, source_unavailable, bad_input, rate_limited.

## Evidence and verification (built)

- Every evidence entry has `source_tier`: T1 (SEC) or T2 (yfinance market data, "unofficial, disclosed"). The news
  tiers T3 and T4, and the labels company_statement and excluded, are defined but not applied, because tiered news
  weighting is deferred (see Sentiment). Every news entry is `unrated`. A derived entry takes the weakest tier of its
  inputs (T1 > T2 > T3 > T4 > the rest). Old ledgers are never rewritten.
- Our reading, open to change: the curated peer and sector-ETF config entries in `fund.py`, and the caller-supplied event
  dates in `precedent.py`, are `unrated`. So precedent excess returns are `unrated` too.
- Verification is an append-only log, `evidence/<run>/verifications.jsonl`; the latest record per ID wins. `verify.py E12
  --withdraw` records a withdrawn claim.
- Citation pass rate: IDs with a check, minus withdrawn ones; share whose latest result is PASS.
- `confidence.py` decides confidence by fixed rules (README, "How confidence works"). Sentiment can only lower it.
  Long term is capped at medium. No percentage scores. If precedent was not run, only "no precedent check" applies, not
  also "fewer than 3 events". Medium uses the smaller event count of its 30- and 90-day windows.
- `evidence_table.py` renders the run's ledger for the verdict document.
- GDELT calls are spaced at least 5.5 s apart across processes, cached, and return `rate_limited` on HTTP 429 without
  retrying.

## Sentiment (tier weighting deferred)

- **Tiered, weighted sentiment is deferred: GDELT has no per-article tone (tested; ToneChart lists about 29% of
  articles in integer bins).** The design was tone weighted by source tier (`config/source_tiers.json`, curated,
  editable), a headline-only factor for paywalled outlets, de-duplication of reposts, 14/30/90-day windows, and
  "insufficient_coverage" below a minimum weight. It needs a tone for every article.
- The test (2026-11-07, query `Nike`, 30 days): ArtList JSON has no tone field documented. ToneChart returned 24 integer
  bins (-12 to +11) covering 504 articles. Each bin lists at most 10 articles, with only `title` and `url`: 145 of
  504 were listed. A listed article's tone is its bin, not an exact value.
- A smaller "trusted sources only" version was considered: one ToneChart per tier, with a `domainis:` OR filter,
  combined by tier weight. **Not built:** the one test request for the domain filter was refused (HTTP 429), so
  whether GDELT accepts `domainis:` joined with OR is untested.
- **What runs instead (interim mode):** `news.py` returns one 90-day GDELT average tone over all matching articles,
  labelled "unweighted, tiers not applied". Short and medium get `not_measured`; long reads the tone at -1.0 / +1.0.
  News tone can only lower confidence.
- `not_measured` is not `no_data`. `confidence.py --sent not_measured` gives no penalty and adds the reason
  "sentiment: not measured for <horizon> (interim mode)". `no_data` keeps its -1: that covers a failed or refused news
  call, a missing 90-day tone, and insufficient_coverage. Counting the missing 14- and 30-day windows as `no_data`
  would force short and medium confidence to low on every run, so they are `not_measured`. High never depended on
  sentiment.

## Horizons and output (built)

- Fixed horizons: short (1–4 weeks), medium (3–6 months), long (1–3 years). Tools run once with the widest settings
  (12 quarters, 2y, 90 days, precedent windows 5/30/90/250); every horizon reads the same evidence.
  `precedent.py` accepts windows up to 250 sessions.
- `round.py` stores the goal (`start --goal`, `goal`). With no goal, next_action says to ask. The goal picks the
  headline horizon (all: medium) and where round-2 questions focus; all three horizons are always computed.
- desk-chief asks the goal question in fixed wording, sends one scope line per analyst, takes direction per horizon
  from cited evidence, and takes confidence only from `confidence.py`.
- Fixed verdict card format, three layers: card in the channel, debate in the thread, evidence table in the verdict
  document. Posting the card as a new top-level message relies on what the 2026-11-05 desk run showed (the chief
  started a top-level message); the Switch docs do not describe it.
- Every agent message ends with one "🔊 " plain-English line of at most 25 words. In the card it comes just before the
  disclaimer, as the card format shows.
- Room alias `chief` for desk-chief, from the documented room `aliases:` field. Not yet seen working in Slack.

## Narrator (built)

- `scripts/narrator.py`: read-only Slack listener that speaks "🔊 " lines locally with `say` or `espeak`. It may call
  only conversations.history and conversations.replies; it never posts and never talks to agents.
- Speaks only messages posted after it started, each line once. It finds thread parents up to 120 minutes back.
- SLACK_BOT_TOKEN and SLACK_CHANNEL_ID come from `.env`. Tests use hand-written fixtures in Slack's documented
  response shape, because no real responses were recorded.

## Known limitations

- **Banks and insurers are unsupported.** Their quarterly revenue uses tags `fund.py` does not read (JPM:
  `RevenuesNetOfInterestExpense`), so the freshness check returns revenue as no_data. Any other metric that is
  still fresh (JPM: net income, EPS) is still reported.
- **No partial-bar detection.** A bar from a session still trading can appear as the "last close". Run the desk
  outside US market hours.
- **No fiscal-quarter labels.** Quarters are named by their end date, not "Q1 FY27".
- **A derived Q4 may combine filings from different dates:** the fiscal year from the latest 10-K minus the nine
  months from an earlier 10-Q. Both inputs are cited.
- **Amended filings (10-K/A, 10-Q/A) are ignored**, so a restatement filed only as an amendment is missed.
- **EPS can show stale for a few weeks after the 10-K (no Q4 EPS).** After the annual filing the latest EPS is Q3's,
  and it can pass the 200-day freshness limit before the next 10-Q (for NKE: mid-September to early October).
- **Sentiment is unweighted.** No source tiers, no de-duplication, off-topic articles included (see Sentiment above).
  `news.py` returns no status per window and has no 14d/30d/90d windows or coverage threshold; the `not_measured`
  stances come from the sentiment agent's instructions, not from the tool.
- **Minor RSI/ATR drift from Wilder seeding:** the values move slightly with the lookback (ATR(14) for NKE: 1.241715
  on 1 year of bars, 1.241751 on 2 years).

## Not built

- A separate research mode or second chat.
- Per-user view preferences.
- Social media (X) ingestion. Future work: a social post would count only if a T3 outlet reports the same event within
  48 hours.
- Backtesting past verdicts.
- The Wispr Flow API (voice input is plain dictation into Slack).
- Percentage confidence scores.
- Any buy/sell or "good to buy" wording.
