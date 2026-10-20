# 02 — Architecture

Decisions: [ADR 0001](../adr/0001-no-in-house-orchestrator-llm-free-core.md), [ADR 0003](../adr/0003-core-is-the-only-gateway.md), [ADR 0004](../adr/0004-foundry-connector-library-plus-system-adapters.md), [ADR 0005](../adr/0005-core-schedules-calls-on-the-gm.md); tickets [#7](https://github.com/Hugo-Grellier/SecondChair/issues/7), [#8](https://github.com/Hugo-Grellier/SecondChair/issues/8), [#12](https://github.com/Hugo-Grellier/SecondChair/issues/12).

## Building blocks

```
            agent hosts (Claude Code, Codex, …)        GM
                    │  MCP (loopback HTTP)              │ CLI / conversation / Director's Desk
                    ▼                                   ▼
   ┌──────────────────────── secondchair serve ────────────────────────┐
   │  Core: canon, fictional time, knowledge, delegation, action log,  │
   │        calls on the GM, job queue, world-turn                     │
   │   ▲ entry points                     ▲ entry points               │
   │  System extension (PF2e, Python)    VTT connector, Python half    │
   └───────────────────────────────────────────────┬───────────────────┘
                                                   │ WebSocket, dialled by the GM's browser
                              Foundry: secondchair-foundry (library) + secondchair-foundry-pf2e (system adapter)
```

- **ARC-01** The Core depends on nothing. System extensions, VTT connectors and Surfaces depend only on Core contracts, never on each other.
- **ARC-02** One process, `secondchair serve <workspace>`, carries the MCP server and the VTT bridge for one campaign. System extensions and VTT connectors are Python packages loaded through entry points. The CLI uses the Core as a library.
- **ARC-03** The **Core is the only MCP server** agents see. Extensions and connectors MUST NOT expose tools of their own: they register tools with the Core, each declaring its responsibility, whether it is a read or a delegated action, and whether it is reversible.
- **ARC-04** The Core wraps every delegated action: level check against the effective delegation level, action log entry, undo. No agent ever talks to the VTT directly ([ADR 0003](../adr/0003-core-is-the-only-gateway.md)).
- **ARC-05** Languages: Python (`uv`) for the Core, System extension, CLI and the connector's Python half; JavaScript only inside the Foundry modules ([ADR 0002](../adr/0002-rebuild-rather-than-evolve.md)).

### Core

Game-agnostic and VTT-agnostic. It owns:

- canon: entities, facts, relations (closed Core list), events, knowers and knowledge, decisions ([04](04-canon-memory-capture.md));
- fictional time: the campaign calendar's arithmetic, the current date, the world-turn and its occurrences ([05](05-living-world-calendar.md));
- delegation: the delegation table, entity overrides, caps, the action log and undo ([03](03-delegation.md));
- calls on the GM: deadlines, breaks, safe defaults ([ADR 0005](../adr/0005-core-schedules-calls-on-the-gm.md));
- the job queue and job contracts;
- the generic event envelope and observations;
- the generic playbooks (prep a session, wrap a session, …).

The Core knows no rules vocabulary.

### System extension (PF2e)

VTT-agnostic Python. It provides:

- schema fragments and relation types added to the Core's lists;
- pure calculators (threat, XP, treasure), usable offline for prep;
- the Absalom Reckoning calendar as code ([ADR 0014](../adr/0014-declarative-campaign-calendar-core-follows-paizo.md)) and the GIS importer as code, with no data ([ADR 0002](../adr/0002-rebuild-rather-than-evolve.md));
- access to user-supplied reference data, which is a Source;
- the stable English keys used by official references ([#17](https://github.com/Hugo-Grellier/SecondChair/issues/17));
- the types of system payloads carried in the event envelope;
- rules checks run on observations ([06](06-pf2e-rules.md));
- deterministic extractors from observations into its planned / obtained / distributed treasure ledger ([#14](https://github.com/Hugo-Grellier/SecondChair/issues/14));
- rules playbooks (running monsters, encounter calibration).

### VTT connector (Foundry)

- **ARC-06** A single, system-agnostic Python half inside `serve`: the bridge endpoint, the handshake, and the mapping between Core contracts and the Foundry modules.
- **ARC-07** `secondchair-foundry`, a system-agnostic Foundry library module: bridge to the Core, ceiling, idempotent write queue, durable capture, scene reconciliation, event envelope, the Director's Desk, generic reads and actions on journals, scenes, tokens, doors, chat and playlists, the generic behaviour traces and the per-user consent ([ADR 0004](../adr/0004-foundry-connector-library-plus-system-adapters.md), [ADR 0012](../adr/0012-behaviour-traces-capture-raw-input-with-consent.md)).
- **ARC-08** One **system adapter** module per system, `secondchair-foundry-pf2e` first. It requires the library and registers through a hook. It provides strikes, conditions, turn context, action costs, spells, self-effects, area Regions, the reaction counter, system event payloads with their outcome traces, the trace readers for third-party modules, turn driver detection, the rules context, the required translation module per campaign language, and campaign calendar sync ([06](06-pf2e-rules.md)).
- **ARC-09** Without a system adapter the library still works generically and refuses mechanical actions as failed actions.
- **ARC-10** VTT playbooks (realising a scene) ship with the connector.

### Surfaces

- **ARC-11** A Surface only displays and relays. It holds no state of its own. What reaches the GM, and when, is decided by the Core ([ADR 0005](../adr/0005-core-schedules-calls-on-the-gm.md)).
- **ARC-12** v4 Surfaces: the conversation in an agent host, the CLI, and the **Director's Desk** inside Foundry.
- **ARC-13** Authenticated Surfaces are the CLI in an interactive terminal and the Director's Desk opened as the VTT's GM user. Conversation is not authenticated ([ADR 0003](../adr/0003-core-is-the-only-gateway.md)).
- **ARC-14** The **Director's Desk** is a minimal panel: the calls due now, approve or reject with a rejection reason, the active NPC's acting cue with "I voice this one" / "Hand back", and the pile held for the break. No tabs: the action log, staging and the living world stay in conversation and the CLI ([ADR 0005](../adr/0005-core-schedules-calls-on-the-gm.md), [#19](https://github.com/Hugo-Grellier/SecondChair/issues/19)).

## Contracts

- **ARC-15** Core ↔ System extension: the Core provides a generic entity model (types, names, description, relations, fictional time, knowledge). The extension adds schema fragments, calculators, calendars, reference-data access and payload types. Entities carry no prose sections with truth value ([ADR 0007](../adr/0007-facts-are-the-unit-of-canon.md)).
- **ARC-16** Core ↔ VTT connector: a generic **event envelope** (timestamp, scene, actor, kind, visibility `players` / `gm` / `blind`, payload). System payloads are typed by the System extension. Visibility sits on the envelope, so a GM-only or blind record never attests what the party knows. The connector also offers turn context and atomic actions.
- **ARC-17** Versioning: the Core publishes a semver protocol version. Each extension, connector and adapter declares the range it supports, and the bridge refuses an incompatible version at handshake; a Python block declares its range at registration and `secondchair serve` refuses an incompatible block at start (GM decision, 2026-10-20, #77).
- **ARC-17a** Contracts are written just in time: each is specified by the first planning slice that needs it, as part of that slice's acceptance, not in an upfront phase. They live in `docs/contracts/`, one file per contract: wire and data formats (event envelope, action log entry, job contract, transcript format) as JSON Schema, validated by both the Python and the JavaScript side; the workspace layout as Markdown with a tree and example files. A System extension's payload schemas ship with that extension and are referenced from the envelope schema. Contracts are versioned by the protocol version (ARC-17) and the workspace schema version (PKG-16); before the v4.0 release a breaking change is free. Settled in planning, 2026-10-19.
- **ARC-18** One process, one campaign. A Foundry world is bound to one campaign by an id stored in the world; the bridge refuses a world bound to another campaign ([ADR 0010](../adr/0010-local-core-reached-by-the-gm-browser.md)).

## Authorities and reconciliation

| What | Authority | How it reaches the others |
|---|---|---|
| Canon | The Core | Changes only through the memory responsibility, at its delegation level |
| Live mechanical state | The VTT | The Core keeps **observations** only; they become canon only through capture → candidate fact → wrap |
| Creative decisions | The GM | Recorded as **decisions** in the GM's own words |
| Prep | The Core, as a **desired state** | Realised in the VTT by reconciliation, which keeps what was played and what the GM retouched |
| Reference data | System extension data for calculations; VTT documents for what is placed in play | Joined by compendium UUID; a version gap is flagged |

## Agents, playbooks and jobs

- **ARC-19** SecondChair ships no agent loop. **Agent hosts** run the agents: Claude Code and Codex first-class (tested on the bench, documented), any other MCP host best effort. Local models only through a host that supports them ([ADR 0001](../adr/0001-no-in-house-orchestrator-llm-free-core.md)).
- **ARC-20** The Core calls no model and holds no host-specific code. Transcription is a CLI step outside the MCP server ([ADR 0008](../adr/0008-capture-cited-facts-rank-as-played.md)).
- **ARC-21** **Playbooks** use the open Agent Skills format, one source read as-is by every supported host, written in English with the instruction to generate content in the campaign language. Each is shipped by the block that owns its scope.
- **ARC-22** Agents are interchangeable. What an agent may do is decided per delegated action by its responsibility. The action log records the acting agent for traceability only.
- **ARC-23** A **job** is any work that needs a model. Its contract states the playbook, inputs, expected output, responsibility, moment, tier, the campaign language and the relevant slice of the campaign vocabulary. The Core queues jobs. A started job is bound by the delegation table of its moment like any agent.
- **ARC-23a** An agent cannot step out of a started job by omitting `job` from a delegated action. A client that keeps an MCP session (the handshake protocols) is bound to the job it starts, or first acts for, until that job ends: its delegated actions are for that job whether or not they pass `job`, and refused for another job. A sessionless client (protocol 2026-07-28) has nothing to bind, so while a world-turn job (living world or narrative direction) is started, its delegated actions without `job` are refused ([#112](https://github.com/Hugo-Grellier/SecondChair/issues/112)).
- **ARC-24** A **runner** is a GM-configured command template (for example a headless Claude Code or Codex invocation) that starts a queued job. Without a runner the Core only signals pending work, and the GM (or their cron) starts an agent.

### Tiers and runner configuration ([#12](https://github.com/Hugo-Grellier/SecondChair/issues/12))

- **ARC-25** A job declares a **tier**: fast, standard or deep. The playbook declares it and the job contract may override it. No model name appears in the Core or in a playbook.
- **ARC-26** The mapping tier → **runner configuration** (agent host, model, effort, ordered fallback list) lives in the GM's machine configuration, keyed by tier only (no per-moment or per-responsibility variation in v4).
- **ARC-27** The runner tries the fallback list in order and the Core logs every attempt with the configuration used. When the list is exhausted the job stays queued and an exception is surfaced at the break. No silent substitution.
- **ARC-28** A live job inherits the deadline of the call it prepares as its latency cap. Missing it applies the call's safe default and is logged. There is no separate latency setting.
- **ARC-29** On a manual start the GM's own host session decides; the tier is shown as a hint and the effective configuration is logged.
- **ARC-30** The test bench injects its own mapping for each configuration it compares, and writes the cheapest passing mapping in runner-configuration format. The GM adopts it by hand.
