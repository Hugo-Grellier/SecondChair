---
name: propose-consequences
description: Propose the derived consequences of the living world's latest offscreen events (NPCs moving along their agendas, knowledge spreading to NPCs and factions), each citing the facts it uses, through SecondChair. Use when running a SecondChair job whose playbook is propose-consequences.
license: Apache-2.0
compatibility: Needs the SecondChair MCP server (secondchair serve).
metadata:
  secondchair-responsibility: living_world
  secondchair-tier: standard
  secondchair-inputs: occurrences
  secondchair-expected-output: Derived consequences proposed, each citing the facts it uses.
---

# Propose consequences

You are running a SecondChair job. SecondChair keeps the campaign's canon; you act on it only through its MCP tools. A world-turn applied rule effects the GM already wrote (front ticks, agenda steps, expired situations). Only the front's carrier and the named participants know of them. You propose what follows from them: **derived consequences**, which SecondChair records at the agent-proposal rank under the living world's delegation level. Each of your actions may be applied at once, held for the GM's approval, or refused.

## Language

Write every statement and description in the **campaign language** of the job contract (`campaign_language`), whatever language this playbook is written in.

## The job contract

You were given a job id. If you were not given its contract, the GM asked you to take a queued job: call `start_job` with the job id and the agent host, model and effort you run with, and read the contract it returns. `inputs.occurrences` lists the occurrence keys the world-turn just recorded, separated by spaces.

## What a derived consequence is

- An NPC or a faction moving along its agenda because of an event: a fact recorded with `record_fact`, or an offscreen event with `record_event` that closes and opens facts.
- Knowledge spreading to an NPC, a faction or a place: `record_knowledge` for a fact that knower can plausibly have learned from someone who knows it.

Not a consequence, so never yours to propose: a new front or situation, a changed agenda, the death or exit of a named NPC, the deadline of a situation the party engaged in. Those are new narrative, for narrative direction and the GM.

## Steps

1. Call `living_world` and `search_facts` to read the fronts and situations the occurrences touched and the facts they opened.
2. For each consequence that clearly follows from those facts, record it with origin `{"kind": "job", "job": "<job id>"}` and pass `job` to the action. Know the ids of the facts it derives from, and propose nothing canon does not support: a knower learns only a fact an event opened or a fact someone it deals with already knows.
3. Never make the party know anything: the living world never discloses, and SecondChair refuses a `record_knowledge` whose knower is `party`. What reaches the party goes through disclosure.
4. Read each result. `applied` and `pending` are fine; an error saying the responsibility is at manual means you may not act: stop and report it.
5. Call `finish_job` with the job id, then reply with the consequences proposed, applied, pending and refused, each with the fact ids it cites.

Proposing nothing is a valid outcome when nothing clearly follows.
