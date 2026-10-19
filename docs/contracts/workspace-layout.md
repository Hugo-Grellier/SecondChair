# Contract: campaign workspace layout

Workspace schema version: **1**. Requirements: ARC-17a, ARC-23, ARC-26, ARC-27, CAN-01, CAN-02, CAN-03, CAN-04, CAN-05, CAN-06, CAN-07, CAN-08, CAN-10, CAN-11, CAN-12, BVE-02, CAN-18, CAL-01, CAL-02, CAL-03, CAL-04, LIC-09, PKG-13, PKG-15, PKG-16.

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
├── canon/
│   ├── entities/      # one Markdown file per entity: e-1a2b3c4d.md
│   ├── facts/         # one Markdown file per fact: f-1a2b3c4d.md
│   ├── events/        # one Markdown file per event: v-1a2b3c4d.md
│   └── mysteries/     # one Markdown file per mystery graph, named by the mystery entity's id
├── .gitignore         # contains `.secondchair/`; `init` appends to an existing one
├── foundry.yaml       # the Foundry world this campaign is bound to; written by the bridge (foundry-bridge.md)
└── .secondchair/      # derived state (index.sqlite, caches, the write lock); git-ignored, rebuildable
```

Later contracts add decisions, the speaker table and friction reports, each as Markdown + YAML (CAN-10). Nothing in `.secondchair/` is a source of truth: deleting it loses nothing.

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

## `moment.yaml`

```yaml
moment: prep   # prep, live-session or between-sessions; a new workspace starts in prep
seq: 1         # grows by one at every moment change
```

Only `secondchair moment <moment>` in an interactive terminal changes it (DEL-03, DEL-03a). While `live-session` is open, only `between-sessions` (ending it) is accepted (DEL-03b). Each action log entry records the `seq` it was taken in; once the moment changes, those entries are frozen and can no longer be undone, approved or rejected (DEL-25).

## `action-log/`

One YAML file per entry, named by its id on six digits, following [`action-log-entry.schema.json`](action-log-entry.schema.json): delegated actions (`kind: action`) and the GM interactions on them (`kind: gm_interaction`: approve, reject, undo, confirm). An action records the workspace file it writes (`target`) and that file's content before and after, which is what undo restores. The Core refuses to approve or undo when the file no longer holds the content the entry expects, such as after a hand edit, so nothing is overwritten unseen. A `confirm` interaction rewrites a canon file itself and carries its own `target`, `before` and `after`.

An action taken for a job carries the job's id (`job`) and the runner configuration the job was started with; it is bound by the delegation table of the job's moment.

## `jobs/`

One YAML file per job, named by its id on six digits, following [`job.schema.json`](job.schema.json): the job contract (playbook, inputs, expected output, responsibility, moment, tier, campaign language, vocabulary), its status (`queued`, `started`, `done`) and every start attempt with the runner configuration used. `secondchair jobs queue <playbook> --input <name>=<value>` writes it; `secondchair jobs` lists the jobs not done; `secondchair jobs run` starts the queued ones with the runner configuration.

## `calls/`

One YAML file per call on the GM. So far the only call is the exception raised when every runner configuration for a job's tier failed; the job stays queued. Scheduling, answering and showing calls come with #42.

```yaml
id: 1
at: '2026-10-19T20:15:00+00:00'
kind: exception
moment: prep
moment_seq: 1
responsibility: memory
deadline: break
job: 1
message: Every runner configuration for tier standard failed; the job stays queued.
status: open
```

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

## Hand edits

A hand edit of `canon/` bypasses the Core (CAN-11). When it rebuilds the index, the Core compares each Markdown file under `canon/` with the content it last left there (replaying applied actions, undos, confirmations and earlier hand edits in the order they hit the workspace) and logs each difference, a new, changed or deleted file, as one `kind: hand_edit` action log entry with the content before and after. The index ranks that content `agent_proposal`, whatever the file's front matter says. `secondchair promote <entry>` in an interactive terminal (an authenticated Surface, DEL-29) makes it a GM decision: the entry's `rank` becomes `gm_decision`, recorded as a `promote` GM interaction; the file itself is not rewritten. A promotion is refused once the file has changed again: the newer hand edit is the one to promote.

## `.secondchair/index.sqlite`

The derived index (CAN-10): entities, facts and events with their derived validity and status, and full-text tables over names, statements and descriptions (CAN-12). It records a fingerprint of `workspace.yaml`, `canon/` and `action-log/`, and any read rebuilds it when they changed. `secondchair check` (in the workspace, or with `-w <workspace>`) rebuilds it from the directory alone, with no Foundry and no Source (PKG-15), logs any hand edit, also validates `moment.yaml`, `delegation.yaml`, the action log, job and call files, names each invalid file and exits 1 if there is one. It lists the hand edits awaiting promotion. Deleting `.secondchair/` loses nothing.

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

  `runners` is keyed by tier only (`fast`, `standard`, `deep`); a tier with no entry has no runner, and its jobs wait for the GM to start them from their own agent host session. Each entry names a host, a model and an effort; model names appear only here (ARC-25). A host is a command template whose `{prompt}`, `{model}`, `{effort}`, `{playbooks}` (the playbooks' directory) and `{job}` are filled in; the built-in `claude` and `codex` templates run Claude Code (`claude -p`, with the playbooks as a plugin directory and only the SecondChair tools and file reads allowed) and Codex (`codex exec`) headless, both reaching the Core through the MCP configuration `secondchair host setup` prints. An entry whose command cannot be run or exits with an error is a failed attempt, and the next entry is tried.

- **Sources** (raw audio, full transcripts, Foundry worlds, rulebooks) stay outside both; the workspace only references them (PKG-12).

## In the tool repository

The tool never ships a workspace (LIC-09). The CI guard `scripts/guard_no_workspace.py` (LIC-10) fails on any tracked `workspace.yaml`, any file under a `.secondchair/` directory, and files that look like Sources (audio, PDF, a Foundry `world.json`), except inside the sample campaign's folder, `sample-campaign/`.
