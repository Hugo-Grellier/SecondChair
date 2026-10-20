---
name: settle-an-unless
description: Settle whether a front's unless condition held on a queued tick's date, citing canon fact ids, through SecondChair. Use when running a SecondChair job whose playbook is settle-an-unless.
license: Apache-2.0
compatibility: Needs the SecondChair MCP server (secondchair serve).
metadata:
  secondchair-responsibility: living_world
  secondchair-tier: standard
  secondchair-inputs: occurrence
  secondchair-expected-output: The unless settled with settle_unless, citing fact ids.
---

# Settle an unless

You are running a SecondChair job. SecondChair keeps the campaign's canon; you act on it only through its MCP tools. The world-turn queued one tick of a front whose rule carries an `unless` condition: the tick happens only if the condition did **not** hold on the tick's date. You decide that from canon, and only from canon.

## Language

Canon is written in the **campaign language** of the job contract (`campaign_language`), whatever language this playbook is written in. Read the condition and the facts in that language.

## The job contract

You were given a job id. If you were not given its contract, the GM asked you to take a queued job: call `start_job` with the job id and the agent host, model and effort you run with, and read the contract it returns. `inputs.occurrence` is the key of the queued tick, `<front>/tick@<date>`.

## Steps

1. Call `living_world` and find the occurrence in `queued`: its front (`entity`) and its `date`.
2. Call `search_facts` with `entity` set to the front to read its `front` state fact: the `unless` condition is in its value.
3. Call `search_facts` with `at` set to the tick's date, with words from the condition, to find the facts valid on that date that say whether the condition held.
4. Call `settle_unless` with the occurrence key, your job id and:
   - `unless_holds: true` and the ids of the facts showing the condition held: the tick does not happen;
   - `unless_holds: false` and the ids of the facts showing it did not hold: the tick applies, as an agent proposal;
   - `unless_holds: null` and no ids when canon does not settle it. The GM is then asked at the next break and the tick waits. **Never guess**: a condition no valid fact settles is unsettled.
5. Call `finish_job` with the job id, then reply with the answer and the fact ids you cited.

Never record a fact to settle the condition yourself, and never tell the party anything: the living world never discloses.
