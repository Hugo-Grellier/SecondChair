# Asset pipeline: licensed assets to a ready Foundry adventure

Design note for [#179](https://github.com/Hugo-Grellier/SecondChair/issues/179) (licensed-asset-to-Foundry production pipeline) and [#194](https://github.com/Hugo-Grellier/SecondChair/issues/194) (art direction and multimodal asset QA). No code. Read against `main` at `e96207e`, 2026-10-20. Risk classes are R0 (docs, tests or bench), R1 (behaviour inside existing invariants) and R2 (a trust, licence, secrecy or data-loss boundary; needs a GM-approved ADR).

#179 owns **structural** production: manifest, desired state, dependency checks, smoke test. #194 owns **artistic** consistency layered on top. Neither should rebuild the reconciler.

## What exists

- **Scene desired state**: `prepare_scene` (`src/secondchair_foundry/tools.py:111`) writes `scenes/<key>.yaml`. The scene's fields and items (Token, Wall, AmbientLight, AmbientSound, Note, Tile, Drawing, Region) are validated by `_check` (`tools.py:143`). That check refuses `ownership`, update operators, foreign `flags`, token `delta`, and Region behaviours outside a safe list.
- **World documents**: `prepare_document` (`tools.py:222`) writes JournalEntry, Actor, Item, Playlist and RollTable state. Scenes refer to these documents as `@prepared:<key>`. Documents are realised before scenes (`bridge.py:57`).
- **Reconciliation**: transplanted from v3 (`foundry/secondchair-foundry/scripts/scenes.js`). Stable keys and `spec`/`local` fingerprints keep played state and GM retouches, and never silently recreate a deleted object. Conflicts need the GM's `keep / overwrite / recreate`.
- **Reports**: one report per scene and per document, under `.secondchair/scenes|documents/` (derived; `bridge.py:486`), read with `scene_report` and `document_report`.
- **Discovery reads**: `browse_files` (paths confined to Foundry data by `_data_path`, `tools.py:307`), `image_size`, `search_compendium` and `list_world_documents`.
- **Playbooks**: `realise-a-scene` (standard tier) assumes the brief, map, sounds and Actor UUIDs already exist. `prepare-a-session` (deep tier) chains scenes and documents into a handoff.

## What is left (#179)

| Gap | Proposal | Risk |
|---|---|---|
| No production brief or asset manifest | `production/<scene>.yaml`: a desired asset list (map spec: scale, grid, levels; portraits; tokens; music; ambience; handouts). Each entry is `{need, source: install|user-file|provider, path?, licence, consent, status: wanted|found|approved}`. It is prep, not canon (ADR 0007), written by a delegated tool | R1 |
| Missing assets are silent until realisation | A pre-realisation `asset_check`: every `src`/`path`/`texture` in `scenes/` and `documents/` resolves through `browse_files`; images have `image_size`; `grid.size` divides the map; every Token `actor` resolves; every `@prepared` reference exists. The report separates `missing`, `mismatched` and `ok` | R1 |
| Walls, lights and regions are hand-authored by the agent | Keep it so. Add derivation helpers only for objective geometry (a grid-aligned wall from a room polygon). No vision-to-walls in v4: unreliable, and the agent cannot see the map without a multimodal host | R1 |
| GM/player preview | A smoke test in the isolated bench Foundry (BEN-05, world restored from a snapshot). Realise the scene, then query visibility as a player user: tokens with `hidden: false` the party should not see, Notes linking journals the player owns at less than OBSERVER, lights revealing a hidden token's square. Output a report, never a fix | R1 |
| Fail-open ceiling for scenes of unknown origin | #163 must be decided first: the pipeline adds more writers to `scenes/` | R2 (#163) |
| The report conflates states | Three report fields: `structurally_valid` (schema and asset_check), `realised` (reconciliation ok), `smoke_tested` (preview ran in Foundry). A visual review is a separate GM verdict (#194) | R0 |

## What is left (#194)

- **Style bible**: `notes/style/visual.md` and `notes/style/audio.md` are ordinary GM-editable Markdown with a version line. The palette, perspective, period, faction vocabulary, typography and accessibility rules live there. They are prep material, not canon. Exemplars are referenced by path, never copied.
- **Identity sheets**: one per recurring NPC: a portrait path, a token path, distinguishing features in words, and a reference image hash. A regenerated portrait is compared against the sheet by a multimodal job (deep tier, host-side). The Core makes no model call (ADR 0001).
- **Deterministic manifest QA**: duplicate files (by hash), dimensions that disagree with the declared grid, transparent-border clipping of tokens, audio loudness (LUFS via `ffmpeg -af ebur128`), and text contrast on handouts. All are local tools, no model.
- **Subjective QA**: a `review-assets` playbook. A multimodal host compares a scene's assets against the style bible and the identity sheets and writes findings to the GM. It never edits.
- **Providers**: optional adapters (image, audio generation, local libraries such as a Forgotten Adventures folder). Each declares its capabilities, a cost estimate, the licence of its outputs, and whether inputs leave the machine. With no provider, the pipeline still runs on GM-supplied art (an #194 acceptance criterion).

## Licence and consent model: questions for the GM

1. **Licence record granularity**: per file, or per pack (a purchased map pack, a module's `assets/`)? Proposal: per pack, with per-file overrides.
2. **Purchased Foundry module assets** (Rusthenge, Kingmaker): may prep *reference* them by path in the GM's own world? Proposal: yes. They are read from the install at runtime (LIC-12) and never copied out of the module. No export or sharing of a world that references them is offered.
3. **Sending assets to third-party models** (a hosted multimodal QA or a generator taking a reference image): default deny per pack, as `model` permission is for library sources. Is one switch per provider enough, or must it be per pack × provider?
4. **Generated asset provenance**: store prompt, provider, version, seed and licence terms beside the file? Proposal: yes, in the manifest entry. The file itself stays in the GM's Foundry data, never in the workspace or the repo (LIC-11).
5. **Foundry AI policy (LIC-16)**: generated maps shipped in a module would breach "no AI-made prepared content shipped". Proposal: generated assets stay local to the GM's world only. Confirm.
6. **Player likeness**: a portrait drawn from a player's photo or description needs that player's consent, recorded like ADR 0012 trace consent. Is that in scope?

## Proposed leaf issues

| Title | Scope | Risk | Deps |
|---|---|---|---|
| Decide the scene-origin ceiling default | Settle #163 | R2 | — |
| Production brief and asset manifest | `production/` schema, a delegated write tool, licence/consent fields | R1 | licence questions 1–4 |
| Pre-realisation asset check | File, size, grid, actor and `@prepared` resolution report | R1 | — |
| Three-state production report | `structurally_valid / realised / smoke_tested` on scene_report | R0 | asset check |
| Player-view smoke test in the bench Foundry | Hidden-token, lit-square and journal-ownership checks under a player user | R1 | BEN-05 bench world |
| Multi-room acceptance scene | One multi-room scene, two levels, secret door; it exercises everything above end to end | R0 | the four above |
| Style bible and NPC identity sheets | Markdown conventions and the prepare-a-session/realise-a-scene playbook steps that read them | R0 | — |
| Deterministic asset QA | Hash duplicates, dimensions, clipping, LUFS, contrast; a local-tools report | R1 | manifest |
| Multimodal asset review playbook | A host-side review against the style bible; findings only | R1 | style bible |
| Optional provider adapters | Capability, cost and licence declaration; a no-provider fallback | R2 | licence questions 3–5 |
