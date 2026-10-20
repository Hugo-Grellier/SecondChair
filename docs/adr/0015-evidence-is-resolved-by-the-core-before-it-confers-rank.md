# Evidence is resolved by the Core before it confers a rank

Status: proposed — awaiting the GM ([#168](https://github.com/Hugo-Grellier/SecondChair/issues/168))

A fact's rank comes from its origin (ADR 0007, CAN-06..08), and today `rank_of` only checks the origin's shape. Any caller of `record_fact`, `record_event` or `record_knowledge` can write `{kind: observation, quote, locator}` with made-up strings and get **played**, or `{kind: source, source, page}` and get **cited_source**. Three paths already check their evidence: capture finds the quote in the job's Source or transcript segment (CAP-04), knowledge resolves an `observations/…#id` locator and its visibility (ARC-16), and a disclosure's locator is an action log entry the Core wrote itself (CAN-17). Every other path trusts the caller. Provenance is a trust boundary, so the decision is where rank-conferring evidence gets checked and what happens when it fails.

We propose that **a rank above agent_proposal is admitted only on evidence the Core resolved itself, in one admission step shared by every write path**. The caller names evidence, and the Core looks it up. The caller never states a rank.

| Origin | Admitted at its rank when the Core… | Otherwise |
|---|---|---|
| `observation`, locator `observations/<session>.jsonl#<id>` | finds the observation, and the quote is in it; for knowledge, its visibility allows it | refused |
| `observation`, locator `<file>:<line>` | finds the file among the Sources of the job the action runs under, and the quote at that line or transcript segment | refused |
| `observation`, locator `action-log/<n>.yaml` | is itself writing it, for a disclosure | refused to every caller |
| `source` | finds the Source registered in the reference library with its permission, and the page in its index; when the origin carries an `excerpt`, finds it on that page | refused when it is unknown; agent_proposal when it is registered but not indexed (a book only on the shelf), until the GM confirms it |
| `gm` | is in an authenticated Surface gesture (`confirm`, DEL-29) | agent_proposal, as today |
| `rule` | is the world-turn | refused, as today |
| `job` | needs nothing | agent_proposal |

## Questions settled

- **(a) Refuse or demote a forged origin?** Refuse with a `CanonError` that names the missing evidence. A silent demotion hides the bug in the agent or playbook, and the agent can still record the fact honestly as a `job` origin.
- **(b) Evidence apart from authority.** An origin keeps its pointer (`quote`, `locator`, `page`, `excerpt`) as evidence. Only the kind, checked as above, carries authority. A `job` origin may carry the same pointers as supporting evidence without being raised (#167).
- **(c) Evidence that changes after admission.** It is checked once, at admission. The quote is stored verbatim, so the record stands even if its Source is later edited or lost. Rebuilding the index does not check again. A `secondchair doctor` check can re-resolve evidence and report what no longer resolves, but it never changes a rank.
- **(d) Imports and the GM's own edits.** A bible or import job writes `job` origins, or `source` ones that resolve against the library. A hand edit to canon Markdown is the GM's act, logged as one (`log_hand_edits`), and keeps its declared origin, because the workspace is the GM's. Whether anything else with disk access must be told apart from the GM is the same question as [#163](https://github.com/Hugo-Grellier/SecondChair/issues/163), and it is settled there.

## Considered Options

- **Check in each tool (status quo, extended)**: rejected. The checks drift apart, which is how direct `record_fact` was left open.
- **Signed observations (an HMAC on each observation line)**: not needed. The Core resolves the locator against its own append-only files. A signature only helps once the files leave the Core's machine.
- **Demote instead of refusing**: rejected, see (a).

## Consequences

- One `admit(ws, origin, context)` in the Core, called by `canon`, `knowledge`, `capture` and `world` before `rank_of`. `rank_of` stays a pure mapping. The context is the job, its Sources, the Surface's authentication and whether the caller is the Core itself.
- An agent outside a job cannot write an `observation` with a file locator, because it has no Sources. It can quote VTT observations by id.
- The `source` origin gains an optional `excerpt`. The library's index already holds page text.
- Tests: a forged file locator, a nonexistent observation id, a quote not in its observation, a spoofed `action-log/` locator, an unknown Source, a Source edited after admission (the record stands, doctor reports it), legitimate capture, disclosure and import paths keeping their ranks, and authenticated confirmation.
