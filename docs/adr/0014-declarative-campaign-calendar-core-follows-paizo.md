# The campaign calendar is declarative, and the Core follows Paizo over the PF2e clock

Each campaign has one calendar, fixed at creation like its language. A calendar is a declarative definition: ordered months (name, length), a leap rule written as a fixed interval plus a first leap year and the month that gains the day, a week (length, names, the weekday of an anchor date) and one era (suffix). Years are signed integers, year 0 included. The workspace configuration either names a calendar a System extension provides as code (`calendar: absalom`, ADR 0002), optionally overriding its month and weekday labels for the campaign language, or declares its own calendar inline. Canon dates are numeric and day-grained (`year-month-day`, or partial `year-month` / `year`), so labels never touch identity, and durations come only in days and weeks (the week's length comes from the calendar). The leap rule takes the same shape as Foundry's core `CalendarConfig`, which has no century exceptions, and that is also Paizo's rule for Absalom Reckoning (a day added to Calistril every 4 years, Core Rulebook p. 419).

The PF2e system's world clock does not follow it. It is Gregorian plus 2,700 years through Luxon, so it drops the 29th of Calistril in 4800 AR and drifts afterwards, and it lacks the 29th of Calistril in 4600 AR, so it is a day apart before that. We chose Paizo's rule for the Core, because canon dates cannot be migrated cheaply, and we anchor the Absalom week on the PF2e clock (1 Abadius 4726 AR is Oathday), so the table and the Core agree on every date between 1 Pharast 4600 and 28 Calistril 4800 AR.

## Considered Options

- **Leap rules as code or with Gregorian-style century exceptions**: rejected. A closed shape stays checkable and expressible in Foundry's core calendar.
- **Follow the PF2e clock (Gregorian)**: rejected. It is an implementation artefact that contradicts Paizo, and it would leave the arithmetic tied to Luxon.
- **Month and year durations**: rejected for v4. Clamping to month ends makes the arithmetic non-associative, so a monthly cadence is written in days.
- **Translated labels read from the GM's install**: not needed. The labels are a small, fixed set, so the workspace overrides them.

## Consequences

- Foundry sync covers only the System extension's named calendar. At session start the PF2e system adapter pushes the campaign's current date into the world clock as a prep desired state, keeping Foundry's time of day, and it reads clock advances as observations. The Core never writes the clock live. A declared calendar such as the sample campaign's has no Foundry sync in v4.
- The adapter refuses to set a date before 1 Pharast 4600 or after 28 Calistril 4800 AR (a failed action) instead of compensating for the PF2e clock's drift.
- The observed clock at session start and end proposes the session's fictional interval. The GM's notes override it, and the wrap asks the GM, in its grouped round, only when both are missing or they disagree. The current date still moves only through the wrap or a GM gesture (ADR 0009).
- The sample campaign declares a deliberately different calendar (10 months, a 6-day week, a one-day festival month, a leap interval other than 4), so that S0 exercises the generic format.
- Time of day is not canon in v4. It stays live VTT state.
