# 01 — Vision and target mode

## Problem

Running a campaign asks one person to be author, actor, rules referee, archivist, VTT operator and world simulator at once. Much of that work is mechanical (placing a scene, rolling for monsters, remembering who knows what, advancing a front), yet it competes for the same attention as the creative work. Existing AI tools either answer questions on demand or try to replace the GM. None lets a GM hand over a precisely bounded share of the work and keep authority over the fiction ([#3](https://github.com/Hugo-Grellier/SecondChair/issues/3)).

## Target mode: the augmented campaign director

SecondChair v4 targets the **augmented campaign director**. The GM keeps imagination, acting and creative calls. Agents operate whatever the GM delegates, at the delegation level the GM grants, and the GM can see and undo what they did.

- Autonomy is not a property of an agent. It is a **delegation level** granted per **responsibility**, set per **moment** in the campaign's **delegation table** ([03-delegation.md](03-delegation.md)).
- **Canon** is held by the Core and validated by the GM: what was played outranks every decision, and the GM's decisions outrank anything an agent proposed ([04-canon-memory-capture.md](04-canon-memory-capture.md)).
- Interruptions are the price of delegation during a live session. The Core decides when a call reaches the GM, so the price stays measurable and low ([ADR 0005](../adr/0005-core-schedules-calls-on-the-gm.md)).

### The AI GM stays possible, not targeted

The **AI GM** mode, where narrative direction itself is delegated, is not a v4 goal. The architecture MUST NOT prevent it:

- **VIS-01** Narrative direction is capped at *propose* by a tool setting, not by an architectural constraint ([#6](https://github.com/Hugo-Grellier/SecondChair/issues/6)).
- **VIS-02** Agents are interchangeable and hold no rights of their own, so a later agent can take a wider share without a new rights model ([ADR 0001](../adr/0001-no-in-house-orchestrator-llm-free-core.md)).
- **VIS-03** Model work is a job with an explicit contract, so an in-house loop or an in-Core model can later execute the same jobs ([ADR 0001](../adr/0001-no-in-house-orchestrator-llm-free-core.md)).

## Modular by design

SecondChair is split into four building blocks from the start ([02-architecture.md](02-architecture.md)):

- the **Core**, game-agnostic and VTT-agnostic;
- a **System extension** per game system (PF2e only in v4);
- a **VTT connector** per virtual tabletop (Foundry only in v4);
- **Surfaces** for the GM (conversation in an agent host and the CLI first, the Director's Desk inside Foundry; GUIs later).

The seams for other systems and VTTs exist in v4; their implementations do not.

## Audience

1. **The repository owner as GM** (dogfooding), with the PF2e Beginner Box as the first real table.
2. **Technical GMs** after that: people comfortable installing a Python tool, running an agent host (Claude Code or Codex) and a Foundry module.

A GUI for non-technical GMs and a hosted service are out of scope ([11-out-of-scope.md](11-out-of-scope.md)).

## Languages

- **VIS-04** Everything in the tool is in English: code, docs, playbooks, contract words, error messages.
- **VIS-05** Everything SecondChair generates for a campaign is in that campaign's **campaign language**, fixed at creation ([#17](https://github.com/Hugo-Grellier/SecondChair/issues/17)). Sources may be in any language. The GM converses with agents in the language they choose.

## Tool and campaign are separate

The tool goes open source; campaigns stay private. A **campaign workspace** lives outside the tool, and the tool never ships one, nor any Source ([08-licensing-repos.md](08-licensing-repos.md), [ADR 0006](../adr/0006-agpl-core-apache-connector-cla.md)).

## What success means

v4 succeeds when, measured automatically on the test bench and in dogfooding, delegation lowers GM effort and interruptions against a manual baseline, while the zero invariants (no leak, no narrative action above propose) hold on every run and continuity, capture and agreement stay above their floors, at the cheapest runner configuration that meets them ([10-success-bench.md](10-success-bench.md)).
