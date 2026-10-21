---
name: develop-campaign-direction
description: Help the GM develop a campaign's direction as an editorial loop - a brief, several materially different pitches kept side by side, a critique checklist, the GM's choice, an open-ended outline and a short player-facing primer, then revisions - through SecondChair. Use when the GM asks for campaign vision, pitches, a premise to choose between, or to develop or revise a campaign's direction.
license: Apache-2.0
compatibility: Needs the SecondChair MCP server (secondchair serve). Layered on the campaign-workshop skill.
metadata:
  secondchair-responsibility: prep
  secondchair-tier: deep
  secondchair-inputs: request?
  secondchair-expected-output: The moves the GM asked for, written as design notes under notes/direction/ (never canon), the campaign primer under prep/ when asked, and a summary of the files changed and the open questions.
---

# Develop campaign direction

You work with the GM on where their campaign is going. This skill **adds to** the `campaign-workshop` protocol (one question at a time, recaps, no required sequence) and never replaces it. The GM decides everything creative. You propose, compare and flag; you never decide an ending, a PC's choice or a PC's feelings.

## Language

Write every note and the primer in the **campaign language** (`campaign_language` of `workspace.yaml`), whatever language this playbook is written in.

## Where things live

- Drafts are **design notes** under `notes/direction/`: Markdown with the front matter of ADR 0017 (`id: d-` plus eight hex digits, `status`, and when they apply `alternatives`, `supersedes`, `cites`, `reason`). Notes are not canon: no canon tool reads them. `secondchair notes check` validates them; run it after writing and show the GM what it reports. Never fix a report silently.
- Setting truths are canon. Write one only when the GM states it and confirms the precise change, through the existing memory tools with origin `{kind: gm, words: ...}`; it stays a proposal until the GM runs `secondchair confirm <id>`. A pitch that relies on a secret does not make it true.
- Read `search_facts`, `what_knows` and `living_world` before pitching, so every pitch is rooted in this campaign's entities, factions and open situations.

## The moves

The GM may ask for any of them, in any order, or skip them. Do only what was asked, then say what the next move could be.

1. **Brief** (`notes/direction/brief.md`, status `draft`): premise, tone, themes, level range, table boundaries (lines and veils), the promise made to the players, how much sandbox freedom, the foundational conflicts. Ask for what is missing one question at a time; leave a gap marked open rather than inventing it.
2. **Pitches**: by default **three**, or the number the GM asks for in this request. Each is one note in the same alternative set (`alternatives: campaign-direction`, status `draft`), and they differ in architecture: another central conflict, structure or antagonist pressure, not one plot in three costumes. Each pitch has these sections: strengths, weak points, hooks, factions, near-term beats (the next two or three sessions), loose long-term possibilities (possibilities, never a schedule), and the canon ids it must respect (also in `cites`). Only canon ids that exist may be cited.
3. **Critique**: write this checklist into each pitch under `## Critique`, one line per item, **flags only** (what you noticed and where, or "no flag"). The GM weighs them; you do not rewrite the pitch to dodge a flag unless asked.
   - Clichés: stock figures or plot beats a table has seen many times.
   - False choices: options that lead to the same place.
   - PC relevance: which PCs have a personal stake, and which have none.
   - Pacing: where the beats stall or rush.
   - Accidental railroading: a step that only works if the party does one thing.
   - Payoff without setup: a payoff with no earlier appearance to prepare it.
   - Unearned revelations: a secret revealed without causes the party could have met.
4. **Choice**: the GM adopts one pitch (status `adopted`; at most one per set), rejects others or merges several into a new note, always with the GM's reason in `reason`. Change a status only at the GM's word. A merge is a new note that `supersedes` its sources.
5. **Outline**: from the adopted pitch, `notes/direction/outline.md` (status `draft`, `cites` the adopted pitch's canon ids). Arcs are pressures and open questions, not plots. Each revelation is linked to its causes and to at least two ways the players could reach it. Never write a fixed ending. Then, only if the GM wants it, a short **campaign primer** for session zero: what the players may know (premise, tone, the promise, how to make a character, the safety tools the brief names), written with `write_prep` at `campaign-primer.md`. Check every line the players will read with `check_audience_content` for the `party` audience, citing the facts it uses; rewrite what is refused. The primer holds no secret, no twist and no hint of the outline's revelations.
6. **Revision**: never edit an adopted or rejected note in place. Write a new note with `supersedes: [<old id>]` and the GM's `reason`; the old note becomes `superseded` at the GM's word. Git keeps the history.

## Closing

Report the files actually changed, the `secondchair notes check` result, any canon proposal still pending the GM's `secondchair confirm`, and the open questions. Claim something is saved only after the write succeeded. The rubric the GM can use to judge a pitch set is in `docs/design/campaign-direction-rubric.md` of the SecondChair repository.
