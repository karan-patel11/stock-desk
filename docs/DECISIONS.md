# Decisions

Locked on 2026-11-06 (change prompt for the 2026-11-07 submission). Status says what is built.

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

## Evidence and verification (Phase 1, built)

- Every evidence entry has `source_tier`: T1 (SEC), T2 (yfinance market data, "unofficial, disclosed"), T3, T4,
  company_statement, excluded, unrated (news). A derived entry takes the weakest tier of its inputs (T1 > T2 > T3 > T4 >
  the rest). Old ledgers are never rewritten.
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

## Sentiment (Phase 2, blocked)

- Weighted news tone by source tier (`config/source_tiers.json`, curated, editable), headline-only factor for paywalled
  outlets, de-duplication of reposts, 14/30/90-day windows, "insufficient_coverage" below a minimum weight.
- Blocked until a live GDELT check shows per-article tone exists. If it does not, news.py keeps its current output,
  labelled "unweighted, tiers not applied", and the fallback is decided by the project owner.

## Horizons and output (Phase 3, built)

- Fixed horizons: short (1–4 weeks), medium (3–6 months), long (1–3 years). Tools run once with the widest settings
  (12 quarters, 2y, 90 days, precedent windows 5/30/90/250); every horizon reads the same evidence.
  `precedent.py` now accepts windows up to 250 sessions.
- `round.py` stores the goal (`start --goal`, `goal`). With no goal, next_action says to ask. The goal picks the
  headline horizon (all: medium) and where round-2 questions focus; all three horizons are always computed.
- desk-chief asks the goal question in fixed wording, sends one scope line per analyst, takes direction per horizon
  from cited evidence, and takes confidence only from `confidence.py`.
- Fixed verdict card format, three layers: card in the channel, debate in the thread, evidence table in the verdict
  document. Posting the card as a new top-level message relies on what the 2026-11-05 desk run showed (the chief
  started a top-level message); the Switch docs do not describe it.
- Every agent message ends with one "🔊 " plain-English line of at most 25 words. In the card it comes just before the
  disclaimer, as the card format shows.
- Interim sentiment (until Phase 2): one 90-day tone labelled "unweighted, tiers not applied"; short and medium are
  insufficient_coverage (so no_data for confidence); long reads the 90-day tone at -1.0 / +1.0.
- Room alias `chief` for desk-chief, from the documented room `aliases:` field. Not yet seen working in Slack.

## Narrator (Phase 4, built)

- `scripts/narrator.py`: read-only Slack listener that speaks "🔊 " lines locally with `say` or `espeak`. It may call
  only conversations.history and conversations.replies; it never posts and never talks to agents.
- Speaks only messages posted after it started, each line once. It finds thread parents up to 120 minutes back.
- SLACK_BOT_TOKEN and SLACK_CHANNEL_ID come from `.env`. Tests use hand-written fixtures in Slack's documented
  response shape, because no real responses were recorded.

## CUT: not built

- A separate research mode or second chat.
- Per-user view preferences.
- Social media (X) ingestion. Future work: a social post would count only if a T3 outlet reports the same event within
  48 hours.
- Backtesting past verdicts.
- The Wispr Flow API (voice input is plain dictation into Slack).
- Percentage confidence scores.
- Any buy/sell or "good to buy" wording.
