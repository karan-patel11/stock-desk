# First full desk run: NKE on Slack

Run on 2026-11-05 on the same local Switch server and Slack connection as Stage 0 (`docs/stage0-results.md`).
Template: `switch/desk-team.template.yaml`, params ticker `NKE`, Stock Desk folder = this repo, Python = this repo's
`.venv/bin/python`, Messaging app = `stockdesk Slack`. Slack times are local (EST, UTC-5): 18:07 EST = 23:07 UTC.
Evidence below is what the user showed or pasted from Slack, plus checks I ran on the local evidence ledger.

## Result: the run completed and closed

| Check | Result | Evidence |
|---|---|---|
| Template imported and used, no error | PASS | Templates > Import template > Save > Use template > Create all; room and four desk agents created |
| Kickoff wakes desk-chief | PASS | `desk-chief` opened run `r-20261105-16` at 18:00 |
| Three analysts report with evidence IDs | PASS | technical, fundamental and sentiment reports posted, every number carries an ID |
| Chief verifies citations | PASS | technical PASS (8/8), fundamental PASS (15/15); sentiment failed twice, corrected, then PASS |
| Two-round cap | PASS | round 2/2 reached; `tools/round.py status` reports `status: ended`, `round 2`, `max_rounds 2` |
| Precedent check | PASS | four events (2 NKE, 2 UAA) with source URLs; mean excess 0.054137 at 5 sessions [E164], 0.04442 at 30 [E166], n = 4 |
| Verdict posted | PASS | `VERDICT - NKE - Neutral/wait - Confidence: low`, with bull, bear, precedent, dissent, view-changers and gaps |
| Verdict saved in the room | PASS | `!list-documents` in the channel lists `desk-rules` and `verdict-NKE-2026-11-05` (room-scoped, created by desk-chief) |

Ledger check on this Mac: 167 evidence entries; spot-checked E103 (39.56 USD), E104, E107, E57 (revenue 11.213B USD,
SEC), E94 (4.066351), E69 (0.019014), E153, E164 to E167. All match what the agents posted. I did not check every number.

## Things worth knowing

- The verifier caught real mistakes: sentiment cited "17%" and "2%" from headline text and a self-counted "20 headlines".
  It corrected both before the chief accepted the report.
- Sentiment could not open the UBS article behind E114 (HTTP 403) and said so. GDELT answered this time, so the
  news call was not rate limited. It is still likely to be refused at times (README, Demo day).
- Operating income and some debt/EPS values were reported as gaps with reasons, not guessed.
- Slack lowercases the channel name: the room is `desk-NKE` in Switch Console and `#desk-nke` in Slack. Agent names
  were unaffected.
- The kickoff thread got 2 replies (the agents' greeting and the chief's session start); the chief then started its
  own top-level message for the run, with 39 replies at the end. Two threads, not one. The desk rule "one thread per
  run" holds for the run itself.
- The run took about seven minutes (18:00 to 18:07 EST).
- No token or secret was entered in chat, written to a file, or committed.

## Still not tested

- A second ticker in the same Switch server (the desk agents already exist; `allow_existing` is unverified).
- Someone other than the owner mentioning the agents (`addressing: owner-agents`).
- A human interrupt mid-run, and the `pause` / `verdict now` commands.
- Memory of an earlier verdict: this run said "No earlier verdict for NKE". A second NKE run in this room should
  find `verdict-NKE-2026-11-05`.
