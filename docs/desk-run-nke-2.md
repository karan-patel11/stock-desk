# Desk run under the new rules: NKE, medium-term goal

Run `r-20261107-05`, 2026-11-07 04:31 to 04:38 UTC (2026-11-06 23:31 to 23:38 EST), room `desk-NKE` (`#desk-nke` in
Slack), the same local Switch server and Slack connection as `docs/desk-run-nke.md`. Started by the user posting
`@desk-chief analyze NKE` in the channel. Evidence below is the Slack thread the user pasted, plus checks I ran on the
local ledger (`evidence/r-20261107-05/`).

## Setup before the run

- The four desk agents kept their names. Their instructions were replaced in Switch Console (Agent settings, Agent
  instructions, Save) with `agents/*.md`, with the repo path and Python interpreter written in. The agents created
  from the 2026-11-05 template still had `{python}` and `{stockdesk_home}` as literal text in their instructions: the
  template's placeholders were not filled in for agent instructions, although `docs/TEMPLATES.md` says any string is.
- Each agent was reset with `!reset @<agent>`, sent as four separate plain messages. A first try sent all four as one
  bulleted, code-formatted message; Slack did not treat that as commands.
- The room's own instructions and its `desk-rules` document were not changed and still have the 2026-11-05 text. The
  `chief` alias was not set.
- The news cache was not warmed: GDELT refused the warm-up at 04:29 UTC (HTTP 429).

## Result: the run completed and closed

| Check | Result | Evidence |
|---|---|---|
| Goal question | PASS | The chief posted the exact goal question; the reply `@desk-chief 2` set goal medium (`state.json` history: start, goal medium, round 2, stop, end) |
| Round 1 scope lines | PASS | One message to all three analysts, each with Scope, Period, Focus and Goal |
| Analyst reports in the new format | PASS | Scope echo on the first line, `Stance: short=… · medium=… · long=…`, and a 🔊 line on every message |
| Verification | PASS | `verifications.jsonl`: 54 checks, all PASS; citation pass rate 28/28, none uncorrected |
| Advice-word scan | PASS | 8 ADVICE scans, including the draft card, all PASS |
| Precedent | PASS | 5 events (2 NKE, 2 UAA, 1 ADDYY), each with a URL the sentiment agent opened; windows 5, 30, 90, 250; n = 5 in each |
| Confidence from the tool | PASS | `confidence.json` matches the card for all three horizons (table below) |
| Card and saved document | PASS (tiers: see below) | Card posted as a new top-level message; room document `verdict-NKE-2026-11-07` per the chief. `!list-documents` was not run |
| Ledger count | PASS | 369 entries (fund.py 164, precedent.py 152, news.py 42, tech.py 11), as the card states |

Confidence, from `evidence/r-20261107-05/confidence.json`:

| Horizon | Outlook (chief) | Confidence (tool) | Inputs and reasons |
|---|---|---|---|
| Short (1–4 weeks) | Neutral | high | tech neutral, fund neutral, sentiment not_measured; reason "sentiment: not measured for short (interim mode)" |
| Medium (3–6 months), the goal | Bearish | high | fund bearish, tech bearish, sentiment not_measured, 5 events in the 30- and 90-session windows, 28/28 citations |
| Long (1–3 years) | Neutral | low | sentiment no_data (the 90-day tone was refused); fund neutral |

The card's three proofs, checked against the ledger:

| ID | Fact | Value | Tier |
|---|---|---|---|
| E159 | Revenue growth YoY, quarter ended 2026-08-31 | -0.043259 | T1 |
| E165, E167 | Last close; SMA200 | 38.59; 45.4136 | T2 |
| E366 | Mean excess return vs XLY, 90 sessions, 5 events | -0.085416 | unrated (derived from the caller-supplied event dates) |

## Things worth knowing

- **News partly arrived.** GDELT returned the headline list at 04:34 UTC (42 news entries); only the tone request was
  refused. The sentiment agent's retry reused the headlines from the cache, as designed. It found none of the returned
  headlines named Nike (copies of one market wrap and a dividend-stocks list) and built no theme from them.
- **The chief described sentiment's effect inaccurately.** It said sentiment "counts as no data for every horizon" and
  "didn't affect the verdict". In fact short and medium were not_measured (no penalty), and long was no_data, which is
  why long-term confidence is low. The tool's results were right; the wording was not.
- **Tier labels.** The chief said its first posted card described sources in words ("official filing", "unofficial")
  instead of tiers, and that it posted a correction and saved the correct labels. Locally,
  `reports/card-draft.txt` has the right labels (T1, T2, unrated), but `reports/verdict-doc.md` still has the wording.
  The saved room document was **not checked**.
- **A duplicate precedent run.** The chief ran the 5-session window once more with one event by mistake (E295, E296),
  then reran all five events (E362 to E369). `confidence.py` reads the latest entry per window, so it used n = 5. The
  card cites only the five-event run. The duplicate stays in the ledger, which is never edited.
- **Not measured versus refused.** Short and medium came out high although the news call was partly refused. That
  follows the rules as built: the 14- and 30-day windows are not measured in interim mode, so only long had a
  measurement to lose. Making any refused news call a penalty on every horizon would be a change to `agents/chief.md`.
- **Precedent method.** All five events are applied to NKE's own returns against XLY, including the UAA and ADDYY
  report dates, as `agents/chief.md` asks ("this company first, then peers").
- The run took about seven minutes (04:31 to 04:38 UTC). No token or secret was entered in chat, written to a file,
  or committed.

## After the run (2026-11-07, 05:20 UTC)

- `@desk-chief explain E159`: correct fact, value -0.043259, source SEC EDGAR, tier T1, PASS, cited by
  desk-fundamental in round 1.
- `@desk-chief evidence`: the full 369-row table, posted as an attached file. Its rows match the local ledger.
- The table showed a label bug: E168 read "death = SMA50 crossed above SMA200". `tools/tech.py` wrote "above" for
  every cross; fixed in commit 875b68c (a death cross is SMA50 crossing below). The value and date were right; the
  card did not cite E168.

## Not tested in this run

- `ask`, `pause` / `resume`, and a human interrupt mid-run.
- The `chief` alias (not set) and the updated room instructions and `desk-rules` document (not applied).
- The content of the saved `verdict-NKE-2026-11-07` document (`!list-documents` lists it, with the description
  "medium-term Bearish (confidence high, from the tool)").
- Sentiment with a warmed cache and a real 90-day tone.
