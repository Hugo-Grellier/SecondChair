# Proactive cues are a call kind, `cue`, that the Core schedules, budgets and lets expire

Status: accepted 2026-10-21 ([#188](https://github.com/Hugo-Grellier/SecondChair/issues/188), epic [#187](https://github.com/Hugo-Grellier/SecondChair/issues/187))

**Amends [ADR 0005](0005-core-schedules-calls-on-the-gm.md) and DEL-30..33 ([03](../spec/03-delegation.md#calls-on-the-gm-adr-0005)).** ADR 0005 knows three calls (proposal, exception, ceiling refusal), each with a deadline *now* or *break* and a safe default that is logged and **shown again at the break**. A proactive cue fits none of them: it asks for no approval, has no state to default, and is wrong once its moment passes. [ADR 0019](0019-post-v4-live-assistance-and-world-horizon.md) (accepted) sequences this amendment second, after the pull-first director (D1–D9 of [live-director.md](../research/live-director.md)) shows a GM-effort gain with no interruption rise. Until the pull-first director has shown that gain, nothing appears on the Desk unasked except the three calls above.

We decide on **a fourth call kind, `cue`: an unasked, GM-only suggestion that the Core alone raises, from a closed trigger list, under a budget, with deadline *now*, a time-to-live, and the safe default *expire***.

1. **Triggers are closed and deterministic.** The Core raises a cue only on one of: a prepared NPC first observed in the active scene; a GM creature's turn starting with an unused listed reaction (RUL-07) or a forgotten persistent condition; a situation deadline reached in prep that falls in this scene. A playbook or a runner cannot raise one. A model line (a `live-cue` job) may fill the cue's text, but the trigger, the timing and the budget are the Core's.
2. **Deadline now, TTL, expire.** A cue's deadline is *now*. It carries a TTL (initially, revised by MET-05a: 60 s or the end of the current turn, whichever comes first). At the TTL it **expires**: dropped, logged, and **never shown at the break**, because a stale cue is wrong, not pending. Expire is a safe default that applies to cues only; proposals and exceptions keep DEL-32 unchanged.
3. **Staleness withdrawal.** Every cue carries `as_of` (observation sequence, scene, combat round and turn). The Core withdraws it the moment any of these changes, before its TTL. A model line that lands after the cue is withdrawn or expired is logged "too late" (BEN-09) and never shown.
4. **Budget held by the Core.** Proposed: at most **4 cues per hour of play**, a cooldown of 10 minutes per NPC, and a salience threshold per trigger. A trigger past budget raises nothing and is logged "over budget". The Surface cannot raise, batch or suppress cues to change the count.
5. **Counted as interruptions.** Every cue shown is an interruption (DEL-33), counted at the Core, the same on the bench and with any Surface. A withdrawn or expired cue the GM never saw is counted apart, so the bench can tell noise from help.
6. **Off by default, two switches.** Cues are off in every base profile. The GM turns them on per delegation-table cell (the responsibility that owns the trigger: NPCs for an NPC entering, rules and combat for a reaction or condition). The Desk's director toggle (D8) sets them off for the session; it is a logged Surface preference relayed to the Core and changes nothing in Foundry or canon.
7. **A cue is a read.** It carries no delegated action, no approval and no write. Answering it is not needed; dismissing it is a logged GM interaction (DEL-27). Any line meant to be voiced goes through `check_audience_content` and cites fact ids only (CAN-16). With a known turn driver active (ADR 0013), the model line is off for GM creatures.

The six invariants of ADR 0019 hold: a cue never writes canon or advances the plot (1); the Core alone decides what reaches the GM and when (2); it uses no player input (3); triggers and budget are deterministic and the Core calls no model (4); with the runner off a cue is the deterministic card text or nothing, and the Desk says so (5); leaks and narrative direction stay 0 (6).

## Decisions

The GM's calls on #188, accepted 2026-10-21 on PR #220.

- **(a) Budget.** ≤ 4 cues per hour of play, cooldown 10 min per NPC, TTL 60 s or the turn. Numbers revised by MET-05a after the first S4 run with cues on.
- **(b) Which cell owns the switch?** The responsibility of the trigger, as in item 6, rather than one new "cues" cell, so a GM who keeps NPCs manual gets no NPC cues.
- **(c) Does a dismissed cue count against the budget?** Yes: the budget counts cues shown, whatever the GM did with them.
- **(d) Does the deadline mode apply?** No. A cell's deadline mode (DEL-07) forced to *break* turns its cues off, since a cue held for the break has no use.

## Considered Options

- **Cues as an ordinary call with safe default reject, shown at the break**: rejected. The break pile would fill with suggestions for moments already gone.
- **The Surface pops cues when it thinks fit**: rejected, as in ADR 0005 and ADR 0019: the interruption count would depend on the Surface.
- **Open triggers chosen by a model**: rejected. The count and the timing would no longer be deterministic, and a runner could interrupt at will.
- **No proactive cues, pull only**: kept as the default (off) and as the baseline every cue run is measured against.

## Consequences

- DEL-30..33 gain the `cue` kind; DEL-32 states that expire applies to cues only. A new DEL entry carries the budget and the closed trigger list.
- The call record gains `kind: cue`, `ttl`, `as_of` and a terminal status `expired | withdrawn | dismissed`. The Desk shows a cue's age and drops it when the Core withdraws it.
- The Core keeps a per-session cue ledger (count, cooldowns) in memory and in the action log, so a restart mid-session does not reset the budget.
- **Test plan.** Core unit tests: each trigger raises exactly one cue; a non-listed event raises none; the fifth cue in an hour and a second cue on the same NPC within 10 min raise nothing and log "over budget"; a scene, round or turn change withdraws a live cue; TTL expiry never reaches the break pile; a late `live-cue` output is logged "too late" and not shown; cues off in a cell or by the director toggle raise nothing; a cell forced to *break* raises none. Bench (S4): interruptions per hour with cues on stay ≤ budget, pull-only stays equal to director-off, leaks and narrative direction 0, GM effort compared with pull-only.

## GM answers (2026-10-21)

1. **Budget clock.** Per hour of play: the session clock minus breaks, read from the session's start, break and end entries in the action log. Wall-clock time would let a long break free budget that is then spent in a burst.
2. **Per-NPC snooze.** Not now. The 10-minute cooldown per NPC, the per-cell switch and the director toggle are enough; a snooze is added only if S4 shows repeated dismissals on one NPC.
3. **Triggers.** The three triggers of item 1 are the closed list to start. A trigger is added or removed only through D11, after measurement.
