# Stage 0: mention test runbook

Goal: prove on a real Switch server that agent mentions, threads and room documents work, before the desk is built
on them. Every step below cites the Switch doc it comes from, as a path in
[sandbox-quantum/switch](https://github.com/sandbox-quantum/switch) (read at commit `9619bc9`). Where the docs do not
settle something, the step says **unverified**.

Template: run `stockdesk template --mention-test` (writes `mention-test.template.yaml`; the source is
`src/stockdesk/data/templates/mention-test.template.yaml`). It creates `s0-chief` and `s0-technical` (Claude Code, this
computer) and a room `desk-mention-test` on the messaging app you pick on the form. They stand in for desk-chief and
desk-technical: the mention mechanics are the same, and separate names keep Stage 0 from blocking the desk template
(see [After Stage 0](#after-stage-0)).

**Messaging app: Slack.** The built-in Mattermost is the fallback only, in [its own section](#fallback-mattermost).

## What you need on this Mac

| Need | Doc | Status on this Mac (checked 2026-11-05) |
|---|---|---|
| Node.js 20 or later | `docs/official/getting-started/index.md`: "you need **Node.js 20 or later** on your own computer" | v22.14.0 |
| An agent provider account (Claude Code) | same page: "Switch Console can install the tool for you, but it can't provide the account" | Claude Code 2.1.310, signed in through claude.ai |
| A Slack workspace that lets you install a custom app | `deploy/messaging-apps/slack.md`: "A Slack workspace where you can install a custom app. Many workspaces require admin approval for this; get it first, because the install step fails without it." | check before you start |
| Admin on the Switch server | same page: "An admin account on the Switch server you're connecting to. If Switch Console set that server up for you, you have one." | you, on a local server |
| Docker: **not needed for Slack** | `getting-started/add-a-server.md`: "Without Docker the server works the same, just with no built-in messaging app — you can still connect Slack, Discord, Telegram, or Microsoft Teams to it." | needed only for the Mattermost fallback |

No public address is needed. `deploy/messaging-apps/slack.md`: "Slack reaches Switch over a connection Switch opens
outwards, so **nothing needs to be publicly reachable**. This works from a laptop."

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
3. Select **Add a server** > **Run a server on this computer** (`getting-started/add-a-server.md`). For Slack, Docker
   does not have to be running. **Also run Mattermost** is on by default only "If Docker (with its Compose plugin) is
   installed and running" (same page); leaving it on keeps the fallback ready.
4. Confirm: the server's label at the top of the sidebar reads **Running locally** (same page, "Confirm it worked").

Keep the Mac awake for the whole test. `deploy/connect-agents/switch-console.md`: "An agent registered to run on this
computer answers while this computer is awake and Switch Console is running."

## A2. Connect Slack

Source for every step: `deploy/messaging-apps/slack.md`. You enter the tokens in Slack and in Switch Console yourself;
never paste them into a chat, a file in this repo, or a commit.

Two documented routes. The guide recommends the Console one: "**Using Switch Console?** Choose **Connect a messaging
app → Use your own app instead → Slack**. Console opens Slack with the app below already filled in, checks your two
tokens as you paste them, and fills in the workspace ID for you. The steps here are for setting it up by hand."
**Unverified:** where **Connect a messaging app** sits in the Console; the guide does not say. If you cannot find it,
use the by-hand route below.

By hand:

1. **Create the app from the manifest.** "Go to [Slack API apps](https://api.slack.com/apps), select **Create New
   App**, then **From an app manifest**. Choose your workspace, paste the manifest below, and create the app." The
   manifest is the **Agent Switch app manifest** in the guide; "The manifest configures the permissions, the events,
   the Switch slash commands, Socket Mode and the app home in one step".
   Guests warning: "Declaring the app an Agent removes access to it for workspace guests, and turns every direct
   message with it into a thread." If your workspace has guests, the guide says to delete the `agent_view` block
   before pasting.
2. **App-level token (Socket Mode).** "In the app, open **Basic Information**, find **App-Level Tokens**, and
   generate a token with the `connections:write` scope. It starts with `xapp-`."
3. **Install and get the bot token.** "Select **Install App** and install it to your workspace. Copy the **Bot User
   OAuth Token** — it starts with `xoxb-`."
4. **Workspace id.** "You need the workspace (team) id, which starts with `T`. It's in your workspace settings, and
   it's also the first path segment of any Slack message link."
5. **Connect in Switch Console.** "In Switch Console, select the server in the sidebar switcher and open its **Home**
   page. **Messaging apps** lists what's connected." Then "Select **Connect**, then choose **Slack** under **Messaging
   app**."
6. **Name the connection.** The guide says to "name it after the workspace". Write the name down: it is the value you
   pick for the template's **Messaging app** input (`docs/TEMPLATES.md`: a bridge param is "The display name of a
   messaging app set up on the server").
7. **Paste the three values** into **Bot Token**, **App Token** and **Workspace Id**. "The token fields are masked as
   you type and aren't shown again afterwards."
8. **Leave Allow creating channels from Switch on.** "**Allow creating channels from Switch** is on by default, and
   it's what lets a room created in Switch — by you or by an agent — get a Slack channel to go with it." The template
   creates the room, so this is how `desk-mention-test` gets its channel.
9. **Agent name autocomplete** is optional. It "needs a paid Slack plan and permission for the bot to manage user
   groups". Without it you type `@s0-chief` in full.
10. **Connect.** "Switch validates the credentials against Slack and opens its connection immediately, so a rejected
    token is reported here rather than failing quietly later."
11. **Link your Slack account.** "Switch Console then asks which Slack account is yours. Search for yourself and select
    **This is me**." Required here: both agents use `addressing: owner-agents`, and
    `getting-started/onboard-your-agents.md` says "Until it is, a message from you reads as a message from a stranger:
    the agent refuses the work".
12. **Confirm.** "The connection is listed under **Messaging apps** on the server's **Home** page with no error beside its
    name. A connection that failed to start shows its status there in red."

Inviting the app to an existing channel (`/invite @Agent Switch`) turns that channel into a room; Stage 0 does not
need it, because the template creates its own room and channel.

## B. Connect the Console to this machine's Claude Code

There is no separate connect step for a local agent: Switch Console starts sessions itself.
`deploy/connect-agents/switch-console.md`: "Address an agent with no session running and Switch Console starts one".

1. **Settings** > **Agent providers**: Claude Code should read **Installed**; if not, install it there
   (`getting-started/set-up-agent-providers.md`).
2. **Settings** > **General**: leave **Auto-trust worktree directories** on. Same page: "a session waiting on that
   confirmation never starts."
3. Your Slack account is linked (A2 step 11). It can also be done later on the server's **Home** page under
   **Messaging apps** (`getting-started/add-a-server.md`).
4. The Stock Desk venv is not needed for Stage 0 (the test runs no Python). It matters in the full run, where the
   template's `python` param points at it.

## C. Load the mention-test template

`docs/TEMPLATES.md`: "Switch Console reads it on the Templates page, builds one form from its `params:` block, and
creates everything in one pass." and "One click creates the agent, then the room with the agent and the deployer in
it, then posts the kickoff."

1. Run `stockdesk template --mention-test`, then open **Templates** in Switch Console and use the contents of the
   `mention-test.template.yaml` it wrote.
   **Unverified:** the click path for a document of your own. The docs name the Templates page, and a Use page that a
   document can be pasted into (`docs/TEMPLATES.md`, Version 2: "the same with its instructions inline, to paste
   into the Use page"), but give no click-by-click steps.
2. The form has one input, **Messaging app**: pick the Slack connection by the name from A2 step 6. It has no default,
   so it is required (`docs/TEMPLATES.md`, `required`: "true when there is no default"). If the form offers to link
   your account, accept: "A template that puts `{$creator}` in a bridged room needs the deployer to have linked their
   account on that messaging app; the form says so and offers to link it." (`docs/TEMPLATES.md`).
3. Create. If the run is refused, the reason names the problem; `docs/TEMPLATES.md` lists codes such as
   `provider_not_installed`, `provider_login_missing` and `name_taken`.
4. Open the new channel in Slack, not only in Switch Console (`getting-started/smoke-test.md`: "Open the channel, not
   Switch Console."). **Unverified:** the exact channel name; the docs do not say how a room name becomes a Slack
   channel name.

## D. Check the pass criteria

Tick each one in order. If a step fails, stop and use the table at the end. In Slack, type agent names in full:
"Slack doesn't complete it, doesn't turn it into a pill, and a typo looks exactly like an agent ignoring you."
(`deploy/messaging-apps/slack.md`). A message an agent is working on is marked: "The message that asked is marked
with 👀 during the turn." (same page).

- [ ] **1. Kickoff wakes s0-chief.** The kickoff is "Posted into the room on behalf of the deployer once the room
  exists and its members have joined. An agent starts working when a message addresses it" (`docs/TEMPLATES.md`,
  Kickoff). You see s0-chief reply.
- [ ] **2. s0-chief mentions s0-technical**, in a message containing `@s0-technical` and PONG.
- [ ] **3. s0-technical replies** `@s0-chief PONG`.
- [ ] **4. The reply wakes s0-chief**, which posts `MENTION TEST PASSED`.
- [ ] **5. One thread.** All of the above sits under the kickoff in one thread. Basis:
  `internals/collaboration-bridge.md`, "A reply carries the event id it replies to. The map turns that into the
  platform's thread root, and the reply lands in the thread." **Unverified:** whether the kickoff itself starts a thread
  or sits at the channel top level; the docs do not say. Write down which you see.
- [ ] **6. A mid-thread human message gets a reply.** In the same thread, post
  `@s0-chief are you still there?`. Include the mention: `using/what-comes-back.md` lists "you replied in a thread
  without repeating the address" as a cause of silence. Expect a line starting `HEARD YOU:`.
- [ ] **7. Room document created.** After `MENTION TEST PASSED`, s0-chief posts `DOCUMENT CREATED: stage0-check`.
  Then send `!list-documents` in the channel; `stage0-check` should be listed. `using/shared-context.md`: "Post
  `!list-documents` in the channel to see what the room holds at all ... The documents live on the Switch server".
- [ ] **8. It survives a second run.** Clear s0-chief's memory with `!reset @s0-chief` ("Clears an agent's context
  and reconnects it.", `resources/room-commands.md`), then post a new message in the **same room**:
  `@s0-chief test the mention again: ask @s0-technical to reply PONG and wait for it.`
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
| Slack connection shows red under **Messaging apps**, or Connect reports a rejected token | Wrong or swapped token, or the app is not installed to the workspace | `deploy/messaging-apps/slack.md`, "Connect" and "Confirm it worked" |
| Install step fails in Slack | The workspace needs admin approval for custom apps | `deploy/messaging-apps/slack.md`, "Before you begin" |
| No **Connect** button on the server's Home page | Signed in without admin rights: "Connecting a messaging app is an administrator action" | `deploy/messaging-apps/slack.md` |
| Template creates no Slack channel | **Allow creating channels from Switch** is off on the connection | `deploy/messaging-apps/slack.md`, A2 step 8 |
| Nothing at all after the kickoff or a message | The message addressed nobody (missing `@`, misspelled name, or a thread reply without the mention), or a session is not receiving room events | `using/what-comes-back.md`; `resources/troubleshooting.md`, "Agent is connected but never answers" |
| Agent says it only takes instructions from its owner / account not linked | Slack account not linked | `getting-started/smoke-test.md`, "When a step doesn't match"; A2 step 11 |
| Agent says it is not available / no session connected | Nothing running behind it; Switch answered for it | `getting-started/smoke-test.md`; post `!run-cmd @s0-chief` for the start command (`using/what-comes-back.md`) |
| Switch Console: "Session did not start" | Claude Code is waiting on a trust or permission prompt in that session's terminal | `resources/troubleshooting.md` |
| Agent never wakes, or "not found" naming Claude Code's built-in subagents | Missing `.claude/agents/<name>.md` in the agent's working directory | `resources/troubleshooting.md`, "Agent not found on launch" |
| s0-technical never answers s0-chief | Addressing does not admit s0-chief, or s0-technical has no session | `getting-started/onboard-your-agents.md`, "Only me and my agents admits the agents you own"; `!agents-status` |
| Every room stops responding | Network change (VPN, sleep) | `resources/troubleshooting.md`, "Every room stops responding" |
| Template refused with `name_taken` | s0-chief or s0-technical already exists (the template was loaded before); use the existing room, step 8 | `docs/TEMPLATES.md`, The agent block |

## Fallback: Mattermost

Use this only if Slack cannot be made to work in the time box.

1. Start Docker Desktop. The built-in Mattermost needs it: "If Docker (with its Compose plugin) is installed and
   running, **Also run Mattermost** is on by default" (`getting-started/add-a-server.md`). On a server that is already
   running, "You can turn it on or off later from the server's page; the change applies straight away, without
   restarting the server." (same page).
2. Link your Mattermost account on the server's **Home** page under **Messaging apps** (`getting-started/add-a-server.md`).
3. Load the template as in C, and pick the Mattermost connection for **Messaging app**.
4. Open the room in Mattermost: "If Switch Console set your server up, the messaging app is a Mattermost it started
   alongside it. Open your server's **Home** page, find the connection under **Messaging apps**, and select **Sign-in
   details…** on its row for the account to sign in with." (`getting-started/smoke-test.md`).
5. Check the criteria in D the same way.

## After Stage 0

The Stage 0 agents are named `s0-chief` and `s0-technical` so they do not collide with the desk's `desk-chief`,
`desk-fundamental`, `desk-technical` and `desk-sentiment`. Per `docs/TEMPLATES.md`, an existing name "blocks creation
with a message; nothing is renamed behind the deployer's back", so the desk template can be loaded on the same server
after Stage 0. The Stage 0 agents can stay registered; the Switch docs describe removing an agent from a room
(`!remove-agent`, `resources/room-commands.md`) but not deleting a registered agent.

Loading the desk template a second time (for another ticker) hits the same rule for the four desk agents.
**Unverified:** whether `allow_existing: true` ("lets the deployer fill it with an agent the server already has instead
of creating it", `docs/TEMPLATES.md`) would let a second load reuse them. Settle it before the second ticker.
