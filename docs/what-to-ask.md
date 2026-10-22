# What to ask your agent

Open your agent (Claude Code or Codex) in the campaign workspace, with `secondchair serve` running and the playbooks installed ([first hour](first-hour.md), step 4). Say what you want in your own words; the agent picks the playbook. The phrasings below are examples, not commands.

Some playbooks are for you to ask for. Others are **jobs** that the Core queues on its own (after a wrap, for instance) and a runner or your agent then runs; you rarely name them, but you see their results. `secondchair jobs` lists pending jobs, and `secondchair jobs run` starts them (or tell your agent: "start SecondChair job <id>").

Nothing below becomes canon without your say-so, unless your delegation table lets that action run on its own. Notes and drafts are never canon.

## You ask for these

| You want to | You might say | Playbook | You get, and where it lands |
| --- | --- | --- | --- |
| Talk an idea through, create or maintain the campaign | "I have a fragment: a bell that rings at night. Help me work it out." | `campaign-workshop` (installed in your workspace by `init`) | A conversation, one question at a time. Working ideas in `notes/workshop/` only if you ask; decisions you state become canon after you confirm them (`secondchair confirm <ids>`). |
| Choose where the campaign is going | "Give me three different pitches for this campaign, then critique them." | `develop-campaign-direction` | Notes in `notes/direction/` (brief, pitches side by side, your choice, an open-ended outline) and, on request, a short player-facing primer under `prep/`. Never canon. |
| Design a situation or a mystery that works without a script | "Design the investigation into who rings the bell. Check the clues." | `design-a-situation` | A draft in `notes/mysteries/<slug>.md` (stakes, parties, clocks, clues, responses, three approaches simulated against canon) and a one-screen play reference. Check it with `secondchair mystery check-draft <slug>`. |
| Plan a multi-session adventure | "Turn the Ashfall pitch we chose into an adventure." Name the direction by its title; it asks once for any party level, size or session count your campaign does not hold yet. | `prepare-an-adventure` | A GM dossier and a players' guide in `prep/adventure-<slug>/` (`dossier.md`, `players-guide.md`), each ending in a checked index block; the open questions in the reply. Check with `secondchair prep check`. |
| Make an adventure's encounters fit your party (PF2e) | "Calibrate the encounters of this adventure for four level-3 characters." | `calibrate-encounters` (a job; `prepare-an-adventure` and `prepare-a-session` usually trigger it) | One prepared scene per encounter you list, built from the PF2e calculators (threat, XP), plus a summary of each encounter's XP, threat and the level's treasure budget. Scenes are written for Foundry. |
| Prepare the next session | "Prepare session 3. Three hours, one fight, lots of talking." In conversation, it first lists the scenes and Foundry material it will prepare and waits for your go. | `prepare-a-session` | `prep/session-3/handoff.md` (read-aloud recap, scenes, clues, DCs, NPC cards, improv kit, open questions) and the Foundry material: scenes, NPC actors, a GM-only journal, hidden handouts, treasure, playlists. |
| Put one scene into Foundry | "Set up the dockside scene in Foundry from this brief." | `realise-a-scene` (a job, Foundry block; `prepare-an-adventure` and `prepare-a-session` usually trigger it) | The scene's desired state (map, tokens, lights, walls, sounds, notes) written for the Foundry module, a reconciliation report, and a list of what still needs you. Usually run for you by `prepare-a-session`. |
| Get an answer at the table, now | "A fence on the docks, now." "What does the harbour master know about the bell?" | `quick-help` | A few usable lines, consistent with canon and the session's prep. Written to a note or Foundry only if you ask. |
| Know what your players' choices opened up | "What did session 3 open up? Give me options for the next two sessions." | `propose-opportunities` | A short list of optional opportunities, each citing the played facts behind it, in `notes/opportunities/session-<n>.md`. You adopt or reject; never canon. |
| Turn a campaign bible into canon | "Import my bible at ~/sources/bible.md." | `rebuild-entities-from-a-bible` (a job) | One canon entity per named person, place, group and thing, the bible's facts, who knows what at the start, and its mysteries. Queue it: `secondchair jobs queue rebuild-entities-from-a-bible --input bible=<path>`. |
| Check whether your delegation settings fit how you play | "Where did the agents get in my way? Suggest delegation changes." | `diagnose-frictions` (a job) | Proposed changes to the delegation table with the frictions behind each. It changes nothing; you apply what you accept. |

## The Core queues these after your actions

| Trigger | Playbook | What it does, and where it lands |
| --- | --- | --- |
| **End session** (or `secondchair session end`) | `wrap-a-session` | Reads your notes and the transcript and proposes candidate facts that quote them verbatim, classified against canon. You answer the grouped questions with `secondchair wrap <session>`. |
| `secondchair world turn <date>` | `world-turn` | Advances the living world to the date: fronts, clocks and what NPCs do off screen. Records occurrences and queues the jobs below. |
| A front's "unless" condition comes due | `settle-an-unless` | Decides, citing canon fact ids, whether the condition held on its date. |
| A situation the party engaged in reaches its deadline, or the party does something unexpected | `propose-narrative-direction` | A proposal for what happens next, held for your approval. |
| Offscreen events were recorded | `propose-consequences` | Derived consequences (NPCs pursuing their agendas, knowledge spreading), each citing the facts it uses, held for you. |
| A bench or test run asks questions of canon | `answer-probes` | Structured answers about canon in the GM view. Developer tooling, not part of play. |

## Where things land

| Place | What is there |
| --- | --- |
| `canon/` | Facts, entities, events and mysteries you confirmed. Authoritative. |
| `notes/` | Drafts and working ideas: `workshop/`, `direction/`, `mysteries/`, `opportunities/`, `npcs/`. Never canon. |
| `prep/` | Handoffs and dossiers for the table. |
| `http://127.0.0.1:7240/` | Read-only review page for all of the above, the pending proposals and the action log. |

Approve a held proposal with `secondchair approve <n>`; reject with `secondchair reject <n> --reason contradiction|rules|tone|other`. The full loop is in the [GM guide](gm-guide.md).
