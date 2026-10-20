---
name: answer-probes
description: Answer probes, questions on a campaign's canon in the GM view, with structured answers in workspace entity ids, reading canon through SecondChair. Use when running a SecondChair job whose playbook is answer-probes.
license: Apache-2.0
compatibility: Needs the SecondChair MCP server (secondchair serve) and read access to the probes file.
metadata:
  secondchair-responsibility: memory
  secondchair-tier: standard
  secondchair-inputs: probes
  secondchair-expected-output: One JSON object, the whole final reply, mapping each probe id to its structured answer in workspace entity ids.
---

# Answer probes

You are running a SecondChair job. SecondChair keeps the campaign's canon; you read it only through its MCP tools. Each probe is a question with an expected structured answer, used to check that canon holds what it should. You answer in the GM view: everything canon records, secrets included.

## Language

Canon is written in the **campaign language** of the job contract (`campaign_language`), whatever language this playbook is written in. Read it in that language; write names exactly as canon spells them.

## The job contract

You were given a job id. If you were not given its contract, the GM asked you to take a queued job: call `start_job` with the job id and the agent host, model and effort you run with, and read the contract it returns. `inputs.probes` is the path of a YAML file: one entry per probe id, with its `question` and the shape of its `answer`.

## Steps

1. Read the probes file.
2. For each probe, find the answer in canon with the reads: `search_entities`, `search_facts` (by text, entity, relation or date), `search_events`, `what_knows`, `living_world`, `check_mystery`. Answer from canon only, never from what you would expect: what canon does not hold, you do not know.
3. Shape each answer as the probe's `answer` says. Name every entity by its workspace entity id (`e-…`), never by its name, unless the shape asks for a name or a label. Use `null` for what canon says does not exist.
4. Take no action: never create, record or correct anything.
5. Call `finish_job` with the job id, then reply with **only** one JSON object mapping each probe id to its answer, with no text around it. Leave out a probe canon does not answer.
