# Phase 4 live batch: runbook

Prepared 24 Nov 2026. **Nothing here has been run.** You run the batch; afterwards `eval/score_runs.py` scores it
(M1–M7, M12) and M10 is computed from the three NKE runs. Metric definitions are fixed in `METRICS.md`.

## 0. Decisions (all made 24 Nov 2026)

1. **Tickers:** 15 runs, section 2. XOM is run 15 and is reported on its own as **"thin ledger after CIK change"**,
   never in the large-cap group.
2. **News names:** option (a). Every run uses the identical override `eval/config/news_names.json`: the 10 shipped
   names unchanged plus one per batch ticker; ZZZQ has none on purpose. Installed in step 1.
3. **Goals:** NKE ×3 use `all`; every other run uses `medium`.
4. **Mention test: PASS with a caveat** (24 Nov 2026, Switch Console v0.41.1). s0-technical also posted
   "I finished without replying." at the channel's top level. That message is an expected Switch side effect: log a
   count per run in the run sheet. It counts as a failure only if it appears with no reply in the run's thread.
5. **Room:** one fresh room for the whole batch (section 1b). Prior verdicts are removed before NKE runs 2 and 3
   (METRICS.md, M10).
6. **Gates:** every box in section 6 is ticked before run 1, including `network_gdelt` PASS and the reset token test.

## 1. Required before run 1 (stop if any step fails)

The batch must measure the setup the README tells people to use. Every earlier live run used the old repo-path setup
(`~/.stockdesk` did not exist on 24 Nov 2026).

```bash
pipx install --force "git+https://github.com/karan-patel11/stock-desk@eval"
```

```bash
stockdesk init
```

Install the news-name override (from a checkout of branch `eval`; `~/.stockdesk/config/` is created by `init`):

```bash
cp eval/config/news_names.json ~/.stockdesk/config/news_names.json
```

Confirm every batch ticker resolves, with the network blocked (no GDELT request):

```bash
python3 eval/check_news_names.py --home ~/.stockdesk
```

- [ ] It ends `PASS: every batch ticker resolves; GDELT not contacted` and reports the file identical to
  `eval/config/news_names.json`. **If not, stop.**

```bash
stockdesk doctor
```

- [ ] No FAIL line. **If any check FAILs, stop.**
- [ ] `network_gdelt` is **PASS**. A WARN (GDELT rate limiting) is not good enough: wait (GDELT can block for hours, and
  every refused request can extend the block), run `stockdesk doctor` once more later, and do not start the batch on a
  WARN. Re-run doctor right before run 1 for this gate.
- [ ] `claude_code` PASS only means the CLI exists. Also check it is signed in: `claude auth login` if in doubt
  (24 Nov 2026: doctor passed while it was signed out, and every agent session failed).

```bash
stockdesk template --mention-test
```

- [ ] In Switch Console load `mention-test.template.yaml` with your Slack connection. Pass criteria (README, Stage 0):
  kickoff wakes s0-chief; s0-chief mentions s0-technical, it replies and the reply wakes s0-chief
  (`MENTION TEST PASSED`); everything stays in one thread. **If the mention test fails, stop.**

```bash
stockdesk template
```

- [ ] Re-import the desk in Switch Console (Templates → Import template → choose `desk-team.template.yaml` → Save →
  Use template) so the four agents call the packaged `stockdesk` with `STOCKDESK_HOME` set. Template file modified
  at: ________
- [ ] Record: `stockdesk --version` ________ · eval commit (`git rev-parse --short origin/eval`) ________ ·
  Switch Console version ________ · Claude model the agents run ________

## 1b. Desk import, fresh room, reset test (after the mention test)

**Remove the four old desk agents** (they call the old repo-path tools). You do this; deletion can't be undone. From
the Switch docs (Agent maintenance): Switch Console → **Your Agents** → the agent's menu → **Remove** → tick
**Also delete this agent in Switch** → **Remove**. Or, in a Slack room: `!delete-agent @desk-chief`, then within 2
minutes `!delete-agent @desk-chief confirm`. Repeat for desk-fundamental, desk-technical, desk-sentiment. (Renaming
instead: the pencil beside the agent's name; the new template still needs the old names to be free.) Deleting the
agents does not delete the old `desk-nke` room or its documents.

**Import the desk into a fresh room.** The template's kickoff posts `@desk-chief analyze {ticker}` as soon as the
room exists, so importing starts an analysis. Suggested: import with ticker **ZZZQ**. The room becomes `desk-ZZZQ`,
a new name with no history, and the kickoff run fails closed fast: ZZZQ isn't in the SEC map, has no news name (so no
GDELT request), and gets one Yahoo price lookup. Don't answer its goal question. Record its run id in the run sheet as
"setup kickoff (excluded)".

```bash
stockdesk template --ticker ZZZQ
```

Switch Console v0.41.1: **Templates → Create template ▾ → Import a file…** → `desk-team.template.yaml` → Save → Use
template → pick your Slack connection → Create. If it says a template with that name already exists (HTTP 409), tell
me before deleting anything.

- [ ] In the new room, `!list-documents` shows `desk-rules` and no `verdict-*` document (no 7 Nov documents carried
  over).
- [ ] `!reset-all-agents` (or the four `!reset @…`), and wait for the replies.

**Reset token test (gate).** For desk-chief, then desk-technical:
1. In a new thread A: `@desk-chief remember the token PELICAN-42. Reply OK only.`
2. As its own plain message: `!reset @desk-chief`, and wait for the reply.
3. In a new thread B: `@desk-chief what token did I ask you to remember? If you don't know, say NONE.`
- **Pass:** it can't recall the token (NONE). **Fail:** it answers PELICAN-42. On a fail, stop and tell me. Per the
  Switch docs (Room commands), `!reset` "Clears an agent’s context and reconnects it", and whether an agent supports it
  is decided when you run it. We would then test a fresh room and, failing that, removing and re-adding the agent in
  Switch Console, and make whichever clears it the between-runs step.
- Then `!reset` both agents again so the test itself isn't in their context.

Do not set `STOCKDESK_CACHE_TTL_HOURS` or run `scripts/warm_demo.sh`: warming changes what sentiment sees. The news
cache keeps its 1-hour default, so a later NKE run may reuse news fetched within the hour by an earlier one. That is
expected for a same-day stability test; note it in the run sheet. Don't edit the override during the batch.

## 2. Tickers (checked against the SEC ticker map and filings on 24 Nov 2026)

Sources: `sec.gov/files/company_tickers.json` and `data.sec.gov` submissions and companyfacts, read in a browser on
24 Nov 2026. "Revenue quarters" are distinct quarterly revenue periods in 10-Q/10-K XBRL, the input fund.py reads.
Sectors are GICS sectors.

| Run(s) | Ticker | Group | Sector | Why it's there | SEC evidence |
|---|---|---|---|---|---|
| 2 | JNJ | Large cap | Health Care | Mega-cap pharma; 52/53-week fiscal year (FYE 0103) tests quarter dating | CIK 200406, SIC 2834; 10-Q to 2026-10-21 |
| 3 | CVX | Large cap | Energy | Integrated oil; takes the energy slot because XOM's ticker moved to a new CIK | CIK 93410, SIC 2911; 10-Q to 2026-11-05 |
| 5 | CAT | Large cap | Industrials | Machinery, with a financial-products segment in its totals | CIK 18230, SIC 3531; 10-Q to 2026-11-04 |
| 8 | PG | Large cap | Consumer Staples | June fiscal year | CIK 80424, SIC 2840; 10-Q to 2026-10-22 |
| 10 | NVDA | Large cap | Information Technology | January fiscal year; fast growth tests the YoY figures | CIK 1045810, SIC 3674; 10-Q to 2026-08-26 |
| 12 | GOOGL | Large cap | Communication Services | Several share classes on one CIK | CIK 1652044, SIC 7370; tickers GOOGL, GOOG |
| 4 | JPM | Bank | Financials | The JPM-style revenue tag (fail-closed case 1) | CIK 19617; us-gaap `Revenues` 20 quarters ending 2014-09-30, `RevenuesNetOfInterestExpense` 39 quarters to 2026-09-30 |
| 6 | NNE | Small cap, thin XBRL history | Utilities (SIC 4911, electric services; pre-revenue nuclear developer) | Public float $0.70B (2025-03-31); listed May 2024; one revenue quarter | CIK 1923891; 8 10-Qs since 2024-06-20; 1 revenue quarter (2026-06-30) |
| 9 | FIG | IPO, last ~2 years | Information Technology | Figma, IPO July 2025 | CIK 1579878; 424B4 2025-07-31; 5 10-Qs; 8 revenue quarters (S-1 comparatives) |
| 11 | BABA | Foreign company trading in the US | Consumer Discretionary | Files 20-F/6-K only with us-gaap XBRL: fail-closed case 5's unclear-detail path | CIK 1577552; us-gaap facts only on 20-F/6-K forms; no 10-Q |
| 13 | ZZZQ | Invalid ticker | — | Well-formed, not a listed company | Absent from the 10,400-entry ticker map; no news name on purpose |
| 1, 7, 14 | NKE | Stability (M10), goal `all` | Consumer Discretionary | The desk's reference ticker, 3 runs on one day | CIK 320187, SIC 3021; 10-Q to 2026-10-02 |
| 15 | XOM | Thin ledger after CIK change (reported separately) | Energy | The ticker now maps to ExxonMobil Holdings Corp; fund.py follows the ticker map, so a mega-cap gets a thin ledger | CIK 2115436: 8-K12B 2026-07-01, 2 10-Qs, 4 revenue quarters; Exxon Mobil Corp's 20 10-Qs stay under CIK 34088 |

**Large caps: 6 runs in 6 different GICS sectors:** JNJ (Health Care), CVX (Energy), CAT (Industrials), PG (Consumer
Staples), NVDA (Information Technology), GOOGL (Communication Services). The large-cap group repeats no sector. FIG
(Information Technology) and BABA and NKE (Consumer Discretionary) are in other groups. XOM shares CVX's sector but is
not in the large-cap group.

Excluded on purpose: AAPL and MSFT (already in the pre-eval runs), and NKE from the large-cap slots (it is the
stability ticker).

## 3. Conditions

- **Outside US market hours** (partial-bar limitation): run the whole batch on one day when the market is closed, e.g.
  a Saturday, or weekdays only after 16:30 or before 09:00 ET. All three NKE runs on the same ET calendar day.
- **Before NKE runs 2 and 3 only:** delete the room document `verdict-NKE-<date>` written by the previous NKE run.
  You own the room, so you can delete its documents (Switch docs, Rooms: in the Gateway, open the room's page, then
  its documents). Then `!list-documents` must show no `verdict-NKE-*`. The card stays in Slack and the evidence table
  can be regenerated from the ledger on disk. Without this, the chief quotes the earlier verdict (`chief.md` step 2),
  and saving the new one may collide with the same-day document name.
- **`!reset` each agent before every run**, each as its own plain message: `!reset @desk-chief`,
  `!reset @desk-fundamental`, `!reset @desk-technical`, `!reset @desk-sentiment`. Wait for all four replies.
- **At least 10 minutes from one run's end to the next kickoff**, for GDELT spacing and Claude usage.
- **Kickoff, with the goal given so the chief doesn't ask:**
  - NKE (runs 1, 7, 14): `@desk-chief analyze NKE all`
  - every other run: `@desk-chief analyze <TICKER> medium`
- **Type nothing else mid-run** unless the desk asks. Anything you do type goes in the run sheet.
- Order (NKE spread across the batch): NKE, JNJ, CVX, JPM, CAT, NNE, NKE, PG, FIG, NVDA, BABA, GOOGL, ZZZQ, NKE, XOM.
  Roughly 7 minutes per run plus 10-minute gaps: about 4½ hours.

## 4. Run sheet (fill in during the batch)

The run id is in the chief's first thread message (`r-YYYYMMDD-NN`).

Extra columns: **Step-2 line** is the chief's second message, either "No earlier verdict for TICKER." or a quoted
verdict. **Stray** is the number of top-level "I finished without replying." messages during the run.

| # | Ticker | Goal | Run id | Kickoff time (ET) | End time (ET) | Step-2 line | Stray | Anything typed mid-run | Anything odd |
|---|---|---|---|---|---|---|---|---|---|
| 0 | ZZZQ | setup kickoff (excluded) | | | | | | | |
| 1 | NKE | all | | | | | | | |
| 2 | JNJ | medium | | | | | | | |
| 3 | CVX | medium | | | | | | | |
| 4 | JPM | medium | | | | | | | |
| 5 | CAT | medium | | | | | | | |
| 6 | NNE | medium | | | | | | | |
| 7 | NKE | all | | | | | | | |
| 8 | PG | medium | | | | | | | |
| 9 | FIG | medium | | | | | | | |
| 10 | NVDA | medium | | | | | | | |
| 11 | BABA | medium | | | | | | | |
| 12 | GOOGL | medium | | | | | | | |
| 13 | ZZZQ | medium | | | | | | | |
| 14 | NKE | all | | | | | | | |
| 15 | XOM | medium | | | | | | | |

## 5. After the batch

Tell me it's done and paste the run sheet. I will write the run ids to `eval/results/batch_runs.txt` (the scorer's
eval-batch list), run `eval/score_runs.py` on `~/.stockdesk/evidence`, compute M10 from the three NKE runs, and show
the table, with XOM reported separately as "thin ledger after CIK change", without interpreting it.

## 6. Pre-run gate checklist (tick every box, then start run 1)

- [ ] **Install:** `pipx install --force "git+https://github.com/karan-patel11/stock-desk@eval"` and `stockdesk init`
  done; `stockdesk --version` recorded.
- [ ] **Name check:** `python3 eval/check_news_names.py --home ~/.stockdesk` ends `PASS`, file identical to the eval copy.
- [ ] **Doctor:** `stockdesk doctor` shows no FAIL, **`network_gdelt` PASS** (re-run right before run 1), and the
  Claude Code CLI is signed in.
- [ ] **Mention test:** PASS (`MENTION TEST PASSED` in one thread; stray top-level message logged, not a failure).
- [ ] **Old agents removed:** the four old desk-* agents deleted (or renamed), and the new desk imported from the
  packaged template.
- [ ] **Fresh room:** `!list-documents` in the new room shows no `verdict-*` document.
- [ ] **Reset token test:** desk-chief and desk-technical both answer NONE after `!reset` (section 1b).
- [ ] **Conditions:** market closed for the whole batch, and all three NKE runs fit on one ET calendar day.
