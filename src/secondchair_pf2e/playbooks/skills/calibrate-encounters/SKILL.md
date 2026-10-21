---
name: calibrate-encounters
description: Prepare a Pathfinder Second Edition adventure's encounters for the party through SecondChair, each one calibrated with the PF2e calculators (threat, XP, treasure) and written as a prepared scene. Use when running a SecondChair job whose playbook is calibrate-encounters.
license: Apache-2.0
compatibility: Needs the SecondChair MCP server (secondchair serve) with the PF2e System extension and a VTT connector offering prepare_scene, and read access to the adventure input.
metadata:
  secondchair-responsibility: prep
  secondchair-tier: standard
  secondchair-writes: "true"
  secondchair-inputs: adventure, party, encounters
  secondchair-expected-output: One prepared scene per encounter listed in the encounters input, under its key, written with prepare_scene, whose creatures and hazards meet the threat the adventure gives it as encounter_xp computes it, and a summary for the GM with each encounter's XP, threat, award and the level's treasure budget.
---

# Calibrate encounters

You are running a SecondChair job. SecondChair holds the campaign's prep; you act on it only through its MCP tools, and its delegation table decides what each of your actions does: applied at once, held for the GM's approval, or refused.

## Language

Write every name and every text a player can see (scene and token names, notes) in the **campaign language** of the job contract (`campaign_language`), whatever language this playbook or the adventure is written in. Keep official names as the adventure spells them.

## The job contract

You were given a job id. If you were not given its contract, the GM asked you to take a queued job: call `start_job` with the job id and the agent host, model and effort you run with, and read the contract it returns. The contract holds:

- `inputs.adventure`: the path of the adventure. It is a Source: read it, never copy it or edit it. When it is a **metadata index** (a YAML file whose `opt_in` is false), the adventure is purchased content the GM has not opted in to send to a model: you have only its file names and sizes. Never look for its content elsewhere on disk; prepare what the index and the other inputs allow and list for the GM what you could not.
- `inputs.party`: the party's level and size, for example `level 1, 4 PCs`.
- `inputs.encounters`: the encounters to prepare, each `key: what it is`, separated by `;`. Keep each key: it is how SecondChair finds the scene again.

## Steps

1. For each encounter, list its creatures and hazards with their levels, from the adventure.
2. Call `encounter_xp` with the party level, the party size and one level per creature (`creatures`), simple hazard and complex hazard. It returns each line's XP, the total, the threat and the threat budgets for this party size.
   - When the adventure names a threat for the encounter and the total does not meet it, adjust only what the adventure leaves open (the number of weaker creatures), call `encounter_xp` again, and note the change for the GM.
   - Never invent a creature level: when the adventure does not give one, say so.
3. Call `prepare_scene` with the encounter key as `key`, the scene, and one Token per creature, `hidden: true`, with your `agent` name and the `job` id. `applied` means it is written; `pending` means it waits for the GM's approval. An error saying the responsibility is at manual means you may not act: stop and report it.
4. Call `treasure_budget` with the party level and size once, and compare the treasure the adventure places in these encounters with it.
5. Call `finish_job` with the job id, then reply with one line per encounter (key, XP total, threat, XP awarded per PC), the treasure placed against the budget, and everything you could not prepare and why.

Do not prepare encounters the `encounters` input does not list.
