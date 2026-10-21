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

`entity`: the NPC's entity id (`e-...`). Without a job, take the id or name the GM gives and resolve it with `search_entities`. Refuse an entity that is not a person or a creature that acts; ask instead of choosing one.

## What you read

Read first, write after. Use only what the tools return.

1. The entity and its relations (`search_entities`, `search_facts` with `entity`, relation facts included).
2. What the NPC knows (`what_knows` with the entity as `knower`, inheritance included) and what is true about them that they do not hold (`search_facts` for the entity minus that set): their secrets.
3. What the party knows of them (`what_knows` with `party`), to separate what the table has seen from what it has not.
4. Current arcs touching them: `living_world` for fronts and situations, `check_mystery` for mysteries naming them, and the adopted notes under `notes/` that cite them.
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
2. **Want, fear, secret**: what they want, what they dread, and the secret as a pointer to its canon fact id. The truth stays in canon: restate it only as far as the GM needs to act, and say when no canon fact backs it so the GM can decide whether to record one.
3. **Voice and mannerisms**: exactly three concrete tells an actor can perform (a gesture, a phrase, a rhythm), not adjectives.
4. **Reaction to the party**, by disposition: friendly, neutral, hostile (wary or afraid if the table has made them so). One or two lines each: what they offer, what they ask, what changes. Say what canon supports today; a disposition canon does not support is a *(proposal)*. Never what a PC does or feels.
5. **What they know**: the facts they hold, each with its id and one phrase.
6. **What they will not reveal** (GM-only), in its own section apart from the one above: each secret or withheld fact with its id, why they hold it back, and what would make them speak (pressure, kindness, a trade).
7. **Hooks into current arcs**: how this NPC can pull the party into the open fronts, situations and mysteries found above, each citing the ids it touches. A possibility the table may pick up, never an event.
8. **Three sample lines**, in the campaign language, each tagged with the situation it fits. Check each with `check_audience_content` for the `party` before keeping it; a line that would reveal a fact the party does not hold is rewritten, or moved to the GM-only section as something the NPC would never say aloud.

Change triggers, as in the workshop skill, only if the GM asks.

## Boundaries

- Never call `record_fact`, `record_knowledge`, `create_entity` or any canon write. A setting truth you needed that canon lacks is an open question for the GM, who decides whether it goes through the workshop's confirmation steps.
- No player-facing output: do not publish, share or journal this note. Player-facing text derived from it goes through the guard.
- Write no other note and edit no other file.

## Before you finish

Run `secondchair notes check` and fix every problem it reports on your note; never drop a cite to make it pass. Report the file actually written, the sample lines' `check_audience_content` results, what is proposed rather than canon, and the open questions. Claim the note is saved only after the write succeeded.
