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
5. **Room:** one fresh room for the whole batch, created by the template import (section 1b). Every run, every ticker,
   happens in that room. Prior verdicts are exported to disk and then removed before NKE runs 2 and 3 (METRICS.md, M10).
6. **Re-runs (METRICS.md, M1):** a run that fails or aborts counts as failed and is **not** re-run. The one exception is
   an infrastructure fault (Slack outage, Claude usage limit, the machine sleeping), which gets **exactly one** re-run,
   logged with the reason. The failed attempt stays in the run sheet and in the counts; the re-run is a new row
   (for example "4b").
7. **One run at a time.** Never start the next run before the previous one reaches `end`, or is declared failed in the
   run sheet. All runs share the current-run pointer: the chief's `round goal`, `round status` and `round next` take no
   `--run`, so overlapping runs would write into each other's state. Tested: starting a new run while run 0 never ended
   doesn't error, moves the pointer to the new run, and leaves run 0's files byte-identical
   (tests/test_eval_run_pointer.py).
8. **Mid-run typing:** anything you type in a run's thread other than the goal answer goes in the run sheet, verbatim.
   If you type to rescue a run (to unstick it, correct it, or push it on), the run counts as **failed** even if it
   reaches `end`. Write "rescued" in the Outcome column.
9. **Gates:** every box in section 6 is ticked before run 1, including `network_gdelt` PASS and the reset token test.

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

**The old 7 Nov room (`desk-NKE`, Slack `#desk-nke`).** Rooms are created only when a template is used (Switch docs,
How templates work: "Switch creates each agent, then the room"). Posting `@desk-chief analyze NKE` never creates or
reuses a room; the chief works in whichever room the message is posted in, and it reads only that room's documents.
The old room held `verdict-NKE-2026-11-07` (docs/desk-run-nke-2.md). Its full text is on disk as
`evidence/r-20261107-05/reports/verdict-doc.md` (393 lines, card plus evidence table) and in the backup tarball.
Deleting the old agents takes them out of that room, and the newly imported agents are new agents that are not members
of it. So it cannot reach the batch unless someone posts batch messages in `#desk-nke` or invites the new agents there.
- **Recommended: archive the old room, don't delete it.** Archiving is reversible and leaves the room, its documents and
  its Slack channel as they are (Switch docs, Rooms: open the room's page in the Gateway and select **Archive room**).
  Deleting is irreversible and not needed.
- Optional check before archiving: in `#desk-nke`, `!list-documents`, and note what it lists in the run sheet.
- Never post batch messages in `#desk-nke`.

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
- Run 0 (the ZZZQ kickoff) goes in the run sheet as **excluded: setup kickoff created by the template import, goal never
  answered, not a batch run**. It never reaches a verdict, so it writes no `verdict-ZZZQ-*` document. Run 13 (ZZZQ) can
  use the same room: it starts a new run id, and the per-ticker document gate below confirms no `verdict-ZZZQ-*` exists
  first.
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
- **Before every ticker's first run (all 15 runs, in the batch room):** `!list-documents`, and confirm there is no
  `verdict-<TICKER>-*` for that ticker. Other tickers' verdicts may be listed; the chief reads only its own ticker's.
  Write "clean" in the run sheet's Docs column.
- **Before NKE runs 2 and 3 only: export, then delete** the `verdict-NKE-<date>` written by the previous NKE run.
  1. Export: in the Gateway, open the batch room's page, open the document, copy its full text, then in Terminal
     (RUN = the previous NKE run's id):
     `pbpaste > ~/.stockdesk/evidence/RUN/reports/verdict-doc.md`
     This matches where r-20261107-05's verdict is kept. It stays in the run folder, outside every repo. Don't put it in
     `eval/results/`, which is pushed to a public repo.
  2. Check: `head -1 ~/.stockdesk/evidence/RUN/reports/verdict-doc.md` starts with `NKE ·`, and
     `wc -l` shows more than 10 lines. Write "exported" in the run sheet.
  3. Delete the document in the Gateway (you own the room, so you can delete its documents). Then `!list-documents` must
     show no `verdict-NKE-*`. Without this, the chief quotes the earlier verdict (`chief.md` step 2), and saving the new
     one may collide with the same-day document name.
- **`!reset` each agent before every run**, each as its own plain message: `!reset @desk-chief`,
  `!reset @desk-fundamental`, `!reset @desk-technical`, `!reset @desk-sentiment`. Wait for all four replies.
- **At least 10 minutes from one run's end to the next kickoff**, for GDELT spacing and Claude usage.
- **Kickoff, with the goal given so the chief doesn't ask:**
  - NKE (runs 1, 7, 14): `@desk-chief analyze NKE all`
  - every other run: `@desk-chief analyze <TICKER> medium`
- **Type nothing else mid-run** unless the desk asks. Anything you do type goes in the run sheet verbatim; a rescue
  counts as failed (decision 8).
- **One run at a time:** the next kickoff only after the previous run's `end`, or after you mark it failed.
- **A run is declared failed** when it aborts, errors out, stalls (no new message in its thread for 15 minutes), or is
  rescued. Write the cause in Outcome: infrastructure (with what happened), rescued, or other. Only infrastructure gets
  a re-run, once.
- Order (NKE spread across the batch): NKE, JNJ, CVX, JPM, CAT, NNE, NKE, PG, FIG, NVDA, BABA, GOOGL, ZZZQ, NKE, XOM.
  Roughly 7 minutes per run plus 10-minute gaps: about 4½ hours.

## 4. Run sheet (fill in during the batch)

The run id is in the chief's first thread message (`r-YYYYMMDD-NN`).

Extra columns: **Docs** is the per-ticker `!list-documents` gate ("clean"). **Step-2 line** is the chief's second
message, either "No earlier verdict for TICKER." or a quoted verdict. **Stray** is the number of top-level "I finished
without replying." messages during the run. **Outcome** is ended, or failed: infrastructure / rescued / other.
**Export** (NKE runs 1 and 7 only) is "exported" once that run's verdict
document is saved to its run folder, before it is deleted.

| # | Ticker | Goal | Run id | Kickoff time (ET) | End time (ET) | Outcome | Docs | Step-2 line | Stray | Export | Anything typed mid-run | Anything odd |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | ZZZQ | excluded: setup kickoff from the template import, goal never answered | | | | | | | | | | |
| 1 | NKE | all | | | | | | | | (before run 7) | | |
| 2 | JNJ | medium | | | | | | | |  | | |
| 3 | CVX | medium | | | | | | | |  | | |
| 4 | JPM | medium | | | | | | | |  | | |
| 5 | CAT | medium | | | | | | | |  | | |
| 6 | NNE | medium | | | | | | | |  | | |
| 7 | NKE | all | | | | | | | | (before run 14) | | |
| 8 | PG | medium | | | | | | | |  | | |
| 9 | FIG | medium | | | | | | | |  | | |
| 10 | NVDA | medium | | | | | | | |  | | |
| 11 | BABA | medium | | | | | | | |  | | |
| 12 | GOOGL | medium | | | | | | | |  | | |
| 13 | ZZZQ | medium | | | | | | | |  | | |
| 14 | NKE | all | | | | | | | |  | | |
| 15 | XOM | medium | | | | | | | |  | | |
| re-runs: add rows like 4b here (infrastructure faults only, once each) | | | | | | | | | | | | |

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
- [ ] **Fresh room:** `!list-documents` in the new batch room shows no `verdict-*` document; the old `desk-NKE` room is
  archived (not deleted), and no batch message goes to `#desk-nke`.
- [ ] **Backup:** the evidence tarball is copied to a second location and its SHA-256 matches (section 8).
- [ ] **Reset token test:** desk-chief and desk-technical both answer NONE after `!reset` (section 1b).
- [ ] **Conditions:** market closed for the whole batch, and all three NKE runs fit on one ET calendar day.

## 7. What you do by hand, in order

1. **Back up a second copy** of the old runs (section 8) and check the checksum.
2. **Remove the four old agents:** Switch Console → Your Agents → desk-chief's menu → Remove → tick **Also delete this
   agent in Switch** → Remove. The same for desk-fundamental, desk-technical, desk-sentiment.
3. **Archive the old room:** Gateway → the `desk-NKE` room's page → **Archive room**. (Optional first: `!list-documents`
   in `#desk-nke`, noted in the run sheet.)
4. **Generate the template** in Terminal: `stockdesk template --ticker ZZZQ`.
5. **Import it:** Switch Console → Templates → Create template ▾ → Import a file… → `desk-team.template.yaml` → Save →
   Use template → Slack connection → Create. This creates the four agents and the batch room `desk-ZZZQ`, and posts the
   kickoff (run 0).
6. **In the batch room:** don't answer run 0's goal question; note its run id as run 0 (excluded).
7. **In the batch room:** `!list-documents` → only `desk-rules`, no `verdict-*`.
8. **In the batch room:** `!reset-all-agents`, and wait for the replies.
9. **Reset token test** for desk-chief, then desk-technical (section 1b). Both must answer NONE. Then `!reset` both.
10. **Terminal:** `stockdesk doctor`. No FAIL, and `network_gdelt` PASS. On a WARN, stop and try again later.
11. **Tick section 6**, then run the batch in the batch room, in section 3's order. Before each run: `!reset` the four
    agents, then the per-ticker `!list-documents` gate. Before NKE runs 2 and 3: export, then delete, the previous NKE
    verdict.

## 8. Second backup copy of the old runs

The 7 Nov runs exist only on this disk (`evidence/` is git-ignored). Never commit `evidence/` or `~/.stockdesk/` to any
repo. SHA-256 of the backup made on 24 Nov 2026:
`4037bff169d8481932288a10041bb2f152fcffba5bed5af351842fdd1b3bfe87`. To copy it to a second location you choose (an
external drive, for example) and check it, set DEST first:

```bash
DEST="/Volumes/YOUR-DRIVE/stock-desk-backup"; mkdir -p "$DEST" && cp ~/Downloads/stock-desk-evidence-backup-2026-11-24.tar.gz "$DEST"/ && shasum -a 256 ~/Downloads/stock-desk-evidence-backup-2026-11-24.tar.gz "$DEST"/stock-desk-evidence-backup-2026-11-24.tar.gz
```

Both lines must show the hash above.
