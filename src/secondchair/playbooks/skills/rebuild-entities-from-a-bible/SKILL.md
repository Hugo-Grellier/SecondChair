---
name: rebuild-entities-from-a-bible
description: Rebuild a campaign's canon from a campaign bible through SecondChair, one entity per named person, place, group and notable thing, then the bible's facts about them. Use when running a SecondChair job whose playbook is rebuild-entities-from-a-bible.
license: Apache-2.0
compatibility: Needs the SecondChair MCP server (secondchair serve) and read access to the bible file.
metadata:
  secondchair-responsibility: memory
  secondchair-tier: standard
  secondchair-inputs: bible
  secondchair-expected-output: One canon entity per named person, place, group or faction, and notable named thing of the bible, created with create_entity, with no duplicate of the campaign vocabulary; then the bible's facts, recorded with record_fact, citing the bible.
---

# Rebuild entities from a bible

You are running a SecondChair job. SecondChair keeps the campaign's canon; you act on it only through its MCP tools. Its delegation table decides what each of your actions does: applied at once, held for the GM's approval, or refused.

## Language

Write every name, alias, description and fact statement you create in the **campaign language** of the job contract (`campaign_language`), whatever language this playbook or the bible is written in. Keep proper nouns exactly as the bible spells them.

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
   - `description`: one or two sentences a player could read, describing what it looks like or is known to be. No secrets, no hidden motives, no statement the GM keeps from the players: what is true about an entity is recorded as facts, not here;
   - `agent`: your name as an agent;
   - `job`: the job id.
4. Read each result. `applied` means the entity exists; `pending` means it waits for the GM's approval, which is fine; an error saying the responsibility is at manual means you may not act: stop and report it. Report any other error and go on with the next entity.
5. Call `search_entities` to read the ids of the entities canon now holds. Then record the bible's facts: for each statement the bible makes about them, secret ones included (canon is the GM's), call `record_fact` with:
   - `statement`: one atomic statement, in the campaign language. A paragraph stating several things gives several facts;
   - `entities`: the ids of the entities it is about;
   - `origin`: `{"kind": "source", "source": <inputs.bible>, "page": <the label of the bible paragraph or section it comes from, such as B04>}`;
   - `relation`: when the statement is one of the Core list, `{"type", "subject", "object"}` with entity ids: `member_of`, `leads`, `lives_in`, `located_in`, `owns`, `knows`, `allied_with`, `opposes`, `serves`, `kin_of`. One relation per fact; leave it out when none fits;
   - `valid_from` / `valid_to`: the campaign dates the bible gives it, if any;
   - `never_true: true` for a belief the bible says is false;
   - `state`: for a front or a situation, its state fact as the tool describes it (a situation's stage, deadline and participants; a front's rule, clock and agenda steps);
   - `agent` and `job` as above.
   Never copy a `CANARY-…` marker into a statement, and never record what someone knows as a statement about them.
6. Read each result as in step 4.
7. When everything is handled, call `finish_job` with the job id, then reply with the count of entities and of facts applied, pending and refused.

Do not invent entities or facts the bible does not state, and do not create the same entity or record the same fact twice.
