# Contract: campaign workspace layout

Workspace schema version: **1**. Requirements: ARC-16, ARC-17a, ARC-23, ARC-26, ARC-27, CAN-01, CAN-02, CAN-03, CAN-04, CAN-05, CAN-06, CAN-07, CAN-08, CAN-10, CAN-11, CAN-12, CAN-13, CAN-14, CAN-15, CAN-16, BVE-02, CAN-18, ARC-10, CAP-01, CAP-02, CAP-03, CAP-15, CAL-01, CAL-02, CAL-03, CAL-04, DEL-11, DEL-13, DEL-16, LIC-09, PKG-13, PKG-15, PKG-16.

A **campaign workspace** is a directory the GM chooses, outside the tool repository, optionally inside a private repository of their own (LIC-09). It is the source of truth for one campaign and its full export (PKG-15). `secondchair init <dir> --language <bcp47> --calendar <name | file.yaml>` creates it; `secondchair serve <dir>` serves it.

## Tree

```text
my-campaign/
├── workspace.yaml     # schema version, campaign language and calendar; written by `init`
├── delegation.yaml    # the delegation table; seeded by `init`
├── moment.yaml        # the current moment; seeded by `init`, changed by `secondchair moment`
├── action-log/        # one YAML file per action log entry: 000001.yaml, 000002.yaml, …
├── jobs/              # one YAML file per job: 000001.yaml, …
├── calls/             # one YAML file per call on the GM: 000001.yaml, …
├── observations/      # one JSON Lines file per live session: 000001.jsonl, …, and outside-sessions.jsonl
├── canon/
│   ├── entities/      # one Markdown file per entity: e-1a2b3c4d.md
│   ├── facts/         # one Markdown file per fact: f-1a2b3c4d.md
│   ├── events/        # one Markdown file per event: v-1a2b3c4d.md
│   ├── mysteries/     # one Markdown file per mystery graph, named by the mystery entity's id
│   └── knowledge/     # one Markdown file per knowledge record: k-1a2b3c4d.md
├── scenes/            # one YAML file per prepared scene's desired state: goblin-cave.yaml
├── .gitignore         # contains `.secondchair/`; `init` appends to an existing one
├── speakers.yaml      # the speaker table (CAP-02); written by the GM
├── sources/           # one YAML reference per Source: s-1a2b3c4d.yaml; written by `secondchair transcribe`
├── foundry.yaml       # the Foundry world this campaign is bound to; written by the bridge (foundry-bridge.md)
└── .secondchair/      # derived state (index.sqlite, caches, the write lock, serve.json: the port `serve` last listened on, scenes/: each prepared scene's last reconciliation report); git-ignored, rebuildable
```

Later contracts add decisions and friction reports, each as Markdown + YAML (CAN-10). Nothing in `.secondchair/` is a source of truth: deleting it loses nothing.

## `workspace.yaml`

```yaml
schema_version: 1
campaign_language: fr
calendar: absalom
```

| Key | Type | Rule |
|---|---|---|
| `schema_version` | integer | The workspace schema this file follows (PKG-16). A version newer than the running SecondChair supports is refused. An older one blocks `serve` until `secondchair upgrade` (in the workspace, or with `-w <workspace>`) migrates it in place, one version at a time; only the migrated files and the `schema_version` line change, so the GM reviews the diff (in their own repository, `git diff`) and commits it. |
| `campaign_language` | string, BCP 47 tag | Set at `init` and fixed for v4 (CAN-18). `init` refuses to run on an existing workspace, so it cannot be changed through the tool. |
| `calendar` | string or mapping | The campaign calendar, required, set at `init` and fixed like the language (CAL-01). One of the three forms below. |

### `calendar`

A calendar a System extension provides as code, by name (CAL-03). The PF2e System extension provides `absalom` (Absalom Reckoning, ADR 0014). Extensions register calendars under the `secondchair.calendars` entry point group.

```yaml
calendar: absalom
```

The same, with month and weekday labels overridden for the campaign language. Either list may be left out; each must have one label per month or weekday. Labels are display only: changing them never changes a stored date (CAL-04), so the GM may edit them after `init`.

```yaml
calendar:
  name: absalom
  labels:
    months: [Abadius, Calistril, Pharast, Gozran, Desnus, Sarenith, Erastus, Arodus, Rova, Lamashan, Neth, Kuthona]
    weekdays: [Lundi, Mardi, Mercredi, Jeudi, Vendredi, Samedi, Dimanche]
```

A calendar declared inline (CAL-02). `init --calendar my-calendar.yaml` copies the file's content here.

```yaml
calendar:
  months:                # ordered; a festival is a one-day month
    - {name: Thaw, days: 36}
    - {name: Lanternnight, days: 1}
    - {name: Ember, days: 36}
  leap:                  # optional; one day added to `month` (1-based) in first_year and every interval years after it
    interval: 5
    first_year: 2
    month: 2
  week:
    days: [Oneday, Twoday, Threeday, Fourday, Fiveday, Restday]   # the week's length is the count
    anchor: {date: "0300-01-01", weekday: 3}                       # weekday is 1-based
  era: AF                # suffix shown after the year
```

Month lengths are 1 to 98 days, at most 99 months.

### Dates and durations

- A **date** is numeric and day-grained: `YYYY-MM-DD`, or partial `YYYY-MM` / `YYYY` (CAL-04). The year is a signed integer written with at least four digits, year 0 included (`-0001-12-31` is the day before `0000-01-01`). A partial date sorts at the start of its period.
- A **duration** is `Nd` or `Nw`, optionally signed (`10d`, `-3d`, `2w`); a week is the calendar's week length (CAL-05). Month and year durations are refused: a monthly cadence is written in days.

## `delegation.yaml`

The delegation table (DEL-05): one column per moment (`prep`, `live-session`, `between-sessions`), one cell per responsibility (the keys of [tool registration](tool-registration.md)), each with a level (`manual`, `propose`, `act-then-review`, `autonomous`) and a deadline mode (`auto`, `now`, `break`). `init` seeds it with the base profiles *prep*, *play* and *prep* (DEL-06, DEL-06a), every deadline mode `auto`. The GM may edit cells by hand; the Core reads the table at every delegated action.

```yaml
prep:
  prep: {level: act-then-review, deadline: auto}
  memory: {level: act-then-review, deadline: auto}
  vtt_operations: {level: act-then-review, deadline: auto}
  rules_and_combat: {level: manual, deadline: auto}
  living_world: {level: act-then-review, deadline: auto}
  npcs: {level: propose, deadline: auto}
  narrative_direction: {level: propose, deadline: auto}
  disclosure: {level: propose, deadline: auto}
live-session:
  prep: {level: propose, deadline: auto}
  # … the rest of the play base profile
between-sessions:
  # … the prep base profile
```

### Entity overrides

An optional `overrides` list lowers the level for one **acting entity** on `npcs`, `rules_and_combat` or `disclosure` (DEL-10, DEL-11), keyed on that entity's canon id, never inherited by a faction. `moment` restricts it to one moment; null applies it to every moment (DEL-13). It holds until the GM removes it.

```yaml
overrides:
  - {entity: e-1a2b3c4d, responsibility: npcs, level: manual, moment: null}
  - {entity: e-1a2b3c4d, responsibility: disclosure, level: propose, moment: live-session}
```

- The effective level of an action whose acting entity has overrides is the lowest of the cell and the overrides that match its responsibility and moment (DEL-12); the irreversible hold applies on top.
- `secondchair override add` (any terminal) or an agent's `add_entity_override` (quoting the GM) adds one and takes effect at once; adding over an override of the same entity, responsibility and moment keeps the lower level, so adding never loosens. `secondchair override remove`, from an interactive terminal only, removes one (DEL-14). Each is an `add_override` or `remove_override` GM interaction in the action log (DEL-27).
- When an override lands, the entity's open calls (the proposal's action entry, else its job, names the entity) and queued jobs (their `entity`) for that responsibility, in a moment the override covers, are `withdrawn`: the same safe default as a passed deadline, logged as a `safe_default` entry carrying the `add_override` entry as `override`, and never shown at the break (DEL-16). Actions already applied stay undoable one by one.
- When entities merge at the wrap, the merged entity's overrides follow the surviving one and the most restrictive wins (DEL-17; `delegation.merge_overrides`).

## `moment.yaml`

```yaml
moment: prep   # prep, live-session or between-sessions; a new workspace starts in prep
seq: 1         # grows by one at every moment change
session: 0     # the last live session's id; the open one's while moment is live-session
```

Only `secondchair moment <moment>`, `secondchair session start` and `secondchair session end` in an interactive terminal change it (DEL-03, DEL-03a). `session start` opens `live-session` with the next session id and is refused while one is open; `session end` returns to `between-sessions` (DEL-03b). Ending a live session, by either command, queues the "wrap a session" job (`wrap-a-session`, under memory, its input `session` the session id; DEL-04, CAP-09); its playbook comes with #46. The end of a moment is the last deadline of its calls: every call still open takes its safe default (`calls/`). While `live-session` is open, only `between-sessions` (ending it) is accepted (DEL-03b). Each action log entry records the `seq` it was taken in; once the moment changes, those entries are frozen and can no longer be undone, approved or rejected (DEL-25).

## `action-log/`

One YAML file per entry, named by its id on six digits, following [`action-log-entry.schema.json`](action-log-entry.schema.json): delegated actions (`kind: action`) and the GM interactions on them (`kind: gm_interaction`: approve, reject, undo, confirm). An action records the workspace file it writes (`target`) and that file's content before and after, which is what undo restores. The Core refuses to approve or undo when the file no longer holds the content the entry expects, such as after a hand edit, so nothing is overwritten unseen. A `confirm` interaction rewrites a canon file itself and carries its own `target`, `before` and `after`.

An action taken for a job carries the job's id (`job`) and the runner configuration the job was started with; it is bound by the delegation table of the job's moment.

## `jobs/`

One YAML file per job, named by its id on six digits, following [`job.schema.json`](job.schema.json): the job contract (playbook, inputs, expected output, responsibility, moment, tier, campaign language, vocabulary), whether its call blocks and its deadline when queued in a live session (ARC-28), the acting entity it works for, if any (`entity`), its status (`queued`, `started`, `done`, `missed`, `withdrawn`) and every start attempt with the runner configuration used. `secondchair jobs queue <playbook> --input <name>=<value>` writes it; `secondchair jobs` lists the jobs queued or started; `secondchair jobs run` starts the queued ones with the runner configuration.

## `calls/`

One YAML file per call on the GM, following [`call.schema.json`](call.schema.json): a pending proposal (one per action held at propose), a surfaced exception, such as the one raised when every runner configuration for a job's tier failed (the job stays queued), or a ceiling refusal (DEL-20), written when the VTT's ceiling refused a delegated action: it names the failed action log `entry`.

```yaml
id: 1
at: '2026-10-19T20:15:00+00:00'
kind: proposal
moment: live-session
moment_seq: 2
session: 1
responsibility: npcs
blocking: true          # declared by the acting agent (`blocking` on every delegated action) or its job
deadline: now           # now or break
interruption: true      # due now during a live session (DEL-33)
entry: 4                # a proposal's action log entry
job: null
message: null           # an exception's text
status: open            # open, answered, defaulted or withdrawn (by an entity override)
shown: false            # a defaulted call shown again at a break
```

- **Deadline** (DEL-30, DEL-07): the delegation table cell's deadline mode for the call's responsibility, in the moment whose table binds it. `auto` gives `now` to a blocking call and `break` to the others; `now` and `break` force it. A blocking call forced to `break` takes its safe default at once (DEL-31). A job's call inherits the job's deadline (ARC-28).
- **Deadlines pass on gestures, never on a clock**: moving on (the blocking turn or scene went on; the Core's `calls.move_on`, which the VTT connector calls) passes `now`; `secondchair break` passes `now` and the live jobs due at the break, then shows the break pile; the end of the moment passes everything.
- **Safe default** (DEL-32): a proposal's pending action is rejected, so an irreversible action never takes effect by default; an exception takes no action; a live job not done is `missed` and takes no further action. Each is a `safe_default` action log entry, not a GM interaction.
- **Break pile**: the calls due at the break still open (shown at every break until answered or the moment ends) and every call defaulted since the last break (shown once, then `shown: true`).
- **Interruptions** (DEL-33, MET-06): calls with `interruption: true`, counted by the Core per live session and per responsibility (`calls.interruptions`), whatever Surface shows them.
- Approving or rejecting a proposal answers its call.
- A ceiling refusal takes no action by default: the action already failed.

## `observations/`

One JSON Lines file per live session, named by the session id on six digits: each line is one observation the VTT connector captured during that session, in the event envelope ([`event-envelope.schema.json`](event-envelope.schema.json); how it arrives: [foundry-bridge.md](foundry-bridge.md), "Observations"). The Core only appends, once per envelope id. Observations are never canon by themselves (CAP-03); capture quotes them at the wrap with the locator `observations/<session>.jsonl#<id>`. A kind recorded in every moment, so far only `ceiling` (a change of the VTT's ceiling, DEL-19a), goes to `observations/outside-sessions.jsonl` with `session: null` when no live session is open.

```json
{"id": "4b1e…", "session": 1, "at": "2026-10-19T20:15:00.000Z", "scene": "Scene.s1", "actor": "Actor.a1", "kind": "chat", "visibility": "players", "payload": {"author": "Gamemaster", "speaker": "Sella", "text": "The bell rings.", "flavor": "", "whisper": [], "rolls": []}}
```

A knowledge record whose origin is an observation with such a locator is refused when the observation does not exist, and, for the party, when its visibility is not `players` (ARC-16, CAP-08).

## `canon/entities/`

An entity carries identity only (CAN-02): YAML front matter, then its player-facing description in the campaign language.

```markdown
---
id: e-1a2b3c4d
names: [Frère Ezren]
aliases: [Ezren]
official_reference: null
---
Un prêtre voûté.
```

`official_reference` (CAN-19) is null, or `{key, pack}`: `key` is the stable English key the System extension provides (PF2e: `system.slug`, falling back to `flags.babele.originalName`), never the translated name, which only ever goes in `names`; `pack` is the compendium pack id when the key collides across packs, null otherwise. The Core refuses a key that is not ASCII, or any other field. Example: `official_reference: {key: goblin-warrior, pack: null}` on an entity named `Gobelin guerrier`.

The campaign vocabulary (CAN-22) is derived from these files: every entity's names and aliases. A job carries the vocabulary of the entities it is about (`secondchair jobs queue --entity <id>`, repeatable), or the whole vocabulary when none is given.

## `canon/facts/`

A fact is one statement about one or more entities, in the campaign language (CAN-01): YAML front matter, then the statement.

```markdown
---
id: f-5e6f7a8b
entities: [e-1a2b3c4d, e-9c8d7e6f]
relation: {type: member_of, subject: e-1a2b3c4d, object: e-9c8d7e6f}
valid_from: "4725-03"
valid_to: null
rank: played
origin: {kind: observation, quote: "Mira joined the Lock Council.", locator: "sessions/01.md:3"}
---
Mira Pell sits on the Lock Council.
```

| Key | Rule |
|---|---|
| `entities` | Entity ids the statement is about, each an existing entity; a relation's subject and object are always included. |
| `relation` | Optional (CAN-03): `type`, `subject`, `object`. The type is one of the Core list `member_of`, `leads`, `lives_in`, `located_in`, `owns`, `knows`, `allied_with`, `opposes`, `serves`, `kin_of`, or one a System extension registers as an iterable of names under the `secondchair.relations` entry point group. Any other type is refused. |
| `valid_from`, `valid_to` | Fictional validity (CAN-04), campaign dates, partial allowed; null when open. An event that opens or closes the fact sets its start or end instead. Validity is start-inclusive, end-exclusive. |
| `rank` | `played`, `gm_decision`, `cited_source` or `agent_proposal`, highest first (CAN-06). Set by the Core from the origin, never by the caller. |
| `origin` | Provenance (CAN-07), by `kind`: `observation` (`quote` verbatim, `locator`) ranks played; `source` (`source`, `page`) ranks cited_source; `gm` (`words`) ranks agent_proposal when an agent records it, and gm_decision once the GM confirms it with `secondchair confirm <id>` in an interactive terminal (CAN-09, DEL-29), which rewrites the rank and logs a `confirm` GM interaction; `job` (`job`) ranks agent_proposal and cannot be confirmed. Approving a proposal never raises its rank (CAN-08). |
| `never_true` | Optional, `true` for a **belief** (CAN-15): a statement that is never true, which knowers can only believe or suspect. It has no validity, no event opens or closes it, and searches at a date leave it out. Absent means false. |

The record time is not in the file: the index takes it from the action log entry whose `after` is the file's current content (`admitted_by`), which carries the real time and the moment. A file changed by hand is admitted by its `hand_edit` entry (below).

## `canon/events/`

An event, played at the table or offscreen, opens and closes facts on a date (CAN-05).

```markdown
---
id: v-0a1b2c3d
date: "4725-05-01"
kind: played            # played or offscreen
opens: [f-22222222]
closes: [f-11111111]
replaces: null          # a retcon: the id of the event it replaces
rank: played
origin: {kind: observation, quote: "We open the bypass.", locator: "sessions/02.md:1"}
---
The party opened the bypass.
```

- An **evolution** is one event that closes the old fact and opens the new one. Closing a fact that ranks above the event, has already ended, or starts after the event is refused as a contradiction.
- A **correction** rewrites a fact file in place, with no event. It is refused when the fact is played or ranks above the correction; the previous version stays in the action log entry's `before`.
- A **retcon** is an event whose `replaces` names an earlier event, with the GM's words as origin. The earlier event stays on record. The retcon takes effect only at the `gm_decision` rank, once the GM confirms it; until then it is `pending_retcon` and the earlier event stays `canon`. Once in effect, the earlier event is `replaced` and the facts only it opened are `retconned`: kept, but left out of searches by default.
- Nothing is deleted.

## `canon/mysteries/`

The graph of a mystery (BVE-02, the v3 mystery graph on facts). The mystery is an entity, and the file is named by its id. Conclusions and clues are facts, nodes are entities. The body holds optional GM notes. `record_mystery` writes it and refuses it when a reference does not resolve.

```markdown
---
id: e-0d0e0a0d                     # the mystery entity
conclusions:
  - {id: conclusion-relay, fact: f-11111111}
nodes:
  - {id: node-weir, entity: e-22222222, entry: true}
  - {id: node-convoy, proactive: f-33333333}
clues:
  - {id: clue-1, fact: f-44444444, on: node-weir, points_to: [conclusion-relay, node-convoy], mobile: false}
---
```

- Local ids (`id`) are the author's, unique within the mystery across conclusions, nodes and clues.
- A node has an `entity` (a place, a person, a faction). It is an entry with `entry: true`, or with a `proactive` fact, such as a front's agenda step, that brings the party in while it holds.
- A clue is discoverable evidence: a fact `on` a node, pointing to node and conclusion ids.
- The file holds no state. A clue is **lost** when its fact no longer holds (closed by an event, or retconned), **found** when the party knows its fact. A conclusion is **solved** when the party knows its fact.
- `check_mystery` reports, while a conclusion is unsolved, the v3 warnings: `mystery-entry` (no entry), `mystery-unreachable` (a node not reachable from the entries through live clues), `mystery-node-clues` (fewer than 3 clues point to a node that is not an entry, the inverted three-clue rule), `mystery-conclusion` (no live clue on a reachable node), `mystery-three-clues` (fewer than 3 live clues, or on reachable nodes), `mystery-single-node` (all of a conclusion's clues on one node).

## `canon/knowledge/`

A knowledge record says a **knower** knows, believes or suspects a fact, and when it learned it (CAN-13, CAN-14). The file is front matter only.

```markdown
---
id: k-3c4d5e6f
knower: e-1a2b3c4d      # "party" for the party as a whole, else an entity id
fact: f-5e6f7a8b
mode: believes          # knows, believes or suspects
date: "4725-04-25"      # the campaign date it learned it
event: null             # or the event it learned it at
rank: cited_source
origin: {kind: source, source: bible.md, page: "B14"}
---
```

- Knowers are the party as a whole (`party`; individual PCs are not knowers), an NPC or a faction. A record whose knower is a place is that place's **common knowledge**.
- Knowledge is closed-world: a knower holds only its own records, plus those of the factions it is a `member_of` and the places it `lives_in` (one level; a faction never inherits from its members). With a date, only relations valid then and records learned by then count. A fact held several ways takes its strongest mode (knows, then believes, then suspects).
- A never-true fact is believed or suspected, never known. Records on retconned facts are ignored.
- Content written for an audience (an NPC line, a disclosure, an entity description) cites the ids of the facts it uses and goes through `check_audience_content` (CAN-16): refused when a cited id is not in canon, when the audience does not hold a cited fact, or when the text carries a canary (`CANARY-<zone>-<n>`) or an entity name (or alias) that appears in no fact the audience holds, the audience's own names excepted. Names match whole-word and case-sensitive; paraphrased leaks are not blocked, the test bench measures them.

## `speakers.yaml`

The speaker table (CAP-02): each Discord user whose track is recorded maps to its player, their PC, and whether it is the GM's track. The GM writes it; `secondchair check` validates it. Keys are strings: quote a numeric Discord id.

```yaml
gm_hugo: {player: Hugo, gm: true}
alice_42: {player: Alice, pc: Valeros}
```

| Key | Type | Rule |
|---|---|---|
| `player` | string | Required. |
| `pc` | string or null | The player's PC; absent for the GM. |
| `gm` | boolean | Default `false`. Exactly one speaker is the GM's track. |

## `sources/`

Raw audio and full transcripts are Sources outside the workspace (CAP-15, PKG-12). `secondchair transcribe --session <id> <discord-user>=<audio> …` runs the engine per speaker track (WhisperX by default, the campaign vocabulary as hotwords) and writes the transcript in the transcript format ([`transcript.schema.json`](transcript.schema.json)) outside the workspace; `secondchair transcribe --session <id> --from <transcript>` references one any engine produced. A single-track input is refused. Each Source gets one reference file here; where it lives on disk is machine configuration (`$XDG_CONFIG_HOME/secondchair/sources.yaml`, id → path), never the workspace.

```yaml
id: s-1a2b3c4d      # s- and the first 8 hex digits of the hash
kind: transcript    # audio | transcript
sha256: 1a2b3c4d…
session: 1
from: [s-5e6f7a8b, s-9c0d1e2f]   # transcript: the audio Sources it was made from; audio: `speaker` instead
```

The engine is `whisperx <audio> --output_dir <dir> --output_format json --language <lang> --hotwords <vocabulary>` unless the machine configuration's `transcription` gives another command list (placeholders `{audio}`, `{out_dir}`, `{language}`, `{hotwords}`; it writes `<out_dir>/<audio stem>.json` with WhisperX's `segments`). The Hugging Face token stays in the engine's environment (`HF_TOKEN`, PKG-14); SecondChair never reads or stores it.

## `scenes/`

One YAML file per prepared scene, named by its key (lowercase words joined by dashes): its **desired state**, what the scene must look like in the VTT after prep (ARC-10). It is not canon: prep is the Core's, realised in the VTT by reconciliation, which keeps what was played and what the GM retouched ([foundry-bridge.md](foundry-bridge.md#prepared-scenes-arc-10-bve-02)). `prepare_scene` writes it (prep, reversible); its format is `desired_scene` in [`foundry-bridge.schema.json`](foundry-bridge.schema.json), the Foundry connector giving the fields their meaning.

```yaml
# scenes/goblin-cave.yaml
scene: {name: Goblin cave, width: 2000, height: 1500, grid: {size: 100}}
items:
  - key: boss
    type: Token
    actor: Compendium.pf2e.pathfinder-bestiary.Actor.aBcD1234
    data: {name: Goblin boss, x: 100, y: 100, hidden: true}
  - key: torch
    type: AmbientLight
    data: {x: 500, y: 500, config: {bright: 2, dim: 4}}
choices: {torch: overwrite}   # the GM's calls on conflicts, optional
```

The GM may edit it by hand: the next GM client connection, or the running one within a second, realises the new version.

## Hand edits

A hand edit of `canon/` bypasses the Core (CAN-11). When it rebuilds the index, the Core compares each Markdown file under `canon/` with the content it last left there (replaying applied actions, undos, confirmations and earlier hand edits in the order they hit the workspace) and logs each difference, a new, changed or deleted file, as one `kind: hand_edit` action log entry with the content before and after. The index ranks that content `agent_proposal`, whatever the file's front matter says. `secondchair promote <entry>` in an interactive terminal (an authenticated Surface, DEL-29) makes it a GM decision: the entry's `rank` becomes `gm_decision`, recorded as a `promote` GM interaction; the file itself is not rewritten. A promotion is refused once the file has changed again: the newer hand edit is the one to promote.

## `.secondchair/index.sqlite`

The derived index (CAN-10): entities, facts, events and knowledge with their derived validity and status, and full-text tables over names, statements and descriptions (CAN-12). It records a fingerprint of `workspace.yaml`, `canon/` and `action-log/`, and any read rebuilds it when they changed. `secondchair check` (in the workspace, or with `-w <workspace>`) rebuilds it from the directory alone, with no Foundry and no Source (PKG-15), logs any hand edit, also validates `moment.yaml`, `delegation.yaml`, the action log, job and call files, names each invalid file and exits 1 if there is one. It lists the hand edits awaiting promotion. Deleting `.secondchair/` loses nothing.

## What is not in the workspace

- **The machine configuration** (PKG-13) lives in `$XDG_CONFIG_HOME/secondchair/` (default `~/.config/secondchair/`) and never travels with the workspace. Its `config.yaml` holds, so far, the port `serve` listens on:

  ```yaml
  port: 7240   # default when the file or the key is absent
  runners:     # the runner configuration (ARC-26): per tier, the entries tried in order
    standard:
      - {host: claude, model: <model>, effort: high}
      - {host: codex, model: <model>, effort: medium}
  hosts:       # optional: command templates, overriding or adding to the built-in claude and codex
    my-host: [my-agent, --model, "{model}", --effort, "{effort}", "{prompt}"]
  ```

  Next to it, `foundry-token` (mode 0600) holds the token the Foundry module connects with, created by `secondchair token` ([foundry-bridge.md](foundry-bridge.md)).

  `runners` is keyed by tier only (`fast`, `standard`, `deep`); a tier with no entry has no runner, and its jobs wait for the GM to start them from their own agent host session. Each entry names a host, a model and an effort; model names appear only here (ARC-25). A host is a command template whose `{prompt}`, `{model}`, `{effort}`, `{playbooks}` (a block's playbook directory; an argument naming it is repeated for each installed block) and `{job}` are filled in; the built-in `claude` and `codex` templates run Claude Code (`claude -p`, with each block's playbooks as a plugin directory and only the SecondChair tools and file reads allowed) and Codex (`codex exec`) headless, both reaching the Core through the MCP configuration `secondchair host setup` prints. An entry whose command cannot be run or exits with an error is a failed attempt, and the next entry is tried.

- **Sources** (raw audio, full transcripts, Foundry worlds, rulebooks) stay outside both; the workspace only references them (PKG-12).

## In the tool repository

The tool never ships a workspace (LIC-09). The CI guard `scripts/guard_no_workspace.py` (LIC-10) fails on any tracked `workspace.yaml`, any file under a `.secondchair/` directory, and files that look like Sources (audio, PDF, a Foundry `world.json`), except inside the sample campaign's folder, `sample-campaign/`.
