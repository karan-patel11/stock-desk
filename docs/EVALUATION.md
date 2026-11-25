# Stock Desk evaluation

> **Draft.** Sections are filled in as each phase finishes. Every number here is taken from a file in
> `eval/results/`; metric definitions are in [`eval/METRICS.md`](../eval/METRICS.md), committed before any live run.

## What was measured, and what was not

_To be written in Phase 6._

## Phase 2: verifier fault injection (M8)

Method: [`eval/inject.py --seed 7`](../eval/inject.py) builds one-change variants of every report from every run
with an evidence ledger (34 reports, 6 runs) and runs `verify --text-file` on each against a copy of that run's
ledger. Results: [`eval/results/before/injection.md`](../eval/results/before/injection.md) (verify.py before the
URL fix) and [`eval/results/after/injection.md`](../eval/results/after/injection.md); side by side in
[`eval/results/before_after.md`](../eval/results/before_after.md).

_Full results tables to be written in Phase 6._

### False alarms on clean and legit_round variants

1. **As pre-registered:** false alarms = **4/61** clean and legit_round variants (after the URL fix).
2. **Breakdown:** 2 are the quoted-headline case (the verifier working as designed). 2 are one pre-existing wrong
   figure in `r-20261107-02/technical-r1.txt`, counted twice because both variants share that source report. The
   verifier correctly caught it, so it is a true positive, not a false alarm.
3. **Adjusted, not pre-registered:** false alarms = **2/59**, leaving out the 2 variants of that one source report
   because its original text holds a real error (`eval/labels/source_errors.csv`). The pre-registered count in line 1
   stands.

**The quoted headline (`r-20261105-16/desk-sentiment-r1.txt`).** The report quotes headlines such as "Up 17% Off
Its 52-Week Low" [E133] and "NIKE Shares Up 2%" [E128]. The cited entries are news articles whose stored value is
text, so no entry holds 17% or 2%, and verify fails the line. That is correct: a number inside a quoted headline is
still a figure the reader sees without verification. The pre-registered label (clean: expected PASS) is kept.

**The pre-existing error (`r-20261107-02/technical-r1.txt`).** Line 4 reads "RSI(14) at 75.0 [E169]"; E169 holds
61.050897. It was planted by a scripted dev check, not written by an analyst: the whole run took 2 seconds, the
report and all four log rows (PASS, PASS, FAIL 75.0, WITHDRAWN) carry the same second, 01:26:58Z, and it ran a
minute after the commits that added the goal flow and the report format it uses. The run is excluded from every run
metric; its reports stay in the injection corpus under the pre-registered corpus rule.

Possible future changes, out of scope for this evaluation:

- (a) the sentiment agent cites headlines by E-id without repeating their numbers;
- (b) the ledger stores headline text so a quoted headline can be matched exactly.

### wrong_id_similar: a figure moved to another entry that holds the same value

Random `wrong_id` substitutions never landed on a look-alike entry, so `inject.py` searched for them on purpose: it
moves a citation to another existing entry whose stored value also matches the displayed figure. It found 6.
verify passed all 6. Each was then inspected by hand ([`eval/labels/wrong_id_similar.csv`](../eval/labels/wrong_id_similar.csv)):

| Variant | Class | Reason |
|---|---|---|
| r-20261107-05/card-draft | equivalent | E364 and E285 are duplicate entries: same fact, value, period and locator (precedent.py wrote it twice) |
| r-20261107-11/card-draft | equivalent | E271 is a mean over 1 event; E259 is that event's excess return; a mean of one value equals the value |
| r-20261107-18/card-draft | equivalent | E258 is a mean over 1 event; E241 is that event's excess return |
| r-20261107-05/fundamental-r1 | misattribution | E11 total debt at 2023-11-30 → E17 LongTermDebtNoncurrent at 2024-02-29 |
| r-20261107-18/fundamental-r1 | misattribution | E206 revenue growth (quarter to 2026-03-31) → E216 operating income growth (quarter to 2026-06-30) |
| r-20261107-18/fundamental-r2 | misattribution | the same pair, in the round 2 report |

The 3 equivalents are excluded from detection: moving the citation between them does not change what the figure
means. **Misattribution detection: 0/3.** Labelled by one person.

## Phase 3: fail-closed cases (M9)

Method: [`tests/test_fail_closed.py`](../tests/test_fail_closed.py), offline, recorded and synthetic fixtures only;
run by [`eval/fail_closed.py`](../eval/fail_closed.py). The tests assert current behaviour (decided 24 Nov 2026);
where it differs from the Phase 3 spec, the test says so. Results: [`eval/results/after/fail_closed.md`](../eval/results/after/fail_closed.md).

| Case | Expected by spec | Actual | Fails closed |
|---|---|---|---|
| 1. Bank (JPM-style revenue tag) | revenue no_data; net income and EPS reported; confidence lowered | JPM-style (stale legacy `Revenues` tag): as spec. A bank whose only revenue tag is `RevenuesNetOfInterestExpense`: no_data for the whole tool, so net income and EPS are lost. Confidence drops only if the chief passes fund=no_data | yes |
| 2. Unknown ticker | bad_input, exit 1 | well-formed but unknown: **no_data** ("not in the SEC ticker map"), exit 1; malformed: bad_input, exit 1. A run can start; confidence.py refuses it (no evidence) | yes |
| 3. GDELT HTTP 429 | rate_limited; sentiment cannot raise confidence | as spec: rate_limited, one request, no news entries; no sentiment value scores above neutral over 1,296 input combinations | yes |
| 4. Stale EPS past 200 days | stale or no_data, never current | as spec: listed as stale, absent from every quarter, never filled from an annual value | yes |
| 5. Foreign filer (20-F, no 10-Q) | fail closed with a clear detail | fails closed (no_data), but the detail is "no quarterly revenue found", with no mention of 20-F or a foreign filer. An IFRS-only filer gets "foreign filer or no XBRL" | yes |
| 6. Partial bar (known limitation) | document only | a bar dated today and fetched mid-session is reported as `last_close`; nothing marks it partial | no (documented) |

Counts: cases that fail closed **5/5**; cases matching the spec exactly **2/5** (3 and 4); tests 13/13. Case 6 is
documented, not scored.

Also found: when fund.py refuses (cases 1 and 5), it has already written 2 entries, the filer's SIC code and fiscal
year end. No financial metric is written.

Future fixes, not built: say "20-F / foreign filer" in fund.py's refusal detail (case 5).

## Bugs found and fixed

| Bug | Found by | Fix | Before | After |
|---|---|---|---|---|
| Digits inside a URL counted as uncited numbers | Phase 1 (M5) and Phase 2 (false alarms) | commit 8e62c76, with regression tests | false alarms 7/61; pre-eval M5 uncited 2/26 numbers | false alarms 4/61; pre-eval M5 uncited 0/24 |
| confidence.py gave a label for a run with no evidence | Phase 0 (r-20261107-07) | commit b221cc3, refuses with `no_data`, with regression tests | r-20261107-07: `ok`, labels low/low/low, citations 0/0, written to confidence.json | `no_data` "run … has no evidence entries", exit 1, nothing written |

(URL counts from `eval/results/before_after.md`. The confidence "before" is the saved
`evidence/r-20261107-07/confidence.json`; the "after" is `tests/test_confidence.py::test_empty_ledger_*`.)
`no_data` was chosen over `bad_input` because the run id is valid and what is missing is data, the same code
`evidence_table.py` gives for the same run.

## Known limits

- **verify checks values, not which fact or period a value belongs to.** A figure cited to the wrong entry passes
  when that entry happens to hold the same value (misattribution detection 0/3 above).
- **"clean" means unchanged, not verified correct.** A source report with a real error produces a failing clean
  variant (`r-20261107-02`, above).
- **Confidence rules are code, but their inputs come from the chief's instructions.** Which analyst is `no_data` or
  `not_measured` is passed in by the chief; M12 checks those inputs against the ledger, counting only allowlisted
  metric entries as evidence (amended before any live run, because fund.py leaves 2 profile entries when it refuses).
  Pre-eval runs: 27/27 checks match under the amended definition and 27/27 under the superseded one
  ([`eval/results/after/summary.md`](../eval/results/after/summary.md)).
- **The shipped config has news names for only 10 tickers.** `news.py --ticker` refuses any other ticker
  (`bad_input`), so it gets no sentiment until the user adds a name; nothing warns beforehand. The Phase 4 batch adds
  names for its tickers (`eval/config/news_names.json`).
- _Limits of the evaluation itself to be written in Phase 6._

## Proposed next steps (not built)

- Warn when a claimed value matches more than one ledger entry with a different fact or period.
- Validate each source report with verify before using it as a clean baseline in fault injection.
- confidence.py derives each analyst's status from the ledger itself instead of taking it as an argument.
- `stockdesk doctor` warns when a ticker has no news name.
