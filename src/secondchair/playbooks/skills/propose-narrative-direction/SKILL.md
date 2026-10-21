---
name: propose-narrative-direction
description: Propose what happens when a situation the party engaged in reaches its deadline, or what follows from an unexpected action the party took in play, as new narrative held for the GM's approval, through SecondChair. Use when running a SecondChair job whose playbook is propose-narrative-direction.
license: Apache-2.0
compatibility: Needs the SecondChair MCP server (secondchair serve).
metadata:
  secondchair-responsibility: narrative_direction
  secondchair-tier: deep
  secondchair-writes: "true"
  secondchair-inputs: observation?, occurrence?
  secondchair-expected-output: A narrative-direction proposal for the deadline.
---

# Propose narrative direction

You are running a SecondChair job. SecondChair keeps the campaign's canon; you act on it only through its MCP tools. The world-turn reached the deadline of a situation the party engaged in. What happens then is **new narrative**: it belongs to the GM. You only propose it. Every action you take for this job is a narrative-direction action, which SecondChair always holds for the GM's approval, whatever the delegation table says.

## Language

Write every statement and description in the **campaign language** of the job contract (`campaign_language`), whatever language this playbook is written in.

## The job contract

You were given a job id. If you were not given its contract, the GM asked you to take a queued job: call `start_job` with the job id and the agent host, model and effort you run with, and read the contract it returns. Exactly one input is given:

- `inputs.occurrence` is the key of the queued deadline, `<situation>/deadline@<date>`.
- `inputs.observation` is the id of an **observed played fact**: something the party did that the campaign did not plan. The world-turn queues no job for it; the GM does.

## Steps

1. Call `living_world` and find the occurrence in `queued`: its situation (`entity`) and its `date`.
2. Call `search_facts` about the situation and its participants, at the deadline's date, to know where it stands.
3. Propose one outcome consistent with canon: an offscreen event with `record_event` dated on the deadline, closing the situation's state fact and opening the facts it leads to (record them first with `record_fact`). Use origin `{"kind": "job", "job": "<job id>"}` and pass `job` to every action. Each comes back `pending`: that is expected. SecondChair links them to the deadline: once the GM approves one, the deadline is applied and leaves the queue.
   **From an observation**: call `search_facts` for the fact and what surrounds it, and read `living_world` for the fronts and situations it touches. Refuse an observation that is not a played fact. Propose one **new situation** it opens: create its entity (`create_entity`) and record its facts (`record_fact`, origin `{"kind": "job", "job": "<job id>"}`, `job` on every action) with stakes, interested parties and a deadline or a clock. Do not close or change an existing fact on the strength of the observation alone. Every action comes back `pending`: new narrative is the GM's, and nothing is applied until they approve.
4. Never make the party know anything: what reaches the party goes through disclosure.
5. Call `finish_job` with the job id, then reply with your proposal and the pending entries, so the GM can approve, edit or reject them.
