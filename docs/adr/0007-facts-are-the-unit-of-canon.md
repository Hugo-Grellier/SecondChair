# Facts are the unit of canon, stored as Markdown the GM can edit

Canon is made of **facts**, not entity sheets. A fact is one statement about one or more entities, in the GM's language, with an optional typed relation, a validity in fictional time, its provenance (authority rank, origin, and the action log entry that admitted it) and the time it was recorded. Entities only carry identity, names and a player-facing description with no truth value. Events open and close facts, and a retcon is an event that replaces another. Knowledge is a link from a knower (the party, an NPC, a faction) to a fact, closed-world plus inheritance from factions and places. We chose this over the v3 entity sheet, whose prose sections cannot be dated, cited or known one statement at a time: the per-NPC knowledge firewall and leak checks need to point at one precise fact. The workspace keeps Markdown + YAML as the source of truth, with a SQLite index derived from it, so the GM can read, diff and edit canon in their own repository.

## Considered Options

- **Entity sheets as in v3**: rejected. Truth, time and knowledge would be attached to sections of prose rather than to statements.
- **Typed triples only**: rejected. Most of what a campaign records does not fit a closed predicate list.
- **SQLite as the source of truth**: rejected. Canon would no longer be diffable or editable by hand.
- **Embeddings for search**: deferred in the original v4 design. The campaign reference library (spec 12) now computes passage embeddings through the GM's local Ollama installation, outside the Core process. This preserves the LLM-free Core decision (ADR 0001) and the canonical source of truth: the index remains derived from workspace notes or registered references.

## Consequences

- A hand edit of the workspace bypasses the Core. The Core picks it up when it rebuilds the index and logs it at the agent-proposal rank, since it cannot tell who typed it. The GM promotes it to a GM decision in one gesture on an authenticated Surface (ADR 0003).
- An approved agent proposal keeps the agent-proposal rank. Only play, or a GM decision in the GM's own words, ranks higher.
- Content written for an audience (an NPC line, a disclosure) cites the ids of the facts it uses. The Core refuses it if the audience does not know a cited fact, and scans it for forbidden strings. Paraphrased leaks are not blocked; the test bench measures them.
- A disclosure marks the facts it cites as known by the party, so the party is not the knower that bounds it: no knower bounds a disclosure the GM authored, whose cited facts only have to exist in canon, be true and carry no canary, the GM's authenticated approval (or a lifted hold) being the gate. When an NPC discloses, as the acting entity, it must know every fact it cites.
