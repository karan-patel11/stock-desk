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

_Results tables to be written in Phase 6._

### Clean reports that fail, with the pre-registered label kept

After the URL fix, 2 of 34 reports still fail verify unchanged, so their `clean` (and `legit_round`) variants count
as false alarms. The labels stay as pre-registered ("clean: expected PASS"); the reasons are recorded here instead.

- **`r-20261105-16/desk-sentiment-r1.txt`: a quoted headline number.** The report quotes headlines such as
  "Up 17% Off Its 52-Week Low" [E133] and "NIKE Shares Up 2%" [E128]. The cited entries are news articles whose
  stored value is text, so no entry holds 17% or 2%, and verify fails the line. This is correct behaviour: a number
  inside a quoted headline is still a figure the reader sees without verification. Not changed.
- **`r-20261107-02/technical-r1.txt`: the report is wrong.** It contains "RSI(14) at 75.0 [E169]" against a stored
  61.050897, planted by a scripted tool check (that run is excluded from all run metrics; see METRICS.md). Its
  reports stay in the injection corpus under the pre-registered rule.

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

## Bugs found

| Bug | Found by | Fix | Before | After |
|---|---|---|---|---|
| Digits inside a URL counted as uncited numbers | Phase 1 (M5) and Phase 2 (false alarms) | commit 8e62c76, with regression tests | false alarms 7/61; pre-eval M5 uncited 2/26 numbers | false alarms 4/61; pre-eval M5 uncited 0/24 |

(Counts from `eval/results/before_after.md`.)

## Known limits

- **verify checks values, not which fact or period a value belongs to.** A figure cited to the wrong entry passes
  when that entry happens to hold the same value (misattribution detection 0/3 above).
- _Limits of the evaluation itself to be written in Phase 6._

## Proposed next steps (not built)

- Warn when a claimed value matches more than one ledger entry with a different fact or period.
