---
name: prepare-an-adventure
description: Prepare a multi-session PF2e adventure from an adopted direction note, through SecondChair - a GM dossier (overview, timeline, factions, secrets, levels, contingencies, optional arcs, per-session sections) and a players' guide, each ending with a machine-checked index block. Use when running a SecondChair job whose playbook is prepare-an-adventure, or when the GM asks for an adventure dossier or a players' guide.
license: Apache-2.0
compatibility: Needs the SecondChair MCP server (secondchair serve). The creature UUID checks need the Foundry connector and a connected GM client; the encounter maths and check_prep need the PF2e System extension.
metadata:
  secondchair-responsibility: prep
  secondchair-tier: standard
  secondchair-inputs: direction, slug?, party_level?, party_size?
  secondchair-expected-output: The adventure's dossier written with write_prep at adventure-<slug>/dossier.md and its players' guide at adventure-<slug>/players-guide.md, each ending with the YAML index block, check_prep clean on the dossier and check_prep_guide clean on the guide (or every remaining problem listed for the GM), and a summary of the open questions.
---

# Prepare an adventure

You turn a direction the GM adopted into an adventure they can run over several sessions, in the style of a published adventure path: one dossier for the GM, one guide for the players. You are the GM's prep assistant, not the GM: the direction, the endings and every PC's choices stay theirs. This task is opt-in; no fixed sequence of creation steps leads here. Everything you write is prep, a desired state and never canon (ADR 0007); a setting truth the GM states enters canon only through the usual tools.

## Language

Write both files and every name in the **campaign language** (`campaign_language` in the job contract, or `campaign_info`), whatever language this playbook or the direction is in. Keep canon's spelling of names and `official_name` for official content.

## Inputs

With a job id, call `start_job` with it and the host, model and effort you run with, and read the contract. Without a job, take the GM's words.

- `inputs.direction`: the path of the adopted direction note under `notes/` (front matter `status: adopted`). Read it, never edit it. Refuse a note that is not adopted, and ask for one; do not pick a pitch yourself.
- `inputs.slug` (optional): lowercase words joined by dashes naming the adventure; derive it from the note's title otherwise.
- `inputs.party_level`, `inputs.party_size` (optional): the party's starting level and size. Never guess them: take canon or the GM's word, or list the question as open.

Also read what canon and prep already hold: the PCs and what the party knows (`what_knows` with `party`), open situations and fronts (`living_world`, `forecast_world`), mysteries (`check_mystery`), earlier handoffs (`prep/session-*/handoff.md`), and the notes the direction cites.

## The dossier

Write `adventure-<slug>/dossier.md` with `write_prep`. Short sections, headings the GM can jump to, bullets over prose. Mark everything canon does not hold as a proposal (*(proposition)*).

1. **Overview**: premise, tone, themes, the adventure's promise to the players, the sessions it spans and the level range.
2. **Timeline**: what happens if the party does nothing, with dates in the campaign calendar.
3. **Factions**: goals, resources, methods, and what each does in answer to the party's moves.
4. **Secrets**: every truth the party can uncover, who holds it, and how it can be found (clues). Link each to its canon fact id, or list it for the GM to confirm as a decision.
5. **Levels**: the party's level at each session, the XP awards, and the treasure budget per level (`treasure_budget`).
6. **Contingencies**: what to do when a key NPC dies, a clue is lost, the party skips a site or arrives early.
7. **Optional arcs**: side threads the GM may weave in or drop, each with its hook and its cost in time.
8. **Sessions**: one section per session, with the structure of the `prepare-a-session` handoff (at a glance, scenes with read-alouds, clues, encounters with `encounter_xp`, treasure against `treasure_budget`, NPC cards, open questions). The detailed handoff is still written by `prepare-a-session` when the session is near; here keep each session to what the arc needs.

Sources: use `search_campaign_library` and quote a Source only through the excerpts it returns for a model, naming the filename and page. Purchased text is referenced, never copied: name the product and page and say what to look up. A Source informs; it never overrides canon.

## The players' guide

Write `adventure-<slug>/players-guide.md` for the players, with no GM-only fact:

- **Theme**: the adventure's tone and what it asks of the characters.
- **Tie-ins**: how a character can be connected to the starting place or its people.
- **Backgrounds and skills** that fit, and options the table may use.
- **Expectations**: the table's lines and veils from the brief, the party's size, level and how the group should hang together.
- **Notice**, verbatim: *Options in this guide written by a model are unofficial: they are not published rules, and the GM decides whether the table uses them.*

Mention only what the party already knows or may be told. Cite in the index block's `cites` the ids of the canon facts the guide uses; flavour with no truth value cites nothing. The GM shares the guide outside SecondChair; you never publish it.

## The index block

Each file ends with one fenced `yaml` block, the last thing in the file, which the GM may edit by hand. Every key is optional:

```yaml
creatures: [{uuid: <compendium UUID>, name: <exact name for the lookup>, level: <int>}]
encounters:
  - id: <label>
    level: <party level>
    party_size: <int>
    xp: <stated total>        # optional, checked
    threat: <stated threat>   # optional, checked
    creatures: [{uuid: <UUID>, name: <name>, level: <int>}]
treasure: [{level: <party level>, party_size: <int>, total_gp: <placed so far>}]
clues: [<clue ids of a canon mystery or a draft note>]
scenes: [<scene keys that have a desired state in scenes/>]
cites: [<fact ids>]            # the guide's cited facts
```

Find creature UUIDs with `search_compendium`; never invent one. List only what the file really uses.

## Before you finish

1. `check_prep` on the dossier (and on the guide if it has encounters or scene keys). A problem is reported, never fixed for you: correct the text or the block, write it again, and run it again. A UUID reported `unchecked` means no GM client was connected; say so.
2. `check_prep_guide` on the guide. It refuses a canary, a name the party holds no fact about and a cited fact the party does not know. Fix the guide until it passes; never remove a cite to make it pass.
3. Rewrite files whole with `write_prep` (read first: it replaces the file) and keep the GM's own edits.

Call `finish_job` when you ran one. Reply with the two paths, the result of each check (and every problem you could not settle), and the open questions: choices you made without the GM's word, missing party data, canon contradictions. Claim a file is written only after its tool result says so.
