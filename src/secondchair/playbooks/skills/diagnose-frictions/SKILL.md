---
name: diagnose-frictions
description: Read a SecondChair friction report (frictions/<seq>.md) and propose delegation table changes that would take the GM's frictions and manual acts off the GM, at propose only. Use when the GM asks for a friction diagnosis, or when running a SecondChair job whose playbook is diagnose-frictions.
license: AGPL-3.0-only
compatibility: Needs read access to the campaign workspace; the SecondChair MCP server (secondchair serve) only when run as a job.
metadata:
  secondchair-responsibility: vtt_operations
  secondchair-tier: standard
  secondchair-inputs: report
  secondchair-expected-output: Proposed delegation table changes, each citing the frictions behind it, for the GM to apply or not.
---

# Diagnose frictions

You read one moment's friction report and **propose** delegation table changes. You change nothing: you never edit `delegation.yaml`, never add or remove an entity override, never approve anything. The GM decides, and edits the table themselves (TRC-06, DEL-06). Write your reply in the **campaign language** of the job contract (`campaign_language`), or of `workspace.yaml` when you run outside a job.

## Inputs

- `report`: the friction report's path, `frictions/<seq>.md` in the campaign workspace. When the GM names a moment instead, it is the file of that moment's `seq` on six digits. If it does not exist, say that the GM can write it with `secondchair frictions <seq>`, and stop.
- If you were given a job id without its contract, call `start_job` with the job id and the agent host, model and effort you run with.

## Steps

1. Read the report. Its front matter holds the moment, `gm_effort` (interactions with SecondChair, manual acts in the VTT, GM frictions), `table_friction` and every friction with its `id`, `detector`, user, `role` and trace span.
2. Read `delegation.yaml` in the same workspace: the current level of each responsibility in the report's moment.
3. Group the **GM** frictions and manual acts by the responsibility that would take them over (DEL-01): rules lookups, long GM-creature turns and dead time in the GM's turn under rules and combat; hunting through sheets and manual corrections under VTT operations, or under rules and combat when they happen in combat turns. Player frictions are table friction: never propose a delegation change from them alone; mention them only as context.
4. For each group worth acting on, propose one cell change: moment, responsibility, current level, proposed level, and the friction ids it rests on. Propose one step looser at most. Never propose narrative direction above propose (DEL-08), never propose lifting the irreversible hold (DEL-09a), and never propose autonomous: it needs the GM's deliberate gesture inside Foundry too (DEL-19a).
5. Reply with the proposals as a list, most frictions first, then one line on table friction. If nothing is worth changing, say so. If you run as a job, call `finish_job` with the job id last.
