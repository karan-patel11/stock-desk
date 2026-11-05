# Stage 0: mention test runbook

Goal: prove on a real Switch server that agent mentions, threads and room documents work, before the desk is built
on them. Every step below cites the Switch doc it comes from, as a path in
[sandbox-quantum/switch](https://github.com/sandbox-quantum/switch) (read at commit `9619bc9`). Where the docs do not
settle something, the step says **unverified**.

Template: `switch/mention-test.template.yaml`. It creates `desk-chief` and `desk-technical` (Claude Code, this
computer) and a room `desk-mention-test` on the server's default messaging app.

## What you need on this Mac

| Need | Doc | Status on this Mac (checked 2026-11-05) |
|---|---|---|
| Node.js 20 or later | `docs/official/getting-started/index.md`: "you need **Node.js 20 or later** on your own computer" | v22.14.0 |
| An agent provider account (Claude Code) | same page: "Switch Console can install the tool for you, but it can't provide the account" | Claude Code 2.1.310 installed |
| Docker, only for the built-in Mattermost | `getting-started/add-a-server.md`: "If Docker (with its Compose plugin) is installed and running, **Also run Mattermost** is on by default" | Docker 28.5.1 installed; start Docker Desktop first |

## A. Run a Switch server

**Fastest for one person: let Switch Console run the server on this computer.**
`docs/official/getting-started/add-a-server.md`: "**Run a server on this computer** ... No Docker needed. Best for
trying Switch out." and "There is no URL to copy and no secret to enter. A first setup takes about a minute."
`docs/official/deploy/index.md` lists this option for "You're trying Switch out, or your agents only need to answer
while your own computer is on."

The other options are slower for one person: a remote host needs "SSH access to a host you've onboarded, with Docker
installed on it" (`getting-started/index.md`), and self-hosting needs "A Linux machine you administer, a name it
answers on, and a certificate" (`deploy/index.md`), with the steps kept in the repository rather than the docs
(`deploy/self-host.md`).

**Railway:** the Switch repository has no Railway template or Railway docs (a search of the whole repo finds the word
nowhere). Do not plan on it unless someone gives you a link to one.

Steps:

1. Install Switch Console: download the release for macOS from
   [the releases page](https://github.com/sandbox-quantum/switch/releases), `arm64` for Apple silicon, `x64` for Intel
   (`getting-started/install-switch-console.md`).
2. Open it. The **Setting up Switch** checklist appears in the sidebar (same page).
3. Start Docker Desktop, then select **Add a server** > **Run a server on this computer**. Leave **Also run Mattermost**
   on (`getting-started/add-a-server.md`).
4. Confirm: the server's label at the top of the sidebar reads **Running locally** (same page, "Confirm it worked").

Keep the Mac awake for the whole test. `deploy/connect-agents/switch-console.md`: "An agent registered to run on this
computer answers while this computer is awake and Switch Console is running."

## B. Connect the Console to this machine's Claude Code

There is no separate connect step for a local agent: Switch Console starts sessions itself.
`deploy/connect-agents/switch-console.md`: "Address an agent with no session running and Switch Console starts one".

1. **Settings** > **Agent providers**: Claude Code should read **Installed**; if not, install it there
   (`getting-started/set-up-agent-providers.md`).
2. **Settings** > **General**: leave **Auto-trust worktree directories** on. Same page: "a session waiting on that
   confirmation never starts."
3. **Link your messaging account** on the server's **Home** page > **Messaging apps** > **Link** > search yourself >
   **This is me** (`getting-started/add-a-server.md`). Required: both agents use `addressing: owner-agents`, and
   `getting-started/onboard-your-agents.md` says "Until it is, a message from you reads as a message from a stranger:
   the agent refuses the work".
4. The Stock Desk venv is not needed for Stage 0 (the test runs no Python). It matters in the full run, where the
   template's `python` param points at it.

## C. Load the mention-test template

`docs/TEMPLATES.md`: "Switch Console reads it on the Templates page, builds one form from its `params:` block, and
creates everything in one pass." and "One click creates the agent, then the room with the agent and the deployer in
it, then posts the kickoff."

1. Open **Templates** in Switch Console and use the contents of `switch/mention-test.template.yaml`.
   **Unverified:** the click path for a document of your own. The docs name the Templates page, and a Use page that a
   document can be pasted into (`docs/TEMPLATES.md`, Version 2: "the same with its instructions inline, to paste
   into the Use page"), but give no click-by-click steps.
2. The form has no inputs (the template declares no params). If it offers to link your account, accept:
   "A template that puts `{$creator}` in a bridged room needs the deployer to have linked their account on that
   messaging app; the form says so and offers to link it." (`docs/TEMPLATES.md`).
3. Create. If the run is refused, the reason names the problem; `docs/TEMPLATES.md` lists codes such as
   `provider_not_installed`, `provider_login_missing` and `name_taken`.
4. Open the room in the messaging app, not only in Switch Console (`getting-started/smoke-test.md`). For the built-in
   Mattermost: server **Home** > **Messaging apps** > **Sign-in details…** (same page).

## D. Check the pass criteria

Tick each one in order. If a step fails, stop and use the table at the end.

- [ ] **1. Kickoff wakes desk-chief.** The kickoff is "Posted into the room on behalf of the deployer once the room
  exists and its members have joined. An agent starts working when a message addresses it" (`docs/TEMPLATES.md`,
  Kickoff). You see desk-chief reply.
- [ ] **2. desk-chief mentions desk-technical**, in a message containing `@desk-technical` and PONG.
- [ ] **3. desk-technical replies** `@desk-chief PONG`.
- [ ] **4. The reply wakes desk-chief**, which posts `MENTION TEST PASSED`.
- [ ] **5. One thread.** All of the above sits under the kickoff in one thread. Basis:
  `internals/collaboration-bridge.md`, "A reply carries the event id it replies to. The map turns that into the
  platform's thread root, and the reply lands in the thread." **Unverified:** whether the kickoff itself starts a thread
  or sits at the channel top level; the docs do not say. Write down which you see.
- [ ] **6. A mid-thread human message gets a reply.** In the same thread, post
  `@desk-chief are you still there?`. Include the mention: `using/what-comes-back.md` lists "you replied in a thread
  without repeating the address" as a cause of silence. Expect a line starting `HEARD YOU:`.
- [ ] **7. Room document created.** After `MENTION TEST PASSED`, desk-chief posts `DOCUMENT CREATED: stage0-check`.
  Then send `!list-documents` in the channel; `stage0-check` should be listed. `using/shared-context.md`: "Post
  `!list-documents` in the channel to see what the room holds at all ... The documents live on the Switch server".
- [ ] **8. It survives a second run.** Clear desk-chief's memory with `!reset @desk-chief` ("Clears an agent's context
  and reconnects it.", `resources/room-commands.md`), then post a new message in the **same room**:
  `@desk-chief test the mention again: ask @desk-technical to reply PONG and wait for it.`
  Expect `MENTION TEST PASSED` and `DOCUMENT FOUND: stage0-check`, and `!list-documents` still lists it.

Why the same room, not loading the template again: a room-scoped document "lives and dies with the room"
(`internals/rooms-and-resources.md`), and loading the template again would try to create agents that already exist:
"A name that an agent on the server already has blocks creation with a message" (`docs/TEMPLATES.md`).

Stage 0 passes when all eight boxes are ticked.

## When a step does not match

`!agents-status` is the first check: "You get a line per agent: 🟢 live, ⚪ no session, 🔴 disconnected, or 🟡 awaiting
a manual poll." (`using/what-comes-back.md`).

| What you see | Likely cause | Doc |
|---|---|---|
| Nothing at all after the kickoff or a message | The message addressed nobody (missing `@`, misspelled name, or a thread reply without the mention), or a session is not receiving room events | `using/what-comes-back.md`; `resources/troubleshooting.md`, "Agent is connected but never answers" |
| Agent says it only takes instructions from its owner / account not linked | Messaging account not linked | `getting-started/smoke-test.md`, "When a step doesn't match"; step B3 |
| Agent says it is not available / no session connected | Nothing running behind it; Switch answered for it | `getting-started/smoke-test.md`; post `!run-cmd @desk-chief` for the start command (`using/what-comes-back.md`) |
| Switch Console: "Session did not start" | Claude Code is waiting on a trust or permission prompt in that session's terminal | `resources/troubleshooting.md` |
| Agent never wakes, or "not found" naming Claude Code's built-in subagents | Missing `.claude/agents/<name>.md` in the agent's working directory | `resources/troubleshooting.md`, "Agent not found on launch" |
| desk-technical never answers desk-chief | Addressing does not admit desk-chief, or desk-technical has no session | `getting-started/onboard-your-agents.md`, "Only me and my agents admits the agents you own"; `!agents-status` |
| Every room stops responding | Network change (VPN, sleep) | `resources/troubleshooting.md`, "Every room stops responding" |
| Template refused with `name_taken` | desk-chief or desk-technical already exists on the server | `docs/TEMPLATES.md`, The agent block |

## After Stage 0

The full desk (`switch/desk-team.template.yaml`) uses the same agent names. Per `docs/TEMPLATES.md`, an existing name
"blocks creation with a message; nothing is renamed behind the deployer's back". The Switch docs describe removing an
agent from a room (`!remove-agent`, `resources/room-commands.md`) but not deleting a registered agent, so settle this
before loading the desk template.
