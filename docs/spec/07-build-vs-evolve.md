# 07 — Build versus evolve

Decision: [ADR 0002](../adr/0002-rebuild-rather-than-evolve.md); tickets [#2](https://github.com/Hugo-Grellier/SecondChair/issues/2), [#3](https://github.com/Hugo-Grellier/SecondChair/issues/3), [#5](https://github.com/Hugo-Grellier/SecondChair/issues/5).

## Decision

v4 is a **clean rebuild** in this repository, in English, split into Core / System extension / VTT connector / Surface from the start. The predecessor `pf2e-open-campaign` (v3: bible CLI, `bible live` MCP server, `bible-sync` Foundry module, skills) is carried over as a **specification**, not as a codebase.

## Why

- No v3 responsibility was ever proven in a real session: proof stopped at unit tests (1 212 Python + 29 module tests) and Foundry recipes with fictional content and a simulated GM ([#2](https://github.com/Hugo-Grellier/SecondChair/issues/2)). A rebuild loses tests, not field validation.
- The v4 seams do not exist in v3: PF2e and Foundry logic leaks into generic code.
- All v3 prose (~25 k lines of docs, skills, spec) is French, and French reaches into data-contract words.

## What v3 delivered, by responsibility

| Responsibility | v3 state | v4 treatment |
|---|---|---|
| Memory | Strong: ids, changesets with undo, cited append-only chronicle | Contracts as spec; new fact model ([04](04-canon-memory-capture.md)) |
| Prep | Strong: XP / treasure / dungeon budgets, scene YAML with reconciliation | Tables and reconciliation transplanted |
| VTT operations | Strong: ~30 MCP tools, idempotent requests, write queue, durable capture | Reliability mechanisms transplanted |
| Living world | Strong: deterministic world-turn, occurrence keys | Keys transplanted; contracts as Core unit tests ([05](05-living-world-calendar.md)) |
| Rules and combat | Weak: Strike / Stride and turn budget only | Rewritten to [06](06-pf2e-rules.md) |
| NPCs | Weak: no per-NPC knowledge | Knowers and acting cues ([04](04-canon-memory-capture.md)) |
| Narrative direction | Weak: data types and skills only | Capped at propose; living-world new narrative class |
| Capture | Never run on a real session | New pipeline ([04](04-canon-memory-capture.md)) |

## Carried over

- **BVE-01** As specification: v3 contracts, algorithms and test cases become English ADRs and acceptance tests.
- **BVE-02** Transplanted as code, translated and placed in their building block, only pure dependency-free algorithms:
  - calendar arithmetic (generalised to the declarative calendar);
  - XP and treasure tables;
  - world-turn occurrence keys;
  - the mystery graph;
  - scene reconciliation;
  - the Foundry reliability mechanisms: idempotent requests, write queue, durable capture.
- **BVE-03** Kept as code with no data, in the PF2e System extension: the Absalom calendar and the GIS importer.

## Dropped

- **BVE-04** French contract words (`ERREUR`, `ALERTE`, `auto · certain`).
- **BVE-05** The read / prep / play access levels, replaced by the delegation model. The names survive only as base profiles ([03](03-delegation.md)).
- **BVE-06** LoreForge-specific transcript revision.
- **BVE-07** Every shipped campaign or GIS dataset.
- **BVE-08** Storage compatibility with v3, and any migration path. The v4 format is free.

## The predecessor

- **BVE-09** `pf2e-open-campaign` is stopped and archived (private, read-only), the reference for the v3 spec and for transplants.
- **BVE-10** Westerhold, a fictional test campaign with no players or sessions, is not migrated. Its v3 bible is a read-only Source that v4 rebuilds with its own playbooks, as scenario S1 ([10](10-success-bench.md)).

## Third-party building blocks ([#3](https://github.com/Hugo-Grellier/SecondChair/issues/3))

| Project | v4 use |
|---|---|
| PF2e Foundry system (Apache-2.0 code) | Required runtime and rules engine; pack data fetched locally, never shipped |
| Foundry MCP Bridge (MIT) | Reference or fork source for generic CRUD tools only |
| Foundry API Bridge, Ninjo's Foundry MCP | Not used (closed relay; proprietary) |
| LangGraph, LiteLLM | Out of the v4 stack ([ADR 0001](../adr/0001-no-in-house-orchestrator-llm-free-core.md)) |
| Concordia, Graphiti | Optional derived engines, not in v4 |
| MCP Python SDK | Candidate for the Core's MCP server (Streamable HTTP) |
| WhisperX | Default transcription engine ([04](04-canon-memory-capture.md)) |
| Babele, pf2-fr | Read at runtime from the GM's install, never shipped |
| PF2e Combater | Design reference and detected turn driver, never a base ([06](06-pf2e-rules.md)) |
| `pf2e-narrative-assistant` (own) | Its PF2e roll classifier is a seed for the System extension |

No open project covers delegation levels plus GM-validated canon; that is SecondChair's own value.
