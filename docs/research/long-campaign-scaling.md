# Long-campaign scaling: a synthetic multi-year campaign and a recall bench

Design note for [#195](https://github.com/Hugo-Grellier/SecondChair/issues/195) (multi-year continuity, temporal recall, storage resilience). No code. It shares its generator with [#204](https://github.com/Hugo-Grellier/SecondChair/issues/204), the benchmark leaf of [#172](https://github.com/Hugo-Grellier/SecondChair/issues/172). Read against `main` at `e96207e`, 2026-10-20. Risk classes are R0 (docs, tests or bench), R1 (behaviour inside existing invariants) and R2 (a trust, licence, secrecy or data-loss boundary; needs a GM-approved ADR).

## Where scale hurts today

- **Every canon read hashes the whole canon and action log.** `index._fingerprint` (`src/secondchair/core/index.py:174`) hashes all of it, and any change triggers a full rebuild (`rebuild`, `:150`). At 400 sessions the action log alone holds tens of thousands of YAML files (one per entry, `delegation._append`). This is #172/#204.
- **Every append lists the directory.** `_append` takes the next id by globbing the whole directory (`core/delegation.py:1342`). It is O(n) per write, under the workspace lock.
- **Scans are linear.** `read_log`, `capture.candidates`, `jobs.pending`, `calls.read_calls` and `world.occurrences` each read every file in their directory.
- **Library search embeds campaign Markdown on first sight** and compares every authorized vector linearly. That is about 1 s per 300k passages (workspace contract), so it grows with `sessions/` and `notes/`.
- **Temporal queries exist only partly.** Facts have `valid_from/valid_to`, ranks and retcons (ADR 0007), and `search_knowledge(at=…)` answers who-knew-what-then (`index.py:582`, #137). "What was believed incorrectly" and "which promise changed when" are not first-class queries. #170 covers as-of-date semantics.

## The synthetic campaign generator (R0)

One deterministic generator, `secondchair.bench.synth`, seeded and fictional, in an original setting (LIC-13: no Golarion names; the sample campaign's deny-list guard applies). It writes through the Core's own APIs, never raw files, so every invariant runs on the way in.

- **Parameters**: `sessions` (10 → 500), `npcs_per_session`, `plots_active`, `retcon_rate`, `contradiction_rate`, `calendar_jumps`, `seed`.
- **Per session**: a moment cycle (prep → live → between), captured candidates quoting synthetic notes, consolidation, a wrap and a world-turn over fronts and clocks. NPC relationship changes, secrets disclosed late, a few retcons and GM corrections, and occasional hand edits (path 6 in [write-paths.md](write-paths.md)).
- **It generates its own synthetic gold set**. This conflicts with MET-02 (gold sets are written by hand, once), so the recall bench is a **tracked, non-reference track**. Its scores are reported and compared over time, never gated as v4 metrics or reference floors, unless the GM amends MET-02 or writes a hand gold set for a fixed seed. The generated answers cover: for chosen `(session, question)` pairs, the true answer as of that session. Who knew X then; the current versus historical relationship of A and B; when promise P was made, broken or kept; which claim holds after the retcon of session k; book claim versus played claim (with a synthetic "book" Source).
- **Sizes**: S (10 sessions; CI), M (100), L (400; local only). One #204 size equals one S/M/L workspace, so the index benchmark and the recall bench share fixtures.
- **Determinism check**: two runs with the same seed on fresh `XDG_*` dirs produce byte-identical workspaces (timestamps from a fixed clock).

## Bench plan

Two harness entries, sharing the generator and `bench/report.py`:

1. **Scaling** (no model; CI at S, local at M/L). For each size: workspace files and bytes; bytes read and wall time for a cold `connect`, an unchanged `connect` and a `connect` after a hand edit (#204's columns); `act` latency (p50/p95 over 100 writes); `check` time; full rebuild time; backup and restore time and size (once ADR 0018 is decided); library search p50/p95.
2. **Recall** (model; local). An `answer-probes` job asks the generated questions in the GM view and in a party view, at the reference runner configuration (BEN-04, N = 3).

| Metric | Floor (proposal, to be set from the S baseline) |
|---|---|
| Current-state recall (facts, relationships) | ≥ 0.9 at every size |
| Historical / as-of recall | ≥ 0.8; may not drop by more than 0.05 from S to L |
| Delayed-revelation correctness (party view never answers before disclosure) | 1.0, an invariant |
| Retcon handling (superseded claim never given as current) | 1.0, an invariant |
| Canary leaks in a party-view or scoped context | 0, an invariant |
| Context-pack tokens per job | reported; must not grow linearly with sessions |
| Unchanged-read bytes read | must not grow with total bytes once #172 lands |

Invariants hold on every run (BEN-04); they are checked by the Core's own rules, not by the gold set. The floors are tracking targets on this non-reference track. They gate nothing until the GM accepts a hand-written gold set or a MET-02 amendment.

## Tiered memory views (design direction, not built)

- **Authoritative**: the action log, canon files and observations. Immutable history, as today.
- **Projections**: the SQLite index (facts, events, knowledge, mysteries), rebuildable.
- **Arc summaries**: written by a job into `notes/arcs/` and citing fact ids. They are prep material, never canon (ADR 0007). They are invalidated when a cited fact is corrected or retconned.
- **Context packs**: per job, built from entity ids (`canon.vocabulary(ws, entities)` already scopes the vocabulary, `core/jobs.py:83`), plus relevant facts as of the job's date, plus the knower filter. The test: a job about NPC A never receives facts only B's secret zone holds.

## Proposed leaf issues

| Title | Scope | Risk | Deps |
|---|---|---|---|
| Synthetic campaign generator (S/M/L, seeded) | `bench/synth.py` through Core APIs; a determinism test; the deny-list guard | R0 | — |
| Share the generator with the index benchmark | #204's sizes use the generator's workspaces | R0 | #204, generator |
| Scaling bench report | The metrics above, without a model; S in CI | R0 | generator |
| Generated temporal gold set and recall bench | As-of, retcon, delayed-revelation and promise questions; GM and party views | R0 | generator, #170 |
| O(1) next id for append-only directories | A counter file under the lock, or the last filename by sort; preserves ids | R1 | scaling bench shows it |
| Scoped context packs for jobs | Entity- and date-scoped facts in the job contract; a leak test | R2 | #168, #191 player gating |
| Arc summaries as invalidated prep | A summary job; invalidation on correction or retcon | R1 | context packs |
| Long-history restore rehearsal | Back up, restore and `check` the L workspace; time and disk | R0 | ADR 0018 |
