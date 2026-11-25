# Phase 4 live batch: runbook

Prepared 24 Nov 2026. **Nothing here has been run.** You run the batch; afterwards `eval/score_runs.py` scores it
(M1–M7, M12) and M10 is computed from the three NKE runs. Metric definitions are fixed in `METRICS.md`.

## 0. Decisions before the batch (yours)

1. **Approve the ticker list** (section 2). It has 14 runs as specified (6 + 1 + 1 + 1 + 1 + 1 + 3). The prompt said
   15; the composition adds to 14. A 15th is proposed: XOM, a real CIK-change case (below). Approve it or drop it.
2. **News names.** `news.py --ticker` only knows 10 tickers (AAPL, COST, DIS, HD, KO, MSFT, NKE, PG, TSLA, WMT);
   any other is `bad_input`, so sentiment becomes no data for every horizon. The README says to add a name before
   analyzing. Choose one:
   - **(a) add names** for the batch tickers in a user override (`stockdesk init --copy-config`, then edit
     `~/.stockdesk/config/news_names.json`; the override is used whole, so keep the existing 10). Measures the desk as
     the README says to set it up. Suggested names are in section 2; ZZZQ gets none.
   - **(b) leave the list as shipped.** Measures the out-of-the-box gap; sentiment is no data on 10 of 14 runs.
3. **NKE goal.** The spec fixes medium for every run except NKE and doesn't say what NKE uses. Suggested: `all`, so
   every horizon is the chief's explicit judgment. Any fixed goal works for M10, which compares each horizon's outlook.

## 1. Required before the batch: the packaged install (stop if any step fails)

The batch must measure the setup the README tells people to use. Every earlier live run used the old repo-path setup
(`~/.stockdesk` did not exist on 24 Nov 2026).

```bash
pipx install --force "git+https://github.com/karan-patel11/stock-desk@eval"
```

```bash
stockdesk init
```

```bash
stockdesk doctor
```

- [ ] `doctor`: no FAIL line. **If any check FAILs, stop**; don't run the batch.
- [ ] Decision 2(a) only: `stockdesk init --copy-config`, add the names, run `stockdesk doctor` again.

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
  Use template) so the four agents call the packaged `stockdesk` with `STOCKDESK_HOME` set. Note the template file's
  modification time here: ________
- [ ] Record: `stockdesk --version` ________ · eval commit (`git rev-parse --short origin/eval`) ________ ·
  Switch Console version ________ · Claude model the agents run ________

Do not set `STOCKDESK_CACHE_TTL_HOURS` or run `scripts/warm_demo.sh` for the batch: warming changes what sentiment
sees. Defaults: news cache 1 hour, so the second and third NKE runs may reuse news fetched by the first if they fall
within the hour. That is expected for a same-day stability test; note it in the run sheet.

## 2. Tickers (checked against the SEC ticker map and filings on 24 Nov 2026)

Sources: `sec.gov/files/company_tickers.json` and `data.sec.gov` submissions and companyfacts, read in a browser on
24 Nov 2026. Quarter counts are distinct quarterly revenue periods in 10-Q/10-K XBRL, the input fund.py reads.

| # | Slot | Ticker | CIK | Why it fits | SEC evidence | Expected path | Suggested news name |
|---|---|---|---|---|---|---|---|
| 1 | Large cap, health care | JNJ | 200406 | Mega-cap pharma; 52/53-week fiscal year (FYE 0103) tests quarter dating | SIC 2834; 10-Q and 10-K current | normal | Johnson & Johnson |
| 2 | Large cap, energy | CVX | 93410 | Integrated oil; replaces XOM, whose ticker moved to a new CIK | SIC 2911; 10-Q to 2026-11-05 | normal | Chevron |
| 3 | Large cap, industrials | CAT | 18230 | Machinery; financial-products segment in the totals | SIC 3531; 10-Q to 2026-11-04 | normal | Caterpillar |
| 4 | Large cap, consumer staples | PG | 80424 | June fiscal year; already in the news-name list | SIC 2840; 10-Q to 2026-10-22 | normal | (already: Procter & Gamble) |
| 5 | Large cap, information technology | NVDA | 1045810 | January fiscal year; fast growth tests the YoY figures | SIC 3674; 10-Q to 2026-08-26 | normal | Nvidia |
| 6 | Large cap, communication services | GOOGL | 1652044 | Several share classes on one CIK | SIC 7370; tickers GOOGL, GOOG | normal | Alphabet |
| 7 | Bank | JPM | 19617 | The JPM-style case (fail-closed case 1) | us-gaap `Revenues` 20 quarters ending 2014-09-30; `RevenuesNetOfInterestExpense` 39 quarters to 2026-09-30 | revenue no_data (stale); net income and EPS reported | JPMorgan |
| 8 | Small cap, thin XBRL history | NNE | 1923891 | Public float $0.70B (2025-03-31); listed May 2024; first revenue quarter 2026-06-30 | 8 10-Qs since 2024-06-20; 1 revenue quarter | revenue YoY unavailable; thin ledger | Nano Nuclear |
| 9 | IPO, last ~2 years | FIG | 1579878 | Figma, IPO July 2025 (424B4 2025-07-31) | 5 10-Qs since 2025-09-03; 8 revenue quarters (S-1 comparatives) | short history, YoY on few quarters | Figma |
| 10 | Foreign company trading in the US | BABA | 1577552 | Files 20-F and 6-K only, us-gaap XBRL | us-gaap facts only on 20-F/6-K forms; no 10-Q | fund.py no_data "no quarterly revenue found" (case 5's unclear detail) | Alibaba |
| 11 | Invalid ticker | ZZZQ | — | Well-formed, not in the SEC ticker map | absent from the 10,400-entry map | fund.py no_data; confidence.py refuses the empty run | none |
| 12–14 | Stability (M10) | NKE ×3 | 320187 | The desk's reference ticker; same day | SIC 3021; 10-Q to 2026-10-02 | normal | (already: Nike) |
| 15 | **Proposed**: CIK change | XOM | 2115436 | The XOM ticker now maps to ExxonMobil Holdings Corp (8-K12B 2026-07-01, 2 10-Qs); Exxon Mobil Corp's history (20 10-Qs) stays under CIK 34088 | new CIK: 4 revenue quarters | a mega-cap with a thin ledger, because fund.py follows the ticker map | Exxon |

Alternatives if you'd rather swap: BAC for the bank (but its `Revenues` tag runs to 2026, so it would not exercise the
bank path), CRWV for the IPO (March 2025, 9 revenue quarters), TSM for the foreign filer (IFRS-only: the clear-detail
path instead of the unclear one).

Excluded on purpose: AAPL and MSFT (already in the pre-eval runs), and NKE from the large-cap slots (it is the
stability ticker).

## 3. Conditions

- **Outside US market hours** (partial-bar limitation): run the whole batch on one day when the market is closed, e.g.
  a Saturday, or weekdays only after 16:30 or before 09:00 ET. All three NKE runs must be on the same ET calendar day.
- **`!reset` each agent before every run**, each as its own plain message: `!reset @desk-chief`,
  `!reset @desk-fundamental`, `!reset @desk-technical`, `!reset @desk-sentiment`. Wait for all four replies.
- **At least 10 minutes from one run's end to the next kickoff**, for GDELT spacing and Claude usage.
- **Same goal, medium, for every run except NKE**, given in the kickoff so the chief doesn't ask:
  `@desk-chief analyze <TICKER> medium`. NKE: `@desk-chief analyze NKE <goal from decision 3>`.
- **Type nothing else mid-run** unless the desk asks. Anything you do type goes in the run sheet.
- Suggested order, NKE spread across the batch: NKE, JNJ, CVX, JPM, CAT, NNE, NKE, PG, FIG, NVDA, BABA, GOOGL, ZZZQ,
  NKE, then XOM if approved. Roughly 7 minutes per run plus 10-minute gaps: about 4 hours.

## 4. Run sheet (fill in during the batch)

The run id is in the chief's first thread message (`r-YYYYMMDD-NN`).

| # | Ticker | Run id | Kickoff time (ET) | End time (ET) | Anything typed mid-run | Anything odd |
|---|---|---|---|---|---|---|
| 1 | NKE | | | | | |
| 2 | JNJ | | | | | |
| 3 | CVX | | | | | |
| 4 | JPM | | | | | |
| 5 | CAT | | | | | |
| 6 | NNE | | | | | |
| 7 | NKE | | | | | |
| 8 | PG | | | | | |
| 9 | FIG | | | | | |
| 10 | NVDA | | | | | |
| 11 | BABA | | | | | |
| 12 | GOOGL | | | | | |
| 13 | ZZZQ | | | | | |
| 14 | NKE | | | | | |
| 15 | XOM (if approved) | | | | | |

## 5. After the batch

Tell me it's done and paste the run sheet. I will write the run ids to `eval/results/batch_runs.txt` (the scorer's
eval-batch list), run `eval/score_runs.py` on `~/.stockdesk/evidence`, compute M10 from the three NKE runs, and show
the table without interpreting it.
