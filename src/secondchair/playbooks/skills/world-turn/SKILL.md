---
name: world-turn
description: Advance a campaign's living world to its current date after a wrap, through SecondChair's deterministic world-turn. Use when running a SecondChair job whose playbook is world-turn.
license: Apache-2.0
compatibility: Needs the SecondChair MCP server (secondchair serve).
metadata:
  secondchair-responsibility: living_world
  secondchair-tier: fast
  secondchair-inputs: until, since?
  secondchair-expected-output: The world-turn run up to the job's until date, its occurrences reported.
---

# World-turn

You are running a SecondChair job. The world-turn is the Core's own deterministic computation: you start it, you never compute or invent its effects. Report in the **campaign language** of the job contract (`campaign_language`).

1. If you were not given the job's contract, call `start_job` with the job id and the agent host, model and effort you run with.
2. Call `run_world_turn` with the job id. It advances the world to `inputs.until` and returns the occurrences it recorded: rule effects applied or held for the GM, and the jobs it queued for `unless` conditions, narrative deadlines and consequences. If it refuses (a live session is open, living world is at manual), report the message and stop.
3. Call `finish_job` with the job id, then reply with the count of occurrences by status and the jobs queued. Do not start those jobs yourself.
