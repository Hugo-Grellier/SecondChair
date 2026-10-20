# GM guide: create, prepare, play, wrap

This guide follows one campaign through SecondChair's loop. Each step names what you say to your agent (Claude Code or Codex, opened in the campaign workspace and connected to `secondchair serve`) and the commands you run yourself. You decide; agents propose, prepare and record what you confirm.

```text
 create ──▶ prepare ──▶ play ──▶ wrap ──┐
   ▲                                    │
   └──────── the world moves on ◀───────┘
```

## Once: set up

```sh
uv tool install "secondchair @ git+https://github.com/Hugo-Grellier/SecondChair@main"
secondchair init ~/campaigns/my-campaign --language fr --calendar absalom
secondchair serve ~/campaigns/my-campaign        # leave it running
secondchair host setup claude                    # or codex: prints the MCP and playbook setup
```

For Foundry, install the two modules and paste `secondchair token` into the module settings ([Foundry setup](../foundry/README.md)). `secondchair status` tells you at any time where the campaign stands and what to do next.

## 1. Create and develop the campaign

Open your agent in the workspace and talk: a fragment, a question, a document, a character idea, an investigation to build. The `campaign-workshop` skill keeps the GM in charge: it proposes, asks one question at a time, and keeps working ideas in `notes/workshop/` until you confirm them.

- Say what you confirm, in your words ("keep this: the Regie controls the furnaces"). The agent records it in canon as facts, with who knows them; an investigation becomes a mystery graph the agent checks (three clues per conclusion).
- Confirm what the agent relayed from your words in one command: `secondchair confirm f-… f-… v-…`. Approve held proposals with `secondchair approve 12 13 14`.
- Register books and PDFs with `secondchair sources add`, permit them, and let the agent cite them.

Come back any day: the workspace is the campaign. The agent rereads canon and notes and continues from there.

## 2. Prepare the next session

Say "prepare session 3" (optionally with a brief: what you want, constraints, duration), or queue it for a runner:

```sh
secondchair jobs queue prepare-a-session --input session=3 --input brief=~/notes/brief-s3.md
```

The `prepare-a-session` playbook writes `prep/session-3/handoff.md`: at a glance, a read-aloud recap from what the party knows, scenes with read-alouds, clues, DCs and calibrated encounters, NPC cards with what they know and hide, the investigation's state, an improv kit and the open questions. In Foundry, it prepares the scenes (maps, hidden tokens, lights, sounds), the NPC actors, the handoff as a GM-only journal, handouts kept hidden until you publish them, treasure and playlists, found in your own install.

Read it in the review page (`http://127.0.0.1:7240/`, printed by `serve`), in Foundry's journal, or in any Markdown reader. Ask for changes in conversation; the agent rewrites the handoff and Foundry reconciles without losing what you retouched.

## 3. Play

- Start: **Start session** on the Director's Desk in Foundry (or `secondchair session start`). SecondChair warns if the last session was never wrapped.
- At the table, ask your agent for quick help ("a fence in the docks, now"): the `quick-help` playbook answers in a few lines, consistent with canon, and only writes or prepares something when you ask.
- Approve or reject what agents hold for you on the Desk; Shift+D reopens it.
- Record the session per speaker (Craig on Discord).
- End: **End session** (or `secondchair session end --notes my-notes.md`). The wrap job is queued.

## 4. Wrap: the world remembers what was played

```sh
secondchair transcribe --session 3 alice=alice.flac bob=bob.flac gm=gm.flac   # per-speaker tracks
secondchair status                                                           # shows the wrap job
```

Ask your agent to "start SecondChair job <id>" (or `secondchair jobs run`). The wrap reads your notes and the transcript, proposes cited facts, and holds questions for you. Then:

```sh
secondchair wrap 3            # answer the grouped questions, settle the dates
secondchair world turn <date> # the world moves on to the next session's date
```

What was played is now canon, ranked above any plan. Prepare the next session: the loop starts again.

## Review what agents changed

`secondchair serve` also serves a read-only review page on its port: what awaits your approval (with the command to run), the recent action log with diffs, the prep notes and handoffs, the Foundry realisation reports, canon search and the jobs. Every agent change can be undone with `secondchair log undo <entry> --reason <why>`.
