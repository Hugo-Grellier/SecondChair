# Creative drafts stay in `notes/`, with an id, a status and alternative sets

Status: accepted 2026-10-21 ([#174](https://github.com/Hugo-Grellier/SecondChair/issues/174), epic [#173](https://github.com/Hugo-Grellier/SecondChair/issues/173))

Spec 12 §3 already keeps working ideas out of canon: the campaign workshop writes them to `notes/workshop/<theme>.md`, no importer promotes them, and `search_facts`, `what_knows`, the mystery checker and the guard read canon only. What `notes/` lacks for a campaign-creation studio is narrow: a stable id to link a draft from prep and from other drafts, a status the GM sets (is this pitch still open, tried, chosen, dropped?), a lineage when one draft forks another, and a way to hold **mutually exclusive futures** side by side without one silently winning. We propose to add exactly that to `notes/`, as optional YAML front matter checked by a pure validator, and nothing else: no new top-level directory, no draft facts, no second source of truth.

A design note is any Markdown file under `notes/` that carries this front matter:

```yaml
id: d-1a2b3c4d             # stable, never reused; the file may move or be renamed
status: draft              # draft | playtested | adopted | rejected | superseded
alternatives: arc-act-1    # optional: a set of mutually exclusive notes; at most one adopted
supersedes: [d-0f0e0d0c]   # optional: the notes this one replaces (they become superseded)
cites: [f-11111111, e-22222222]  # optional: canon ids this note builds on; each must resolve
reason: ""                 # optional: the GM's words for a rejection or supersession
```

- **draft**: open. Review is a conversation, not a status.
- **playtested**: tried outside the campaign's canon (a test table, a bench run, a simulated approach), with findings in the body. Playing it at the campaign's own table is not a status change: the wrap turns what was played into canon (ADR 0008).
- **adopted**: the GM chose this as the direction prep works from. Adoption is not evidence that anything happened (ADR 0007). A setting secret the adopted note relies on (the mayor already sold the gate key) enters canon separately, as a GM decision through the existing tools and `secondchair confirm` (CAN-09).
- **rejected**, **superseded**: kept for the record, with the GM's reason when given.

Versioning is the workspace's Git history plus `supersedes`; there is no version counter in the file. "Produced" (prep exists) is derived from the prep and scene files that cite the note's id, never stored.

## Considered Options

- **Free-form `notes/` as today**: rejected as the endpoint. No way to tell an open pitch from a dropped one, or to keep two exclusive futures without the agent picking one.
- **A new `design/` tree with its own schema per document type** (vision, arc, NPC dossier, situation, brief), as #174 sketched: rejected for now. It duplicates `notes/`, which spec 12 and the library already index, and fixes document types before the studio has been used once. Typed bodies can come later inside `notes/` without moving files.
- **Draft facts in `canon/` with a `draft` status**: rejected. Every canon reader (`search_facts`, knowledge, the guard, the mystery checker, the world-turn) would need a filter, and one missed filter turns an unwritten future into truth or a leak. It also stretches ADR 0007: a fact is something that holds.
- **One Git branch per possible future**: rejected. The Core reads one tree, and the GM would have to merge branches to compare pitches.
- **A derived index as the authority for status**: rejected. Markdown stays the source of truth (CAN-10); any index is rebuilt from the front matter.

## Consequences

- A pure validator (`secondchair notes check`, and the same check on index rebuild) reports: duplicate or malformed ids, unknown statuses, more than one `adopted` note in an alternative set, `supersedes` pointing at an unknown id, a superseded note not marked so, and `cites` that do not resolve in canon. Problems are reported, never fixed silently.
- The reference library keeps indexing `notes/`. Its results carry the note's status; `rejected` and `superseded` notes are left out unless asked for. Canon tools still never read `notes/`.
- Nothing in `notes/` reaches players: disclosures cite canon facts only (CAN-16), and Foundry journals the agent prepares stay GM-only. Player-facing text derived from a note goes through the existing guard.
- Status changes are hand edits or agent writes at the GM's word. Whether agent writes to `notes/` go through a logged Core tool, like `write_prep`, is left to a follow-up (see the design doc); until then the GM's Git history is the provenance.
- Migration: none. Notes without front matter stay valid working notes; the validator ignores them.
- Typed document bodies (NPC dossier, situation, mystery draft) are conventions of the task skills that write them ([creative-studio.md](../design/creative-studio.md)), not schemas of this ADR.
