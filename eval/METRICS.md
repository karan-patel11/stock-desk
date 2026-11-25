# Stock Desk evaluation: metric definitions (pre-registered)

Committed 24 Nov 2026, before any Phase 4 (live batch) run. A metric is not added, dropped or redefined after live
results are seen. A change goes in a new commit to this file with a dated "Changes" entry giving the reason.

These metrics test what Stock Desk claims, not whether its verdicts were right. Forward returns are not measured: the
sample is too small, a historical replay leaks the future (through the model's training data and through tools that
fetch today's data), and the product is research, not advice.

## Claims under test

1. Every number traces to an evidence entry.
2. It fails closed instead of guessing.
3. Confidence follows fixed code rules.
4. It uses no advice language.
5. One Slack thread finishes an analysis in minutes.

## Reporting rules

- Every result is a count with its denominator ("14/15"), never a bare percentage.
- Where a count has zero failures, the rule-of-three 95% upper bound on the failure rate is also given: 3/n.
- Medians are given with n. No mean without its n and the min and max.
- A value that can't be computed from the files is left blank with a note saying why. It is never estimated.

## Inclusion rule

Decided 24 Nov 2026, before anything is scored.

| Set | Runs | Used for |
|---|---|---|
| **Eval batch** | The runs listed in `eval/RUNBOOK.md`'s run sheet for the Phase 4 batch, and only those | All headline metrics (M1–M7, M10) |
| **Pre-eval runs** | 7 Nov 2026 desk runs (driven through Slack by the agents) that reach `end` and have both `verifications.jsonl` and `confidence.json` | Reported separately, labelled "pre-eval runs". Never pooled with the eval batch |
| **Excluded** | Every other run: runs dated before 7 Nov 2026, incomplete runs (no `end`, or missing `verifications.jsonl` or `confidence.json`), and scripted tool checks | No metric. Listed below by id with the reason |
| **Injection corpus** | Every `reports/*.txt` from any run that has an evidence ledger (at least one `E*.json`) | Phase 2 (M8) only |

The pre-eval set under this rule is 3 runs: r-20261107-05 (NKE), r-20261107-11 (AAPL), r-20261107-18 (MSFT).

Excluded runs (as of 24 Nov 2026, repo `evidence/`; `~/.stockdesk/evidence/` did not exist):

| Run | Reason |
|---|---|
| r-20261105-01 … r-20261105-16 (16 runs) | Before 7 Nov. Also: -02, -03, -04, -06, -08, -09 never reach `end`; none have `verifications.jsonl` or `confidence.json` |
| r-20261106-01, r-20261106-02 | Before 7 Nov; no `verifications.jsonl` or `confidence.json` |
| r-20261107-03, -04, -06, -09, -10, -12, -13, -14, -15, -16, -17 | Reach `end` but have no `verifications.jsonl` and no `confidence.json` |
| r-20261107-01, -02, -07, -08 | Scripted tool checks, not desk runs: every verify and confidence call lands within 1–2 seconds (-01: 01:14:24–25; -02: start to end in 2 s; -07: under 1 s with an empty ledger; -08: 4 s, 222 entries written in 3 s); the checked text was planted (a withdrawn "RSI 75.0", "A strong buy.", E5 = "1.0") |

## Files read

Per run, under `<evidence root>/<run>/`:

- `state.json`: `ticker`, `goal`, `history` (list of `{at, event}`, UTC ISO timestamps).
- `verifications.jsonl`: one row per check: `id`, `claimed`, `result` (PASS, FAIL or WITHDRAWN), `detail`,
  `checked_at`. Rows written after commit 5f51d81 (24 Nov 2026) also have `source`, `source_sha256`, and on ADVICE
  rows `numbers` and `uncited`. Pre-eval runs have none of these keys.
- `confidence.json`: per horizon `direction`, `confidence`, `reasons`, `citations` ("p/c"), `uncorrected`,
  `inputs` (`fund`, `tech`, `sent`, `precedent_events`), `computed_at`.
- `reports/`: report files written by the chief.
- `E*.json`: the evidence ledger.

**Analyst report file:** a file in `reports/` named `<analyst>-r<N>.txt` or `<analyst>-r<N><letters>.txt`, where
`<analyst>` is `fundamental`, `technical` or `sentiment`. A letter suffix is a correction posted under its own name
(e.g. `technical-r2c.txt`) and counts as its own source file. **Card file:** `reports/card-draft.txt`. Other files
in `reports/` (verdict documents, evidence exports) are not reports for these metrics.

**Final-round report:** an analyst report file whose round `N` is the highest round of that analyst in that run.

**Report check:** one `verify --text-file` call. In the log it is a contiguous block of rows with the same `source`
and `source_sha256`, ending with its ADVICE row. ADVICE is always written last in report mode, so the ADVICE row
closes the block. A block whose rows are interleaved with another source's rows is flagged in `notes` and not
scored for M3 or M5.

## Metrics

### M1: Run completed (claim 5)

`state.json` `history` contains an event equal to `end`. Values: yes or no. Reported as completed/runs.

### M2: Wall-clock minutes, start to end (claim 5)

`at` of the first `end` event minus `at` of the first event whose text begins with `start`, in minutes (1 decimal).
Blank if either is missing. Reported as the median with n, min and max. Runs with M1 = no are not in the median.

### M3: First-pass citation result per report (claim 1)

For each analyst report file `X` in `reports/`: the **first** report check whose `source` is `X`.

- **PASS** if that check has no FAIL row and its ADVICE row has `uncited` = 0. This is the same rule
  `verify.py` uses for `data.result`.
- **FAIL** otherwise. Every later check of the same source counts as a correction. They are counted
  (`corrections`) but do not change M3.
- **not checked** if no row has `source` = `X`.

Reported as PASS/checked reports, plus not-checked/reports. Computed per analyst and in total.
**Pre-eval runs:** blank, with the note "log predates source field". Rows written before 24 Nov can't be traced to a
report file.

### M4: Final citation pass rate and uncorrected FAILs (claim 1)

`stockdesk.common.citation_summary` on the run's full `verifications.jsonl`: among evidence IDs with at least one
check, minus those whose latest row is WITHDRAWN, the number whose latest row is PASS. Reported as passed/checked per
run and summed. **Uncorrected FAILs** are IDs whose latest row is FAIL, reported as a count per run, plus the
number of runs with one or more.

### M5: Numbers and uncited numbers per report (claim 1; anti-gaming)

A high pass rate from very few numbers is not a win, so the number of figures is reported next to the pass rate.

- **Eval batch:** for each final-round analyst report, from the ADVICE row of that source's **first** check
  (`numbers`, `uncited`) and of its **last** check. Reported as the median numbers per report (n, min, max) and as
  total uncited over total numbers, for first and last checks separately.
- **Pre-eval runs, labelled "final report text":** the saved final-round report file is copied with its run's
  ledger into a temp evidence root, and `verify --text-file` is run on the copy. `numbers` = checked + uncited from
  that output. The real run is never touched. This measures the text as saved, not what the chief checked first.

### M6: Advice scan (claim 4)

From ADVICE rows.

- **Card:** the result of the last report check whose `source` is `card-draft.txt`. Reported as PASS/runs with a
  card. A run with no card check counts as "card not checked".
- **Reports:** for each analyst report source, its first and its last check's ADVICE result. Reported as the number
  of first checks with an ADVICE FAIL, and the number of sources whose last ADVICE is FAIL (expected 0).
- **Pre-eval runs:** ADVICE rows have no source, so only run-level counts are given (ADVICE rows, ADVICE FAILs, and
  whether the run's last ADVICE row is PASS). Per-report and card values are blank, noted "log predates source field".

### M7: Confidence follows the code rule (claim 3)

For each horizon in `confidence.json`:

- **Re-computation:** `confidence.score(horizon, direction, inputs{fund, tech, sent}, precedent_events, citations)`,
  with `citations` rebuilt from the saved values: `uncorrected` as saved, and `all_pass` = passed = checked > 0
  from the saved `citations` "p/c". **M7 match** = re-computed label equals the saved `confidence`.
- **Rule version:** eval batch runs are re-computed with the current rule (CAP, commit 4fa63c8). Pre-eval runs are
  re-computed with the rule in force on 7 Nov (KEEP, frozen copy of `score()` from commit 5f51d81 in `eval/`). The
  CAP label is reported next to it, never in place of it.
- **Ledger consistency (M7b):** `citation_summary` re-derived from the log rows with `checked_at` ≤ `computed_at`
  (second resolution, so rows in the same second are included) must give the saved "p/c" and `uncorrected`. A
  mismatch means confidence.py saw a different log state than the file now implies, and is reported, not hidden.
- Reported as matching horizons/horizons computed, for M7 and M7b separately. Also the label distribution
  (low/medium/high per horizon).

Not checked by M7: whether the stances the chief passed equal the stances the analysts wrote. That is a chief
behaviour, not a confidence-rule property.

### M8: Verifier fault detection (claim 1; Phase 2)

From `eval/results/injection.csv`, produced by `eval/inject.py --seed 7` on copies of the injection corpus.

- **Detection rate** per corruption type (`off_small`, `off_large`, `unit_swap`, `wrong_id`, `missing_id`,
  `uncited`, `advice`): variants where `verify --text-file` returned `result` FAIL / variants of that type.
- **False-alarm rate:** variants of type `clean` or `legit_round` where `result` was FAIL / variants of that type.
- `wrong_id` variants where the substituted entry's stored value would match the displayed figure within its
  display rounding are labelled `wrong_id_similar`. They are reported in their own row, never pooled into
  `wrong_id` and never dropped.

### M9: Fail-closed cases (claim 2; Phase 3)

The tests in `tests/test_fail_closed.py`, one per case in the Phase 3 list. Run offline with pytest's
`--junitxml`, parsed with `xml.etree`. Reported as passed/cases. Case 6 (partial bar) documents observed behaviour
and is reported as "documented", not as pass or fail.

### M10: Outlook stability (claim 3; Phase 4)

The 3 same-day NKE runs in the eval batch. For each horizon (short, medium, long), stable = the 3 runs'
`confidence.json` `direction` values are identical. Reported as stable horizons/3. **M10b:** the same for the
`confidence` label. Reported alongside, never instead.

### M11: Unsupported qualitative claims (claim 1 gap; Phase 5)

`verify.py` checks numbers only. `eval/extract_claims.py` lists sentences in final-round analyst reports (eval
batch) that make a factual or causal claim with no number. Up to 40 are sampled (seeded) across analysts. Each is
labelled by hand by one person: `supported`, `unsupported` or `not_checkable`. No LLM judging, no pre-filled labels.
Reported as counts per label per analyst, with the sample size.

## Changes

- **24 Nov 2026, before any eval run or scoring:** pre-eval set narrowed from 7 runs to the 3 desk runs.
  r-20261107-01, -02, -07 and -08 meet the file rule but are scripted tool checks (timings and planted text above),
  so they say nothing about how the desk behaves. Decided by the project owner after the run timings were checked.
