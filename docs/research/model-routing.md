# Model routing: tiers per playbook

Design note for [#180](https://github.com/Hugo-Grellier/SecondChair/issues/180) (route creative judgment to the strongest model, bookkeeping to cheaper ones). No code. Read against `main` at `e96207e`, 2026-10-20.

## Constraints that already hold

- **ARC-25**: a job declares a tier (`fast`, `standard`, `deep`). The playbook declares it in `metadata.secondchair-tier`, and the job contract may override it. **No model name appears in the Core or in a playbook.** CI enforces this (`MODEL_NAME`, `tests/test_jobs.py:432`).
- **ARC-26**: the tier → runner configuration mapping (host, model, effort, ordered fallbacks) lives only in the GM's machine configuration, keyed by tier.
- **ARC-27/28/29/30**: fallbacks are tried in order and logged, and are never silently substituted. A live job's latency cap is its call's deadline. On a manual start the GM's own session decides. The bench writes the cheapest passing mapping.

#180's taxonomy therefore maps onto tiers, never onto model ids. Which model sits behind `deep` is the GM's machine config. The issue's Opus/Sonnet/Haiku split is one example config.

## Finding: Core-queued jobs ignore the playbook's tier

`runner.queue` (CLI, bench) reads the tier from the playbook (`src/secondchair/runner.py:99`). The Core's own queues pass literals instead:

| Queued at | Playbook | Literal | Playbook declares |
|---|---|---|---|
| `core/capture.py:89` (`queue_wrap`) | wrap-a-session | standard | standard |
| `core/capture.py:471` (wrap end → world-turn) | world-turn | **standard** | **fast** |
| `core/world.py:362` (narrative occurrence) | propose-narrative-direction | standard | standard |
| `core/world.py:362` (unless) | settle-an-unless | standard | standard |
| `core/world.py:374` | propose-consequences | standard | standard |

The world-turn mismatch is a live bug: every post-wrap world-turn runs one tier higher than declared. Changing a playbook's tier would also silently not apply to Core-queued jobs. Fix (R1): `jobs.queue` takes `tier=None`, meaning "the playbook's", and resolves it where the playbook is known. Alternatively, a test asserts that every Core literal equals the playbook's frontmatter. The test is smaller. The `None` default removes the duplication. Recommend the default, with the test below as the guard.

## Proposed tier per playbook

Cognitive work, not importance, picks the tier. **Deep** is open-ended creative or editorial judgment whose quality the GM feels. **Standard** is a bounded conversion or synthesis against a clear contract and checks. **Fast** is short extraction, classification or lookup, or a deterministic tool driver.

| Playbook | Today | Proposed | Why |
|---|---|---|---|
| prepare-a-session | deep | **deep** | Session design across canon, scenes and NPCs; the GM-facing handoff |
| propose-narrative-direction | standard | **deep** | Creative alternatives at a deadline; #180's main case |
| quick-help | fast | **fast** | Live, under a call deadline (ARC-28); canon-consistent short answer |
| wrap-a-session | standard | **standard** | Verbatim-quote capture plus classification; Core consolidation validates it |
| world-turn | fast (Core: standard) | **fast** | Drives the deterministic `world_turn` tool (ADR 0009); no judgment |
| settle-an-unless | standard | **standard** | Bounded judgment citing facts |
| propose-consequences | standard | **standard** | Derived consequences citing facts; escalate on a failed check, not by default |
| rebuild-entities-from-a-bible | standard | **standard** | Bulk extraction with entity resolution; volume makes deep costly |
| answer-probes | standard | **standard** | Bench scoring; changing it shifts the S0 baseline, so decide with #69 |
| diagnose-frictions | standard | **standard** | Proposes delegation-table changes; bounded |
| calibrate-encounters (pf2e) | standard | **standard** | Python calculators do the maths; the agent picks creatures |
| realise-a-scene (foundry) | standard | **standard** | Desired-state authoring against a strict schema |
| *(future)* campaign vision / editorial (#175) | — | **deep** | Editorial criticism |
| *(future)* source entity extraction (knowledge-ingestion.md) | — | **fast** | Short cited extraction into a review queue |

Net change: propose-narrative-direction moves to deep, and the world-turn literal is aligned to fast.

## Open product choices for the GM

1. **Escalation on failure.** ARC-27 falls back within one tier's list. Should a job whose output contract fails (#171) be requeued once at the next tier up? Proposal: yes, as a logged new attempt with `escalated_from`, never for live jobs (latency) and never more than one step. This is explicit, not silent, so ARC-27 holds.
2. **Escalation on uncertainty.** Should an agent be able to *request* a higher tier ("this needs deep")? Proposal: no in v4. It can only raise a call on the GM. Self-escalation is unmeasurable.
3. **Per-responsibility tiers.** ARC-26 forbids per-moment and per-responsibility variation in v4. Keep that. The playbook tier is the only dial.
4. **The live quick-help tier.** If `fast` answers are too bland at the table, does the GM accept the latency of `standard`? It is a bench question (#69, S4 deadlines).
5. **Haiku-class claims.** These need no special gate. Every tier's output passes the same Core checks (consolidation, citations, #168 provenance). The acceptance criterion holds by construction. A test pins it (below).

## Example machine configuration (not shipped, not required)

```yaml
# ~/.config/secondchair/config.yaml — the GM's choice; a subscription host works as well as API keys
runners:
  deep:     [{host: claude, model: opus,   effort: high}]
  standard: [{host: claude, model: sonnet, effort: medium}, {host: codex, model: <gm's>, effort: medium}]
  fast:     [{host: claude, model: haiku,  effort: low}]
```

## Tests (R0)

- `test_each_playbook_declares_its_intended_tier`: a dict `{playbook: tier}` in `tests/test_jobs.py` equal to `{s.name: runner.playbook(s.name)["tier"] for s in runner.skills()}`. Changing a tier then needs a conscious edit of the table. This covers "creative jobs request deep, clerical jobs avoid accidental deep".
- `test_core_queued_jobs_use_the_playbook_tier`: run a wrap end and a world-turn with one narrative occurrence, one unless and one applied effect on the sample campaign. Assert that every queued job's tier equals `runner.playbook(job["playbook"])["tier"]`.
- `test_tier_does_not_change_admission`: the same candidate consolidated from a job at `fast` and at `deep` gets the same rank and checks.

## Leaves

| Title | Risk | Deps |
|---|---|---|
| Core-queued jobs take the playbook's tier (fixes world-turn) | R1 | — |
| Pin each playbook's tier in a test; narrative direction to deep | R0 | — |
| Logged one-step escalation on a failed output contract | R1 | #171, GM choice 1 |
| Bench: mixed creative and bookkeeping task set by host × model × effort | R0 | #69 |
