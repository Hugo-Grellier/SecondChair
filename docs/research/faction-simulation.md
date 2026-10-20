# Faction intentions under bounded deterministic resources

Research for [#192](https://github.com/Hugo-Grellier/SecondChair/issues/192), parent [#187](https://github.com/Hugo-Grellier/SecondChair/issues/187). Post-v4: it amends [ADR 0009](../adr/0009-world-turn-deterministic-three-effect-classes.md) ("simulating factions as agents: rejected for v4") and LW-02, sequenced by [ADR 0019](../adr/0019-post-v4-live-assistance-and-world-horizon.md) (proposed). Depends on [#169](https://github.com/Hugo-Grellier/SecondChair/issues/169) (recoverable transactions), [#170](https://github.com/Hugo-Grellier/SecondChair/issues/170) (temporal semantics), [#174](https://github.com/Hugo-Grellier/SecondChair/issues/174) (design/canon boundary). Distinct from [#185](https://github.com/Hugo-Grellier/SecondChair/issues/185) (dramatic opportunities). No code.

## What exists

The world-turn (`src/secondchair/core/world.py`, spec [05](../spec/05-living-world-calendar.md)): fronts and situations are entities whose state is state facts; occurrences over `]cursor, now]` with keys used once (LW-04, LW-13); rule effects, derived consequences and new narrative (three classes); `unless` and new narrative become jobs (LW-06); a played contradiction becomes a call and stays queued (LW-09); undo walks the cascade (LW-12); forecast is read-only (LW-18). A faction is a knower (CAN-13) and acts only through the fronts it carries (LW-02).

## Model

Everything is state facts on the faction entity, so it is canon, bitemporal and undoable like a front (LW-03). No separate store.

| State | Shape | Written by |
|---|---|---|
| `intent` | One to three goals, each citing the fronts or situations it pursues | GM |
| `pool` | Named integer resources (coin, troops, influence, secrecy…), each with an income per fictional interval and a cap | GM; changed only by validated effects |
| `capacity` | Actions per interval | GM |
| `catalogue` | Actions: cost per pool, prerequisites (facts, relations, territory, a front's clock), duration, effect template, contest rule | GM |
| `relation` | Ally, rival, vassal… as typed relations (CAN-03) | GM, or a validated effect |
| Knowledge | What the faction knows, believes or suspects (CAN-14, CAN-15), with information latency from LW-11 | Existing knowledge model |

## The faction turn (inside the world-turn, never live)

1. **Budget.** For each interval step, the Core credits income up to the cap, deterministically, as a rule effect. Its occurrence key is `<faction>/income@<date>`.
2. **Intent job.** One ephemeral `faction-intent` job per faction (deep or standard tier) receives **only the faction's knowledge view** (`what_knows`), its pools, its catalogue and its intents. It returns up to `capacity` ranked choices **from the catalogue only**, each citing the fact ids it relied on. It cannot invent an action, a cost or an effect.
3. **Validation.** A deterministic step checks each choice against **truth**, not belief: prerequisites hold, pools cover the cost, capacity left. A choice built on a false belief fails, and the failure is an offscreen event the faction learns. Each accepted choice is an occurrence `<faction>/<action>@<date>` whose cost is debited in the same transaction as its effect (#169), so a retry cannot double-spend.
4. **Contest.** Two choices on the same target in one step resolve by the catalogue's contest rule: compare committed pools, ties and rolls seeded from the occurrence keys. A replay gives the same result.
5. **Effects by class.** The effect template decides the class, not the agent (ADR 0009):

| Effect | Class | Level and rank |
|---|---|---|
| Income, upkeep, a purely deterministic choice (no job, GM-declared priority) | Rule effect | Living world, the GM decision's rank |
| A catalogued action's effect on the faction's own pools, the fronts it carries (a tick, an agenda step), a relation the catalogue allows, knowledge spreading | Derived consequence | Living world, agent proposal |
| A new front or situation, a changed intent or agenda, a named NPC's death or exit, territory changing hands beyond the catalogue | New narrative | Narrative direction, capped at propose |
| Anything the party would see or hear | Disclosure | Never from the living world (LW-08) |

6. **Audit.** Each occurrence links the job, the cited facts, the validation result and the debit, so the GM can read *why* and *what the faction thought*.

**Low-fidelity mode.** No job: the Core takes the first affordable catalogue action per intent in GM-declared priority order. Fully deterministic; also what the **forecast** runs (LW-18), so forecasts never call a model.

**GM override.** Pause a faction (no income, no turn), pin an action, or veto one; each is a GM decision on an authenticated Surface.

## What stays GM-authored

Intents, pools, incomes, caps, capacity, catalogue (costs, prerequisites, effects, contest rules), relations at creation, territory, every new-narrative outcome, every disclosure, and the prose of any outcome the party will meet. The model chooses among what the GM wrote; it never writes the menu.

## What must change in ADR 0009

1. Replace the rejected option "simulating factions as agents" with "faction intent jobs choose from a GM-written catalogue under deterministic validation".
2. Add income and catalogue actions as occurrences with keys used once; debit and effect in one transaction.
3. Keep: never live; three classes decided by the effect; the living world never discloses; LW-09 for played contradictions.
4. LW-02 becomes "a faction acts through the fronts it carries and its catalogue".

## Bench (S0 extension)

Three opposing factions over six synthetic months on the sample campaign: no pool below zero, no action without its prerequisites, information boundaries respected (a faction never cites a fact it does not hold), replay byte-identical, retry without double-spend, no new narrative above propose, ignored PCs still produce consequences. Report job cost, GM correction rate (rejections and undos), contradictions, and diversity of chosen actions.

## Proposed leaf issues

Risk as in [live-director.md](live-director.md#proposed-leaf-issues).

| # | Title | Scope | Risk | Deps |
|---|---|---|---|---|
| F1 | ADR: faction intents | The ADR 0009 amendment above | R2 | ADR 0019 accepted |
| F2 | Faction state facts | `intent`, `pool`, `capacity`, `catalogue` as state facts, checked like `front` | R2 | F1, #170 |
| F3 | Income and debit occurrences | Keys used once; debit with effect in one transaction | R2 | F2, #169 |
| F4 | Deterministic validator and contest | Truth-checked prerequisites, seeded contest, failure as a known offscreen event | R1 | F2 |
| F5 | `faction-intent` playbook | Knowledge-view inputs, catalogue-only outputs citing fact ids | R1 | F4 |
| F6 | Low-fidelity mode and forecast | Deterministic priority policy; forecast uses it | R1 | F4 |
| F7 | GM overrides | Pause, pin, veto as GM decisions | R2 | F2 |
| F8 | S0 three-faction bench | The checks and reports above | R1 | F3–F6 |
