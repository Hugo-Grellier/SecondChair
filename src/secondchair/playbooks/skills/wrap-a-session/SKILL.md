---
name: wrap-a-session
description: Wrap a played session into canon from its Sources (the GM's session notes, the session transcript), as candidate facts that quote the Source verbatim, through SecondChair. Use when running a SecondChair job whose playbook is wrap-a-session.
license: Apache-2.0
compatibility: Needs the SecondChair MCP server (secondchair serve) and read access to the session's Sources.
metadata:
  secondchair-responsibility: memory
  secondchair-tier: standard
  secondchair-inputs: session, notes?, transcript?
  secondchair-expected-output: Every played statement of the session's Sources captured as a candidate fact quoting its Source verbatim, classified against canon, and consolidated by the Core.
---

# Wrap a session

You are running a SecondChair job. SecondChair keeps the campaign's canon; you act on it only through its MCP tools. Its delegation table decides what each of your actions does: applied at once, held for the GM's approval, or refused. The wrap runs between sessions: never ask the GM anything while you work. Questions are held for the GM's grouped round.

## Language

Write every statement in the **campaign language** of the job contract (`campaign_language`). Quotes stay in the Source's own language, exactly as written; when the Source is in another language, add a `translation` of the quote into the campaign language.

## The job contract

You were given a job id. If you were not given its contract, call `start_job` with the job id and the agent host, model and effort you run with, and read the contract it returns:

- `inputs.session`: the session id.
- `inputs.notes`: the path of the GM's notes for the session, a Source: read it, never copy or edit it.
- `inputs.transcript`: the path of the session transcript, a Source read the same way (see "The transcript" below).
- Without notes or a transcript, there is nothing to capture: call `finish_job` and say so.
- `vocabulary`: the names canon already knows.

## The transcript

The transcript is JSON Lines: one segment per line, `{"speaker", "start", "end", "text"}`, in order of `start` (seconds into the recording). `speaker` is a Discord user; the campaign's speaker table, `speakers.yaml` in the campaign workspace, maps each one to its `player`, its `pc`, and marks the GM's track (`gm: true`).

- The GM's track carries the narration and every NPC's voice: what the GM describes or an NPC says happened in the fiction, and the party saw or heard it (`known_by: "party"`).
- A player speaks in character (their PC acts or speaks: a played statement about that PC) or out of character. Drop table talk, rules and dice chatter, jokes, and planning that never became an action.
- Read segments in sequence: one statement often spans several segments, and a player's declared action is played only once the GM's narration confirms or resolves it.
- Transcription mishears names. Match a misheard name to canon's spelling with the job's `vocabulary` and write canon's spelling in the `statement`; when you are not sure it is that entity, classify the candidate `non_blocking_ambiguity` and say which name you matched. The quote keeps the words as transcribed.

When the job has both notes and a transcript, they tell the same session twice: capture each played statement once, from the Source that states it most clearly, and do not submit the other as a second candidate. Where they disagree on what happened, the notes win over the transcript: submit the transcript's version as a `contradiction` with a `reason` naming the notes' line.

## Steps

1. Read each Source whole. Note the session's fictional interval if one states it, and call `report_session_interval` with its start, end and the words that state it (from the transcript, with the segment's `locator` too).
2. Keep only what was said or done in the fiction at the table. Drop out-of-character chatter, recaps of earlier sessions, and speculation nobody established: never submit them.
3. Find each entity in canon with `search_entities`, and what canon already holds with `search_facts` and `what_knows`.
4. For each played statement, call `capture_candidate` with:
   - `job`, `source` (the Source's path, as given), `locator` (`<file>:<line>`, or a notes line's label) and `quote`: the Source's exact words, copied character for character. In the transcript, the line is the segment's line in the file (the first segment is line 1) and the quote is that segment's `text`, or an exact part of it, as decoded text (not the JSON escapes); the Core records the segment's speaker. A candidate whose quote is not in the Source is dropped;
   - `statement`: what is now true, in the campaign language, using canon's spelling of every name;
   - `date`: the campaign date it happened, the session end unless the Source dates it. When neither the Sources nor canon date the session, use the campaign's current date (`living_world`), and never classify a candidate as an ambiguity for the date alone: the GM settles the session's interval once, with `secondchair wrap <session> --start … --end …`. Say so once in your reply;
   - `entities`: the canon ids it is about; a name canon does not know goes in `new_names` instead, spelt as the Source spells it. Never put a known name in `new_names`;
   - `known_by`: `"party"` for what the table saw or heard, and the ids of the NPCs or factions who saw it or were told;
   - `closes`: the ids of facts this played event ends, if any;
   - `classification` against canon, with a `reason` for the GM whenever it is not `certain`:
     - `certain`: new, and consistent with canon;
     - `duplicate`: canon already holds it; name the fact in `duplicate_of` (its `known_by` still records who learned it);
     - `contradiction`: it contradicts earlier play or a higher-ranked fact. Never resolve a contradiction yourself;
     - `blocking_ambiguity`: you cannot record it without the GM's answer (who, what or when is unclear);
     - `non_blocking_ambiguity`: recordable as it stands, but worth the GM's look;
   - `inferred: true` when the statement says more than the quote.
   Several facts from one line may share its quote. A rerun returns `seen` for what is already captured: that is fine.
5. Call `consolidate_candidates` with the job id and read each outcome: `applied`, `duplicate`, `pending` (held by the table for the GM), `held` (a question for the GM's round), `unattested` (a new name only one candidate attests: no entity yet) or `failed` (report its error).
6. Call `finish_job` with the job id, then reply with the counts by outcome and the questions held for the GM, contradictions first. The GM answers them and settles the session with `secondchair wrap <session>`.
