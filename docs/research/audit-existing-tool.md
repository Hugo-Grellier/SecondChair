# Audit of the existing tool by responsibility

Ticket: #2 (map #1). Date: 2026-10-18. Method: read-only inspection of four local repositories, plus running
their test suites. Sources are cited as `repo:path` (repo `poc` = `pf2e-open-campaign`, the private
predecessor). Every number below was produced on 2026-10-18 by the commands listed in
[Method](#method).

## Short answer

- `pf2e-open-campaign` (the "bible") is a substantial, well-tested **campaign-memory and prep engine**: 11.3 k lines
  of Python (`tools/bible/`), 1 212 passing tests, 15 skills, a v3 spec. Its strongest, best-proven parts are
  canonical memory (ids, relations, changesets with undo/recover, cited events, append-only chronicle) and the
  deterministic world-turn. These are proven by tests and two fictional end-to-end demos with a simulated GM, never
  by a real session.
- The Foundry layer (`bible live` MCP + `bible-sync` module, ~3.4 k lines Python + JS) is **proven in a real
  Foundry** (V14.367 / PF2e 8.6.1, world `bible-demo`) for scene prep/reconciliation, placement, strikes/moves with a
  module-held turn budget, idempotent requests and durable capture. Combat covers Strikes and Strides only.
- Session capture, living-world autonomy, NPC knowledge and narrative direction are the weakest areas: no real
  session has ever been captured, transcribed and wrapped; there is no per-NPC knowledge model; "narrative
  direction" exists only as skills and data types (situations, fronts, mysteries), not as an engine.
- About **70 % of the Python is Core-reusable in design**, ~18 % is PF2e/Golarion-bound, ~10 % Foundry-bound.
  But **all prose is French**: 100 % of skills, 79 of 82 docs files, `AGENTS.md`, and ~18 % of Python string literals
  (CLI help, messages, data-contract words such as `ERREUR`, `ALERTE`, `auto · certain`). Campaign-bound content in
  the tool is small (a handful of Absalom/Golarion references, one fixture named `westerhold-test`).
- Reuse verdict for an English modular rebuild: **port the data model and algorithms, not the code verbatim**.
  Directly reusable: the ADR decisions, the changeset contract, the world-turn algorithm, the Foundry module's
  reliability mechanisms (budget, idempotence, write queue, capture journal) and the test scenarios as behavioural
  specifications. Rewrite: every French string, skill and doc, and the PF2e/Foundry code that sits inside Core
  modules.

## The four repositories

| Repo | What it is | Relation to the main repo | Size / proof |
|---|---|---|---|
| `pf2e-open-campaign` | Tool + spec: `bible` CLI (Python, `uv`), `bible live` MCP server, `bible-sync` Foundry module, 15 skills under `.agents/skills/` | the main repo (private) | 314 commits; 11 333 Py lines, 10 407 test lines, 1 212 tests pass in 84 s; JS module 1 802 lines, 29 node tests pass |
| `pf2e-demo-bible` | fictional demo bible ("Westerhold-test") used for Foundry recipes: 38 entity files, S001–S004, S003 "played" with Foundry traces + transcript + cited wrap | test corpus for the main tool, run with `bible --root …/pf2e-demo-bible` | 3 commits; validation by a simulated GM |
| `foundry-vtt-mcp` | upstream clone of `adambdooley/foundry-vtt-mcp` v0.8.4 (MIT), multi-system MCP bridge (TS, 52.8 k lines incl. module); no local commits, clean tree | **not used by the bible**. The spec says the bridge "requires no third-party relay" (`poc:docs/spec/42-foundry-live.md` l.16) | 18 test files upstream; relevant as prior art: system-adapter registry (`ADDING_NEW_SYSTEMS.md`, `packages/mcp-server/src/systems/{pf2e,dnd5e,…}`) |
| `pf2e-narrative-assistant` | own Foundry v14 module (MIT, GitHub `Hugo-Grellier/pf2e-narrative-assistant`): after a PF2e roll, whispers the GM a hand-written narration line from EN/FR RollTables; no LLM, read-only | independent of the bible; shares the PF2e roll-parsing domain | 17 commits; 1 157 src lines; 80 tests pass, 10 TODO ("298 outcomes without text yet"), one non-reproducible failure on a first run |

## Per responsibility

Proof levels: **T** = automated tests (fakes for Foundry); **F** = recipe in a real Foundry with fictional content
and simulated GM; **S** = real session with the real GM. No responsibility has reached **S**.

Layers: **Core**, **Sys** (PF2e extension), **VTT** (Foundry connector), **Surf** (surface: CLI / skills /
conversation).

### 1. Prep

- **Delivered**: `/prep` (one-page session sheet + annexes, threat/XP/treasure computed), `/dungeon` (`rooms.yaml`,
  `bible dungeon budget`), `/hex`, `/scene` (scene plan → `world/atlas/scenes/<key>.yaml` → `foundry_scene_apply`),
  `bible xp plan|award`, `bible treasure`, `bible roll`, `bible assets find` (an index of purchased
  scenes and playlists; `poc:docs/improvements.md` FLOW-05). Rolling N-session horizon is written as a contract
  only (FLOW-03; `poc:docs/spec/44-gm-workflow.md`).
- **Proof**: T (xp, treasure, dungeon budget, tables, scenes); F for P1–P6 scene prep and reconciliation that
  preserves played state and GM edits (`poc:docs/spec/43-foundry-prep.md` l.90; FLOW-04, FLOW-08). Two fictional
  demos ran prep → wrap → world-turn → prep with 0 manual workarounds (`poc:docs/acceptance/readiness-2026-10-17.md`
  C1, C7).
- **Debt**: `/prep` stops at documents and leaves sites/scenes "to do" — transitions between skills are an agent
  procedure, not code (`poc:docs/acceptance/tool-audit-2026-10-17.md` §2; FLOW-02). Walls added by the bible
  unsupported (FLOW-15); chest contents never rewritten (FLOW-14); bought-map modules may be inactive in the target
  world (FLOW-13). GM load in demo 2: 50 questions over 12 rounds (readiness §Charge).
- **Reuse**: Core — table rolling, horizon concept. Sys — `mechanics.py`, `treasure.py`, `dungeons.py` XP budget,
  `_meta/pf2e/*.yaml` tables (port as-is, translate). VTT — scene YAML format and its per-object fingerprint
  reconciliation (`poc:tools/bible/scenes.py`, `poc:docs/spec/adr/0009-foundry-reconciliation.md`) is the most
  valuable reusable design. Surf — skills must be rewritten in English.

### 2. Memory / continuity

- **Delivered**: Markdown entity files with opaque immutable ids, single-sided relations with derived inverses,
  fixed section model (`Description` / `Party knows` / `GM › Truth, Agenda, Deceptions, Undecided` / `Ideas`),
  authority order (played > GM decision > cited official > AI), changesets as the only agent write path with
  simulate → apply → undo → recover and file backups, append-only chronicle with `played|offscreen|retcon` events,
  Absalom calendar arithmetic, citations `[src:id p.N]`, source ingestion/search, leak guard on recaps
  (`poc:AGENTS.md`; `poc:docs/spec/20,21,22,23`; ADR 0001–0007).
- **Proof**: T, the densest coverage (apply, undo, recover, lock, changeset, chronicle, events, check, index,
  rename/retype ≈ 250 test functions). Demo C3: 27 played facts quoted verbatim, C4: 12 variants of a secret name
  blocked, C5: retcon and level-up in conversation (readiness).
- **Debt**: knowledge is party-level only — no per-NPC knowledge firewall (template `poc:_templates/npc.md` has no
  "knows" field; `21-knowledge.md` mentions NPCs only for secret natures). Validation relies on trust: an agent
  passing invented GM words to `bible decide` is undetectable (readiness §Limites). Temporal facts exist only as
  chronicle events, not as time-scoped attributes. Calendar is hard-wired to Absalom (`poc:tools/bible/dates.py`).
- **Reuse**: Core — high. The contracts (ADRs, changeset format, authority rules, id scheme) port directly; the
  code (`vault`, `changeset`, `apply`, `simulate`, `journal`, `lock`, `recover`, `timeline`, `index`, `check`) is
  stdlib + `ruamel.yaml` and system-agnostic except messages and a few PF2e checks in `check.py`/`simulate.py`.
  Calendar must become a Sys/setting plugin.

### 3. Foundry ops

- **Delivered**: bundle export with whitelist, forbidden-string check and ownerships, imported by the GM through
  `bible-sync` (`poc:docs/spec/40-foundry.md`); live MCP bridge `bible live serve` ↔ module over
  `ws://127.0.0.1:31420` with token and GM-chosen access level (read / prep / play) — ~30 `foundry_*` tools: scene
  read/image/apply/activate, place/place_encounter/undo, reveal, door, playlist, journal show, whisper, say, request
  roll, triggers, capture, chat, trace ingest (`poc:docs/spec/42-foundry-live.md`; `poc:tools/bible/live.py`;
  `poc:foundry/bible-sync/scripts/live.mjs`). Player-side check `api.check()` (FLOW-06).
- **Proof**: F — live recipe 2026-10-17 and R1 2026-10-18 in `bible-demo` with a real player client
  (`poc:docs/acceptance/live-2026-10-17.md`, `poc:docs/acceptance/r1-2026-10-18.md`): idempotent repeated request
  (one attack, three identical answers, survives reload), bundle re-import keeps HP/conditions/tokens/walls
  (FLOW-17). T — 29 node tests with Foundry doubles; Python bridge tests use a fake module.
- **Debt**: requires a GM browser client to be open, no permanent access (FLOW-11); GM documents are readable from
  the player console (accepted limit, `40-foundry.md`); only validated on V14.367 / PF2e 8.6.1; module-interaction
  quirks recorded by hand. `live.mjs` mixes VTT transport with PF2e rules (strike, MAP,
  conditions) in one 1 002-line file.
- **Reuse**: VTT — protocol and reliability mechanisms are directly reusable (request id logged on the GM user,
  `foundry_result` states done/running/interrupted/unknown, serialized write queue, conflict-aware undo). The
  module code is reusable after splitting VTT transport from PF2e logic and translating strings.
  `foundry-vtt-mcp` offers a broader, multi-system tool surface (MIT) and an adapter registry worth studying, but
  none of the bible's reliability guarantees.

### 4. Rules / combat

- **Delivered**: `/monsters` skill; `foundry_turn_context`, `foundry_strike` (MAP, damage incl. crits applied),
  `foundry_move` (wall-aware, ≤ 3 actions of Speed), `foundry_condition`, `foundry_end_turn`, `foundry_undo_play`,
  `foundry_budget`; module-held turn budget counting slowed/stunned/quickened and manual GM actions (FIX-04).
  Offline rules: XP/threat, treasure, hexploration tables, PF2e data sync and `bible pf2e find` with UUIDs.
- **Proof**: F — R1 recipe: move + 3 strikes, third refused for budget; manual GM attack counted; manual token move
  makes the budget unknown and refuses (r1 §Recette). T — 20 `live.test.mjs` scenarios.
- **Debt**: no spells, skill actions, reactions, non-standard costs, stunned consumed per action, other-module
  consequences (FLOW-10; r1 §Non couvert). Only two rounds played; never a full combat with the GM. `hexploration.yaml`
  still `verified: false` (readiness §Peut attendre).
- **Reuse**: Sys — budget/MAP logic and the PF2e Remaster tables port with translation. The `pf2e-narrative-assistant`
  roll parser (`src/extract.mjs`, `src/engine.mjs`: degree-of-success and event classification for strikes, saves,
  skill actions, spells) is the most complete PF2e roll-event model across the repos and is English-first.

### 5. Living world

- **Delivered**: `/world-turn` + `bible turn plan|pending|decide`: fronts with clocks, agenda steps, situation
  deadlines, `unless` conditions, cursor vs decision queue, unique occurrence keys making replanning safe,
  reschedule chains (`poc:docs/spec/33-world-turn.md`; `poc:tools/bible/turn.py`).
- **Proof**: T — `test_turn_guard` (25), `test_turn_plan` (18), queue/keys/cli, world-turn scenario. Demo C6: a
  3-week deterministic, replayable turn with an empty queue at the end (readiness). Large turn (50 fronts, 1 year)
  ≈ 5 min.
- **Debt**: the engine only schedules what the GM authored (ticks, steps); consequences and rumours are AI
  proposals in conversation, no faction simulation or delayed-consequence model. Never run on the real campaign.
- **Reuse**: Core — high. The occurrence-key/queue algorithm is system-agnostic and the strongest candidate to port
  nearly as-is (logic), with translated messages.

### 6. NPCs

- **Delivered**: `npc` entity type with `location`, `state`, `pf2e` (compendium UUID), relations, Truth / Agenda /
  Deceptions; agenda steps driven by world-turn; `/new`, `bible review` flags NPCs without agenda; live voicing via
  `foundry_say` / `foundry_whisper`; NPC actors importable to Foundry.
- **Proof**: T for entity checks and review hints; F for `foundry_say` during the combat recipe.
- **Debt**: no per-NPC knowledge or memory of interactions, no "what this NPC knows / believes" firewall, no
  personality/voice model for live play — this is an open map item ("per-NPC knowledge firewall", issue #1).
- **Reuse**: Core — entity schema and section model only; the NPC-knowledge model must be designed new.

### 7. Narrative direction

- **Delivered**: data types and skills, no engine: situations (stakes, hooks, deadlines, outcomes; `/situation`),
  fronts, mysteries with conclusions/nodes/clues, three-clue rule, reachability graph and loss simulation
  (`bible mystery --lose`; `/mystery`), `/forge` worldbuilding projects by decision tickets, `/grill` decision
  rounds, `/check` narrative review (`poc:docs/spec/31,34,35`).
- **Proof**: T — mysteries (22 + 9 graph + 3 scenario), forge (13), situations. Demo C2: losing the only clue of a
  node writes the played fact and raises `ALERTE mystery-unreachable`.
- **Debt**: direction during play (pacing, spotlight, improvisation support) is absent; it lives in the GM's head
  and in conversation. Arcs/hook generation is prompt work in French skills.
- **Reuse**: Core — the mystery graph checker is a clean, system-agnostic algorithm (port as-is). Skills' procedures
  are good specifications but must be rewritten in English.

### 8. Session capture

- **Delivered**: Foundry capture (HP, conditions, effects, inventory, combat, deleted messages) with durable
  browser-side journal and resume marker (FIX-07); `foundry_trace_ingest` / `bible trace ingest` → idempotent
  `campaign/sessions/Snnn/foundry.jsonl`; `bible trace transcript` imports Scriberr/WhisperX or LoreForge segments
  into a timestamped, never-overwritten `transcript.md`; `bible trace show` cross-timeline; `/wrap` turns notes +
  traces into a cited changeset (`played` only with literal quote) and a player recap (`poc:docs/spec/32,42`;
  `poc:tools/bible/trace.py`).
- **Proof**: F — capture resume after reload (r1); S003 in the demo bible "played" with traces, a transcript and a
  cited wrap, but fictional and GM-simulated. T — trace (11), recap (13), session scenario.
- **Debt**: no audio recording or transcription in the repo; no real session ever imported (FLOW-07, FLOW-18; R2
  blocked). Capture misses anything while the GM client is closed; multi-client coverage not tested (FIX-08).
  Craig multi-track not importable in one go; no speaker → player mapping. Note: two recorded Craig sessions are now
  sitting untracked at the repo root (`craig-*.flac.zip`, `craig-*.aac.zip`), which is the input R2 was waiting for.
- **Reuse**: Core — the raw-source / observation / candidate fact / canon separation and the citation guard port
  directly; transcript importers port as-is (format adapters). VTT — capture journal mechanism.

## Summary table

| Responsibility | Delivered | Best proof | Main debt | Reuse in rebuild |
|---|---|---|---|---|
| Prep | high | F (scenes), demo | skill-to-skill transitions, N-session horizon | Sys tables, VTT scene format: high |
| Memory / continuity | high | T (dense), demo | no per-NPC knowledge, Absalom-only calendar | Core contracts + algorithms: high |
| Foundry ops | high | F (R1) | GM client required, module mixes VTT+PF2e | VTT reliability design: high |
| Rules / combat | low–medium | F (2 rounds) | Strike/Stride only | Sys: medium; narrative-assistant parser |
| Living world | medium | T, demo | GM-authored schedules only | Core algorithm: high |
| NPCs | low | T | no knowledge/memory model | schema only |
| Narrative direction | medium (data) | T, demo | no in-play direction | mystery graph: high |
| Session capture | medium | F (fictional) | no real audio→wrap ever | Core separation + importers: high |

## French-bound and campaign-bound share

| Area | Measure | Result |
|---|---|---|
| Docs (`docs/**/*.md`, 82 files, 30 755 lines) | file majority of French vs English stop-words | 79 French files (22 927 lines, 75 %); 3 English (the `docs/superpowers` plans, 7 830 lines) |
| Spec v3 (`docs/spec/`, 35 files) | same | 100 % French |
| Skills (`.agents/skills/`, 15 files, 1 481 lines) | same | 100 % French |
| `AGENTS.md` | same | French |
| Python `tools/bible/` | string literals > 3 chars (AST) that are French | 1 049 / 5 973 = 18 %; line-level 11 % |
| JS `foundry/bible-sync/scripts/` | lines with French words/accents | 12 % |
| Tests (`tools/tests/`) | same | 9 % (fixtures and asserted messages) |
| Data contracts in French | grep | `ERREUR`/`ALERTE` prefixes, class `auto · certain` (4 files), access levels "lecture / préparation / jeu", CLI help; section headings are already English (`Party knows`, `Truth`) |
| Campaign-bound in code | grep `Westerhold`, `Absalom`, `Golarion`, `Rova`, `beginner` | 6 files: calendar (`dates.py`, `check.py`, `notes.py`, `cli.py`), GIS import (`gis.py`); fixture `tools/fixtures/westerhold-test` |
| Golarion/PF2e-bound Python | module classification | 2 007 lines (18 %): `dates`, `gis`, `mechanics`, `treasure`, `pf2e`, `dungeons`; plus PF2e mentions in 13 of 39 files |
| Foundry-bound Python | module classification | 1 122 lines (10 %): `foundry`, `live`, `scenes`, `assets` |
| Core-shaped Python | remainder minus `cli.py` | 7 117 lines (63 %); `cli.py` 1 087 lines (10 %) is all French help |

Reading: the *code structure* is mostly portable; the *language* is not. Every prose artefact that an agent reads
(skills, `AGENTS.md`, spec, changeset guide) must be rewritten, which is roughly 25 k lines of French prose. Code
translation is a string sweep (~1 000 literals) plus renaming data-contract words, which would break compatibility
with the existing Westerhold bible unless a migration maps them.

## What this means for the rebuild decision

1. The v3 tool already embodies most of the v4 Core concepts (canon vs sources, delegated writes through reviewed
   changesets, access levels per moment). Its access levels read / prep / play are the seed of the delegation
   profile.
2. Proof is strong where it is cheapest (unit tests on Markdown data) and weak where v4 claims its value (real
   sessions, capture, live play). A rebuild does not lose real-world validation, because there is none yet; it
   loses ~1 200 behavioural tests, which should be carried over as specifications.
3. The module boundaries v4 wants are not present: PF2e and Foundry logic sits inside `check.py`, `simulate.py`,
   `trace.py` and `live.mjs`. A rebuild can draw the seams from the start; evolving would need that split anyway.
4. `foundry-vtt-mcp` is prior art for a multi-system VTT connector (adapter registry) but is not part of the
   running tool; `pf2e-narrative-assistant` is a separate product whose PF2e roll-event classifier is a good seed
   for the System extension.

## Method

- Repos, commit counts and authors: `git log`, `git remote -v`, `git status` in each repo.
- Line counts: `wc -l` on `tools/bible/*.py`, `tools/tests/*.py`, `foundry/**/*.{mjs,json,py,sh}`, skills, docs.
- Tests: `uv run pytest -q` (1 212 passed, 84 s); `node --test foundry/bible-sync/tests/*.mjs` (29 pass);
  `node --test tests/*.test.mjs` in `pf2e-narrative-assistant` (80 pass, 10 todo; one failure on the first run
  did not reproduce).
- Test functions per area: `grep -c 'def test_'` per file.
- French share: a script counting French vs English stop-words per file (majority = file language), per line, and
  per Python string literal via `ast`; accented characters count as French. It is a heuristic: tables and code
  blocks inside French docs count as non-French lines, so line-level percentages under-estimate prose language.
- Layer classification: by module docstring and imports, assigned by hand (lists in the Foundry/PF2e rows above).
- Claims about delivery state come from the repo's own registers (`docs/improvements.md`, `docs/acceptance/*`), cross-checked against code paths where named.
