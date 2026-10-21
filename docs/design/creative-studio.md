# Design: the campaign-creation studio

Status: proposal — awaiting the GM's decisions. Binds nothing until accepted ([spec README](../spec/README.md#precedence)).

Covers [#173](https://github.com/Hugo-Grellier/SecondChair/issues/173) (epic), [#175](#175--campaign-direction-and-the-editorial-loop), [#176](#176--npc-and-pc-arcs-and-acting-direction), [#177](#177--non-linear-situations-and-mystery-drafts), [#178](#178--adventure-dossier-and-players-guide), [#185](#185--played-choices-become-opportunities). The draft/canon boundary ([#174](https://github.com/Hugo-Grellier/SecondChair/issues/174)) is [ADR 0017](../adr/0017-creative-drafts-live-in-notes-with-a-status.md), proposed. Evaluation ([#182](https://github.com/Hugo-Grellier/SecondChair/issues/182)) is [editorial-evaluation.md](editorial-evaluation.md). The vertical slice ([#183](#183--vertical-slice-blocked)) is blocked.

## Principles every proposal keeps

- **The GM is the creative authority** (VIS-01). Narrative direction stays capped at *propose* (DEL-08). The studio proposes, compares and checks; it never decides an ending, a PC's choice or a PC's feelings.
- **The Core stays LLM-free** (ADR 0001). Every new model step is a playbook (Agent Skill) run by an agent host; every new check is a pure function in the Core or the System extension.
- **Tiers, not models** (ARC-25). Issues ask for "Opus-led" or "Sonnet production": a playbook declares `deep`, `standard` or `fast`, and the GM's runner configuration maps `deep` to whichever model they choose. No model name enters a playbook. #180 (routing) changes the mapping, not this rule.
- **No fixed creation sequence** (spec 12 §2). Every studio workflow is an opt-in **task skill** the GM invokes, layered on the campaign workshop protocol, never a mandatory pipeline.
- **Drafts are notes, truth is canon, prep is desired state.** Possible futures and editorial material live in `notes/` with ADR 0017's front matter; what is true now is canon facts; what a session should look like is `prep/` and the VTT's desired state. Nothing moves between them without a GM gesture.
- **Ship the smallest useful slice first.** Each workstream starts with a skill and the existing tools; new Core tools come only where a check cannot be done otherwise.

Risk in the leaf tables follows the Ballast tiers ([#186](https://github.com/Hugo-Grellier/SecondChair/issues/186)): R0 text-only (skills, docs), R1 a contained code change with tests, R2 touches an R2 trigger (canon writes, delegation, disclosure, secrets) and needs design approval and a human merge.

## What exists today

| Need | Already there |
|---|---|
| Open-ended creative conversation, recaps, decisions vs ideas | `campaign-workshop` skill (spec 12 §1–2) |
| Ideas kept out of canon | `notes/workshop/<theme>.md`, never imported (spec 12 §3) |
| Truth, secrets, who knows what | facts, knowledge, guard and canaries (CAN-01–17) |
| Session prep | `prepare-a-session`: `prep/session-<n>/handoff.md` (scenes, read-alouds, clues, NPC cards, improv kit), Foundry desired state |
| Encounter and treasure maths | PF2e `encounter_xp`, `treasure_budget` ([#56](https://github.com/Hugo-Grellier/SecondChair/issues/56)) |
| Mystery robustness | `record_mystery` / `check_mystery`: three-clue rule, reachability, single point of failure, simulated clue loss (`lose`), mobile clues |
| NPC voice at the table | acting cue on the Director's Desk: goal, guarded line, knows / does not know |
| Fronts, situations, consequences | world-turn, `propose-consequences`, `propose-narrative-direction` (deadlines only) |
| Played evidence | wrap: quoted candidate facts at the played rank (ADR 0008) |
| Rules and setting look-ups | reference library with per-source permissions |

The gap is not storage or checks. It is **editorial method** (diverge, critique, choose, revise), **acting direction** that is not truth, **drafts that can be checked before they are canon**, and **links from play back to the drafts**.

---

## #175 — Campaign direction and the editorial loop

**Exists.** The workshop protocol (one question at a time, recaps, no forced sequence). `propose-narrative-direction` handles one situation's deadline, not a campaign's shape.

**Gap.** No method for divergent pitches, a critical pass, or a selected outline that stays open-ended. No place where three exclusive pitches coexist with a status.

**Proposed shape.**

- Task skill `develop-campaign-direction` (tier `deep`), invoked by the GM in conversation. It adds guidance to the workshop protocol and never replaces it; the GM may stop or skip any step.
- Moves, in any order the GM wants:
  1. **Brief**: premise, tone, themes, level range, table boundaries (lines and veils), player-facing promise, sandbox freedom, foundational conflicts. Note `notes/direction/brief.md`.
  2. **Pitches**: three materially different architectures (different central conflict, structure or antagonist pressure, not three skins of one plot), each with strengths, weak points, hooks, factions, near-term beats and loose long-term possibilities, and the canon ids it must respect. Three notes in one alternative set (`alternatives: campaign-direction`).
  3. **Critique**: a fixed checklist written into each pitch: clichés, false choices, PC relevance, pacing, accidental railroading, payoff without setup, unearned revelations. Flags only; the GM weighs them.
  4. **Choice**: the GM adopts one (status `adopted`), rejects or merges others with a reason.
  5. **Outline**: arcs as pressures and open questions, revelations linked to causes and possible player paths, never a fixed ending; a short **campaign primer** for session zero (player-facing, guarded).
  6. **Revision**: a new note that `supersedes` the old one; Git keeps history.
- Canon writes only for setting truths the GM states, through the existing tools and `secondchair confirm`.

**Decisions needed.**

1. Accept ADR 0017 (notes with id/status/alternatives) as the store for pitches? If not, which alternative?
2. Is "three pitches" a default the GM can change per request, or fixed?
3. Should the critique checklist live in the skill (editable by the GM via a campaign skill) or be the rubric of `editorial-evaluation.md` verbatim?
4. Is the campaign primer a `prep/` file (desired state, GM reads aloud) or a Foundry journal prepared GM-only for later publication?

**Proposed leaves.**

| Title | Scope | Risk | Depends on |
|---|---|---|---|
| Note front matter and `secondchair notes check` | Implement ADR 0017's validator and library status filter. Pure, no model. | R1 | ADR 0017 accepted |
| `develop-campaign-direction` task skill | The six moves above as an Agent Skill; tier deep; writes notes only. | R0 | note front matter |
| Pilot: expand an existing two-session premise | Run the skill on the sample campaign; show no fact changes (`git diff canon/` empty). | R0 | skill |

---

## #176 — NPC and PC arcs and acting direction

**Exists.** Entities carry identity only (CAN-02); an NPC's agenda and secrets are facts the party does not know. The acting cue shows goal, one guarded line, knows / does not know. `prepare-a-session` writes NPC cards (voice, wants, hides, lines, reactions).

**Gap.** Acting direction (desire, need, fear, contradiction, voice, body language, pressure responses, improvisation rules) has no truth value, so it is not canon, yet it has no stable home either: each handoff rewrites it. Expected changes ("if the party spares her brother, she softens") are possible futures, so they are drafts. PC arcs have no player-owned record. Spotlight is not measured.

**Proposed shape.**

- **NPC dossier**: a note `notes/npcs/<entity id>.md` with ADR 0017 front matter, `cites` the NPC's canon facts. Sections: desire, need, fear, contradiction, vulnerabilities, relationships (each citing facts), current attitude, voice and body, improvisation rules, change triggers (each a possible future, never applied by itself). What is *true now* (a secret motive) stays a canon fact the party does not know; the dossier points to it by id.
- **Scene cue**: in the handoff, per NPC per scene: objective, tactic, emotional posture, one opening line (guarded with `check_audience_content`), two or three likely responses. 5–10 seconds to read.
- **Acting cue**: add one optional field, `posture` (a few words, GM-only), to `show_acting_cue`. No new panel, no tab (ARC-14). Only `line` remains audience content.
- **PC hooks**: `notes/pcs/<entity id>.md`, written only from what the player gave (goals, ties), marked with the player as owner. The agent proposes hooks for the PC's world, never what the PC decides or feels.
- **Spotlight**: a deterministic count, per session, of played facts citing each PC entity (from the wrap's admitted facts), reported after the wrap. No model.
- **After the wrap**: dossier updates are proposals in the dossier's body, each citing the played fact that motivates it; see #185.

**Decisions needed.**

1. Dossier per NPC as a note (proposed) or as a section of each handoff (status quo)?
2. Add `posture` to the acting cue, or keep the Desk unchanged and leave posture in the handoff?
3. Who may write a PC hook note: only with the player's input relayed by the GM, or also GM-only hooks the player does not see?
4. Is the spotlight count by played facts a good-enough proxy, or does the GM want scene-level tagging in the handoff?

**Proposed leaves.**

| Title | Scope | Risk | Depends on |
|---|---|---|---|
| NPC dossier convention in the workshop skill | Section list and rules (truth in canon, direction in note, triggers as futures). Skill text only. | R0 | ADR 0017 |
| Scene cues in `prepare-a-session` | Per-NPC per-scene cue block; opening line guarded. Playbook text only. | R0 | — |
| Acting cue `posture` field | Optional GM-only string in `show_acting_cue` and the Desk; tests for absence and display. | R1 | decision 2 |
| Spotlight report after the wrap | Count played facts per PC entity per session; shown in the wrap summary. Pure. | R1 | — |
| Worked 3-NPC example | Three contrasting dossiers on sample-campaign NPCs, with non-combat reactions; probe that secret motives never appear in player text. | R0 | dossier convention |

---

## #177 — Non-linear situations and mystery drafts

**Exists.** Situations and fronts as entities with facts (LW-01–03). The mystery checker: three-clue rule, inverted rule, reachability, single point of failure, simulated loss, `mobile` clues. But `record_mystery` needs every clue and conclusion to be a **canon fact** already.

**Gap.** A mystery cannot be checked while it is still a draft, so either the agent writes unplayed clues into canon early or the GM checks nothing until it is too late. No method for situation design (stakes, parties, pressure, responses). No proposal path for an unexpected player action other than a deadline.

**Proposed shape.**

- **Mystery draft**: a note `notes/mysteries/<slug>.md` whose front matter has the same graph as `canon/mysteries/`, but each conclusion and clue carries a draft `statement` instead of a fact id (or a fact id when the truth is already canon).
- **`check_draft_mystery`**: a read tool that feeds the draft to the existing pure `mystery.check` with synthetic facts for draft statements. Same warnings, same `lose` simulation. No canon write.
- **Promotion** (GM gesture): the GM confirms the setting truths (conclusions, past events) as GM-decision facts; clue facts are recorded as GM-decision facts the party does not know yet; then `record_mystery`. The draft note becomes `adopted` and cites the new ids. The skill must resolve warnings by adding clues or entries, never by dropping the check.
- **Secrets and clues**: location-agnostic clues are `mobile: true` (already supported); fixed evidence is `mobile: false`.
- Task skill `design-a-situation` (tier `deep`): stakes, interested parties, resources, pressure over time, clues, optional scenes, at least three plausible responses with consequences, what happens if ignored; a one-screen operational reference for play.
- **Approach simulation**: the skill writes, per draft, three divergent approaches (social, stealth, force, or what fits) and their consequences, checked against canon. Human-judged quality (#182), not a Core check.
- **Unexpected action**: generalise `propose-narrative-direction` with an `observation` input: from an observed played fact, propose a new situation, held at *propose* (it is new narrative, LW class 3).

**Decisions needed.**

1. May clue facts enter canon at promotion, before play, as GM decisions the party does not know (as `canon/mysteries/` requires today)? Or must clues stay drafts until found?
2. Is `check_draft_mystery` a Core MCP tool (proposed) or a CLI-only check?
3. Should the unexpected-action proposal be a new input of `propose-narrative-direction` or a separate playbook?

**Proposed leaves.**

| Title | Scope | Risk | Depends on |
|---|---|---|---|
| `check_draft_mystery` | Run `mystery.check` on a note with draft statements; same report shape; tests with a lost clue and a single-node conclusion. | R1 | ADR 0017 |
| `design-a-situation` task skill | Situation and mystery-draft method, approach simulation, play reference. Skill text. | R0 | `check_draft_mystery` |
| Mystery promotion steps | Documented GM flow (confirm truths, record clues, `record_mystery`), in the workshop skill. | R0 | decision 1 |
| Proposal from an unexpected action | `propose-narrative-direction` accepts an observed fact; proposal stays pending. | R2 (narrative-direction authority) | decision 3 |

---

## #178 — Adventure dossier and players' guide

**Exists.** `prepare-a-session` writes one session's handoff with scenes, read-alouds, encounters (`encounter_xp`), treasure (`treasure_budget`), NPC cards, improv kit, Foundry material, open questions. Compendium search for creatures and items. Purchased content stays metadata-only in `.secondchair/purchased/`.

**Gap.** No multi-session view (GM overview, timeline, contingencies, optional arcs). No deterministic check that a handoff's references resolve (creature UUIDs, clue ids, scene keys, treasure totals). No players' guide, and no whole-document leak check for one.

**Proposed shape.**

- Task skill `prepare-an-adventure` (tier `standard`, from an adopted direction note): `prep/adventure-<slug>/dossier.md` (overview, timeline, factions, secrets, levels, contingencies, optional arcs, then per-session sections reusing the handoff's structure) and `prep/adventure-<slug>/players-guide.md` (theme, tie-ins, backgrounds and skills that fit, expectations; a fixed notice that model-written options are unofficial). Each session's handoff stays where `prepare-a-session` writes it.
- **`check_prep`**: a deterministic linter over a prep file's structured block (a fenced YAML index at the end listing creature UUIDs, encounter specs, clue ids, scene keys, treasure): every UUID resolves through the connector, every encounter's XP and threat is recomputed with `encounter_xp`, treasure totals against `treasure_budget`, every clue id exists in a mystery, every scene key has a desired state. Reports, never fixes.
- **Players' guide guard**: run the existing guard over the whole guide for the party audience: secret names, canaries, cited facts the party does not know. The guide cites facts it uses; flavour with no truth value cites nothing.
- **Licensing**: the dossier quotes Sources only through model-permitted excerpts, with filename and page; purchased text is referenced, never copied (spec 08).

**Decisions needed.**

1. Is a dossier a new `prep/adventure-*` tree (proposed) or simply longer session handoffs?
2. Is the structured YAML index at the end of a prep file acceptable to the GM as a hand-editable convention?
3. Does the players' guide need a disclosure (publication in Foundry, DEL-29) or does the GM share it outside SecondChair?

**Proposed leaves.**

| Title | Scope | Risk | Depends on |
|---|---|---|---|
| `check_prep` linter | Resolve UUIDs, recompute XP/threat and treasure, check clue ids and scene keys from a prep file's index block. | R1 | decision 2 |
| Players' guide guard | Guard a whole prep file for the party audience; CLI and MCP read. | R2 (secrets, player-facing) | — |
| `prepare-an-adventure` task skill | Dossier and guide structure; calls `check_prep` and the guard before finishing. | R0 | both checks |
| Time-to-run review | One GM read-through with the #182 table-use log. | R0 | #182 rubric |

---

## #185 — Played choices become opportunities

**Exists.** The wrap admits played facts with quotes. The world-turn applies rule effects deterministically; `propose-consequences` proposes derived consequences; `propose-narrative-direction` proposes new narrative at deadlines. Fronts and clocks are canon facts.

**Gap.** Nothing links a played choice back to the drafts it touches (a promise kept, a relationship strained, a hook consumed), and nothing turns that into a short list of optional next-session opportunities with evidence.

**Proposed shape.**

- Task skill `propose-opportunities` (tier `standard`; `deep` when it proposes a new arc), run after the wrap on the GM's request or as a queued job. Reads the session's admitted facts, adopted notes and NPC dossiers. Writes `notes/opportunities/session-<n>.md`: each opportunity cites the played fact ids that justify it and the note ids it touches, names the PCs it concerns, and is a draft. Nothing enters canon; a new front or situation still goes through narrative direction at *propose*.
- **No destiny engine.** World state moves only by the deterministic world-turn (ADR 0009). The skill never advances an arc because a beat seems due; an abandoned hook or missed clue changes nothing unless a front's rules say so.
- Deterministic signals for the skill, from the Core: unused prep (handoff clue ids not found, `check_mystery`), the spotlight count (#176), dossier change triggers whose cited facts now hold.
- **Repeatable loop**: wrap → `propose-opportunities` → GM adopts or rejects → `prepare-a-session` reads adopted opportunities. Tested over three synthetic sessions of the sample campaign.

**Decisions needed.**

1. After the wrap, should opportunities be queued automatically (a job, like the world-turn) or only on request?
2. Does the GM want contradicted foreshadowing and repeated faction beats flagged by the skill (model judgement), or only the deterministic signals?

**Proposed leaves.**

| Title | Scope | Risk | Depends on |
|---|---|---|---|
| `propose-opportunities` task skill | Opportunity notes citing played facts and note ids; no canon writes. | R0 | ADR 0017, #176 dossiers |
| Deterministic signals | Unused prep and fulfilled change triggers as a read tool. | R1 | `check_prep`, spotlight |
| Three-session loop test | Scripted sample-campaign loop; asserts no opportunity is canon and no secret reaches party text. | R1 | the two above |

---

## #183 — Vertical slice (blocked)

Blocked on: the foundations ([#167](https://github.com/Hugo-Grellier/SecondChair/issues/167)–[#171](https://github.com/Hugo-Grellier/SecondChair/issues/171), [#163](https://github.com/Hugo-Grellier/SecondChair/issues/163) as security gate), ADR 0017 accepted, the R0 skills above, the leaf checks it exercises (`check_draft_mystery`, `check_prep`, guide guard), asset pipeline [#179](https://github.com/Hugo-Grellier/SecondChair/issues/179), routing [#180](https://github.com/Hugo-Grellier/SecondChair/issues/180), and the #182 rubric. Nothing to design until those land; its workflow is already the sum of the sections above, run on a synthetic Westerhold-like neighbourhood, with the #182 table-use log as its report.

## Sequencing

1. GM decides ADR 0017 and the questions above.
2. R0 skill text (direction, dossier convention, scene cues, situation design) can ship as soon as ADR 0017 is accepted: no Core change.
3. R1 checks: notes validator, `check_draft_mystery`, `check_prep`, guide guard, spotlight.
4. `propose-opportunities` and the loop test.
5. #183 once its blockers close.

None of this is v4 release scope unless the GM says so (spec 11); it sequences behind correctness work and dogfooding ([#71](https://github.com/Hugo-Grellier/SecondChair/issues/71)).
