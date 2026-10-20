---
name: diagnose-frictions
description: Read a moment's friction report and propose delegation table changes to the GM, without making any. Use when the GM asks for a friction diagnosis, or when running a SecondChair job whose playbook is diagnose-frictions.
license: Apache-2.0
compatibility: Needs the SecondChair MCP server (secondchair serve) and read access to the campaign workspace's friction reports.
metadata:
  secondchair-responsibility: prep
  secondchair-tier: standard
  secondchair-inputs: report
  secondchair-expected-output: Proposed delegation table changes, each citing the frictions behind it, for the GM to apply or not.
---

# Diagnose frictions

The GM asked for a diagnosis, on demand. A friction report says where operating the VTT cost the GM or the players effort in one moment. You read it and **propose** delegation table changes. You propose only: you never change the delegation table, an override or a hold, and you take no delegated action. The GM decides and applies what they accept.

## Language

Write your proposal in the **campaign language** of the job contract (`campaign_language`), or the language the GM spoke to you in, whatever language this playbook is written in.

## The report

If you run a job and were not given its contract, call `start_job` with the job id and the agent host, model and effort you run with, and read the contract it returns. `inputs.report` is the path of the friction report: `frictions/<moment seq>.md` in the campaign workspace. Outside a job, the GM names the moment or the file. Read the whole file. Its front matter holds:

- `moment` and `seq`: the moment the report covers (prep, live-session or between-sessions);
- `gm_effort`: `interactions` (GM interactions with SecondChair: approvals, rejections, edits, undos, answers, overrides) and `manual_acts` (the GM's acts in the VTT, read from their behaviour traces);
- `frictions`: each with its `detector`, the `user` and `name` it belongs to, `gm` (true for the GM's), and `from`, `to`: the trace span it cites;
- `table_friction`: how many frictions the players had. Table friction is never part of GM effort;
- `gaps`: traces lost with no GM client to relay them. A gap means the report is incomplete for that user and span: say so, and do not read silence as the absence of friction.

The detectors are a closed list. For the GM: `rules-lookup` (in live play), `hunting` (windows opened and closed with no action), `long-gm-creature-turn`, `manual-correction` (an undo, cancelled move or re-roll) and `dead-time` (no input in the GM's own turn). For a player: `long-turn`, `hunting`, `cancelled-roll-dialog`, `rage-clicks`, `click-on-nothing`, `late-targeting`, `rules-lookup` and `stumbling-input`.

## Steps

1. Group the frictions by detector and by user. Note how much of GM effort is manual acts, and which GM frictions repeat.
2. Map each pattern to the responsibility it points at ([03 — Delegation](https://github.com/Hugo-Grellier/SecondChair/blob/main/docs/spec/03-delegation.md)): GM-creature turns, manual corrections and rules lookups in live play point at rules and combat; hunting and dead time often point at VTT operations or NPCs; many interactions for few manual acts may mean a responsibility is held too low and asks the GM too often. Player frictions point at the table's ease with the VTT: a delegation change may help (for example, VTT operations preparing what players look for) or may not; say which.
3. For each change you propose, give: the moment column, the responsibility, the current level and the proposed one (`manual`, `propose`, `act-then-review` or `autonomous`), or an entity override, a deadline mode or an irreversible hold, and the frictions it answers, cited by detector, user and span. Never propose raising narrative direction above propose, nor lifting an irreversible hold: those stay with the GM.
4. If nothing in the report calls for a change, say so. A proposal with no friction behind it is not one.
5. If you run a job, call `finish_job` with the job id. Then reply with your proposals. The GM applies the ones they accept by editing `delegation.yaml` or with `secondchair override` and `secondchair hold`.
