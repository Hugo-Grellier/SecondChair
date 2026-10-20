---
name: realise-a-scene
description: Write a prepared scene's desired state for Foundry VTT (the map, its tokens, lights, walls, sounds, notes) through SecondChair, then read how Foundry realised it and list what needs the GM. Use when running a SecondChair job whose playbook is realise-a-scene.
license: Apache-2.0
compatibility: Needs the SecondChair MCP server (secondchair serve) with the Foundry connector, and read access to the brief file.
metadata:
  secondchair-responsibility: prep
  secondchair-tier: standard
  secondchair-inputs: brief, scene
  secondchair-expected-output: The scene's desired state written with prepare_scene under the key given as the scene input, and its reconciliation report read with scene_report, with every conflict and error listed for the GM.
---

# Realise a scene

You are running a SecondChair job. SecondChair holds the campaign's prep as a **desired state**: what a scene must look like in Foundry. You write that state; the GM's Foundry client realises it by reconciliation whenever it is connected, keeping what was played (a token moved, a door opened, a creature killed) and what the GM retouched by hand. You never act in Foundry directly.

## Language

Write every name and every text a player can see (scene name, token names, note texts) in the **campaign language** of the job contract (`campaign_language`), whatever language this playbook or the brief is written in. Keep proper nouns as the brief spells them.

## The job contract

You were given a job id. If you were not given its contract, the GM asked you to take a queued job: call `start_job` with the job id and the agent host, model and effort you run with, and read the contract it returns. The contract holds:

- `inputs.brief`: the path of the prep brief for this scene (what is in it, where, and why). It is a Source: read it, never copy it or edit it.
- `inputs.scene`: the key of the scene, lowercase words joined by dashes. Keep it: it is how SecondChair finds the scene again.
- `expected_output`: what you must have produced when you finish.

## Steps

1. Read the brief. If `scene_report` with the scene key answers, the scene was prepared before: keep every object key it used for the same object, so reconciliation updates objects instead of replacing them.
2. Build the desired state, in Foundry's own document fields:
   - `scene`: `name`, and what the brief gives of `width`, `height`, `grid` (`{size}`, pixels per square) and `background` (`{src}`, an image path in the Foundry world).
   - `items`: one entry per object, `{key, type, data}`. Pixel positions are the object's top-left corner for tokens and tiles, its centre for lights, sounds and notes.
     - `Token`: `actor` is the UUID of the Actor it is made from, a world Actor or a compendium entry (`Compendium.<pack>.Actor.<id>`); `data` holds at least `x`, `y`, and `hidden: true` for anything the party has not seen, with `name` and `disposition` (-1 hostile, 0 neutral, 1 friendly) when the brief sets them.
     - `AmbientLight`: `x`, `y`, `config` (`bright`, `dim` in grid units, `color`).
     - `Wall`: `c` (`[x0, y0, x1, y1]`), and `door` (1 a door, 2 a secret door) with `ds` (0 closed, 2 locked) for doors.
     - `AmbientSound`: `x`, `y`, `radius`, `path`. `Note`: `x`, `y`, `text`. `Tile`: `x`, `y`, `width`, `height`, `texture` (`{src}`). `Region`: `name`, `shapes`, `behaviors`.
   - Give each item a short, stable key naming what it is (`goblin-boss`, `east-door`), never a number that shifts when an item is added.
3. Call `prepare_scene` with `key` (the scene input), `scene`, `items`, your `agent` name and the `job` id. `applied` means the desired state is written; `pending` means it waits for the GM's approval. An error saying the responsibility is at manual means you may not act: stop and report it. A refusal names what is malformed: fix it and call again.
4. Call `scene_report` with the scene key.
   - `realised: false`: no GM client has connected since; the scene is realised when one does. Say so.
   - `pending: true`: the GM client has not realised this version yet. Call `scene_report` again a few times; if it stays pending, say the scene waits for a GM client.
   - `reason: "ceiling"`: the world's delegation ceiling refused the realisation. Say so: the scene is realised once the GM raises the ceiling in Foundry's module settings.
   - Otherwise read `report`: what each object became (`create`, `update`, `noop`; `retouched` kept as the GM left it; `kept-deleted`, deleted in play and not recreated), each `conflict` (retouched in Foundry and changed in prep) and each error.
5. Never settle a conflict or recreate a deleted object yourself. List them for the GM, with the reason, and the call that settles each: `prepare_scene` again with `choices` mapping the object key (`_scene` for the scene itself) to `keep` (Foundry's version), `overwrite` (the prep's) or `recreate`. Make that call only with the GM's answer.
6. Call `finish_job` with the job id, then reply with the scene's summary, the conflicts and the errors.

Do not place anything the brief does not ask for, and do not move or reveal objects to reflect play: what happens at the table belongs to Foundry, not to the desired state.
