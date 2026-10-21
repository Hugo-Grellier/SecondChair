# SecondChair v4 specification

SecondChair is an open-source, human-directed and AI-operated campaign director for tabletop game masters: the GM keeps imagination, acting and creative calls, and agents operate whatever the GM delegates. v4 targets PF2e on Foundry VTT.

This specification is the destination of the map [SecondChair v4 spec (#1)](https://github.com/Hugo-Grellier/SecondChair/issues/1). It describes *what* v4 is and must do, for hand-off to planning. It contains no code and no implementation plan.

## Reading order

| File | Topic |
|---|---|
| [01-vision.md](01-vision.md) | Vision, target mode, audience, languages |
| [02-architecture.md](02-architecture.md) | Core, System extension, VTT connector, Surface; contracts and authorities; agents and jobs |
| [03-delegation.md](03-delegation.md) | Responsibilities, levels, moments, delegation table, enforcement, action log, calls on the GM |
| [04-canon-memory-capture.md](04-canon-memory-capture.md) | Canon, facts, knowledge, campaign language, capture and wrap, behaviour traces |
| [05-living-world-calendar.md](05-living-world-calendar.md) | Fronts, situations, world-turn, forecast, campaign calendar |
| [06-pf2e-rules.md](06-pf2e-rules.md) | PF2e rules coverage, rules checks, third-party modules, house rules |
| [07-build-vs-evolve.md](07-build-vs-evolve.md) | Rebuild decision, what is carried over, transplanted, dropped |
| [08-licensing-repos.md](08-licensing-repos.md) | Licences, CLA, repositories, shipped content, legal constraints |
| [09-packaging.md](09-packaging.md) | Install, process model, Foundry link, workspace, export, distribution |
| [10-success-bench.md](10-success-bench.md) | Measurable success criteria and the test bench |
| [11-out-of-scope.md](11-out-of-scope.md) | Out of scope for v4, and open questions handed to planning |
| [12-campaign-creation-and-library.md](12-campaign-creation-and-library.md) | Campaign workshop skill and reference library |

## Conventions

- Terms in this spec are those of [`GLOSSARY.md`](../../GLOSSARY.md), used with exactly that meaning. A glossary term's _Avoid_ list applies here too.
- Requirements carry an id (`DEL-03`, `CAN-12`…) so planning can trace tickets to them. **MUST** / **MUST NOT** mark hard requirements; everything else is description.
- "The GM" is the human game master who owns the campaign. "Agent" is one agent host session (see [02-architecture.md](02-architecture.md)).

## Precedence

1. Accepted ADRs in [`docs/adr/`](../adr/) are binding; an ADR whose status is proposed binds nothing until the GM accepts it. This spec restates them and never contradicts them. If this spec and an ADR disagree, the ADR wins and the spec is a bug.
2. [`GLOSSARY.md`](../../GLOSSARY.md) fixes the vocabulary.
3. The resolutions of the map's child tickets fill in what the ADRs leave open. Where a later resolution refines an earlier one, the later one holds (for example [#19](https://github.com/Hugo-Grellier/SecondChair/issues/19) replaces the "per-entity overrides deferred" note in [#6](https://github.com/Hugo-Grellier/SecondChair/issues/6), and ADR 0012 widens the GM-effort definition of [#9](https://github.com/Hugo-Grellier/SecondChair/issues/9)).
4. [`docs/design/`](../design/) and ADRs marked *proposed* are proposals awaiting the GM's decision. They bind nothing until accepted.

### Amendments settled while writing this spec (GM, 2026-10-19)

Two ticket resolutions disagreed with an ADR or with each other. The GM settled them:

- **Transcripts stay outside the campaign workspace.** [#18](https://github.com/Hugo-Grellier/SecondChair/issues/18) listed "transcripts" in the workspace; ADR 0008 keeps raw audio and full transcripts as Sources outside it. ADR 0008 holds: the workspace keeps only the quotes attached to facts and the speaker table.
- **The ceiling is a maximum delegation level.** [#6](https://github.com/Hugo-Grellier/SecondChair/issues/6) kept the v3 read / prep / play steps for the ceiling, while ADR 0002 drops those access levels and the glossary calls the ceiling "a maximum level". The ceiling is one of the four delegation levels, global, set by the GM inside the VTT. The names read, prep and play survive only as the three base profiles.

## Decision index

### ADRs

| ADR | Decision | Spec |
|---|---|---|
| [0001](../adr/0001-no-in-house-orchestrator-llm-free-core.md) | No in-house orchestrator; the Core never calls a model; model work is a job started by a runner | [02](02-architecture.md) |
| [0002](../adr/0002-rebuild-rather-than-evolve.md) | Rebuild in English rather than evolve v3; v3 carried as spec, pure algorithms transplanted | [07](07-build-vs-evolve.md) |
| [0003](../adr/0003-core-is-the-only-gateway.md) | The Core is the only MCP server and gateway; irreversible approvals need an authenticated Surface | [02](02-architecture.md), [03](03-delegation.md) |
| [0004](../adr/0004-foundry-connector-library-plus-system-adapters.md) | Foundry connector = system-agnostic library module + one system adapter module per system | [02](02-architecture.md) |
| [0005](../adr/0005-core-schedules-calls-on-the-gm.md) | The Core gives every call on the GM a deadline; Surfaces only display; v4 ships the Director's Desk | [03](03-delegation.md), [02](02-architecture.md) |
| [0006](../adr/0006-agpl-core-apache-connector-cla.md) | AGPL-3.0 Core, Apache-2.0 Foundry modules and playbooks, CLA; one public monorepo | [08](08-licensing-repos.md) |
| [0007](../adr/0007-facts-are-the-unit-of-canon.md) | Facts are the unit of canon, Markdown source of truth, SQLite derived; knowers; cited audience content | [04](04-canon-memory-capture.md) |
| [0008](../adr/0008-capture-cited-facts-rank-as-played.md) | Captured facts that quote the table rank as played; capture never calls on the GM during play | [04](04-canon-memory-capture.md) |
| [0009](../adr/0009-world-turn-deterministic-three-effect-classes.md) | The world-turn is deterministic, never live, with three effect classes | [05](05-living-world-calendar.md) |
| [0010](../adr/0010-local-core-reached-by-the-gm-browser.md) | Local Core over loopback HTTP; the GM's browser dials the Core; the workspace is the export | [09](09-packaging.md) |
| [0011](../adr/0011-foundry-automates-secondchair-checks.md) | Foundry automates the rules; SecondChair checks outcomes against their own trace | [06](06-pf2e-rules.md) |
| [0012](../adr/0012-behaviour-traces-capture-raw-input-with-consent.md) | Behaviour traces capture raw input, locally and only with consent | [04](04-canon-memory-capture.md), [10](10-success-bench.md) |
| [0013](../adr/0013-third-party-modules-are-evidence-turn-drivers-take-over.md) | Third-party modules are optional evidence; a turn driver takes over; house rules come from discrepancies | [06](06-pf2e-rules.md) |
| [0014](../adr/0014-declarative-campaign-calendar-core-follows-paizo.md) | Declarative campaign calendar; the Core follows Paizo over the PF2e clock | [05](05-living-world-calendar.md) |
| [0015](../adr/0015-evidence-is-resolved-by-the-core-before-it-confers-rank.md) | Evidence is resolved by the Core before it confers a rank | [04](04-canon-memory-capture.md) |
| [0016](../adr/0016-a-world-turn-occurrence-is-applied-through-a-roll-forward-journal.md) | A world-turn occurrence is applied through a roll-forward journal | [05](05-living-world-calendar.md), [02](02-architecture.md) |
| [0017](../adr/0017-creative-drafts-live-in-notes-with-a-status.md) | Creative drafts stay in `notes/` with an id, a status and alternative sets; no draft facts | [12](12-campaign-creation-and-library.md) |
| [0018](../adr/0018-snapshot-boundary-restore-and-upgrade-consent.md) | A snapshot is the workspace plus a paired Foundry world; restore into a fresh directory; a destructive migration needs consent. Amends ADR 0010 (in-place upgrade) and PKG-16 | [09](09-packaging.md) |

### Ticket resolutions without an ADR

| Ticket | Decision | Spec |
|---|---|---|
| [#2 Audit the existing tool](https://github.com/Hugo-Grellier/SecondChair/issues/2) | Nothing proven in a real session; carry contracts, algorithms and tests as spec | [07](07-build-vs-evolve.md) |
| [#3 Survey open-source building blocks](https://github.com/Hugo-Grellier/SecondChair/issues/3) | PF2e system required; Foundry MCP Bridge as reference only; no project covers delegation | [07](07-build-vs-evolve.md) |
| [#4 Map legal constraints](https://github.com/Hugo-Grellier/SecondChair/issues/4) | Ship code only; Foundry AI policy binds listed packages only | [08](08-licensing-repos.md) |
| [#6 Define the delegation model](https://github.com/Hugo-Grellier/SecondChair/issues/6) | 8 responsibilities × 4 levels × 3 moments; one action log; caps | [03](03-delegation.md) |
| [#9 Success metrics and test bench](https://github.com/Hugo-Grellier/SecondChair/issues/9) | Metrics from the action log, gold sets written once, no LLM judge; scenarios | [10](10-success-bench.md) |
| [#12 How jobs pick model and effort](https://github.com/Hugo-Grellier/SecondChair/issues/12) | Tier, not model; mapping in the GM's runner configuration | [02](02-architecture.md) |
| [#13 Model canonical memory](https://github.com/Hugo-Grellier/SecondChair/issues/13) | Details of ADR 0007 | [04](04-canon-memory-capture.md) |
| [#14 Session capture and consolidation](https://github.com/Hugo-Grellier/SecondChair/issues/14) | Details of ADR 0008: jobs, tiers, classification, wrap round | [04](04-canon-memory-capture.md) |
| [#15 Bound the living world](https://github.com/Hugo-Grellier/SecondChair/issues/15) | Details of ADR 0009 | [05](05-living-world-calendar.md) |
| [#16 Babele and PF2e translations](https://github.com/Hugo-Grellier/SecondChair/issues/16) | Key on English slug / originalName; read translations at runtime | [04](04-canon-memory-capture.md) |
| [#17 Generated content follows the GM's language](https://github.com/Hugo-Grellier/SecondChair/issues/17) | One campaign language; official reference by English key; campaign vocabulary | [04](04-canon-memory-capture.md) |
| [#18 Packaging and deployment](https://github.com/Hugo-Grellier/SecondChair/issues/18) | Details of ADR 0010 (amended above for transcripts) | [09](09-packaging.md) |
| [#19 Per-entity delegation overrides](https://github.com/Hugo-Grellier/SecondChair/issues/19) | Entity overrides keyed on the acting entity, lower only | [03](03-delegation.md) |
| [#20 PF2e system automation inventory](https://github.com/Hugo-Grellier/SecondChair/issues/20) | What the PF2e system exposes to code | [06](06-pf2e-rules.md) |
| [#22 Westerhold as a public sample](https://github.com/Hugo-Grellier/SecondChair/issues/22) | Westerhold stays private; a new sample campaign ships publicly (S0) | [10](10-success-bench.md), [08](08-licensing-repos.md) |
| [#24 PF2e automation module survey](https://github.com/Hugo-Grellier/SecondChair/issues/24) | No module is a usable base; known flags to read | [06](06-pf2e-rules.md) |

Tickets [#5](https://github.com/Hugo-Grellier/SecondChair/issues/5), [#7](https://github.com/Hugo-Grellier/SecondChair/issues/7), [#8](https://github.com/Hugo-Grellier/SecondChair/issues/8), [#10](https://github.com/Hugo-Grellier/SecondChair/issues/10), [#11](https://github.com/Hugo-Grellier/SecondChair/issues/11), [#21](https://github.com/Hugo-Grellier/SecondChair/issues/21), [#23](https://github.com/Hugo-Grellier/SecondChair/issues/23), [#25](https://github.com/Hugo-Grellier/SecondChair/issues/25) and [#26](https://github.com/Hugo-Grellier/SecondChair/issues/26) are recorded by the ADRs above.
