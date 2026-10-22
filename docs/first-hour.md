# Your first hour with SecondChair

This page takes you from nothing installed to a prepared, played and wrapped session. It assumes you are comfortable with a terminal and with YAML, and that you run Pathfinder 2e on Foundry VTT v14. Each step gives the command and what you should see. Allow about an hour; the longest waits are your agent working.

Two ideas to hold on to. You decide: agents propose, and nothing becomes canon until you confirm it. And the **Core**, the program you start in step 3, is the only door to your campaign: agents and Foundry both go through it.

You need: Python 3.14 or later, [uv](https://docs.astral.sh/uv/), Claude Code or Codex, and a Foundry v14 world you administer.

## 1. Install

```sh
uv tool install "secondchair @ git+https://github.com/Hugo-Grellier/SecondChair@main"
secondchair --help
```

`@main` is the head of the repository, not a pinned release; there are no release tags yet, so a later install may differ from this page.

You should see a usage line and the list of commands (`init`, `serve`, `token`, `host`, `status`, and so on). If `secondchair` is not found, add uv's tool directory to your `PATH` (`uv tool update-shell`) and open a new terminal.

## 2. Create the campaign workspace

```sh
secondchair init ~/campaigns/my-campaign --language en --calendar absalom
```

You should see `Created campaign workspace … (campaign language en)`. The directory holds your campaign: Markdown and YAML files that you own and can put under git. The language and the calendar cannot be changed later, so pick them now. `absalom` is the Pathfinder calendar; the other option is your own YAML calendar file (see `secondchair init --help`).

`init` ends by printing the next steps (serve, connect your agent, Foundry token, open your agent). They are the steps 3 to 5 below, with the commands filled in for your workspace. At any time `secondchair status` says where the campaign stands and what to do next. Commands below take `-w <workspace>`, or run from inside the workspace; the rest of this page assumes you are in it:

```sh
cd ~/campaigns/my-campaign
```

## 3. Start the Core

```sh
secondchair serve -w ~/campaigns/my-campaign
```

You should see `Serving … on http://127.0.0.1:7240` and a line with the review page address. Leave this terminal open for the whole hour. The Core listens on your computer only. Open `http://127.0.0.1:7240/` in a browser: it is a read-only page for pending proposals, the action log and your prep. If the port is taken, set `port:` in `~/.config/secondchair/config.yaml`.

## 4. Connect your agent

In a second terminal:

```sh
secondchair host setup claude        # or: secondchair host setup codex
```

It prints, and never applies, two things: the command or config that adds the Core's MCP server (`http://127.0.0.1:7240/mcp`) to your agent, and the commands that install the SecondChair playbooks. For Claude Code that is `claude mcp add --scope user --transport http secondchair http://127.0.0.1:7240/mcp` plus `claude plugin marketplace add …` and `claude plugin install …` lines. Copy the lines exactly as printed, one block at a time: the paths in them are specific to your machine.

Check the whole setup with one command (with `serve` still running):

```sh
secondchair check-setup
```

It prints one line per check: `ok`, `WARN` (worth knowing, not blocking) or `FAIL`, and under each warning or failure a `Fix:` line with the command to run. It covers the workspace, the campaign date, the Core answering on its port, the Foundry token, your agent host (registers the Core, has the playbooks), a configured runner and the transcription engine. It ends with the `status` summary and exits 1 if anything failed. Two things are expected at this point: `WARN campaign date not set` (step 6 fixes it) and `WARN no runner configured` (optional; your agent can start jobs). Fix every `FAIL` before going on, then run it again. The Foundry connection itself is checked in step 5.

Then check the agent end to end: open your agent in the workspace (`cd ~/campaigns/my-campaign && claude`) and ask "what do you know about this campaign?". It should call SecondChair and tell you the campaign is empty, in English. If it cannot see SecondChair, `serve` is not running or the MCP command was not applied; restart the agent after applying it.

## 5. Connect Foundry

Get the token:

```sh
secondchair token
```

You should see a line of explanation and a token. It is created once and kept readable only by you. Then, in Foundry:

1. Setup screen, **Install Module**, paste `https://raw.githubusercontent.com/Hugo-Grellier/SecondChair/main/foundry/secondchair-foundry/module.json`.
2. Install the PF2e companion the same way: `https://raw.githubusercontent.com/Hugo-Grellier/SecondChair/main/foundry/secondchair-foundry-pf2e/module.json`.
3. Enable both in your world, log in as GM, **Configure Settings, SecondChair**, paste the token into **Core token**.
4. Reload.

You should see a notification, "connected to the Core", and the **Director's Desk** window open. If your browser asks whether the Foundry site may connect to services on your computer, allow it. Details and the delegation ceiling are in the [Foundry setup](../foundry/README.md).

## 6. Set the date and talk your first idea through

The campaign needs a current date before play. This command needs a real terminal (agents cannot run it):

```sh
secondchair date 4726-03-14
```

Use any date of your calendar, in `YYYY-MM-DD`. Running `secondchair date` alone prints it.

Now, with your agent open in the workspace, give it your first prompt. Start with a fragment, not a form:

> I want a campaign about a river town whose bell rings at night and nobody admits to ringing it. Help me work out what is going on. Ask me one question at a time.

The agent uses the `campaign-workshop` skill. Answer its questions. Liking an idea does not make it canon; it stays a working idea (in `notes/workshop/` if you ask for notes). When you decide something, say so in your words: "keep this: the ferryman rings it". The agent shows the change and records it as canon once you agree. If it relays a decision from your words, confirm it:

```sh
secondchair confirm f-1a2b3c4d      # the id the agent gives you
```

Run `secondchair status`: the canon counts have moved. Other things to ask are in [What to ask your agent](what-to-ask.md).

Have an existing campaign bible instead? Queue the import and run it:

```sh
secondchair jobs queue rebuild-entities-from-a-bible --input bible=~/sources/bible.md
secondchair jobs                    # pending jobs
secondchair jobs run                # needs a runner; otherwise ask your agent to "start SecondChair job <id>"
```

## 7. Prepare a session

Tell your agent: "Prepare session 1. About three hours, a mix of investigation and one fight." (A brief is optional.)

The `prepare-a-session` playbook takes a few minutes. You should end with:

- `prep/session-1/handoff.md`: your table-ready guide (recap to read aloud, scenes, clues, NPC cards, an improv kit, open questions). Read it on the review page, in Foundry's journal, or in any Markdown viewer.
- In Foundry: the session's scenes, NPC actors, a GM-only journal, handouts hidden until you publish them, treasure and playlists. Some items are held for you on the Desk: approve or reject them there.

Something not right? Say so in conversation ("the second scene is too long, cut a clue"); the agent rewrites the handoff and Foundry follows without losing your own edits.

## 8. Play

On the Director's Desk (**Shift+D** reopens it):

- **Start session** opens the live session. You should see the button become **End session 1**. (`secondchair session start` does the same from a terminal.)
- **Acting cue**: when an agent shows an NPC's cue, you see their goal, a guarded line, what they know and do not know. Press **I voice this one** to take that NPC over yourself; **Hand back** returns it.
- **Calls**: what an agent wants to do that your delegation table holds for you appears here. Approve, or reject with a reason.
- **Break**: shows what was held for the break.

Last-minute needs go to your agent in plain words: "a fence on the docks, now". The `quick-help` playbook answers in a few lines and writes nothing unless you ask.

## 9. Wrap

When the session ends, press **End session** (or `secondchair session end --notes my-notes.md`; with the notes file your wrap has its Source). Then:

```sh
secondchair transcribe --session 1 alice=alice.flac gm=gm.flac   # optional: per-speaker audio tracks
secondchair status                                               # shows the queued wrap job
secondchair jobs run                                             # or ask your agent to start the job
secondchair wrap 1                                               # your round of grouped questions
```

`wrap` asks you to settle each question and the session's dates. It is interactive on purpose. When it finishes, what was played is canon, ranked above any plan, the campaign date is the session's end date, and a world-turn job is queued (`wrap` prints `World-turn job N queued`). Run it with `secondchair jobs run` (or ask your agent to start it) and the world moves on to that date.

To move the world on to a later date, for example before the next session, run:

```sh
secondchair world turn 4726-03-21
```

Now prepare session 2. That is the whole loop; the [GM guide](gm-guide.md) goes deeper.

## When something fails

First run `secondchair check-setup`: every `FAIL` comes with the command that fixes it. The table below covers what it cannot see.

| You see | Do this |
| --- | --- |
| The agent does not mention SecondChair, or its tool calls fail | Is `secondchair serve` still running? Re-apply the `host setup` output and restart the agent. |
| Foundry says it cannot reach the Core | Check `serve` is running; check the **Core port** in the module settings; allow the browser's "local network" prompt for your Foundry site, then reload. |
| Foundry refuses to connect, naming the world or a module | A world binds to one campaign. For a PF2e world, both modules and the pf2e system must be enabled on Foundry v14. |
| A command says it needs an interactive terminal | `date`, `session`, `wrap`, `confirm` and a few more are yours alone; run them in a normal terminal, not through an agent. |
| `status` or the agent says something looks inconsistent | `secondchair check` rebuilds the index and reports invalid files; `secondchair doctor` reports facts whose evidence no longer resolves. It changes nothing. |
| An agent change is wrong | `secondchair log undo <entry> --reason <why>` (entry numbers are on the review page). Reject a pending one with `secondchair reject <n> --reason tone`. |
| A job sits in `secondchair jobs` | Run `secondchair jobs run`; with no runner configured, ask your agent to "start SecondChair job <id>". |
| You want a safety net | `secondchair backup <workspace> <archive>`; back up the Foundry world separately. |

Still stuck: [open an issue](https://github.com/Hugo-Grellier/SecondChair/issues) with the command and the message, and nothing from your campaign.
