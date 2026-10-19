"""Absalom Reckoning as code, with no data (BVE-03, CAL-08, CAL-09, ADR 0014).

Paizo's rule, not the PF2e system's Gregorian world clock: Calistril gains a day every 4 years,
4800 AR included (Core Rulebook p. 419). The week is anchored on the PF2e clock, where
1 Abadius 4726 AR is Oathday, so the table and the Core agree before 4800 AR.
"""

from secondchair.core.calendar import Calendar, LeapRule, Month

ABSALOM = Calendar(
    months=(
        Month("Abadius", 31),
        Month("Calistril", 28),
        Month("Pharast", 31),
        Month("Gozran", 30),
        Month("Desnus", 31),
        Month("Sarenith", 30),
        Month("Erastus", 31),
        Month("Arodus", 31),
        Month("Rova", 30),
        Month("Lamashan", 31),
        Month("Neth", 30),
        Month("Kuthona", 31),
    ),
    leap=LeapRule(interval=4, first_year=0, month=2),
    weekdays=("Moonday", "Toilday", "Wealday", "Oathday", "Fireday", "Starday", "Sunday"),
    anchor="4726-01-01",
    anchor_weekday=4,
    era="AR",
)
