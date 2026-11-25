# Phase 4 live batch: runbook

Prepared 24 Nov 2026. **Nothing here has been run.** You run the batch; afterwards `eval/score_runs.py` scores it
(M1–M7, M12) and M10 is computed from the three NKE runs. Metric definitions are fixed in `METRICS.md`.

## 0. Decisions (all made 24 Nov 2026)

1. **Tickers:** 15 runs, section 2. XOM is run 15 and is reported on its own as **"thin ledger after CIK change"**,
   never in the large-cap group.
2. **News names:** option (a). Every run uses the identical override `eval/config/news_names.json`: the 10 shipped
   names unchanged plus one per batch ticker; ZZZQ has none on purpose. Installed in step 1.
3. **Goals:** NKE ×3 use `all`; every other run uses `medium`.

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

| # | Ticker | Goal | Run id | Kickoff time (ET) | End time (ET) | Anything typed mid-run | Anything odd |
|---|---|---|---|---|---|---|---|
| 1 | NKE | all | | | | | |
| 2 | JNJ | medium | | | | | |
| 3 | CVX | medium | | | | | |
| 4 | JPM | medium | | | | | |
| 5 | CAT | medium | | | | | |
| 6 | NNE | medium | | | | | |
| 7 | NKE | all | | | | | |
| 8 | PG | medium | | | | | |
| 9 | FIG | medium | | | | | |
| 10 | NVDA | medium | | | | | |
| 11 | BABA | medium | | | | | |
| 12 | GOOGL | medium | | | | | |
| 13 | ZZZQ | medium | | | | | |
| 14 | NKE | all | | | | | |
| 15 | XOM | medium | | | | | |

## 5. After the batch

Tell me it's done and paste the run sheet. I will write the run ids to `eval/results/batch_runs.txt` (the scorer's
eval-batch list), run `eval/score_runs.py` on `~/.stockdesk/evidence`, compute M10 from the three NKE runs, and show
the table, with XOM reported separately as "thin ledger after CIK change", without interpreting it.
