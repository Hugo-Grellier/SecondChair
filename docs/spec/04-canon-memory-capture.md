# 04 — Canon, memory and capture

Decisions: [ADR 0007](../adr/0007-facts-are-the-unit-of-canon.md), [ADR 0008](../adr/0008-capture-cited-facts-rank-as-played.md), [ADR 0012](../adr/0012-behaviour-traces-capture-raw-input-with-consent.md); tickets [#13](https://github.com/Hugo-Grellier/SecondChair/issues/13), [#14](https://github.com/Hugo-Grellier/SecondChair/issues/14), [#16](https://github.com/Hugo-Grellier/SecondChair/issues/16), [#17](https://github.com/Hugo-Grellier/SecondChair/issues/17), [#23](https://github.com/Hugo-Grellier/SecondChair/issues/23).

## Canon model

- **CAN-01** The **fact** is the unit of canon: one statement about one or more entities, written in the campaign language, with an optional typed **relation**, a validity in fictional time, its provenance and its authority rank.
- **CAN-02** An **entity** carries only identity: a stable id, its names and aliases, an optional **kind** (pc, npc, faction, place, item or other; an entity without one stays valid until the kind is set), an optional **official reference**, and a player-facing description with no truth value. The GM's truth about it (agenda, secrets, deceptions) is facts the party does not know.
- **CAN-03** Relation types come from a closed Core list (member of, lives in, owns, knows, …) that a System extension can extend.
- **CAN-04** Facts are **bitemporal**:
  - fictional validity from a start date to an optional end, empty while the fact holds; dates are campaign-calendar dates, partial (`year-month`, `year`) allowed ([05](05-living-world-calendar.md));
  - record time is real time: the session and the action log entry that admitted it.
- **CAN-05** **Events** (played or offscreen) open and close facts. An evolution is an event that closes the old fact and opens a new one. A **correction** rewrites a wrongly recorded fact with no event, when nothing played is contradicted. A **retcon** is a GM decision recorded as an event that replaces an earlier one, which stays on record. Nothing is deleted. The v3 test applies: "could a player remember the old version?"
- **CAN-06** **Authority ranks**, highest first: played, GM decision, cited official source, agent proposal.
- **CAN-07** Provenance holds the rank, the origin (an observation with a verbatim quote, the GM's words, a Source with page, or a job) and the admitting action log entry.
- **CAN-08** An approved agent proposal keeps the agent-proposal rank. Only play or a GM decision in the GM's own words ranks higher.
- **CAN-09** A **decision** records a creative call with the GM's own words. Entering canon at the GM-decision rank requires an authenticated Surface ([03](03-delegation.md), DEL-29).

## Storage

- **CAN-10** Markdown + YAML in the campaign workspace is the source of truth. A SQLite index is derived from it and rebuildable, kept in the git-ignored `.secondchair/` ([ADR 0010](../adr/0010-local-core-reached-by-the-gm-browser.md)).
- **CAN-11** A hand edit of the workspace bypasses the Core. The Core detects it when it rebuilds the index and logs it at the agent-proposal rank. The GM promotes it to a GM decision in one gesture on an authenticated Surface.
- **CAN-12** Search is structured plus full text. No embeddings in v4; the derived index leaves room for a job to compute them later.

## Knowledge

- **CAN-13** **Knowers** are the party as a whole, each NPC and each faction. Individual PCs are not knowers: knowledge recorded for an entity of kind pc is refused.
- **CAN-14** A knower knows, believes or suspects a fact, with when it learned it (fictional date and event). The model is closed-world, plus inheritance from the knower's factions and the **common knowledge** of the places it lives in.
- **CAN-15** A **belief** is a fact recorded as never true, which a knower believes.
- **CAN-16** Content written for an audience (an NPC line in an acting cue, a disclosure, an entity description) MUST cite the ids of the facts it uses. The Core refuses it if the audience does not know a cited fact, refuses unknown ids, and scans it for forbidden strings (secret names, canaries). Paraphrased leaks are not blocked; the test bench measures them. A disclosure is the exception: its cited facts teach the party (CAN-17), so the party need not know them beforehand. No knower bounds a disclosure the GM authored: its cited facts MUST exist in canon, be true and carry no canary, and the GM's authenticated approval (or a lifted hold, DEL-09a) is the gate. When an NPC (the acting entity) discloses, it MUST know every fact it cites.
- **CAN-17** A disclosure marks the facts it cites as known by the party, with the fictional date and the session. A whisper to one player does not: its cited facts become calls held for the wrap (CAP-08; GM decision, [#118](https://github.com/Hugo-Grellier/SecondChair/issues/118)).

## Campaign language and names ([#16](https://github.com/Hugo-Grellier/SecondChair/issues/16), [#17](https://github.com/Hugo-Grellier/SecondChair/issues/17))

- **CAN-18** One **campaign language** per campaign (BCP 47 tag), set at creation in the workspace configuration and fixed for v4. Facts, acting cues, GM notes and disclosures are written in it.
- **CAN-19** An **official reference** is the stable English key the System extension provides (PF2e: `system.slug`, falling back to `flags.babele.originalName`, plus the pack on collision). The Core stores the key, never the translation.
- **CAN-20** The translated name is read at runtime from the GM's install and offered as the entity's name when it is created. The connector strips the bilingual suffix of pf2-fr's `vf-vo` display mode. `doc.name` is a label, never a key.
- **CAN-21** The system adapter declares, per campaign language, the official translation module it requires (PF2e + `fr` → `pf2-fr`); the connector refuses to start without it, with a clear message. Where an entry has no translation, or the language has no module, the name comes from an agent proposal (at propose) or a GM choice. An official name is never machine-translated silently.
- **CAN-22** The **campaign vocabulary** is derived from the names and aliases of the campaign's entities. There is no other proper-noun store. It feeds jobs and the transcription engine.
- **CAN-23** The Core holds any job output containing a near-miss of a known name (close but not exact) as a blocking question at the wrap. Language drift is not blocked; the bench measures it.

## Capture

- **CAP-01** **Transcription** is a CLI step outside the Core's MCP server: WhisperX by default, any engine producing the transcript format accepted. The format is timestamped per speaker and accepts a live stream of segments, so live audio capture can be added later. The campaign vocabulary is fed to the engine as hotwords.
- **CAP-02** A per-campaign speaker table maps Discord user → player → PC, and marks the GM's track. Single-track diarization is out of v4: capture needs per-speaker tracks or an already attributed transcript.
- **CAP-03** VTT observations are recorded live by the connector (durable capture) and consolidated only at the wrap.
- **CAP-04** **Capture** turns Sources (voice transcripts, observations, the GM's optional notes) into **candidate facts**. A candidate MUST quote its Source verbatim, in the Source's language, with a locator (file and timestamp, or page). No quote, no fact. A translation into the campaign language is an optional extra field, shown by default when the Source is in another language; a translated quote alone is never accepted.
- **CAP-05** A candidate whose quote is what was said or done at the table enters canon at the **played** rank, with the observation and quote as origin. Anything inferred beyond the quote stays at agent proposal.
- **CAP-06** Candidates are keyed by Source and quoted span, so a rerun yields only what is new.
- **CAP-07** Out-of-character chatter is dropped and never logged as a fact.
- **CAP-08** What is said or shown to the table marks the fact as known by the party. A whisper or a blind roll becomes a call held for the wrap.

### Jobs and tiers

| Step | Kind | Tier |
|---|---|---|
| Voice / VTT alignment, scene split | Deterministic | — |
| Extraction, per ~20 min slice | Job | standard |
| Name resolution | Deterministic lookup, then job | fast |
| Consolidation against canon | Job | deep |
| Recap (players and GM) | Job | standard |
| Mechanics (XP awarded, items transferred) | Deterministic extractors of the System extension | — |

S3 emits the cheapest passing mapping ([10](10-success-bench.md)).

## Wrap

- **CAP-09** The **wrap** runs between sessions only, so capture never calls on the GM during play. The Core queues the "wrap a session" job when the live session ends; a runner starts it or it waits for the GM.
- **CAP-10** Classification of candidates:
  - *certain*: applied at the memory level for between sessions;
  - *duplicate*: adds provenance, not a fact;
  - *contradiction* (with earlier play or a higher rank) and *blocking ambiguity*: always a call on the GM, whatever the memory level. An agent never resolves a contradiction;
  - *non-blocking ambiguity*: applied and flagged.
- **CAP-11** Source precedence: the VTT wins on mechanics, voice on narrative, the GM's notes over the transcript. A narrative divergence is a contradiction. Mechanics come from voice only where the VTT is silent, and then at agent proposal.
- **CAP-12** Entity creation: an unknown name becomes an entity only when attested twice consistently or confirmed by the VTT. A fuzzy or phonetic match with a known entity or VTT name is a blocking question, never a creation. A single attestation stays flagged.
- **CAP-13** Validation is **one grouped round** in conversation or the CLI (not the Director's Desk): contradictions and blocking ambiguities first, then a summary of what was applied, undoable per item. Items entering canon at the GM-decision rank are confirmed on an authenticated Surface (DEL-29).
- **CAP-14** The wrap also settles the session's fictional interval ([05](05-living-world-calendar.md)). After it, the current date advances to the session end and a world-turn job is queued under living world.

## Privacy of Sources

- **CAP-15** Raw audio and full transcripts are Sources outside the campaign workspace, referenced by id and hash, never copied. The workspace keeps only the short quotes attached to facts and the speaker table (amendment of [#18](https://github.com/Hugo-Grellier/SecondChair/issues/18), see [README](README.md#amendments-settled-while-writing-this-spec-gm-2026-10-19)).

## Behaviour traces ([ADR 0012](../adr/0012-behaviour-traces-capture-raw-input-with-consent.md))

Behaviour traces measure how users operate the VTT. They say nothing about the fiction: never canon, never a source of candidate facts.

- **TRC-01** Each user (the GM, each player) opts in individually in the Foundry module. Consent is off by default, revocable, and filtered in that user's own client: nothing is emitted before consent. The GM sees who consents and cannot consent for a player. Revoking stops capture and lets the player erase their past traces.
- **TRC-02** Traces cover all three moments, each tagged by moment, as two streams on one clock:
  - semantic Foundry events: windows opened and closed with type and document, rolls and cancelled roll dialogs, actions, spells and strikes, targeting, token moves and cancelled moves, turn start and end, focus and idle, undo. Generic ones from the library, system ones from the adapter;
  - raw input: clicks with button, screen and canvas position and target element; mouse moves at about 10 Hz while focused (tunable); wheel; drag and drop; keys outside text fields. Inside text fields only the rhythm (timing, deletions, duration), never a character.
- **TRC-03** Detectors are a closed, deterministic list with no model, thresholds tunable per campaign; each friction cites its trace span.
  - GM: rules lookup in live play; hunting (≥ 3 windows opened and closed with no action in 30 s); long GM-creature turn; manual correction (undo, cancelled move or re-roll within 10 s); dead time in the GM's turn.
  - Player: long turn; hunting; cancelled roll dialog; rage clicks (≥ 3 at one spot in under 2 s); click on nothing; targeting fixed after the action started; rules lookup; stumbling input.
- **TRC-04** Raw traces are a Source on the GM's machine, outside the workspace, with no automatic expiry in v4. Nothing leaves the machine. The workspace keeps only the per-moment friction report.
- **TRC-05** Player traces reach the Core through the GM's client. With no GM client open they are lost and the gap is noted in the report. No buffer in v4.
- **TRC-06** A diagnostic playbook, run on demand, reads the friction report and proposes delegation table changes, at propose only.
