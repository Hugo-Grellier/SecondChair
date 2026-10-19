# 11 — Out of scope, and open questions for planning

## Out of scope for v4

Each item is excluded from v4 only; none is excluded by the architecture.

| Out of scope | Why, and what keeps it possible | Source |
|---|---|---|
| The AI GM as a goal | Only "not prevented by the architecture": narrative direction capped at propose by a setting ([01](01-vision.md)) | [#1](https://github.com/Hugo-Grellier/SecondChair/issues/1), [#6](https://github.com/Hugo-Grellier/SecondChair/issues/6) |
| Game systems other than PF2e, VTTs other than Foundry | The seams (System extension, VTT connector, system adapter) exist; the implementations don't | [#1](https://github.com/Hugo-Grellier/SecondChair/issues/1), [ADR 0004](../adr/0004-foundry-connector-library-plus-system-adapters.md) |
| Foundry v13 / pf2e 7.x | One Foundry/system pair at a time: v14 + pf2e 8.x | [ADR 0011](../adr/0011-foundry-automates-secondchair-checks.md) |
| A GUI for non-technical GMs; a hosted SaaS | Surfaces can be layered later; the remote Core is deferred, not excluded | [#1](https://github.com/Hugo-Grellier/SecondChair/issues/1), [ADR 0010](../adr/0010-local-core-reached-by-the-gm-browser.md) |
| An in-house agent loop; an LLM client in the Core; LangGraph, LiteLLM | Jobs have a contract another executor can run later | [ADR 0001](../adr/0001-no-in-house-orchestrator-llm-free-core.md) |
| Embeddings and semantic search | The derived index leaves room for a job to compute them | [ADR 0007](../adr/0007-facts-are-the-unit-of-canon.md) |
| Docker packaging | Can be added later without changing anything else | [ADR 0010](../adr/0010-local-core-reached-by-the-gm-browser.md) |
| LoreForge integration; SecondChair as the engine of a hosted LoreForge | A fresh effort, kept possible by dual licensing under the CLA and the deferred remote Core | [#1](https://github.com/Hugo-Grellier/SecondChair/issues/1), [ADR 0006](../adr/0006-agpl-core-apache-connector-cla.md) |
| The monetization model | The licences only keep it possible | [ADR 0006](../adr/0006-agpl-core-apache-connector-cla.md) |
| Faction simulation by agents | A faction acts through the fronts it carries | [ADR 0009](../adr/0009-world-turn-deterministic-three-effect-classes.md) |
| A world-turn during a live session | Fictional time moves only at the wrap or by a GM gesture | [ADR 0009](../adr/0009-world-turn-deterministic-three-effect-classes.md) |
| Migrating any v3 campaign or storage | No migration; Westerhold is rebuilt from its bible as a Source | [ADR 0002](../adr/0002-rebuild-rather-than-evolve.md) |
| Making Westerhold public | It stays a private Source; revisit after v4 | [#22](https://github.com/Hugo-Grellier/SecondChair/issues/22) |
| Changing a campaign's language or calendar mid-campaign | A later re-translation job could add the language change | [#17](https://github.com/Hugo-Grellier/SecondChair/issues/17), [ADR 0014](../adr/0014-declarative-campaign-calendar-core-follows-paizo.md) |
| Month and year durations; century leap exceptions; time of day as canon | Closed calendar shape, associative arithmetic | [ADR 0014](../adr/0014-declarative-campaign-calendar-core-follows-paizo.md) |
| Foundry sync for declared calendars | Only a System extension's named calendar syncs | [ADR 0014](../adr/0014-declarative-campaign-calendar-core-follows-paizo.md) |
| Live capture and consolidation during play; single-track diarization | The transcript format accepts a live stream, still consolidated at the wrap | [ADR 0008](../adr/0008-capture-cited-facts-rank-as-played.md), [#14](https://github.com/Hugo-Grellier/SecondChair/issues/14) |
| Agents acting outside encounters, for PCs, or on non-listed reactions | Exploration and downtime are checked, not acted | [ADR 0011](../adr/0011-foundry-automates-secondchair-checks.md) |
| A PF2e rules engine; recomputing outcomes from sheets | Foundry automates; checks read the trace | [ADR 0011](../adr/0011-foundry-automates-secondchair-checks.md) |
| Hard dependencies on third-party automation modules | Only by a later ADR | [ADR 0013](../adr/0013-third-party-modules-are-evidence-turn-drivers-take-over.md) |
| Agents proposing in the acting cue while a turn driver plays | The driver already plans | [ADR 0013](../adr/0013-third-party-modules-are-evidence-turn-drivers-take-over.md) |
| Per-entity overrides on prep, memory, VTT operations, living world, narrative direction; per-entity ceilings; faction-wide overrides; automatic expiry | Overrides stay on acting entities, individually | [#19](https://github.com/Hugo-Grellier/SecondChair/issues/19) |
| Per-moment or per-responsibility tier mapping | Keyed by tier only | [#12](https://github.com/Hugo-Grellier/SecondChair/issues/12) |
| A Director's Desk with tabs (staging, living world, decisions) | Between-session work stays in conversation and the CLI | [ADR 0005](../adr/0005-core-schedules-calls-on-the-gm.md) |
| Typed text in behaviour traces; LLM friction detection; buffering player traces; automatic trace expiry | Consent, privacy and reproducibility | [ADR 0012](../adr/0012-behaviour-traces-capture-raw-input-with-consent.md) |
| An LLM judge in reference metrics | Possible later as a labelled secondary metric | [#9](https://github.com/Hugo-Grellier/SecondChair/issues/9) |

## Open questions handed to planning

None of these contradicts a decision; each is a detail the map left unspecified.

1. ~~**Base profile values.**~~ Settled 2026-10-19: [03](03-delegation.md), DEL-06 to DEL-06b.
2. ~~**Moment transitions.**~~ Settled 2026-10-19: [03](03-delegation.md), DEL-03 to DEL-03b.
3. ~~**Ceiling defaults.**~~ Settled 2026-10-19: [03](03-delegation.md), DEL-19a.
4. ~~**Disclosure hold lift.**~~ Settled 2026-10-19: [03](03-delegation.md), DEL-09a.
5. ~~**Event envelope and payload schemas, transcript format, job contract format, workspace layout.**~~ Settled 2026-10-19: written just in time, [02](02-architecture.md), ARC-17a.
6. ~~**Floors and numeric targets.**~~ Process settled 2026-10-19: [10](10-success-bench.md), MET-05a; the numbers come from the "Set floors" ticket.
7. ~~**Dogfooding as an acceptance gate.**~~ Settled 2026-10-19: yes, [10](10-success-bench.md), BEN-14.
8. **Pre-publication pass** (LIC-17): its checklist and who runs it.
9. **Package index** for the Python distribution (PKG-17).
