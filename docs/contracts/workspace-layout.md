# Contract: campaign workspace layout

Workspace schema version: **1**. Requirements: RUL-17, RUL-24, ARC-16, ARC-17a, ARC-23, ARC-26, ARC-27, CAN-01, CAN-02, CAN-03, CAN-04, CAN-05, CAN-06, CAN-07, CAN-08, CAN-10, CAN-11, CAN-12, CAN-13, CAN-14, CAN-15, CAN-16, BVE-02, CAN-18, CAN-23, ARC-10, CAP-01, CAP-02, CAP-03, CAP-04, CAP-05, CAP-06, CAP-08, CAP-10, CAP-12, CAP-13, CAP-14, CAP-15, CAL-01, CAL-02, CAL-03, CAL-04, TRC-03, TRC-04, TRC-05, TRC-06, CAL-14, DEL-11, DEL-13, DEL-16, LIC-09, LIC-12, PKG-13, PKG-15, PKG-16, LW-03, LW-04, LW-07, LW-13.

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
├── house-rules.yaml   # the campaign's house rules, which silence a kind of rules check
├── observations/      # one JSON Lines file per live session: 000001.jsonl, …, and outside-sessions.jsonl
├── living-world.yaml  # the world-turn cursor; written by the first world-turn
├── occurrences/       # one YAML file per world-turn occurrence: 000001.yaml, …
├── capture/           # one YAML file per candidate fact, named by its key
├── time.yaml          # the current date and each wrapped session's interval; written by the wrap
├── frictions/         # one friction report per moment: 000001.md, …
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
└── .secondchair/      # derived state (index.sqlite, caches, the write lock, serve.json: the port `serve` last listened on, scenes/: each prepared scene's last reconciliation report, cue.json: the active NPC's acting cue, purchased/: metadata indexes of purchased content); git-ignored, rebuildable
```

Later contracts add decisions, each as Markdown + YAML (CAN-10). Nothing in `.secondchair/` is a source of truth: deleting it loses nothing.

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
| `friction_thresholds` | mapping, optional | The campaign's friction detector thresholds (TRC-03), each a positive number overriding its default; see [`frictions/`](#frictions). An unknown name is refused when a report is written. |

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

The delegation table (DEL-05): one column per moment (`prep`, `live-session`, `between-sessions`), one cell per responsibility (the keys of [tool registration](tool-registration.md)), each with a level (`manual`, `propose`, `act-then-review`, `autonomous`) a deadline mode (`auto`, `now`, `break`) and an irreversible hold (below). `init` seeds it with the base profiles *prep*, *play* and *prep* (DEL-06, DEL-06a), every deadline mode `auto` and every hold set. The GM may edit cells by hand; the Core reads the table at every delegated action.

```yaml
prep:
  prep: {level: act-then-review, deadline: auto, hold: true}
  memory: {level: act-then-review, deadline: auto, hold: true}
  vtt_operations: {level: act-then-review, deadline: auto, hold: true}
  rules_and_combat: {level: manual, deadline: auto, hold: true}
  living_world: {level: act-then-review, deadline: auto, hold: true}
  npcs: {level: propose, deadline: auto, hold: true}
  narrative_direction: {level: propose, deadline: auto, hold: true}
  disclosure: {level: propose, deadline: auto, hold: true}
live-session:
  prep: {level: propose, deadline: auto, hold: true}
  # … the rest of the play base profile
between-sessions:
  # … the prep base profile
```

### The irreversible hold

Each cell also carries `hold` (DEL-09, DEL-09a), `true` in every base profile and when absent: the cell's irreversible actions (a disclosure, a public line) are held at propose whatever its level. `false` lets them run at the cell's effective level, still bounded by entity overrides and the VTT's ceiling: applied at once, logged, never undoable; a safe default never applies one.

- `secondchair hold lift <responsibility> <moment>`, from an interactive terminal only, lifts it, since it stands for approving every future irreversible action of the cell. `secondchair hold restore <responsibility> <moment>` (any terminal) or an agent's `restore_hold` (quoting the GM) restores it, in force at once. Each is a `lift_hold` or `restore_hold` GM interaction in the action log, carrying the cell as `hold` (DEL-27).

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

Only `secondchair moment <moment>`, `secondchair session start` and `secondchair session end` in an interactive terminal, and Start / End session on the Director's Desk ([foundry-bridge.md](foundry-bridge.md)), change it (DEL-03, DEL-03a). `session start` opens `live-session` with the next session id and is refused while one is open; `session end` returns to `between-sessions` (DEL-03b). Ending a live session, by any of these, queues the "wrap a session" job (`wrap-a-session`, under memory, its input `session` the session id; DEL-04, CAP-09); `session end --notes <file>` gives it the GM's notes for the session as its optional `notes` input, its Source ([capture](#capture)). The end of a moment is the last deadline of its calls: every call still open takes its safe default (`calls/`). While `live-session` is open, only `between-sessions` (ending it) is accepted (DEL-03b). Each action log entry records the `seq` it was taken in; once the moment changes, those entries are frozen and can no longer be undone, approved or rejected (DEL-25).

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
- A **discrepancy** (RUL-17) is a rules check that failed on an observation: `kind: discrepancy` under rules_and_combat, never blocking, so held for the break unless the cell's deadline mode forces now. It carries its `message` (what is inconsistent), the kind of `check` and the checked `observation`'s locator; it names no module. Its safe default takes no action. The GM answers it by marking it intended (a house rule, below) or approving a fix an agent proposed (`fix_discrepancy`, which answers it and is always a proposal).

## `house-rules.yaml`

The campaign's house rules (RUL-23, RUL-24), written by `secondchair house-rule mark <call> <name>` and `remove <name>`, each a `gm_interaction` log entry (`add_house_rule`, `remove_house_rule`):

```yaml
house_rules:
  - name: Heroic nudge     # unique
    check: degree          # the kind of rules check it silences
    call: 7                # the discrepancy marked as intended
    at: '2026-10-19T21:02:00+00:00'
```

While a house rule names a kind of check, no discrepancy of that kind is raised. Removing it restores the check for the observations recorded afterwards.

## `observations/`

One JSON Lines file per live session, named by the session id on six digits: each line is one observation the VTT connector captured during that session, in the event envelope ([`event-envelope.schema.json`](event-envelope.schema.json); how it arrives: [foundry-bridge.md](foundry-bridge.md), "Observations"). The Core only appends, once per envelope id. Observations are never canon by themselves (CAP-03); capture quotes them at the wrap with the locator `observations/<session>.jsonl#<id>`. A kind recorded in every moment (`ceiling`, a change of the VTT's ceiling, DEL-19a; `clock` and `rules_context`, RUL-22, CAL-12) goes to `observations/outside-sessions.jsonl` with `session: null` when no live session is open.

```json
{"id": "4b1e…", "session": 1, "at": "2026-10-19T20:15:00.000Z", "scene": "Scene.s1", "actor": "Actor.a1", "kind": "chat", "visibility": "players", "payload": {"author": "Gamemaster", "speaker": "Sella", "text": "The bell rings.", "flavor": "", "whisper": [], "rolls": []}}
```

A knowledge record whose origin is an observation with such a locator is refused when the observation does not exist, and, for the party, when its visibility is not `players` (ARC-16, CAP-08).

## `living-world.yaml` and `occurrences/`

The world-turn (05-living-world-calendar.md) advances fronts and situations over `]cursor, now]`. `living-world.yaml` holds its cursor, `cursor: '4725-01-15'`, the date up to which every occurrence is recorded (applied or queued); it never moves back. `occurrences/` holds one YAML file per occurrence, named by its id on six digits:

```yaml
id: 3
at: '2026-10-20T09:00:00+00:00'
key: e-1a2b3c4d/tick@4725-01-08   # used once, whatever happens to it (LW-13)
kind: tick                        # tick, step, deadline, pause or resume
class: rule                       # rule, derived (an unless tick) or narrative (ADR 0009)
entity: e-1a2b3c4d
date: '4725-01-08'                # its fictional date; a late accept keeps it (LW-17)
rule: f-5e6f7a8b                  # the state fact it applies
ticks: 1                          # a tick's clock segments
status: applied                   # queued, applied, rejected, rescheduled or suppressed
entries: [12, 13, 14]             # the action log entries that applied it
call: null                        # the call on the GM it waits on
job: null                         # the settle-an-unless or narrative-direction job
cites: []                         # the fact ids an unless was settled with
cause: null                       # a threshold step: the tick that crossed it
rescheduled_from: null
rescheduled_to: null              # <key>~<date>, a new key linked to it (LW-16)
rescheduled_date: null
```

Keys: `<front>/tick@<date>`, `<front>/<step id>`, `<situation>/deadline@<date>`, `<front>/pause@<date>`, `<front>/resume@<date>`, and `<key>~<date>` for a rescheduled one. A rule effect is applied through the action log under living world, every entry carrying the key (`occurrence`); an `unless` tick queues a `settle-an-unless` job (input `occurrence`) and an engaged situation's deadline a `propose-narrative-direction` job, whose every action carries the deadline's key: approving one applies the occurrence (its `entries`), rejecting it leaves the occurrence queued, and undoing the last approved one returns it to the queue (LW-19); a world-turn that applied anything queues one `propose-consequences` job (input `occurrences`, the keys). On the CLI, in the workspace: `secondchair world turn <date> [--since <date>]` (refused in a live session; `--since` on the first one), `secondchair world forecast <date>` (writes nothing), `secondchair world decide <key> accept|reject|reschedule [--date <date>]`, `secondchair world undo <key> --reason <reason>` (with its cascade; the keys return to the queue) and `secondchair world pause|resume <front> <date>`.
## `frictions/`

The per-moment friction report (TRC-03, TRC-04), the only trace-derived content the workspace keeps: one Markdown file per moment, named by the moment's `seq` on six digits, written by the Core from the raw behaviour traces ([foundry-bridge.md](foundry-bridge.md), "Behaviour traces"), which stay outside the workspace. It is rewritten when a gap arrives for that moment, and once a user's first records of the next moment arrive, when the moment's traces are complete.

The front matter holds:

- `gaps`: traces lost because no GM client relayed them (TRC-05);
- `gm_effort`: `interactions`, the moment's GM interactions in the action log (DEL-27; a Director's Desk gesture is one), and `manual_acts`, the GM's acts in the VTT read from their traces: rolls, moves, targeting, undos (Ctrl+Z) and a system adapter's acts, except the events SecondChair's own writes triggered (`secondchair: true`), so a Desk gesture counts once;
- `table_friction`: how many frictions the players had; never part of GM effort;
- `frictions`: each with its `detector`, the `user` and their `name`, `gm`, and the trace span it cites: `from` and `to`, the `t` of the first and last trace records it rests on.

The detectors are a closed, deterministic list (TRC-03). Thresholds are the defaults below unless `friction_thresholds` in `workspace.yaml` overrides them.

| Detector | Whose | Fires on | Thresholds (default) |
|---|---|---|---|
| `rules-lookup` | GM in live sessions, players | a compendium document opened (`window.open` of a `Compendium.` UUID) | |
| `hunting` | GM, players | windows opened and closed with no act in between | `hunting_windows` (3) within `hunting_s` (30) |
| `long-gm-creature-turn` | GM | a GM creature's turn (`turn` with `own`) until the next turn | longer than `gm_turn_s` (90) |
| `manual-correction` | GM | an undo (Ctrl+Z, or the adapter's `undo`) or a cancelled move soon after an act, or the same roll formulas again | within `correction_s` (10) |
| `dead-time` | GM | no input at all in a GM creature's turn | `dead_time_s` (20) |
| `long-turn` | players | the player's own turn until the next turn | longer than `player_turn_s` (120) |
| `cancelled-roll-dialog` | players | the adapter's `roll.cancel` | |
| `rage-clicks` | players | clicks at one spot | `rage_clicks` (3) within `rage_s` (2) and `rage_px` (24) screen pixels |
| `click-on-nothing` | players | a click on no element, or on the bare page | |
| `late-targeting` | players | a `target` after the adapter's `action`, `strike` or `spell` | within `retarget_s` (10) |
| `stumbling-input` | players | deletions while typing in a text field | `stumble_deletions` (5) within `stumble_s` (10) |

Times are in seconds. The playbook `diagnose-frictions` (TRC-06), run on demand, reads a report and proposes delegation table changes; it never makes them.

```markdown
---
moment: live-session
seq: 2
gaps:
- user: aB3dE5fG7hI9jK1l
  name: Alice
  from: '2025-10-09T08:53:20Z'
  to: '2025-10-09T08:54:50Z'
  lost: 42
gm_effort:
  interactions: 4
  manual_acts: 31
table_friction: 1
frictions:
- detector: hunting
  user: gM1aB3dE5fG7hI9j
  name: Gamemaster
  gm: true
  from: 1760000010000
  to: 1760000015000
- detector: rage-clicks
  user: aB3dE5fG7hI9jK1l
  name: Alice
  gm: false
  from: 1760000160000
  to: 1760000161000
---

# Friction report: live-session (moment 2)

## Trace gaps

- Alice: 42 records lost from 2025-10-09T08:53:20Z to 2025-10-09T08:54:50Z, with no GM client to relay them (TRC-05).

## GM effort

35: 4 interactions with SecondChair (a Director's Desk gesture counts once) and 31 manual acts in the VTT.

## GM frictions

- hunting: Gamemaster, 2025-10-09T08:53:30.000Z to 2025-10-09T08:53:35.000Z.

## Table friction

Player frictions: watched over time, never part of GM effort.

- rage-clicks: Alice, 2025-10-09T08:56:00.000Z to 2025-10-09T08:56:01.000Z.
```

## `capture/`

Candidate facts (CAP-04..06), one YAML file each, named by the candidate's **key**: the first 16 hex digits of the SHA-256 of its Source path and quote, so a rerun of capture finds what it already holds and yields only what is new. The wrap job (`wrap-a-session`) submits them with `capture_candidate` ([tool registration](tool-registration.md#jobs)); a quote is short, so the workspace keeps quotes, never the Source (CAP-15).

```yaml
key: 3f2a9c0d1e4b5a6f
session: 1
job: 4
source: /home/gm/notes/01-dry-bell.md   # one of the job's inputs
locator: 01-dry-bell.md:7
quote: Edda paid the party 12 silver coins for inspecting the bell chain.
translation: null        # the quote in the campaign language, when the Source is in another
statement: Edda Vale paid the party 12 silver coins.
date: '0302-04-26'
classification: certain  # certain, duplicate, contradiction, blocking_ambiguity, non_blocking_ambiguity
reason: null             # for the GM, required unless certain
entities: [e-1a2b3c4d]
relation: null
closes: []               # facts this played event ends
known_by: [party, e-1a2b3c4d]
duplicate_of: null       # the fact a duplicate repeats
new_names: []            # names canon does not know yet
inferred: false          # the statement goes beyond the quote: agent proposal, not played
status: applied          # captured, applied, pending, duplicate, held, unattested, rejected or failed
entries: [12, 13, 14]    # the action log entries it produced
error: null
fact: f-5e6f7a8b         # once applied, or the fact a duplicate repeats
```

- **No quote, no fact**: a candidate whose quote is empty or not in the Source, read from the job's input, is dropped and never stored.
- **Near-miss** (CAN-23, CAP-12): the Core makes a candidate a `blocking_ambiguity` when its statement, or one of its `new_names`, is close to a canon name without being it (spelling similarity of 0.75 or more, case and a possessive `'s` ignored).
- **Consolidation** (`consolidate_candidates`, CAP-10), under the wrap job, bound by the job's moment: a `certain` or `non_blocking_ambiguity` candidate is recorded with `record_fact` at the memory cell's level (`pending` when the cell holds it for approval), from its date, or opened by a played `record_event` closing `closes`; then `record_knowledge` for each of `known_by` on its date (CAP-08). Its origin is an `observation` with the quote and locator, ranked played (CAP-05), or a `job` origin carrying them, ranked agent_proposal, when `inferred`; a `translation` rides in the origin. A `duplicate` adds no fact: the candidate file is the added provenance, and its `known_by` learn the repeated fact. A `contradiction` or `blocking_ambiguity` is always a call on the GM, whatever the memory level: its `record_fact` is held at propose (`held`), the call's `message` saying why. The GM approves it to admit it as written, or rejects it (`rejected`). A candidate whose fact the table held for approval is `pending`; once the GM approves either, the wrap records its event and knowledge. A candidate whose actions fail part way is `failed`, its `error` and the entries already applied kept for the GM.
- **New names** (CAP-12): an entity is created for a name in `new_names` only once two candidates attest it; until then the candidate is `unattested` (flagged, nothing applied) and is reconsidered at the next consolidation. A held candidate never creates an entity.

## `time.yaml`

Fictional time (CAP-14, CAL-14, LW-05): the current date, null until a wrap or a GM gesture sets it, and each session's interval.

```yaml
current_date: '0302-04-26'
sessions:
  1: {start: '0302-04-25', end: '0302-04-26', from: notes, wrapped: true}
```

- The wrap job reports the interval its notes state (`report_session_interval`, quoting them): `from: notes`.
- The VTT clock observed during the session proposes it too (CAL-14): the first and last `clock` observations of the session ([foundry-bridge.md](foundry-bridge.md), "The rules context and the world clock"). The wrap takes it when the notes give no interval (`from: clock`), and asks the GM for `--start` and `--end` when the two disagree.
- `secondchair date` shows the current date; `secondchair date <date>`, in an interactive terminal, sets it (a GM gesture). At session start a served Core pushes it into the VTT clock when the calendar is a System extension's named one (CAL-11).
- `secondchair wrap <session> [--start <date>] [--end <date>]`, in an interactive terminal and outside a live session, is the GM's grouped round (CAP-13). It refuses while a wrap job for the session is queued or started, or a candidate is not consolidated. First come the session's open calls, held questions with contradictions leading, then pending proposals, which the GM answers with `secondchair approve` or `secondchair reject`, then, once none is open, what was applied with its action log entries, each undoable with `secondchair log undo`. It then settles the interval (the GM's dates over the notes' or the clock's, `from: gm`; it asks for `--end` when none gives one), refuses an end before the current date, moves the current date to the end and queues the world-turn job (`world-turn`, under living world, inputs `until`, the new current date, and `since`, the session start, used only while `living-world.yaml` has no cursor) (LW-07). Its agent starts the Core's world-turn with `run_world_turn`; the GM may run `secondchair world turn` instead. A wrapped session is not wrapped again.

## `canon/entities/`

An entity carries identity only (CAN-02): YAML front matter, then its player-facing description in the campaign language.

```markdown
---
id: e-1a2b3c4d
names: [Frère Ezren]
aliases: [Ezren]
kind: npc
official_reference: null
---
Un prêtre voûté.
```

`kind` is `pc`, `npc`, `faction`, `place`, `item` or `other`, or null (or absent) until it is set; any other value is refused. An entity of kind `pc` is never a knower (CAN-13).

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
| `origin` | Provenance (CAN-07), by `kind`: `observation` (`quote` verbatim, `locator`) ranks played; `source` (`source`, `page`) ranks cited_source; `gm` (`words`) ranks agent_proposal when an agent records it, and gm_decision once the GM confirms it with `secondchair confirm <id>` in an interactive terminal (CAN-09, DEL-29), which rewrites the rank and logs a `confirm` GM interaction; `job` (`job`) ranks agent_proposal and cannot be confirmed; `rule` (`fact`, `key`) is written by the world-turn only, for a rule effect: it takes the rank of the rule fact it applies (ADR 0009). Approving a proposal never raises its rank (CAN-08). |
| `state` | Optional (LW-03): makes it a **state fact** of a front or a situation, `{of, key, value}`, `of` one of its `entities`. `key` and `value`: `front` `{carrier, participants: [], capacity, every (a duration ≥ 1d), ticks: 1, anchor (a date), unless: null (a condition in words), active: true}`; `clock` (an integer ≥ 0); `agenda` `{id, when: {date} or {clock_gte}, status: pending, done or averted}`, one fact per step; `situation` `{stage: available, active (the party engaged it), resolved or expired, deadline: null, participants: []}`. An entity holds at most one current fact per key (one per agenda step). Every change is an offscreen event closing the old state fact and opening the new one. |
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

- Knowers are the party as a whole (`party`; individual PCs are not knowers, so a record whose knower is an entity of kind `pc` is refused), an NPC or a faction. A record whose knower is a place is that place's **common knowledge**.
- A disclosure (a VTT action with `cites`, [tool registration](tool-registration.md)) writes, once applied, one record per cited fact the party does not know yet (CAN-17): knower `party`, mode `knows`, `date` the current date of `time.yaml`, an `observation` origin whose `locator` is the disclosure's action log entry (`action-log/000012.yaml`), ranked played, and `session`, the live session it was disclosed in (null outside one). Each record is written by its own irreversible action entry. `session` is optional on other records.
- Knowledge is closed-world: a knower holds only its own records, plus those of the factions it is a `member_of` and the places it `lives_in` (one level; a faction never inherits from its members). With a date, only relations valid then and records learned by then count. A fact held several ways takes its strongest mode (knows, then believes, then suspects).
- A never-true fact is believed or suspected, never known. Records on retconned facts are ignored.
- Content written for an audience (an NPC line, a disclosure, an entity description) cites the ids of the facts it uses and goes through `check_audience_content` (CAN-16): refused when a cited id is not in canon, when the audience does not hold a cited fact, or when the text carries a canary (`CANARY-<zone>-<n>`) or an entity name (or alias) that appears in no fact the audience holds, the audience's own names excepted. Names match whole-word and case-sensitive; paraphrased leaks are not blocked, the test bench measures them. A disclosure is checked by the Core's delegation wrap instead ([tool registration](tool-registration.md)): no knower bounds it but its acting NPC, if any, since it teaches the party what it cites (CAN-17).

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

The derived index (CAN-10): entities, facts, events and knowledge with their derived validity and status, and full-text tables over names, statements and descriptions (CAN-12). It records a fingerprint of `workspace.yaml`, `canon/` and `action-log/`, and any read rebuilds it when they changed. `secondchair check` (in the workspace, or with `-w <workspace>`) rebuilds it from the directory alone, with no Foundry and no Source (PKG-15), logs any hand edit, also validates `moment.yaml`, `delegation.yaml`, the action log, job, call and occurrence files, names each invalid file and exits 1 if there is one. It lists the hand edits awaiting promotion. Deleting `.secondchair/` loses nothing.

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
  purchased_content:   # LIC-12: directories or files of purchased content (e.g. a premium Foundry module)
    - path: ~/foundrydata/Data/modules/pf2e-beginner-box
      opt_in: false    # true sends its content to models; default false
  ```

  Next to it, `foundry-token` (mode 0600) holds the token the Foundry module connects with, created by `secondchair token` ([foundry-bridge.md](foundry-bridge.md)).

  `runners` is keyed by tier only (`fast`, `standard`, `deep`); a tier with no entry has no runner, and its jobs wait for the GM to start them from their own agent host session. Each entry names a host, a model and an effort; model names appear only here (ARC-25). A host is a command template whose `{prompt}`, `{model}`, `{effort}`, `{playbooks}` (a block's playbook directory; an argument naming it is repeated for each installed block) and `{job}` are filled in; the built-in `claude` and `codex` templates run Claude Code (`claude -p`, with each block's playbooks as a plugin directory and only the SecondChair tools and file reads allowed) and Codex (`codex exec`) headless, both reaching the Core through the MCP configuration `secondchair host setup` prints. An entry whose command cannot be run or exits with an error is a failed attempt, and the next entry is tried.

`purchased_content` lists the GM's purchased content (LIC-12). Without `opt_in: true`, it is indexed by metadata only: when a job is queued, an input naming such a path, or a directory holding one, is replaced by the path of its **metadata index**, `.secondchair/purchased/<16 hex digits of the SHA-256 of the path>.yaml`, so none of its text reaches the job. The index holds the path's name, `opt_in: false`, a note for the agent and each file's relative `path` and size in `bytes`; nothing of the content. With `opt_in: true` the input is passed as given.

- **Behaviour traces** (TRC-04) are a Source kept by the Core in `$XDG_DATA_HOME/secondchair/traces/<campaign id>/<user id>.jsonl` (default `~/.local/share/secondchair/`), never in the workspace and never sent anywhere ([foundry-bridge.md](foundry-bridge.md), "Behaviour traces").

- **Sources** (raw audio, full transcripts, Foundry worlds, rulebooks) stay outside both; the workspace only references them (PKG-12).

## In the tool repository

The tool never ships a workspace (LIC-09). The CI guard `scripts/guard_no_workspace.py` (LIC-10) fails on any tracked `workspace.yaml`, any file under a `.secondchair/` directory, and files that look like Sources (audio, PDF, a Foundry `world.json`), except inside the sample campaign's folder, `sample-campaign/`.
