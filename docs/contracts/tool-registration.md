# Contract: tool registration and the Core's MCP endpoint

Protocol version: **0.1.0** (`secondchair.core.PROTOCOL_VERSION`). Requirements: ARC-01, ARC-02, ARC-03, ARC-04, CAN-12, DEL-09, DEL-10, DEL-14, DEL-18, DEL-21, DEL-28, ARC-17, ARC-17a, ARC-19, ARC-21, ARC-23, ARC-23a, ARC-29, PKG-05, PKG-06, PKG-19, ARC-10, DEL-23, RUL-03, RUL-04, RUL-05, RUL-06, RUL-07, RUL-08, RUL-09, RUL-12, DEL-22.

## The MCP endpoint

`secondchair serve -w <workspace>` carries the Core's MCP server over **Streamable HTTP** at `http://127.0.0.1:<port>/mcp`, the port coming from the machine configuration (default 7240). There is no stdio mode: every agent host (the GM's session, the runners) shares this one Core. The endpoint is unauthenticated and bound to loopback only; requests whose `Host` or `Origin` is not a loopback name are refused (DNS rebinding). `GET /` answers `{"service": "secondchair", "campaign_language": …, "protocol_version": …}`.

`secondchair host setup <claude|codex>` prints the configuration an agent host needs to reach that endpoint, and how to install the playbooks: for Claude Code one plugin per block (`claude plugin marketplace add <playbooks>` then `claude plugin install <name>@<name>`, `secondchair` for the Core's), for Codex every skill linked into `~/.codex/skills/`. It writes no file: the GM pastes or runs what it prints.

## Registering tools

The Core is the only MCP server agents see (ARC-03). A block (System extension, VTT connector, or the Core itself) registers tools through a Python **entry point** in the group `secondchair.tools`:

```toml
# the block's pyproject.toml
[project.entry-points."secondchair.tools"]
pf2e = "secondchair_pf2e.tools:BLOCK"
```

The entry point names a `Block`: the protocol range the block supports and a function called once when `serve` starts, with the served `Workspace`, returning the block's tools:

```python
from secondchair.core.tools import Block, Tool
from secondchair.core.workspace import Workspace


def tools(ws: Workspace) -> list[Tool]:
    def roll_initiative(creature: str) -> str:
        """Roll initiative for a creature."""
        ...

    return [
        Tool(
            fn=roll_initiative,
            responsibility="rules_and_combat",
            delegated_action=True,
            reversible=False,
        ),
    ]


BLOCK = Block(protocol=("0.1.0", "0.2.0"), tools=tools)
```

| `Block` field | Type | Rule |
|---|---|---|
| `protocol` | pair of strings | The protocol range the block supports (ARC-17): the lowest version it supports and the first it does not, each `X.Y.Z`. `serve` refuses the block unless the Core's protocol version lies in it. |
| `tools` | function | Called with the served `Workspace`, returns the block's `Tool`s. |

| `Tool` field | Type | Rule |
|---|---|---|
| `fn` | function | Its name is the MCP tool name, its docstring the description, its typed parameters the input schema. Names are unique across all blocks. |
| `responsibility` | string | One of `prep`, `memory`, `vtt_operations`, `rules_and_combat`, `living_world`, `npcs`, `narrative_direction`, `disclosure` (DEL-01). |
| `delegated_action` | bool | `true` for a delegated action, `false` for a read. |
| `reversible` | bool | Whether the action can be undone (DEL-25). A read declares `true`. |

All three declarations are required. An entry point naming no `Block`, a protocol range not holding the Core's version, a registration missing a declaration, with an unknown responsibility or a non-boolean flag, a duplicate name, or an entry point that raises, stops `serve` before it listens, with a message naming the block.

## Delegated actions

The Core wraps every delegated action (ARC-04). A delegated action's `fn` does not act: it describes its effect and returns a `Change`, and the Core decides what happens to it.

```python
from secondchair.core.tools import Change


def create_note(title: str) -> Change:
    """Create a note."""
    return Change(path=f"notes/{title}.md", after=f"# {title}\n")
```

| `Change` field | Type | Rule |
|---|---|---|
| `path` | string | The workspace file the action writes, relative to the workspace root. |
| `after` | string or null | The file's new content; null deletes it. |
| `source` | string or null | What the action draws on, recorded in the log (DEL-24). |
| `entity` | string or null | The **acting entity**'s canon id (the NPC who speaks, the creature that strikes), never the entity the action is about; null (the default) when nothing acts, such as scene prep or a world-turn (DEL-10). Entity overrides key on it. |

An action that acts in the VTT returns a `VttAction` instead, which the Core logs and has the VTT connector take ([foundry-bridge.md](foundry-bridge.md#actions-arc-04-arc-07-arc-09)). The Core reads none of its fields; the connector gives them their meaning.

```python
from secondchair.core.tools import VttAction


def move_token(token: str, x: int, y: int) -> VttAction:
    """Move a token on its scene."""
    return VttAction(op="move_token", target=token, params={"x": x, "y": y})
```

| `VttAction` field | Type | Rule |
|---|---|---|
| `op` | string | The connector's operation, generic or mechanical. |
| `target` | string | The document acted on, as the connector names it (a Foundry UUID). |
| `params` | object | The fields to set. |
| `source` | string or null | As for `Change`. |
| `entity` | string or null | As for `Change`. |
| `cites` | list of strings or null | A disclosure's facts: the ids of what the players learn from it (CAN-16). The Core refuses the action when one is not in canon, is never true or carries a canary, when the acting `entity` (an NPC who discloses) does not know it, or when `time.yaml` has no current date, and checks again at the GM's approval; the party need not know them beforehand; it logs them as `cites`, and once the action is applied (at once, or at the GM's approval) marks each one the party does not know yet as known by the party, on the current date and in the current session (CAN-17; [knowledge](workspace-layout.md#canonknowledge)). Null (the default) for an action that shows the players nothing. |
| `whisper` | boolean | True for a disclosure shown to some of the table only: its `cites` mark nothing known by the party, the wrap holds each as a call on the GM instead (CAP-08). Logged as `whisper` with the live `session`. False by default. |
| `hold` | string or null | Holds the action at propose whatever the level, the call carrying it as its `message`: an action the GM resolves, which an agent may only propose (RUL-08). Null (the default) otherwise. |

The log entry of a VTT action carries `op`, and the fields the VTT reported `before` and `after` it. A VTT action the VTT did not take is a **failed action**: logged with status `failed` and its `error`, and returned to the agent as an MCP error. The Foundry connector registers `move_token` and `set_door` (VTT operations, reversible), `reveal_token`, `publish_journal`, `speak(token, line, cites, entity)` and `whisper(user, line, cites)` (disclosure, irreversible, each with `cites`; `speak` has a creature say a line aloud to the table; `whisper` tells one player, a Foundry User, which marks no fact known by the party: the wrap asks the GM, CAP-08), and `prepare_scene` (prep, reversible), which writes a scene's desired state, with its reads `scene_report` and `asset_check` ([foundry-bridge.md](foundry-bridge.md#prepared-scenes-arc-10-bve-02)), and `prepare_document(key, type, data, base, choice)` (prep, reversible), which writes a world document's (a journal, an actor, an item, a playlist, a roll table), with its read `document_report` ([foundry-bridge.md](foundry-bridge.md#prepared-world-documents-arc-07-arc-10)). Its prep reads `browse_files(path, source, extensions)`, `search_compendium(query, type, limit)` (returning `{entries, offline, snapshot}`), `image_size(path)` and `list_world_documents(type, query)` find the files, compendium entries and world documents of the GM's install ([foundry-bridge.md](foundry-bridge.md#reads-can-20-rul-22)). Its read `lookup_rule(query, type, limit)` (rules and combat) cites rule entries from the offline snapshot alone, whether or not a GM client is connected: each entry has its UUID and the snapshot's system version and translation module, and `house_rule_notice` names the campaign's house rules (RUL-22, RUL-23); it returns no book text. Its read `official_name(key, pack)` (under memory) returns the name official game content has in the GM's install, in the campaign language, with the official reference to store on a new entity; `name` is null when the entry has no translation (CAN-20, CAN-21; [foundry-bridge.md](foundry-bridge.md#reads-can-20-rul-22)).

The Core adds a required `agent` string argument to every delegated action's MCP input schema: the agent's name, recorded for traceability only (ARC-22). It also adds an optional `job` integer: the job the agent is running (see below), and an optional `blocking` boolean (default false): whether the table waits on this action to go on with the current turn or scene, which makes its proposal due now rather than at the next break (DEL-30; a job's actions block as the job does). A block's `fn` must not have an `agent`, `job` or `blocking` parameter. On each call the Core reads the current moment and the delegation table, then:

| Effective level | What happens | Result |
|---|---|---|
| manual | refused; nothing is written or logged | an MCP error saying why |
| propose | logged as pending, a call on the GM ([calls](workspace-layout.md#calls)); nothing is written until the GM approves | `{"entry": 3, "status": "pending"}`, or `"rejected"` when a blocking call forced to break takes its safe default at once (DEL-31) |
| act-then-review, autonomous | written at once and logged | `{"entry": 3, "status": "applied"}` |

An irreversible action is held at propose while its cell's hold is set (DEL-09, DEL-09a; [workspace layout](workspace-layout.md#delegationyaml)), and only an authenticated Surface approves it (DEL-29). Once the GM lifts the hold, it runs at the cell's effective level: applied at once, logged, and never undoable. A narrative-direction action is held at propose whatever its cell (DEL-08).

An action taken for a world-turn job, whose responsibility is `living_world` or `narrative_direction`, is also governed by the job's responsibility, since the class of the effect decides (ADR 0009). It takes the stricter of the two effective levels (DEL-23) and is logged under the job's responsibility. Under `living_world`, a `disclosure` tool, or an action that makes the party know a fact (a knowledge record whose knower is `party`), is refused: the living world never discloses (LW-08).

The effective level is the table cell for the moment, lowered by every **entity override** of the action's acting entity for that responsibility and moment (DEL-12; [workspace layout](workspace-layout.md#entity-overrides)); the log entry records the `entity` and whether an override lowered the level (`override_lowered`). An override at manual refuses the action like a manual cell.

The Core can hold an action at propose whatever the level: the wrap does so for a contradiction or a blocking question (CAP-10), the call carrying the reason as its `message`.

A delegated action's `fn` that finds its change would contradict canon raises `secondchair.core.tools.Contradiction(path, message)`. The Core writes nothing, logs the action with `status: refused` and the message as `refusal` (a continuity error, MET-01), and returns an MCP error.

The PF2e System extension (`secondchair_pf2e.tools`) registers a GM creature's turn in an encounter, under rules and combat and reversible, each one VTT action the PF2e adapter's executor takes ([foundry-bridge.md](foundry-bridge.md#the-executor-rul-0310)): `strike(creature, strike, target, attack, entity)`, `use_action(creature, action, target, entity)`, `saving_throw(target, save, dc, entity)`, `cast_spell(creature, spell, rank, variant, actions, entity)`, `use_self_effect(creature, item, entity)`, `place_area(creature, area, size, x, y, direction, name, entity)` and `reactive_strike(creature, strike, target, trigger, entity)`, the tokens named by their Foundry UUIDs and `entity` being the acting creature's canon id. `cast_spell` with `actions` (the cost an agent proposes for a variable-cost spell with no overlay, which the adapter refuses without it) is held at propose whatever the level, with `hold`: the GM resolves it (RUL-08). The adapter refuses them outside a started combat, and `strike` and `use_action` for a PC (RUL-03, RUL-04): a failed action. While a known turn driver is active it refuses every one of them for every creature, also a failed action: the GM runs turns through the driver, and SecondChair observes and checks them as the GM's acts (RUL-12, DEL-22). `saving_throw` on a PC rolls nothing: its player is asked to roll. A strike and the line its creature shouts are two actions, `strike` under rules and combat and `speak` under disclosure, each checked on its own (DEL-23).

The Core's own delegated actions are all under memory and reversible: `create_entity`, `record_fact`, `correct_fact`, `record_event` and `record_knowledge` ([workspace layout](workspace-layout.md#canonfacts)).
The mystery graph adds `record_mystery`, under prep and reversible ([workspace layout](workspace-layout.md#canonmysteries)).

## Rules checks and discrepancies

A System extension registers its rules checks (RUL-14) through the entry point group `secondchair.rules_checks`: a function `(observation, earlier) -> [(check, text)]`, where `earlier()` returns the observation's live session in capture order. The PF2e System extension registers `secondchair_pf2e.checks:check`, which tests each `pf2e.outcome` observation ([`pf2e-outcome.schema.json`](pf2e-outcome.schema.json)) against its own trace, with the kinds of check `modifiers`, `degree`, `damage`, `resource`, `conditions`, `activity` and `follow_up` (an agent action's ambiguous follow-up, RUL-10), reading third-party flags through its trace readers (`secondchair_pf2e.readers`, RUL-19). The Core runs every checker on each observation it records for the first time; a checker that raises is reported on stderr and checks nothing. A failed check is a **discrepancy**: a call on the GM ([workspace layout](workspace-layout.md#calls)), unless a house rule silences its kind.

`fix_discrepancy(discrepancy, op, target, params, agent, job)` is served by the Core outside block registration, with the `_meta` of a delegated action under rules_and_combat: it proposes the VTT action that fixes an open discrepancy (such as the PF2e adapter's `set_actor`), which the Core holds at propose whatever the level, the proposal's call carrying the discrepancy as its message; the discrepancy's call is answered. Fixing is never automatic (RUL-17).

On the CLI: `secondchair house-rule mark <call> <name>` marks an open discrepancy as intended, recording a named house rule that silences its kind of check (interactive terminal only, since it turns a check off); `secondchair house-rule list`; `secondchair house-rule remove <name>`, after which that kind of check runs again (RUL-24).

## GM interactions relayed by agents

`approve_proposal(entry, gm_words)` is served by the Core itself, outside block registration, with `_meta: {"secondchair/gm_interaction": true}`. An agent calls it only when the GM approved a pending reversible action in conversation, quoting the GM's words; the approval is logged "via agent" with the quote (DEL-28). An irreversible action cannot be approved this way.

`add_entity_override(entity, responsibility, level, gm_words, moment)` is served the same way: an agent calls it when the GM asks in conversation to lower the level for one acting entity, quoting the GM's words; it is logged "via agent" (DEL-14). There is no tool to remove an override: loosening needs an authenticated Surface.

On the CLI, in the workspace (or with `-w <workspace>`): `secondchair approve <entry>`, `secondchair reject <entry> --reason <reason>`, `secondchair log undo <entry> --reason <reason>`, the reason one of contradiction, rules, tone, other (DEL-26), and `secondchair moment <prep|live-session|between-sessions>`, which needs an interactive terminal (DEL-03a), and `secondchair override add <entity> <responsibility> <level> [--moment <moment>]` and `secondchair override remove <entity> <responsibility> [--moment <moment>]`, the latter from an interactive terminal only (DEL-14). The Director's Desk in Foundry approves, rejects and confirms too ([foundry-bridge.md](foundry-bridge.md)). The log records the channel each GM interaction came through (`cli`, `desk`, `via agent`) and whether it was authenticated: an interactive terminal or the Desk (`authenticated`).

Approving or undoing a VTT action needs the GM client, which only the `serve` process holds. The CLI therefore relays those two gestures to `POST /gm` on the Core serving the campaign, found through `.secondchair/serve.json`: `{"gesture": "approve" | "undo", "entry", "reason", "authenticated", "workspace"}` with `Authorization: Bearer <token>`, the token `secondchair token` prints. The Core refuses a wrong token (401), a malformed gesture (400) and another workspace's gesture (409), and answers a refused gesture with 409 and its message. With no Core serving the campaign, the CLI says to run `secondchair serve`.

## Jobs

An agent running a job ([`job.schema.json`](job.schema.json)) passes `job` to every delegated action. The job must be started; the action is then bound by the delegation table of the job's moment (a manual cell refuses it), and its log entry records the job and the runner configuration it was started with. Omitting `job` does not leave the job (ARC-23a): a session-keeping client (handshake protocols) is bound to the job it starts with `start_job`, or first acts for, until the job ends, so its delegated actions are for that job with or without `job` and refused for another job, and `start_job` is refused while it runs one; a sessionless client (2026-07-28) gets every delegated action without `job` refused while a `living_world` or `narrative_direction` job is started. Three tools, served by the Core outside block registration with `_meta: {"secondchair/job": true}`, let a session take, answer and close a job:

| Tool | Does |
|---|---|
| `start_job(job, host, model, effort)` | Starts a queued job from the GM's own session (ARC-29): the host, model and effort the session reports are logged as the effective configuration. Returns the job record; its tier is only a hint. |
| `finish_job(job)` | Marks a started job done. For a job whose playbook writes (`writes` in the job contract), it is refused, and the attempt keeps running, until the action log holds at least one applied or pending delegated action under that job; the refusal lists the job's logged actions. Finishing a job that is already done changes nothing. |
| `settle_unless(occurrence, unless_holds, cites, job)` | The answer of a started `settle-an-unless` job (LW-10): whether a front's `unless` held on the tick's date, citing the ids of canon facts valid then. Held: the tick is suppressed. Not held: the tick applies at the agent-proposal rank. `null` or no citation: a call on the GM at the next break, and the tick stays queued. |

The "wrap a session" job adds three tools, served the same way (CAP-04..13; [workspace layout](workspace-layout.md#capture)):

| Tool | Does |
|---|---|
| `capture_candidate(job, source, locator, quote, statement, date, classification, reason, entities, relation, closes, known_by, duplicate_of, new_names, inferred, translation)` | Submits one candidate fact quoting `source`, one of the started job's inputs, verbatim. Returns its `key` and `captured`, `seen` (already captured: a rerun) or `dropped` (no quote, or a quote not in the Source). In the job's `transcript`, `locator` is `<file>:<line>` and the quote must be in that segment's `text`; the candidate records the segment's `speaker`. |
| `report_session_interval(job, start, end, quote, locator)` | Records the session's fictional interval as a Source of the job states it, quoted (CAL-14). From the job's `transcript`, `locator` (`<file>:<line>`) names the segment whose decoded `text` holds the quote. |
| `consolidate_candidates(job)` | Routes the session's captured candidates through the Core's delegated actions, under the job; returns each candidate's outcome. |
| `run_world_turn(job)` | For a started `world-turn` job, which a wrap queues (LW-07): runs the Core's world-turn up to the job's `until` and returns the occurrences recorded. |

A runner started by `secondchair jobs run` logs its attempt itself and gives the agent the contract in its prompt; the job is done only when the agent calls `finish_job`. An agent that exits cleanly without it is a failed attempt (ARC-27); a retry's prompt lists the actions the job already took, so it continues rather than redoes them. When every configuration fails, the exception call lists the actions the job took, which stay logged and undoable.

## Playbooks

A playbook is an [Agent Skills](https://agentskills.io/specification) skill (`skills/<name>/SKILL.md`), in English, telling the agent to write in the campaign language (ARC-21). Its front matter's `metadata` declares what the Core needs to queue a job for it, never a model name (ARC-25):

```yaml
metadata:
  secondchair-responsibility: memory
  secondchair-tier: standard              # fast, standard or deep; a job may override it
  secondchair-inputs: bible               # comma-separated input names; a trailing ? marks one optional
  secondchair-expected-output: One canon entity per named person, place, …
```

Each block ships its playbooks in one directory that is both a Claude Code plugin (`.claude-plugin/`, the plugin and its marketplace named alike) and, through its `skills/` directory, a Codex skill bundle (PKG-19), registered under the `secondchair.playbooks` entry point group as the directory's path. Playbook names are unique across blocks. The Core's live in `src/secondchair/playbooks/` (`secondchair`): `rebuild-entities-from-a-bible` (memory, standard; it creates the bible's entities, then records its facts with `record_fact`, citing the bible paragraph, with a relation where the Core list fits, who knows what at start with `record_knowledge` and each mystery's graph with `record_mystery`, under prep), `answer-probes` (memory, standard; input `probes`, a file of questions and answer shapes), which answers probes from canon in the GM view and replies with one JSON object of structured answers in workspace entity ids, as the bench asks them, `wrap-a-session` (memory, standard; inputs `session` and the optional `notes`) and `world-turn` (living world, fast; inputs `until` and the optional `since`). `develop-campaign-direction` (prep, deep; the optional input `request`), an opt-in task skill on the campaign workshop that writes design notes under `notes/direction/` (ADR 0017) and, when asked, a player-facing campaign primer with `write_prep`; it writes no canon on its own. `write-an-npc-dossier` (prep, deep; the input `entity`), an opt-in task skill, drafts a short GM-only dossier note at `notes/npcs/<entity id>.md` (ADR 0017; the same file as the workshop's fuller dossier) from what canon holds, and writes no canon. The Foundry connector's VTT playbooks ship with it (ARC-10) in `src/secondchair_foundry/playbooks/` (`secondchair-foundry`): `realise-a-scene` (prep, standard; inputs `brief` and `scene`), which writes a scene's desired state and reads back its reconciliation report. The PF2e System extension's rules playbooks live in `src/secondchair_pf2e/playbooks/` (`secondchair-pf2e`): `calibrate-encounters` (prep, standard; inputs `adventure`, `party` and `encounters`), which prepares each listed encounter as a scene calibrated with `encounter_xp` and checks the treasure against `treasure_budget`.

## Setup check

`secondchair check-setup [-w DIR]` writes no host or machine file (PKG-19; the `status` block may refresh the derived index): it prints `ok`, `WARN` or `FAIL` for the workspace (valid, language, calendar, current date), something answering on the configured port (a loopback connect with no auth, so it cannot tell the Core from another listener), the Foundry token existing, an agent host (`claude`, `codex`) on `PATH`, each present host registering the Core at the configured URL (Claude Code: the user file `$CLAUDE_CONFIG_DIR/.claude.json` or `~/.claude.json`, its entry for this workspace's absolute path, and the workspace's `.mcp.json`; Codex: `$CODEX_HOME/config.toml`) and having the playbooks installed, runners configured, and the transcription engine on `PATH`, each with a one-action fix, then the `status` block (handoff, jobs, calls). It reports presence only: never the token or a runner's content. A machine `config.yaml` that cannot be used is a `FAIL` line and the check goes on; an unreadable Foundry token file is a `FAIL`. A host configuration it cannot find, parse or understand (a missing `~/.claude.json` included) is a `WARN`, and no message quotes its content or the parse error; each points to `secondchair host setup`. The exit code is 1 if any line is `FAIL`; runners, the transcription engine and the campaign date are `WARN`. `secondchair doctor` is unrelated: it re-checks the evidence of played and cited facts (ADR 0015).

## What agents see

Each tool in `tools/list` carries its declarations in `_meta`, and the matching MCP annotations:

```json
{
  "name": "roll_initiative",
  "_meta": {
    "secondchair/responsibility": "rules_and_combat",
    "secondchair/delegated_action": true,
    "secondchair/reversible": false
  },
  "annotations": {"readOnlyHint": false, "destructiveHint": true}
}
```

The Core's own reads, all under memory: `campaign_info` returns the campaign language, the workspace schema version and the protocol version; `search_entities(text)`, `search_facts(text, entity, relation, at, include_retconned)` and `search_events(text, fact)` search the derived index, structured and full text (every word of `text` must match); `what_knows(knower, at)` returns what a knower holds, inheritance included, and `check_audience_content(audience, text, cites, at)` checks content for an audience ([workspace layout](workspace-layout.md#canonknowledge)).  Under prep, `check_prep_guide(path, at)` runs that guard for the party over a whole prep note, and the PF2e extension's `check_prep(path)` lints a prep note's index block ([workspace layout](workspace-layout.md#the-index-block)). Under npcs, `show_acting_cue(npc, goal, line, cites, knows, does_not_know)` makes an NPC's acting cue the one the Director's Desk shows (DEL-15, [foundry-bridge.md](foundry-bridge.md#the-directors-desk-arc-12-arc-13-arc-14)): `line` goes through the same check as `check_audience_content`, every fact in `knows` must be held by the NPC and none in `does_not_know` may be; it replaces the active cue and, being a read, is accepted at every level, manual included. A read's refusal reaches the agent as an MCP error with its message. The mystery graph adds `check_mystery(mystery, lose)`, under prep: the graph with each element's state, its problems and warnings, `lose` simulating the loss of clues without writing. `check_draft_mystery(mystery, lose)`, also a read under prep, gives the same report for the draft note `notes/mysteries/<mystery>.md`, whose front matter has the graph of `canon/mysteries/` except that a conclusion or clue may carry a draft `statement` instead of a fact id; each statement stands for a synthetic fact that holds and that nobody knows. It writes nothing, and `secondchair mystery check-draft <slug> [--lose <clue>]` runs it from the command line (#177). `session_signals(session)`, also a read under prep, returns the deterministic signals for `propose-opportunities`: `unused_prep` (the clue ids of `prep/session-<n>/handoff.md` that no admitted played fact of the session found, plus the open `check_mystery` warnings of their mysteries), `spotlight` (as the wrap summary) and `fulfilled_triggers` (the `triggers: [{if, facts}]` of `notes/npcs/<id>.md` whose cited facts all hold in canon); `secondchair signals <session>` runs it from the command line (#185). The living world adds, under living world: `living_world()`, each front's clock, capacity, activity and agenda steps, each situation's stage and deadline, the world-turn cursor and the occurrences still queued; `forecast_world(until)`, what coming world-turns would record up to a campaign date, writing nothing (LW-18). The living world adds, under living world: `living_world()`, each front's clock, capacity, activity and agenda steps, each situation's stage and deadline, the world-turn cursor and the occurrences still queued; `forecast_world(until)`, what coming world-turns would record up to a campaign date, writing nothing (LW-18).

## Versioning

The protocol version is semver and versions this contract and the wire contracts that follow (ARC-17a); before v4.0 a breaking change is free. The Foundry modules' version is checked at the bridge handshake ([foundry-bridge.md](foundry-bridge.md)); a Python block declares the range it supports on its `Block`, and `serve` refuses an incompatible block at start, before it listens (#77). That range also covers the block's other entry points (connectors, rules checks, calendars, playbooks), which ship in the same distribution.
