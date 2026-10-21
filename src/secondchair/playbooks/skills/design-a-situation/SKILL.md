---
name: design-a-situation
description: Design a non-linear situation or a mystery with the GM through SecondChair - stakes, interested parties, pressure over time, clues, plausible responses and their consequences, three divergent approaches simulated against canon, and a one-screen reference for play, kept as a draft note and checked with check_draft_mystery. Use when the GM asks to design a situation, an investigation or a mystery, or when running a SecondChair job whose playbook is design-a-situation.
license: Apache-2.0
compatibility: Needs the SecondChair MCP server (secondchair serve).
metadata:
  secondchair-responsibility: prep
  secondchair-tier: deep
  secondchair-inputs: brief?
  secondchair-expected-output: A situation draft note at notes/mysteries/<slug>.md (or notes/workshop/ when it has no investigation), its mystery graph checked with check_draft_mystery with no warning left unresolved, three approaches simulated, and a summary for the GM of what is settled, what needs them and the open questions.
---

# Design a situation

A task skill layered on the campaign workshop protocol: the GM directs, you collaborate, there is no required sequence and no deliverable the GM did not ask for. You design a situation the party can approach in many ways, so no single clue, place or choice can stall the table. You propose, compare and check; the GM decides. You never decide an ending, what a PC chooses or what a PC feels.

## Language

Write every statement and note in the **campaign language** (`campaign_info`), whatever language this playbook is written in.

## Where the work lives

The design is a **draft note**, never canon. Write it to `notes/mysteries/<slug>.md` with ADR 0017's front matter (`id`, `status: draft`, `cites` for the canon ids it builds on). When there is no investigation, a note in `notes/workshop/` is enough. Read existing notes and canon first (`search_entities`, `search_facts`, `what_knows`) so the situation fits what is true and what the party knows. Show the GM each step before writing it, and save only what they approve.

## Method

Work with the GM, one question at a time, in whatever order the conversation needs.

1. **Stakes**: what is lost or gained, and for whom, if nothing is done.
2. **Interested parties**: who wants what, what each can do, and what each knows (a canon entity each, or a name to create if the GM agrees).
3. **Resources**: what each side commands (people, money, time, leverage, secrets).
4. **Pressure over time**: what moves without the party, at which dates. If it ends at a date, say what that date triggers; it can become a situation's deadline in the living world.
5. **Clues**: the evidence that reveals the truth. Give each conclusion three or more clues spread over different places or people. Mark a clue `mobile: true` when the party can find it wherever they are looking (a rumour, a letter, a witness who comes to them), `mobile: false` for fixed evidence. Say how each clue is found.
6. **Scenes** (optional): only those the GM wants. A scene is a possible place for clues and pressure, never a required step.
7. **Responses**: at least three plausible responses of the party, each with its consequences, and what happens if they ignore the situation.
8. **Three divergent approaches**: write the situation played three ways (social, stealth, force, or what fits the table). For each, say which clues it finds, what the parties do in return and where it leads, checking every claim against canon. This is a human-judged simulation, not a Core check: mark what you could not verify.
9. **Operational reference**: one screen the GM can run from: the situation in two lines, the parties and their aims, the clue table (clue, where, how found, points to), the clock, and the three approaches' likely consequences.

## The mystery graph and its check

Keep the graph in the note's front matter, the same as `record_mystery`: `conclusions` and `clues` each with an `id`, and either a draft `statement` or, when the truth is already canon, a `fact` id; `nodes` naming canon entities (`entry: true` where the party is led in); `clues` with `on` and `points_to`. Mix both forms freely.

Call `check_draft_mystery` with the note's slug after every change to the graph. Resolve each warning by **adding clues, nodes or entries**, or by rewiring `points_to`: never by dropping a conclusion, a node or the check. Use `lose` to simulate losing a clue or two and fix what then breaks. Report to the GM any warning you could not resolve with the reason.

## Promotion

Only when the GM asks to adopt the design, follow the promotion steps of the campaign workshop skill. Nothing in the draft is true until then.

## Finish

Reply with the files written, the check's final report, what the GM still has to decide and the open questions. Claim something saved only after the write succeeded.
