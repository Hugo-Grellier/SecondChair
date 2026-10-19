# Contract: campaign workspace layout

Workspace schema version: **1**. Requirements: ARC-17a, CAN-02, CAN-10, CAN-18, CAL-01, CAL-02, CAL-03, CAL-04, LIC-09, PKG-13, PKG-16.

A **campaign workspace** is a directory the GM chooses, outside the tool repository, optionally inside a private repository of their own (LIC-09). It is the source of truth for one campaign and its full export (PKG-15). `secondchair init <dir> --language <bcp47> --calendar <name | file.yaml>` creates it; `secondchair serve <dir>` serves it.

## Tree

```text
my-campaign/
├── workspace.yaml     # schema version, campaign language and calendar; written by `init`
├── delegation.yaml    # the delegation table; seeded by `init`
├── moment.yaml        # the current moment; seeded by `init`, changed by `secondchair moment`
├── action-log/        # one YAML file per action log entry: 000001.yaml, 000002.yaml, …
├── canon/
│   └── entities/      # one Markdown file per entity: e-1a2b3c4d.md
├── .gitignore         # contains `.secondchair/`; `init` appends to an existing one
└── .secondchair/      # derived state (SQLite index, caches, the write lock); git-ignored, rebuildable
```

Later contracts add facts, decisions, the speaker table and friction reports, each as Markdown + YAML (CAN-10). Nothing in `.secondchair/` is a source of truth: deleting it loses nothing.

## `workspace.yaml`

```yaml
schema_version: 1
campaign_language: fr
calendar: absalom
```

| Key | Type | Rule |
|---|---|---|
| `schema_version` | integer | The workspace schema this file follows (PKG-16). A version newer than the running SecondChair supports is refused. An older one blocks `serve` until `secondchair upgrade` migrates it in place, as a reviewable diff. |
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

One YAML file per entry, named by its id on six digits, following [`action-log-entry.schema.json`](action-log-entry.schema.json): delegated actions (`kind: action`) and the GM interactions on them (`kind: gm_interaction`: approve, reject, undo). An action records the workspace file it writes (`target`) and that file's content before and after, which is what undo restores. The Core refuses to approve or undo when the file no longer holds the content the entry expects, such as after a hand edit, so nothing is overwritten unseen.

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

## What is not in the workspace

- **The machine configuration** (PKG-13) lives in `$XDG_CONFIG_HOME/secondchair/` (default `~/.config/secondchair/`) and never travels with the workspace. Its `config.yaml` holds, so far, the port `serve` listens on:

  ```yaml
  port: 7240   # default when the file or the key is absent
  ```

- **Sources** (raw audio, full transcripts, Foundry worlds, rulebooks) stay outside both; the workspace only references them (PKG-12).

## In the tool repository

The tool never ships a workspace (LIC-09). The CI guard `scripts/guard_no_workspace.py` (LIC-10) fails on any tracked `workspace.yaml`, any file under a `.secondchair/` directory, and files that look like Sources (audio, PDF, a Foundry `world.json`), except inside the sample campaign's folder, `sample-campaign/`.
