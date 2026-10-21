# The live director: in-session cues, tactical help and a session-first flow

Research for [#187](https://github.com/Hugo-Grellier/SecondChair/issues/187), covering [#188](https://github.com/Hugo-Grellier/SecondChair/issues/188) (acting and pacing cues), [#193](https://github.com/Hugo-Grellier/SecondChair/issues/193) (PF2e tactical help) and [#196](https://github.com/Hugo-Grellier/SecondChair/issues/196) (session-first use in Foundry). Post-v4; scope horizon in [ADR 0019](../adr/0019-post-v4-live-assistance-and-world-horizon.md) (proposed). No code.

## What exists

| Piece | Where | What it gives live |
|---|---|---|
| Director's Desk | `foundry/secondchair-foundry/scripts/desk.js`, [foundry-bridge](../contracts/foundry-bridge.md) | GM-only window: calls due now, approve/reject with reason, break pile, Start/End session, decisions to confirm, ceiling read-only, turn driver, the active acting cue with *I voice this one* / *Hand back*. Shift+D. Holds no state (ARC-11) |
| `show_acting_cue` | `src/secondchair/core/knowledge.py` | Goal, a line citing fact ids, what the NPC knows and must not let slip. Audience-checked (CAN-16), shown at every level since it is a read |
| `quick-help` playbook | `src/secondchair/playbooks/skills/quick-help/SKILL.md` | Pull-only, fast tier: NPC card, place, complication, rules reminder in under 15 lines. Reached from the agent host conversation, not from Foundry |
| Read-only review page | `src/secondchair/review.py` | Prep, canon search, pending calls, jobs on `serve`'s loopback port. Approves nothing (ARC-14a) |
| `secondchair status` | `src/secondchair/cli.py` | Moment, pending entries, open calls, jobs, one terminal command |
| PF2e executor | `foundry/secondchair-foundry-pf2e/scripts/executor.js` | `strike`, `reaction`, `cast_spell`, `self_effect`, `place_area`, `use_action`, `saving_throw` for GM creatures in encounters; one reaction per round tracked (RUL-07) |
| Rules checks, discrepancies | `src/secondchair/core/rules.py`, spec [06](../spec/06-pf2e-rules.md) | A failed check is a call under rules and combat, held for the break by default |
| Friction detectors | `src/secondchair/core/frictions.py`, TRC-03 | Rules lookup in live play, hunting, long GM-creature turn, manual correction, dead time: the GM's live pain, measured deterministically |

## Gaps

1. **No pull from Foundry.** The only on-demand help (`quick-help`) lives in the agent host; the GM leaves Foundry to ask.
2. **No situation snapshot.** Nothing assembles active scene, active combatant, present NPCs, their known and forbidden facts, and the session handoff into one GM-only read.
3. **Cues have no freshness.** The active cue stays until replaced; nothing withdraws it when the scene or turn moves on (#188 "a stale cue is not shown later").
4. **No NPC turn card.** The executor acts, but the GM driving a creature by hand gets no compact read of its strikes, actions, MAP, reaction left, conditions and reach (#193).
5. **No cited rules lookup.** No path returns a rule with its installed compendium entry and system version; book rules wait for [#190](https://github.com/Hugo-Grellier/SecondChair/issues/190)/[#191](https://github.com/Hugo-Grellier/SecondChair/issues/191).
6. **Latency is a runner's cold start.** The Core calls no model (ADR 0001); a model-written line means queueing a job a runner starts. A headless host per job costs seconds before the first token.
7. **No in-Foundry readiness.** Core reachable, world bound, adapter and translation module versions, runner available: today found by reading terminal errors (#196).

## Design: pull-first, deterministic first, model second

**Two stages per pull.** A GM gesture on the Desk (hotkey, or "this NPC" / "this situation" / "this turn") asks the Core for a **card**:

1. **Deterministic card, at once.** The Core assembles it from what it holds, no model: active scene and combatant (observations), NPCs present, each one's known and forbidden facts (`what_knows`, CAN-14), situations and fronts they take part in, the matching lines of `prep/session-<n>/handoff.md`, open calls touching them. For a GM creature's turn the adapter adds its strikes and variants, system actions, MAP, reaction left (RUL-07), conditions, tokens within reach. It is a read: no delegated action, no call, no interruption.
2. **Optional model line, under a deadline.** The same gesture may queue a `live-cue` job (fast tier) whose output is `show_acting_cue` with `as_of`. If it lands after its deadline it is logged "too late" (as BEN-09) and never shown.

**Freshness.** Every card and cue carries `as_of`: observation sequence, scene, combat round and turn. The Core withdraws it when any of these changes; the Desk shows its age. Nothing renders a cue built for an earlier turn.

**Visibility.** Cards exist only in the GM client (the bridge never opens in a player's client). Any line that might be read aloud goes through `check_audience_content`; card text the GM must not voice is labelled by kind: *GM-only suggestion*, *prepared design*, *approved canon*, *player disclosure* (the last only for disclosures already approved).

**Proactive cues (later, ADR 0005 amendment).** Unasked cues are a call kind `cue` the Core schedules: closed trigger list (a prepared NPC first observed in the active scene; a GM creature's turn starts with an unused listed reaction or a forgotten persistent condition; a situation deadline reached in prep falling in this scene), salience threshold, cooldown per NPC, budget per hour, TTL; safe default *expire*. They count as interruptions. Off by default per delegation-table cell.

**Turn drivers.** With a known driver active (ADR 0013) the model line is off for GM creatures; the deterministic turn card stays, since it is a read of pf2e data and proposes nothing.

**Tactical honesty (#193).** The turn card lists what the actor *has*, from `actor.system.actions` and its items; it never ranks outcomes from recomputed math (RUL-15). A "likely tactic" is the NPC's prepared intent fact, cited, or nothing. Rules lookup returns the installed compendium entry (UUID, system version, translation) and flags a known house rule (RUL-22) instead of silently overriding it.

**Session flow (#196).** The Desk already holds Start session, Break, End session. Add a **readiness card** at connect (Core reachable, world/workspace pairing, pf2e and adapter versions, translation module, runner available, speech off) and the wrap state after End session (queued, running, awaiting the grouped round in the CLI). No tabs (spec 11); cards stack, collapsed by default.

**Off switch.** One Desk toggle sets the director off for the session: no cards, no jobs, no cue calls. It is a Surface preference relayed to the Core, logged, and changes nothing in Foundry or canon.

## Proposed amendment: Desk cards under ARC-14 (#196)

The pull-path cards (situation D1, NPC turn D3, readiness D7, wrap state) need no ADR: [ADR 0019](../adr/0019-post-v4-live-assistance-and-world-horizon.md) maps them to ARC-14 at spec level, since a card is a read like the acting cue, with no delegated action and no call. ADR 0005 is not changed: the cards add no call and no interruption, and it already leaves the Desk's contents to the spec. The amendment is to [02-architecture.md](../spec/02-architecture.md) ARC-14, to land with D1 once the GM agrees; until then ARC-14 holds as written.

> **ARC-14** The **Director's Desk** is a minimal panel: the calls due now, approve or reject with a rejection reason, the active NPC's acting cue with "I voice this one" / "Hand back", and the pile held for the break. It may also show **read-only cards** the GM pulls (situation, NPC turn, readiness at connect, wrap state after End session): each is assembled by the Core, carries `as_of` and is withdrawn when it goes stale, holds no delegated action and raises no call. Cards stack, collapsed by default. No tabs: the action log, staging and the living world stay in conversation and the CLI ([ADR 0005](../adr/0005-core-schedules-calls-on-the-gm.md), [#19](https://github.com/Hugo-Grellier/SecondChair/issues/19)).

Spec 11's row "A Director's Desk with tabs" stays as written. Unasked cards are not part of this amendment: they are cues, [ADR 0020](../adr/0020-proactive-cues-are-a-call-kind-that-expires.md) (proposed). The GM accepted this text on PR #220 (2026-10-21), to be applied to ARC-14 with D1, and answered its two questions: the wrap-state card stays after End session until the grouped round in the CLI is done, then is withdrawn as stale; the readiness card shows at connect only when a check fails, and otherwise can be pulled, with a one-line ready status.

## Budgets (proposed; numbers set by MET-05a after the first S4 run)

| Item | Budget |
|---|---|
| Deterministic card, gesture → render | p95 ≤ 500 ms |
| Model line on pull | deadline 8 s default, configurable per cell; late → dropped, counted "too late" |
| Proactive cue calls | ≤ 4 per hour of play, cooldown 10 min per NPC, TTL 60 s or the turn, whichever ends first |
| Desk footprint | one collapsed stack, never over the active sheet or chat; zero focus steal while the GM types |
| Runner | a warm agent host session claims fast-tier `live-cue` jobs during the live session; without it, stage 1 only |

## Success criteria (tied to [10-success-bench.md](../spec/10-success-bench.md))

| Criterion | Metric | Where |
|---|---|---|
| No leak, no narrative action above propose with the director on | Leaks, Narrative direction: 0 on every run | S4, dogfooding |
| Live help lowers GM effort | GM effort (live) median below director-off on the same replay | S4 (chat log + transcript), dogfooding |
| Pull adds no interruptions; proactive stays in budget | Interruptions per hour: pull = director-off; with proactive ≤ budget | S4 |
| Fast enough to use | Cost, latency p50/p95 per card and per `live-cue`; "too late" share | S4 |
| Tactical card is right | Agreement rate: the GM's actual action (chat log) is among the card's listed options | S4 |
| Less live lookup pain | TRC-03 frictions per hour (rules lookup in live play, hunting, long GM-creature turn) below the v4 dogfood baseline | Dogfooding only (S4 has no traces) |
| Session-first | GM interactions plus terminal commands from connect to wrap; BEN-14 "never abandons" holds | Dogfooding |
| Off is off | Director off: identical Foundry observations and canon on the same replay | S4 |

## Proposed leaf issues

Risk: R0 docs or bench only; R1 reversible behaviour; R2 touches delegation, call scheduling, disclosure, canon or privacy (#186).

| # | Title | Scope | Risk | Deps |
|---|---|---|---|---|
| D1 | Situation card on the Desk | Core assembles the deterministic GM-only card; Desk pull by hotkey; `as_of` | R1 | — |
| D2 | Withdraw stale cues | `as_of` on the acting cue; Core withdraws on scene/turn change; Desk shows age | R1 | — |
| D3 | NPC turn card | Adapter read of strikes, actions, MAP, reaction left, conditions, reach for the active GM creature; stays under a turn driver | R1 | — |
| D4 | Pull a line from the Desk | Gesture queues `live-cue` with a deadline; late output dropped and counted | R1 | D1, D5 |
| D5 | Warm live runner | Runner keeps one host session for fast-tier jobs during the live session; Desk shows degraded when absent | R1 | — |
| D6 | Cited quick rule lookup | Installed compendium entry with UUID and version; house-rule notice | R1 | #190, #191 for book text |
| D7 | Readiness card | Connect-time checks and one-action fixes for the common failures listed in #196 | R1 | — |
| D8 | Director off toggle | Logged session preference; no cards, jobs or cue calls | R1 | D1 |
| D9 | S4 director metrics | Card and `live-cue` latency, "too late", tactical agreement, director-off comparison | R1 | D1, D3 |
| D10 | ADR: the `cue` call kind | Amend ADR 0005 (TTL, expire default, budget, cooldown, closed triggers) | R2 | ADR 0019, D9 results |
| D11 | Proactive cues | Implement D10 behind a delegation-table cell, off by default | R2 | D10 |

Out of these leaves: acting dossiers ([#176](https://github.com/Hugo-Grellier/SecondChair/issues/176)) and post-session opportunities ([#185](https://github.com/Hugo-Grellier/SecondChair/issues/185)) feed the cards' content; speech input is [speech-fusion.md](speech-fusion.md).
