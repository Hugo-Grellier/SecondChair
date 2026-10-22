---
name: write-an-npc-dossier
description: Write a GM-facing dossier draft for one NPC through SecondChair - an at-a-glance line, want, fear and secret, voice with three tells, reactions by disposition, what they know and will not reveal, hooks into current arcs and three sample lines - from what canon holds, as a draft note the GM adopts or rejects. Use when the GM asks for an NPC's dossier or acting notes, or when running a SecondChair job whose playbook is write-an-npc-dossier.
license: Apache-2.0
compatibility: Needs the SecondChair MCP server (secondchair serve). Layered on the campaign-workshop skill.
metadata:
  secondchair-responsibility: prep
  secondchair-tier: deep
  secondchair-inputs: entity
  secondchair-expected-output: The NPC's dossier written as a draft note at notes/npcs/<entity id>.md (never canon, GM-only), checked with notes check and check_audience_content on its sample lines, and a summary of what is proposed, what canon could not support and the open questions.
---

# Write an NPC dossier

You turn what canon holds about one NPC into a dossier the GM can act from at the table. This skill **adds to** the `campaign-workshop` protocol ("NPC dossiers") and never replaces it. The GM decides everything creative; you run only when asked. Acting direction has no truth value, so it is a draft note and never canon (ADR 0017).

## Language

Write the note in the **campaign language** (`campaign_info`), whatever language this playbook is written in, including the three sample lines.

## Inputs

`entity`: the NPC's entity id (`e-...`). Without a job, take the id or name the GM gives and resolve it with `search_entities`.

- No match: say so and ask; never create the entity.
- Several matches: list them with their ids and ask which; never pick one.
- The entity's `kind` (in the `search_entities` result) is `pc`, `faction`, `place` or `item`: refuse, say why. A PC is never a knower and is the player's, not yours to direct. `npc`, `other` or no kind set: go on (mention a missing kind as an open question).

## Relation to the workshop dossier

This is a deliberate, shorter subset of the workshop's dossier convention, for the GM who wants a table-ready page. It uses the same file, `notes/npcs/<entity id>.md`, and the same front matter, so there is one dossier per NPC, never two. If a fuller workshop dossier is already there, keep its sections and the GM's edits, add or refresh only the sections below, and do not delete the rest.

## What you read

Read first, write after. Use only what the tools return.

1. The entity and its relations (`search_entities`, `search_facts` with `entity`, relation facts included).
2. What the NPC knows: `what_knows` with the entity as `knower`, inheritance included.
3. What the party knows: `what_knows` with `party`. **The NPC's secrets are the facts the NPC holds that the party does not**: `what_knows(npc)` minus `what_knows(party)`. These are what they "will not reveal". Truths about the NPC that the NPC does not hold (what they are wrong or blind about) are not secrets: list them separately and optionally as *blind spots*.
4. Current arcs touching them: `living_world` for fronts and situations; for mysteries, read the files in `canon/mysteries/` (the mystery id is the file name) that name the entity and call `check_mystery` with that id; if none names them, skip it. Also the adopted notes under `notes/` that cite them.

If `what_knows` for the NPC is empty or canon holds no fact about them, either ask the GM for the missing setting, or write a thin dossier whose every item is *(proposal)* and flag at the top that canon holds nothing on them. Never invent a secret as if it were canon.

5. The existing `notes/npcs/<entity id>.md`, if any: read it first and keep the GM's edits. Voice and mannerisms the GM already stated win over anything you invent.

## The note

Write `notes/npcs/<entity id>.md` with this front matter:

```yaml
id: d-<8 hex>          # new, never reused; keep the existing one on a rewrite
status: draft          # always draft: only the GM adopts or rejects
cites: [f-..., e-...]  # every entity and fact id cited below; each must resolve
```

A GM-only note: nothing here is for players. Cite entity and fact ids (`f-...`, `e-...`), never a bible paragraph label (B07) or a purchased page. Mark everything canon does not hold as *(proposal)*.

1. **At a glance**: one line, who they are, what they do, how they sound.
2. **Want, fear, secret**: what they want, what they dread, and the secret as a pointer to its canon fact id. Cite the fact id plus a few words and never restate it; only the GM-only section (6) elaborates. Say when no canon fact backs a secret so the GM can decide whether to record one.
3. **Voice and mannerisms**: exactly three concrete tells an actor can perform (a gesture, a phrase, a rhythm), not adjectives.
4. **Reaction to the party**, by disposition: friendly, neutral, hostile (wary or afraid if the table has made them so). One or two lines each: what they offer, what they ask, what changes. Say what canon supports today; a disposition canon does not support is a *(proposal)*. Never what a PC does or feels.
5. **What they know**: the facts they hold, each with its id and one phrase.
6. **What they will not reveal** (GM-only), in its own section apart from the one above: the facts they hold that the party does not, each with its id, why they hold it back, and what would make them speak (pressure, kindness, a trade). Optional *Blind spots* below it: truths about them they do not hold, each with its id.
7. **Hooks into current arcs**: how this NPC can pull the party into the open fronts, situations and mysteries found above, each citing the ids it touches. A possibility the table may pick up, never an event.
8. **Three sample lines**, in the campaign language, each tagged with the situation it fits. Check each with `check_audience_content`, `audience` the `party`, `cites` the ids of the facts the line uses (the party must hold each one; a line with no fact behind it cites none). If it is refused because it names someone the party holds no fact about, or voices a fact the party lacks, rewrite it without the name or the fact, or drop it. Never keep a refused line.

Change triggers, as in the workshop skill, only if the GM asks.

## Boundaries

- Never call `record_fact`, `record_knowledge`, `create_entity` or any canon write. A setting truth you needed that canon lacks is an open question for the GM, who decides whether it goes through the workshop's confirmation steps.
- No player-facing output: do not publish, share or journal this note. Player-facing text derived from it goes through the guard.
- Write no other note and edit no other file.

## Before you finish

Run `secondchair notes check` and fix every problem it reports on your note; never drop a cite to make it pass. Report the file actually written, the sample lines' `check_audience_content` results, what is proposed rather than canon, and the open questions. Claim the note is saved only after the write succeeded.
