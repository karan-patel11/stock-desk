# Stage 0 results

Run on 2026-11-05 on a local Switch server (Switch Console 0.40.1), Slack as the messaging app, template
`switch/mention-test.template.yaml`. Slack times are local (EST, UTC-5): 17:23 EST = 22:23 UTC.
Every PASS below is from what the user reported or showed in Slack, not from logs I read.

## Result: all five criteria PASS, no failures

| # | Criterion | Result | Evidence (Slack, EST) |
|---|---|---|---|
| a | Kickoff wakes s0-chief | PASS | 17:23: kickoff "Template kickoff on behalf of @karanp1" posted; s0-chief answered with "Starting a session" and then worked (9s, 2 tool calls) |
| b | s0-chief mentions s0-technical, it replies PONG, the reply wakes s0-chief | PASS | s0-chief posted `@s0-technical Mention test: please reply...`; s0-technical replied `@s0-chief PONG`; s0-chief then posted `MENTION TEST PASSED` |
| c | Everything in one thread | PASS | All 9 replies of the first run sit under the one kickoff message; no stray top-level replies |
| d | Mid-thread human message gets a reply | PASS | After run 1 (time not shown): user posted `@s0-chief are you still there?` in the thread; s0-chief replied `HEARD YOU: checking if I'm still here. Yes. The mention test passed and stage0-check was created.` |
| e | Agent-created room document persists across a second run | PASS | First run: `DOCUMENT CREATED: stage0-check`. 17:35: `!list-documents` in the channel listed `stage0-check` (room-scoped, created by s0-chief). 17:41: `!reset @s0-chief`. 17:42: new top-level request in the same room; thread showed `MENTION TEST PASSED` and `DOCUMENT FOUND: stage0-check` (no second `DOCUMENT CREATED`). 17:45: `!list-documents` again listed `stage0-check` |

Errors: none seen during the Stage 0 run. No exact error text to record.

## Timeline

- Slack connection finished before the template step. The exact connect time is not recorded: an earlier note said
  about 20:56 UTC, but the clock read 22:22 UTC when the template form was filled in, so that note was an estimate.
- ~22:22 UTC: template form ready, **Create all** clicked soon after.
- 22:23 UTC (17:23 EST): room `desk-mention-test` created, kickoff posted, run 1 completed within the same minute or so.
- 22:45 UTC (17:45 EST): last check (`!list-documents` after the reset) done.

## What this settles (previously unverified)

- Click path for a template of your own: Templates, Import template, Choose file (or paste YAML), Save (name,
  who can use it), Use template, pick the connection, Create all.
- The kickoff posts at the channel top level, as "Agent Switch", and the agents' replies go into a thread under it.
- A bridge param shows the Slack connection (Name `stockdesk Slack`) and the room is created on it.
- The room name `desk-mention-test` stays lowercase as written. A room name with an **upper-case** ticker
  (`desk-{ticker}`) is still **unverified**.
- Agents wake on a plain-text `@s0-chief` typed in Slack. No separate agent definition files were needed.
- `!list-documents` and `!reset @agent` work in the channel and reply in a thread under the command.
- Room documents survive `!reset` of the agent in the same room.

## Observations and deviations

- The kickoff names both agents, so s0-technical also woke on the kickoff ("Worked for 4s") and posted nothing
  visible. Harmless here. The desk template's kickoff names only desk-chief.
- The user posted two stray messages: a runbook sentence pasted into the channel (17:44), and `!list-documents` once
  into the local terminal instead of Slack (no effect). Neither woke an agent.
- The Console wording differs from the Switch docs in places (setup screens, "Local Switch server"); no behavior
  conflict was found.
- The `switch-buddy-admin` agent card showed "stopping" once during setup and was green afterwards. Not traced.
- The agent statements ("the document is still here") were not treated as evidence; only the posted marker lines
  and `!list-documents` output were.
- No token, workspace id or secret was entered in chat, written to a file, or committed.

## Not tested in Stage 0

- The Stock Desk template (`switch/desk-team.template.yaml`) has not been loaded or run.
- Slack agent-name autocomplete (free plan; names are typed in full).
- Whether a non-owner user can trigger the agents (`addressing: owner-agents`).

## Next

Load `switch/desk-team.template.yaml` with the same Slack connection (see `docs/stage0.md`, "After Stage 0").
