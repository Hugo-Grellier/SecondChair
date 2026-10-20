---
name: rebuild-entities-from-a-bible
description: Rebuild a campaign's canon entities from a campaign bible, one entity per named person, place, group and notable thing, through SecondChair. Use when running a SecondChair job whose playbook is rebuild-entities-from-a-bible.
license: Apache-2.0
compatibility: Needs the SecondChair MCP server (secondchair serve) and read access to the bible file.
metadata:
  secondchair-responsibility: memory
  secondchair-tier: standard
  secondchair-inputs: bible
  secondchair-expected-output: One canon entity per named person, place, group or faction, and notable named thing of the bible, created with create_entity, with no duplicate of the campaign vocabulary.
---

# Rebuild entities from a bible

You are running a SecondChair job. SecondChair keeps the campaign's canon; you act on it only through its MCP tools. Its delegation table decides what each of your actions does: applied at once, held for the GM's approval, or refused.

## Language

Write every name, alias and description you create in the **campaign language** of the job contract (`campaign_language`), whatever language this playbook or the bible is written in. Keep proper nouns exactly as the bible spells them.

## The job contract

You were given a job id. If you were not given its contract, the GM asked you to take a queued job: call `start_job` with the job id and the agent host, model and effort you run with, and read the contract it returns. The contract holds:

- `inputs.bible`: the path of the campaign bible. It is a Source: read it, never copy it or edit it.
- `vocabulary`: the names and aliases canon already knows. Never create an entity for one of them.
- `expected_output`: what you must have produced when you finish.

## Steps

1. Read the whole bible before creating anything.
2. List every **named** person (player characters and non-player characters), place, group or faction, and notable named thing (an object, a vessel, a document). Skip unnamed extras and generic nouns. When the bible gives one entity several names or a title, that is one entity with aliases, not several.
3. For each entity not already in the vocabulary, call `create_entity` with:
   - `names`: its main name, as the bible spells it;
   - `aliases`: its other names, titles and short forms, if any;
   - `kind`: `pc` for a player character, `npc` for another person, `faction` for a group or faction, `place`, `item` for a named thing, or `other`;
   - `description`: one or two sentences a player could read, describing what it looks like or is known to be. No secrets, no hidden motives, no statement the GM keeps from the players: what is true about an entity is recorded as facts later, not here;
   - `agent`: your name as an agent;
   - `job`: the job id.
4. Read each result. `applied` means the entity exists; `pending` means it waits for the GM's approval, which is fine; an error saying the responsibility is at manual means you may not act: stop creating entities and report it. Report any other error and go on with the next entity.
5. When every entity is handled, call `finish_job` with the job id, then reply with the count of entities applied, pending and refused.

Do not invent entities the bible does not name, and do not create the same entity twice.
