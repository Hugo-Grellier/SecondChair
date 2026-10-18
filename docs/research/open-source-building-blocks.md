# Reusable open-source building blocks

Answers [#3](https://github.com/Hugo-Grellier/SecondChair/issues/3). Facts checked on **2026-10-18** against
GitHub (repo metadata, `LICENSE`, manifests via the GitHub API) and foundryvtt.com package pages. Starting
inventories: `docs/etat_de_lart.md` and `docs/agent_et_autmatisme.md` in `pf2e-open-campaign`; where they
disagree with a primary source, the primary source wins and the gap is noted.

Stack layers used below: **Core** (memory, orchestration, delegation), **System extension** (PF2e),
**VTT connector** (Foundry), **Surface** (conversation / CLI).

## Summary

| Candidate | Licence | Maturity (Oct 2026) | Layer | Verdict |
|---|---|---|---|---|
| Foundry MCP Bridge (adambdooley) | MIT (+ restricted SDXL model if ComfyUI installed) | v0.8.5, 2026-10-17, active, ~10 contributors | VTT connector | **Reference / fork candidate** |
| Foundry API Bridge (Nitrmonoon) | Module MIT; service closed, Patreon-gated | v8.14.0, 2026-10-08 | VTT connector | **Do not depend on** (cloud relay) |
| Ninjo's Foundry MCP | **Proprietary** since 14.2609.4 | 14.2609.6, active, 0 stars | VTT connector | **Do not reuse code**; ideas only |
| Simulacrum | MIT | 1.1.0, 2026-06-20, 4 stars | Surface (in-Foundry) | Watch only |
| PF2e system (foundryvtt/pf2e) | Apache-2.0 code; content under Paizo/Foundry agreement + OGL | pf2e-8.6.1, 2026-10-12, Foundry 14 only | System extension | **Mandatory dependency** (runtime + data) |
| LangGraph | MIT | 1.2.16, 2026-10-16, 43k stars | Core (orchestration) | Optional; adopt only if durable HITL graphs are needed |
| LiteLLM | MIT (except `enterprise/`) | v1.106.0, 2026-10-18 | Core (model access) | Optional BYOK layer; pin and verify |
| Concordia (DeepMind) | Apache-2.0 | v2.4.0 (2026-03), commits to 2026-10 | Core (living world) | Pattern source / possible engine for between-session sim |
| Graphiti (Zep) *(added)* | Apache-2.0 | v0.31.1, 2026-10-15, 32k stars | Core (temporal memory) | Strong candidate for temporal facts + provenance |
| MCP Python SDK *(added)* | MIT | v2.3.0, 2026-10-02 | Core / Surface | Already the de facto choice; keep |
| WhisperX *(added)* | BSD-2-Clause | v3.8.6, 2026-05-25 | Core (session capture) | Reuse as a generic voice source |
| Babele + pf2-fr *(added)* | Not stated on package pages | Babele 2.9.1, pf2-fr 8.0.0, Foundry 14 | System extension (i18n) | Read-only source for official French names |
| Letta *(added)* | Apache-2.0 | 0.16.8 (2026-05), last push 2026-09 | Core (agent memory) | Not a fit (owns the agent loop) |

## VTT connector candidates

### Foundry MCP Bridge — `adambdooley/foundry-vtt-mcp`

- **Licence**: MIT, © 2025 Adam Dooley. GitHub reports `NOASSERTION` only because `LICENSE` appends a
  third-party note: the optional ComfyUI component ships the *D&D Battlemaps SDXL* model under a custom,
  usage-restricted licence. [src: repo `LICENSE`]
- **Maturity**: latest release v0.8.5 on 2026-10-17; last push 2026-10-17; 74 stars; ~10 contributors.
  Pre-1.0, single maintainer driving releases. [src: GitHub API]
- **Foundry / PF2e fit**: module manifest `compatibility {minimum 13, verified 14, maximum 14}`. README lists
  PF2e among six systems; "the majority of MCP tools are system agnostic". 49 MCP tools. [src:
  `packages/foundry-module/module.json`, `README.md`]
- **Architecture**: two packages, `foundry-module` (runs in the GM browser) and `mcp-server` (Node, stdio to
  the client). The module connects to the server on fixed port **31415**; optional WebRTC for remote
  connections; installers for Windows/Mac target Claude Desktop. [src: `README.md`]
- **Relation to our stack**: this is structurally the same design as `bible live` + `bible-sync`
  (port 31420): sidecar MCP server + GM-side module over a local socket.
  It would **replace** the generic CRUD half of `bible-sync`
  (actors, journals, scenes, playlists, compendium search, token moves). It does **not** provide what makes
  `bible-sync` specific: graded access levels (read / prep / play), turn budget and MAP tracking, idempotent
  writes with `foundry_result`, undo of plays, durable capture of traces, prepared-scene reconciliation.
- **Risks**: Claude-Desktop-centric install path; fixed module id/port; pre-1.0 API churn; generic tools
  invite the "free agent with GM rights" pattern the state-of-the-art report warns against.
- **Recommendation**: MIT allows forking or vendoring. Best use is as a **reference and source of tool
  implementations** for the connector, not as a runtime dependency we cannot shape to the delegation model.

### Foundry API Bridge / Foundry MCP — `alexivenkov/foundry-api-bridge-module` (author Nitrmonoon)

- **Licence**: the module repo is MIT (© 2025 "AI DM Project"); the package page states no licence. The
  server side (`foundry-mcp.com`, `api.foundry-mcp.com`, code mode sandbox) is **not** in the repo. [src:
  repo `LICENSE`, package page]
- **Maturity**: v8.14.0 released 2026-10-08; 11 stars. [src: GitHub API]
- **Foundry / PF2e fit**: Foundry 11+, verified 14; 14 dedicated `pf2e-*` tools. [src: package page]
- **Architecture**: the GM client opens an outgoing WebSocket to `wss://foundry-mcp.com/ws`; MCP clients
  connect to `https://foundry-mcp.com/mcp`; auth via Patreon key `pk_…`. Tool tiers are gated by Patreon
  membership (scenes, tokens, combat, compendiums need the top tier). [src: README, package page] The
  inventory's "€0 / €3 / €10" prices are not on the package page; tier gating is confirmed.
- **Relation to our stack**: would replace the connector but routes all commands through a third-party
  cloud with GM permissions. Conflicts with the map's local-first / BYOK packaging direction.
- **Recommendation**: **do not depend on it**. Its PF2e tool list and "code mode" (one sandboxed script
  instead of dozens of tool calls) are worth studying as design input.

### Ninjo's Foundry MCP — `Niclasp1501/ninjos-foundry-mcp`

- **Licence**: **not open source** from v14.2609.4 onward: "All rights reserved"; use, local modification and
  separate interoperating modules are allowed; redistribution, copying code into another project and
  bundling are forbidden without written permission. Versions before 14.2609.4 (a fork of adambdooley's
  bridge) remain MIT; the author states 14.2609.4 is a rewrite. German text prevails. [src: repo `LICENSE`]
- **Maturity**: 14.2609.6; last push 2026-10-17; 0 stars. [src: GitHub API, package page]
- **Foundry / PF2e fit**: Foundry 13–14, verified 14; PF2e listed; per-document-type permissions
  (read / create-edit / delete), delete off by default, scene restore from world backup. [src: package page]
- **Recommendation**: **no code reuse** (licence incompatible with an open-source SecondChair). Its
  permission model (per document type, delete off by default) is a useful comparison point for the
  delegation design; ideas are not copyrightable, code is.

## Surface candidate

### Simulacrum — `Daxiongmao87/simulacrum-foundry`

- **Licence**: MIT. [src: GitHub API]
- **Maturity**: 1.1.0 on 2026-06-20; 4 stars; repo created 2025-08. Manifest `minimum 13, verified 14`.
  The package page discloses AI-assisted code generation. [src: GitHub API, `module.json`, package listing]
- **Fit**: in-browser sidebar agent: document CRUD, compendium/asset search, schema introspection,
  macro and JavaScript execution behind confirmations; OpenAI-compatible and local model endpoints.
- **Relation to our stack**: an alternative *Surface* (chat inside Foundry). It mixes UI, API secrets and GM
  permissions in the browser, and arbitrary JS execution undermines a delegation model.
- **Recommendation**: watch only. If an in-Foundry surface is wanted later, build a thin chat panel over our
  own Core rather than adopt an agent that owns the loop.

## System extension

### PF2e system — `foundryvtt/pf2e`

- **Licence**: code (HTML/CSS/JS) Apache-2.0. PF2e content used under the Paizo / Foundry Gaming LLC
  agreement; mechanics under OGL 1.0a; art licences in `static/licenses/`; the README points similar projects
  to Paizo's Community Use Policy. [src: repo `README.md`]
- **Maturity**: pf2e-8.6.1 released 2026-10-12 (same repo now also ships SF2e); pushed daily; 648 stars.
  Manifest `system.pf2e.json`: `compatibility {minimum 14.361, verified 14.369, maximum 14}`, i.e. **Foundry
  14 only**. [src: GitHub API, manifest] The inventory's "8.6.1 on 12 Oct 2026" is confirmed.
- **Fit**: it *is* the rules engine at the table: statistics, strikes with MAP, conditions, effects, rule
  elements, compendium packs (`packs/`). Already consumed by `bible pf2e sync` for creature/item lookup.
- **What it provides**: the deterministic rules layer the AI must call rather than imagine; the data source
  for XP/treasure/creature search. It replaces any home-grown rules engine.
- **Risks**: content licence is a partnership grant, not an open licence: SecondChair must **not
  redistribute** pack data; fetch it on the user's machine (as `bible pf2e sync` does). System version pins
  Foundry minor versions; the connector must track both.

### Babele + Pathfinder 2 FR *(added)*

- Babele 2.9.1 (Foundry 13+, verified 14), source `gitlab.com/riccisi/foundryvtt-babele`; pf2-fr 8.0.0
  (Foundry 13–14.999, PF2e 8.0+), source `gitlab.com/pathfinder-fr/foundryvtt-pathfinder2-fr`, relies on
  ORC, AXE and Paizo's PCUP. Neither package page states the module licence. [src: package pages]
- **Use**: read-only source for official French proper nouns and compendium names, feeding the i18n
  glossary for GM-language content. Not a code dependency.

## Core candidates

### LangGraph — `langchain-ai/langgraph`

- **Licence**: MIT. **Maturity**: 1.2.16 on 2026-10-16; 43k stars; daily commits. [src: GitHub API]
- **Provides**: durable execution (resume after failure), human-in-the-loop interrupts, checkpointed state.
  [src: `README.md`]
- **Relation**: could implement the delegation gates (pause for GM approval) and long-running world-turn
  jobs. Today these are covered by changesets + `bible apply` + agent skills; the coding agent (Claude Code /
  Codex) already is the orchestrator.
- **Risk**: framework lock-in and LangChain ecosystem churn; duplicates the host agent's loop.
- **Recommendation**: not needed for v4 if the Surface stays a coding agent. Revisit if SecondChair needs
  its own headless runtime (e.g. unattended between-session jobs).

### LiteLLM — `BerriAI/litellm`

- **Licence**: MIT for everything outside `enterprise/`, which has its own licence. [src: repo `LICENSE`]
- **Maturity**: v1.106.0 on 2026-10-18; 61k stars; now described as "Rust core with Python SDK".
  [src: GitHub API]
- **Provides**: one OpenAI-format interface to 100+ providers, cost tracking, fallbacks: a ready BYOK and
  local-model (Ollama, vLLM) layer.
- **Risk**: **supply-chain incident** on 2026-03-24: PyPI releases 1.82.7 and 1.82.8 were malicious
  (credential stealer, `.pth` launcher); fixed from 1.83.0 via a new pipeline. [src: secondary reports,
  e.g. [Comet](https://www.comet.com/site/blog/litellm-supply-chain-attack/),
  [Bastion](https://bastion.tech/blog/litellm-pypi-supply-chain-attack)] Pin exact versions with hashes.
- **Recommendation**: only needed if SecondChair calls models directly (headless jobs, cheap extraction
  passes). Then prefer it over per-provider SDKs, pinned.

### Concordia — `google-deepmind/concordia`

- **Licence**: Apache-2.0. **Maturity**: v2.4.0 (2026-03-06), commits through 2026-10-16; 1.8k stars.
  [src: GitHub API]
- **Provides**: generative social simulation built from entities/components, with a **Game Master** entity
  that resolves player entities' actions — the same metaphor as TTRPGs. [src: `README.md`]
- **Relation**: candidate engine, or at least pattern source, for the "living world" open question (factions,
  NPC agendas between sessions). Today `bible turn plan` is a deterministic scheduler over fronts/agendas.
- **Risk**: research library; outputs are free text, not canonical facts; needs an LLM per step (cost).
- **Recommendation**: prototype a between-session faction turn with Concordia whose outputs land as
  **proposed** changeset items for GM validation; do not make it the source of truth.

### Graphiti — `getzep/graphiti` *(added)*

- **Licence**: Apache-2.0. **Maturity**: v0.31.1 on 2026-10-15; 32k stars. [src: GitHub API]
- **Provides**: temporal knowledge graph for agents (bi-temporal edges, episodes as provenance).
- **Relation**: directly addresses the map's "temporal facts, provenance, per-NPC knowledge firewall".
- **Risk**: needs a graph DB (Neo4j/FalkorDB/…) and LLM-driven extraction; conflicts with the v3 choice of
  human-readable Markdown as the canonical store.
- **Recommendation**: evaluate as a **derived index** over the canonical Markdown, not as the canon.

### MCP Python SDK — `modelcontextprotocol/python-sdk` *(added)*

- MIT; v2.3.0 on 2026-10-02. The official SDK; the natural base for the Core's tool surface (whatever
  `bible live` uses today should track it).

### WhisperX — `m-bain/whisperX` *(added)*

- BSD-2-Clause; v3.8.6 on 2026-05-25; word-level timestamps + diarization. Fits "voice stays a generic
  source": transcription of Craig FLAC recordings into `transcript.md` (the current tool already imports
  WhisperX/Scriberr JSON).

### Letta *(added, rejected)*

- Apache-2.0; 0.16.8 (2026-05), last push 2026-09. A stateful-agent *platform*: it owns the agent loop and
  memory store, which clashes with GM-validated canon. Not recommended.

## Not covered / gaps

- No open-source project found that provides PF2e-aware **delegation levels**, turn budgets or canonical
  campaign memory with GM validation: that remains SecondChair's own value.
- Familiar (commercial, closed releases repo) not evaluated as a building block.
- Babele and pf2-fr licences need a look at their GitLab repos before any reuse beyond reading data.
