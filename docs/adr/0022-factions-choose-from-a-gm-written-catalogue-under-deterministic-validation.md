# Factions choose from a GM-written catalogue; a deterministic step validates, debits and applies

Status: accepted 2026-10-21 ([#192](https://github.com/Hugo-Grellier/SecondChair/issues/192), epic [#187](https://github.com/Hugo-Grellier/SecondChair/issues/187))

**Amends [ADR 0009](0009-world-turn-deterministic-three-effect-classes.md) (its rejected option "simulating factions as agents") and LW-02 ([05](../spec/05-living-world-calendar.md)).** Today a faction acts only through the fronts it carries: it has no resources, no choices and no reaction to the party's absence beyond the clocks the GM wrote. [ADR 0019](0019-post-v4-live-assistance-and-world-horizon.md) (accepted) sequences this amendment third, after recoverable transactions ([ADR 0016](0016-a-world-turn-occurrence-is-applied-through-a-roll-forward-journal.md), #169) and temporal semantics (#170), between sessions only. The design is [faction-simulation.md](../research/faction-simulation.md).

We decide that **during the world-turn, an ephemeral job per faction may choose among actions the GM wrote, and a deterministic Core step validates each choice against truth, debits its cost and applies its effect in one journaled transaction; the effect's class comes from the GM's template, not from the agent**.

1. **GM-written state facts.** On the faction entity, as state facts (canon, bitemporal, undoable like a front, LW-03; no separate store): `intent` (one to three goals citing the fronts or situations they pursue), `pool` (named integer resources, each with an income per fictional interval and a cap), `capacity` (actions per interval) and `catalogue` (actions with cost per pool, prerequisites, duration, effect template and contest rule). The GM writes all of them. Only a validated effect changes a pool.
2. **Income.** For each interval step the Core credits income up to the cap, as a rule effect with key `<faction>/income@<date>`, used once (LW-13).
3. **Ephemeral choice.** The world-turn queues one `faction-intent` job per faction. Its input is **only the faction's knowledge view** (`what_knows`, CAN-14/15), its pools, catalogue and intents. It returns up to `capacity` ranked choices **from the catalogue only**, each citing the fact ids it relied on. It cannot invent an action, a cost or an effect; an output naming anything else is refused whole.
4. **Deterministic validation and debit.** A Core step checks each choice against **truth, not belief**: prerequisites hold as of the occurrence date (#170), pools cover the cost, capacity is left. A choice built on a false belief fails, and the failure is an offscreen event the faction learns. Each accepted choice is an occurrence `<faction>/<action>@<date>` whose debit and effect are one plan in one journal (ADR 0016), so a crash or a retry cannot double-spend.
5. **Seeded contests.** Two choices on one target in one step resolve by the catalogue's contest rule: committed pools compared, ties and any roll seeded from the occurrence keys. A replay gives the same result.
6. **Class from the template.** The effect template, written by the GM, fixes the class (ADR 0009). Effects on the faction's own pools, a tick or agenda step on a front it carries, a relation the catalogue allows, knowledge spreading: derived consequences, at the living world's level and the agent-proposal rank. A new front or situation, a changed intent or agenda, a named NPC's death or exit, any territory change: new narrative, at narrative direction, **capped at propose as today**. Anything the party would see or hear: never from the living world (LW-08).
7. **Low-fidelity mode.** With no job (no runner, or the GM's choice per faction), the Core takes the first affordable catalogue action per intent in GM-declared priority order. It is fully deterministic and is what the **forecast** runs (LW-18), so a forecast never queues a model job.
8. **Never live.** The faction turn runs inside the world-turn, so between sessions or in prep only (LW-05). It adds no live interruption.

The six invariants of ADR 0019 hold: new narrative stays at propose and nothing discloses (1); calls follow ADR 0009 and LW-09 (2); no player input is used (3); time, pools and effects move only through keyed deterministic steps, the job's output is a proposal the validator checks, and the Core calls no model (4); with no runner, low-fidelity mode runs and the world-turn report says so (5); leaks and narrative direction stay 0 (6).

## Decisions

The GM's calls on #192, accepted 2026-10-21 on PR #220.

- **(a) Who writes the catalogue?** The GM, in prep, with the agent drafting at most into `notes/` (ADR 0017). A catalogue entry is a GM decision.
- **(b) Fidelity default.** Low-fidelity for every faction until the GM opts one into jobs.
- **(c) A failed choice on a false belief.** Becomes an offscreen event the faction (and only the faction) learns, as a derived consequence.
- **(d) GM overrides.** Pause a faction (no income, no turn), pin an action, or veto one, each a GM decision on an authenticated Surface.

## Considered Options

- **Keep ADR 0009 as is**: kept until #169 and #170 land; the fronts a faction carries remain the baseline.
- **Factions as free agents writing their own actions**: rejected. The model would write the menu, costs and effects, and the class would depend on the agent.
- **A separate faction store (pools in SQLite or a sidecar)**: rejected. A second source of truth; state facts already give undo, bitemporality and audit.
- **Choices validated against the faction's beliefs**: rejected. A faction could spend resources it does not have; failing on truth is what makes a false belief matter.
- **Faction turns during play**: rejected (LW-05).

## Consequences

- LW-02 becomes "a faction acts through the fronts it carries and its catalogue". Spec 11's row "Faction simulation by agents" becomes "Factions acting outside a GM-written catalogue". New LW entries carry income, validation, contests, low-fidelity mode and overrides.
- Each occurrence links the job, the cited facts, the validation result and the debit, so the GM can read why the faction acted and what it believed.
- **Test plan.** Core unit tests: income stops at the cap; a choice outside the catalogue refuses the whole output; a prerequisite false in truth but believed fails and becomes an offscreen event known to that faction only; a cost the pools cannot cover fails; capacity is respected; a contest replays byte-identical; fault injection on the journal (ADR 0016's plan) never debits without the effect or twice; a new-narrative template is held at propose; the forecast queues no job. Bench (S0 extension): three opposing factions over six synthetic months on the sample campaign with no pool below zero, no action without prerequisites, no faction citing a fact it does not hold, replay byte-identical, leaks and narrative direction 0; job cost, GM correction rate and action diversity reported.

## GM answers (2026-10-21)

1. **Interval.** One campaign-wide step, one fictional week by default, configurable per campaign. Contests (item 5) need a shared step; a slower faction is expressed through its income and capacity, not its own clock.
2. **Territory.** Every territory change is new narrative, capped at propose, even when a catalogue template describes it. Item 6's "territory beyond the catalogue" therefore reads "any territory change". To be relaxed only if the bench shows the proposals are too many.
3. **Failed choices.** The GM sees them: the world-turn report lists each faction's ranked choices that failed validation, with the reason, collapsed by default. A failure on a false belief is often the best hook.
