---
name: propose-opportunities
description: After a wrapped session, propose a short list of optional dramatic opportunities for the next sessions, each citing the played facts that justify it, as a draft note the GM adopts or rejects, through SecondChair. Use when the GM asks what their players' choices open up, or for opportunities after a wrap.
license: Apache-2.0
compatibility: Needs the SecondChair MCP server (secondchair serve). Layered on the campaign-workshop skill.
metadata:
  secondchair-responsibility: prep
  secondchair-tier: standard
  secondchair-inputs: session
  secondchair-expected-output: The session's opportunities written as a draft note at notes/opportunities/session-<session>.md (never canon), and a summary of the opportunities, the signals they rest on and the open questions.
---

# Propose opportunities

You turn what the table played into a short list of **optional** next-session opportunities for the GM. This skill **adds to** the `campaign-workshop` protocol and never replaces it. The GM decides everything creative. You run only when the GM asks, after the session is wrapped; nothing queues you.

An opportunity is a possibility, not a plot: a promise kept or broken, a relationship strained, a hook consumed, a door the party opened, a thread left loose. You never decide what a PC does or feels, and you never decide an ending.

## Language

Write the note in the **campaign language** (`campaign_language` of `workspace.yaml`), whatever language this playbook is written in.

## Inputs

`session`: the number of a wrapped session. Without a job, take the number the GM gives, or the last wrapped one (`moment.yaml`). Refuse a session that is not wrapped: its played facts are not in canon yet.

## What you read

1. **Played facts** of the session: `search_facts` at the played rank, with the quote and locator each carries. This is your only evidence of what happened.
2. **Adopted notes**: the notes under `notes/` whose front matter (ADR 0017) has `status: adopted`, and the opportunity notes of earlier sessions (adopted, rejected or still draft). Skip `rejected` and `superseded` ones except to avoid proposing again what the GM refused.
3. **NPC dossiers**, when present: `notes/npcs/<entity id>.md`, in particular their change triggers.
4. **Deterministic signals**: call `session_signals(session)` once and use only what it returns, recomputing nothing:
   - `unused_prep`: the handoff's clue ids that no played fact of the session found, with the open `check_mystery` warnings of their mysteries.
   - `spotlight`: how many played facts concern each PC this session. A PC with few is a prompt to offer them a hook, never a verdict.
   - `fulfilled_triggers`: the dossier change triggers (`triggers:` in the front matter) whose cited facts now all hold in canon.

You apply no judgement of your own to decide that a beat is due, that foreshadowing was contradicted or that a faction repeats itself. If the GM wants that, they ask in conversation.

## No destiny engine

World state moves only by the world-turn and the rules the GM wrote. You never advance an arc because a beat seems due. An abandoned hook or a missed clue changes nothing unless a front's rules say so; say that, rather than treating it as pressure. Never write an opportunity as something that will happen: write what the table could pick up.

## The note

Write `notes/opportunities/session-<n>.md` (the GM's Git history keeps earlier versions; read it first if it exists and keep the GM's edits), with this front matter:

```yaml
id: d-<8 hex>          # new, never reused
status: draft          # always draft: only the GM adopts or rejects
cites: [f-...]         # every played fact id cited below; each must resolve in canon
```

The body is a list of opportunities, at most five, each with:

- a one-line title and 2 to 4 sentences of what could happen;
- **Because**: the played fact ids that justify it, with a short quote (no opportunity without at least one);
- **Touches**: the ids of the notes (dossiers, adopted pitches) it concerns, when any;
- **For**: the PCs it concerns, by name; offer each PC's player a way in, never a decision;
- **Signal**: which deterministic signal raised it (unused prep, spotlight, a fulfilled change trigger), when one did;
- **Cost of ignoring it**: "nothing changes" unless a front's rules say otherwise.

Sections for the GM only. A secret an opportunity relies on stays a canon fact the party does not know; point to it by id and never restate it in text players will read.

## Boundaries

- Nothing enters canon from this note. Never call `record_fact` or `record_knowledge` for an opportunity. A setting truth the GM states goes through the workshop's confirmation steps.
- A new front, situation or arc is new narrative: propose it in the note as a pitch and let the GM take it through `propose-narrative-direction`, which stays at *propose*. When you do propose a new arc, tell the GM it is better run on the `deep` tier and let them choose.
- You do not edit another note. Adopting or rejecting is the GM's gesture on this note's `status`; `prepare-a-session` then reads adopted opportunities as ideas to weave in, never as events.

Report the file actually written, the opportunities with the facts they cite, the signals that were unavailable, and the open questions. Claim the note is saved only after the write succeeded.
