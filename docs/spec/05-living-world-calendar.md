# 05 — Living world and campaign calendar

Decisions: [ADR 0009](../adr/0009-world-turn-deterministic-three-effect-classes.md), [ADR 0014](../adr/0014-declarative-campaign-calendar-core-follows-paizo.md); tickets [#15](https://github.com/Hugo-Grellier/SecondChair/issues/15), [#26](https://github.com/Hugo-Grellier/SecondChair/issues/26).

## Scope

- **LW-01** The living world covers **fronts** (a clock filled by ticks at an anchored rate, an optional `unless` condition, agenda steps reached by date or clock threshold, pause and resume), **situations** (hooks, a stage relative to the party, progress, an optional deadline) and offscreen consequences.
- **LW-02** A faction acts through the fronts it carries and its catalogue ([ADR 0022](../adr/0022-factions-choose-from-a-gm-written-catalogue-under-deterministic-validation.md)).

## Model

- **LW-03** Fronts, situations and factions are entities. All their state (clock value, stage, agenda steps, deadline, stakes; a faction's intent, pools, capacity and catalogue, which the GM writes) is facts. Every tick or step is an offscreen event that closes and opens facts ([ADR 0007](../adr/0007-facts-are-the-unit-of-canon.md)). There is no separate store. A faction holds one fact per key on any date, so the GM changes one in two steps: end the current fact on a date, then record the new one starting that date.
- **LW-20** Faction pools and capacity count over one campaign-wide **faction step**, one fictional week unless the campaign sets another (`faction_step` in `workspace.yaml`). A slower faction is expressed through its income and capacity, not its own step (ADR 0022).
- **LW-21** A faction's ranked choices are validated by a deterministic Core step against **truth**, not belief, on the step's date: only the faction's GM-decided (or rule-effect) state facts are read; a choice naming no catalogue action refuses the whole output; each choice must find its pools, capacity left, its prerequisites holding and its cost covered in rank order. Two accepted choices contesting one target resolve by the pool committed, then a d20 seeded from the occurrence key `<faction>/<action>@<date>`, then the key, so a replay is identical. A failed choice is listed with its reason in the world-turn report, collapsed by default; one that failed on a false belief is an offscreen event only that faction learns, a derived consequence (ADR 0022).

## World-turn

- **LW-04** The **world-turn** is a deterministic Core computation over the fictional interval `]cursor, now]`. It schedules the due ticks, agenda steps and deadlines, each an **occurrence** with a key used only once, even if rejected. Re-running it is idempotent.
- **LW-05** Fictional time moves only through the wrap or a GM gesture, so the world-turn runs between sessions or in prep, **never during a live session**.
- **LW-06** Creative work (settling an `unless`, proposing consequences) is a job the world-turn queues. The Core calls no model.
- **LW-07** After a wrap advances the current date, a world-turn job is queued under living world ([04](04-canon-memory-capture.md)).

### Three effect classes

The class, not the agent, decides which responsibility governs an effect.

| Class | Examples | Responsibility and level | Rank |
|---|---|---|---|
| Rule effects | A tick with no condition; a dated or threshold agenda step; the expiry of a situation the party has not engaged | Living world, at its level | The GM decision that wrote the rule |
| Derived consequences | An NPC moving along its agenda; knowledge spreading to NPCs and factions; an `unless` settled by citing fact ids | Living world, at its level | Agent proposal |
| New narrative | A new front or situation; a changed agenda; the deadline of a situation the party is engaged in; the death or exit of a named NPC | Narrative direction, capped at propose | Agent proposal (until a GM decision) |

- **LW-08** The living world never discloses. Anything reaching the party goes through disclosure.
- **LW-09** An occurrence that contradicts a fact at the played rank is never applied, even a rule effect. It becomes a call on the GM (reschedule, reject or retcon) and stays queued by default.
- **LW-10** An `unless` must be settled by citing fact ids; otherwise it becomes a call on the GM due at the next break. Safe default: the tick does not happen and stays queued.
- **LW-11** Only the front's carrier and the named participants know an offscreen event. Anyone else learns it through a derived consequence that cites its facts.
- **LW-12** Undoing an effect undoes its cascade (threshold steps, consequences citing it) and returns the keys to the queue. Once the moment is frozen, only a correction or a retcon changes it.
- **LW-19** A new-narrative occurrence is linked to its narrative-direction job: every action of the job carries the occurrence. When the GM approves the proposal, the occurrence becomes applied; when the GM rejects it, the occurrence stays queued. Undoing the applied outcome returns the occurrence to the queue (LW-12). GM decision on [#111](https://github.com/Hugo-Grellier/SecondChair/issues/111), 2026-10-20.

### v3 contracts carried as Core unit tests

- **LW-13** A key is used once, even if rejected.
- **LW-14** Pause has no catch-up; resume re-anchors the rate.
- **LW-15** More than six ticks of one front in one world-turn are shown grouped, with one key each.
- **LW-16** Rescheduling creates a linked key.
- **LW-17** A late-accepted effect is dated at its original date.
- v3 criteria T1–T8 become Core unit tests ([#15](https://github.com/Hugo-Grellier/SecondChair/issues/15)).

### Forecast

- **LW-18** A **forecast** is a read-only look at what coming world-turns would do, used in prep. It writes no fact or event and moves no cursor.

## Campaign calendar

- **CAL-01** One **campaign calendar** per campaign, fixed at creation like its language. Changing it mid-campaign is out of scope.
- **CAL-02** A calendar is declarative:
  - ordered months, each with a name and a length;
  - a leap rule: a fixed interval, a first leap year, and the month that gains the day (no century exceptions; the same shape as Foundry core's `CalendarConfig`);
  - a week: length, day names, and the weekday of an anchor date;
  - one era, as a suffix.
  Years are signed integers, year 0 included. There is no intercalary concept: a festival is a one-day month.
- **CAL-03** The workspace configuration either names a calendar a System extension provides as code (`calendar: absalom`), optionally overriding its month and weekday labels for the campaign language, or declares a calendar inline.
- **CAL-04** Canon dates are numeric and day-grained (`year-month-day`, or partial `year-month` / `year`). Labels are display only and never touch identity.
- **CAL-05** Durations are in days and weeks only (the week length comes from the calendar). No month or year durations; a monthly cadence is written in days.
- **CAL-06** Time of day is not canon in v4; it stays live VTT state.
- **CAL-07** The v3 ordinal date arithmetic is transplanted, generalised to the declarative definition ([ADR 0002](../adr/0002-rebuild-rather-than-evolve.md)).

### Absalom Reckoning (PF2e System extension)

- **CAL-08** Follows Paizo: one day added to the leap month every 4 years. It does not follow the PF2e system's world clock (Gregorian + 2700 years through Luxon).
- **CAL-09** Its week is anchored so the table and the Core agree on every date between 1 Pharast 4600 and 28 Calistril 4800 AR (1 Abadius 4726 AR is Oathday).

### Foundry sync

- **CAL-10** Only a System extension's named calendar is synced with Foundry. A declared calendar (such as the sample campaign's) has no Foundry sync in v4.
- **CAL-11** At session start the PF2e system adapter pushes the campaign's current date into the world clock as a prep desired state, keeping Foundry's time of day. The Core never writes the clock live.
- **CAL-12** The adapter reads clock advances as observations.
- **CAL-13** The adapter refuses to set a date before 1 Pharast 4600 or after 28 Calistril 4800 AR (a failed action) instead of compensating for the PF2e clock's drift.
- **CAL-14** The observed clock at session start and end proposes the session's fictional interval. The GM's notes override it. The wrap asks the GM, in its grouped round, only when both are missing or they disagree. The current date moves only through the wrap or a GM gesture.
