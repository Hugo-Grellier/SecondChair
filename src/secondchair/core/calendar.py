"""The campaign calendar (CAL-01..07, ADR 0014): a declarative definition and its date arithmetic.

Canon dates are numeric strings: `YYYY-MM-DD`, or partial `YYYY-MM` / `YYYY`, with a signed year
of at least four digits (`-0001-12-31`, `0000-01-01`). Month and weekday names are labels only.
The ordinal arithmetic is v3's (`pf2e-open-campaign`, `tools/bible/dates.py`), generalised.
"""

import re
from dataclasses import dataclass, field, replace
from importlib.metadata import entry_points
from typing import Any

ENTRY_POINT_GROUP = "secondchair.calendars"

_DATE = re.compile(r"(-?\d{4,})(?:-(\d{2})(?:-(\d{2}))?)?")
_DURATION = re.compile(r"([+-]?\d+)([dw])")


class CalendarError(ValueError):
    """An invalid calendar, date or duration, with a message for the GM."""


@dataclass(frozen=True)
class Month:
    name: str
    days: int


@dataclass(frozen=True)
class LeapRule:
    """One day added to `month` (1-based) every `interval` years from `first_year`, none before
    it, as in Foundry core's `CalendarConfig` (`leapStart`, `leapInterval`)."""

    interval: int
    first_year: int
    month: int


@dataclass(frozen=True)
class Calendar:
    months: tuple[Month, ...]
    leap: LeapRule | None
    weekdays: tuple[str, ...]
    anchor: str  # a full date ...
    anchor_weekday: int  # ... and its weekday, 1-based
    era: str
    # The System extension's name for it (`absalom`), None when declared inline. Only a named
    # calendar is synced with a VTT (CAL-10); the name is not part of its identity.
    name: str | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        if not self.months:
            raise CalendarError("A calendar needs at least one month in `months`.")
        for m in self.months:
            if not (isinstance(m.name, str) and m.name):
                raise CalendarError(f"Every month needs a name, got {m.name!r}.")
            if type(m.days) is not int or not 1 <= m.days <= 98:
                raise CalendarError(f"Month {m.name!r}: days must be an integer from 1 to 98.")
        if len(self.months) > 99:
            raise CalendarError("A calendar has at most 99 months.")
        if self.leap is not None:
            if type(self.leap.interval) is not int or self.leap.interval < 1:
                raise CalendarError("The leap interval must be a positive integer.")
            if type(self.leap.first_year) is not int:
                raise CalendarError("The leap first_year must be an integer.")
            if self.leap.month not in range(1, len(self.months) + 1):
                raise CalendarError(f"The leap month must be from 1 to {len(self.months)}.")
        if not self.weekdays or not all(isinstance(d, str) and d for d in self.weekdays):
            raise CalendarError("The week needs at least one named day.")
        if self.anchor_weekday not in range(1, len(self.weekdays) + 1):
            raise CalendarError(f"The anchor weekday must be from 1 to {len(self.weekdays)}.")
        self.parse(self.anchor)
        if not (isinstance(self.era, str) and self.era):
            raise CalendarError("The calendar needs an era suffix in `era`.")

    # Dates

    def is_leap(self, year: int) -> bool:
        if self.leap is None or year < self.leap.first_year:
            return False
        return (year - self.leap.first_year) % self.leap.interval == 0

    def month_length(self, year: int, month: int) -> int:
        leap_day = self.leap is not None and month == self.leap.month and self.is_leap(year)
        return self.months[month - 1].days + leap_day

    def parse(self, value: Any, partial: bool = False) -> tuple[int, int, int]:
        """(year, month, day), 0 for an absent part. Takes a str, an int year or a YAML date."""
        is_year = isinstance(value, int) and not isinstance(value, bool)
        match = _DATE.fullmatch(_format(value, 0, 0) if is_year else str(value))
        if match is None or (not partial and match[3] is None):
            expected = "YYYY-MM-DD" + (" (or YYYY-MM, YYYY)" if partial else "")
            raise CalendarError(f"Date {value!r}: expected {expected}.")
        year, month, day = (int(g) if g is not None else 0 for g in match.groups())
        if (match[2] is not None and not 1 <= month <= len(self.months)) or (
            match[3] is not None and not 1 <= day <= self.month_length(year, month)
        ):
            raise CalendarError(f"Date {value!r}: month or day outside the campaign calendar.")
        return year, month, day

    def is_date(self, value: Any, partial: bool = False) -> bool:
        try:
            self.parse(value, partial)
        except CalendarError:
            return False
        return True

    def canonical(self, value: Any, partial: bool = False) -> str:
        """The stored form of a date: labels never touch it (CAL-04)."""
        return _format(*self.parse(value, partial))

    def sort_key(self, value: Any) -> tuple[int, int, int]:
        return self.parse(value, partial=True)

    def add(self, value: Any, duration: str) -> str:
        return self._from_ordinal(self._ordinal(*self.parse(value)) + self._signed_days(duration))

    def diff(self, a: Any, b: Any) -> int:
        """Days from `a` to `b`."""
        return self._ordinal(*self.parse(b)) - self._ordinal(*self.parse(a))

    def days(self, duration: str) -> int:
        """Days of a positive, unsigned duration (`7d`, `2w`): a cadence step."""
        if str(duration)[:1] in "+-" or self._signed_days(duration) <= 0:
            raise CalendarError(f"Duration {duration!r}: expected a positive Nd or Nw (7d, 2w).")
        return self._signed_days(duration)

    def weekday(self, value: Any) -> int:
        """The weekday of a full date, 1-based."""
        offset = self.diff(self.anchor, value)
        return (self.anchor_weekday - 1 + offset) % len(self.weekdays) + 1

    def weekday_name(self, value: Any) -> str:
        return self.weekdays[self.weekday(value) - 1]

    def display(self, value: Any) -> str:
        year, month, day = self.parse(value, partial=True)
        parts = [str(day)] if day else []
        if month:
            parts.append(self.months[month - 1].name)
        return " ".join([*parts, str(year), self.era])

    def relabel(self, months: list[str] | None, weekdays: list[str] | None) -> Calendar:
        """The same calendar with display labels overridden for the campaign language."""
        names = [m.name for m in self.months]
        for labels, current in ((months, names), (weekdays, self.weekdays)):
            if labels is not None and (not isinstance(labels, list) or len(labels) != len(current)):
                raise CalendarError(f"Expected a list of {len(current)} labels, got {labels!r}.")
        return replace(
            self,
            months=tuple(
                Month(n, m.days) for n, m in zip(months or names, self.months, strict=True)
            ),
            weekdays=tuple(weekdays or self.weekdays),
        )

    # Ordinal arithmetic: days since 0000-01-01.

    def _signed_days(self, duration: str) -> int:
        match = _DURATION.fullmatch(str(duration))
        if match is None:
            raise CalendarError(
                f"Duration {duration!r}: expected Nd or Nw (10d, -3d, 2w); "
                "durations are in days and weeks only."
            )
        return int(match[1]) * (len(self.weekdays) if match[2] == "w" else 1)

    def _leaps_before(self, year: int) -> int:
        """Leap years in [0, year), negative for a negative year."""
        leap = self.leap
        if leap is None:
            return 0

        def up_to(y: int) -> int:  # leap years before y, counted from the first one
            return max(0, -((leap.first_year - y) // leap.interval))

        return up_to(year) - up_to(0)

    def _year_start(self, year: int) -> int:
        return sum(m.days for m in self.months) * year + self._leaps_before(year)

    def _ordinal(self, year: int, month: int, day: int) -> int:
        before = sum(self.month_length(year, m) for m in range(1, month))
        return self._year_start(year) + before + day - 1

    def _from_ordinal(self, n: int) -> str:
        year = n // (sum(m.days for m in self.months) + 1)
        while self._year_start(year + 1) <= n:
            year += 1
        while self._year_start(year) > n:
            year -= 1
        n -= self._year_start(year)
        month = 1
        while n >= self.month_length(year, month):
            n -= self.month_length(year, month)
            month += 1
        return _format(year, month, n + 1)


def _format(year: int, month: int, day: int) -> str:
    text = f"-{-year:04d}" if year < 0 else f"{year:04d}"
    return text + "".join(f"-{part:02d}" for part in (month, day) if part)


def from_config(value: Any) -> Calendar:
    """The calendar a workspace configures (CAL-03): a System extension's calendar by name
    (`absalom`, or `{name: absalom, labels: {months: [...], weekdays: [...]}}`), or one declared
    inline (`{months, leap, week, era}`)."""
    if isinstance(value, str):
        return _named(value)
    if not isinstance(value, dict):
        raise CalendarError("`calendar` must be a calendar name or a mapping.")
    if "name" in value:
        _no_other_keys(value, {"name", "labels"})
        labels = value.get("labels") or {}
        if not isinstance(labels, dict):
            raise CalendarError("`labels` must be a mapping of `months` and `weekdays`.")
        _no_other_keys(labels, {"months", "weekdays"})
        return _named(value["name"]).relabel(labels.get("months"), labels.get("weekdays"))
    _no_other_keys(value, {"months", "leap", "week", "era"})
    try:
        leap = value.get("leap")
        week = value["week"]
        _no_other_keys(week, {"days", "anchor"})
        return Calendar(
            months=tuple(Month(m["name"], m["days"]) for m in value["months"]),
            leap=LeapRule(leap["interval"], leap["first_year"], leap["month"]) if leap else None,
            weekdays=tuple(week["days"]),
            anchor=week["anchor"]["date"],
            anchor_weekday=week["anchor"]["weekday"],
            era=value["era"],
        )
    except (KeyError, TypeError) as e:
        raise CalendarError(
            f"An inline calendar needs months (name, days), week (days, anchor: date, weekday) "
            f"and era; problem with {e}."
        ) from e


def available_calendars() -> list[str]:
    """The calendar names the installed System extensions provide."""
    return sorted(ep.name for ep in entry_points(group=ENTRY_POINT_GROUP))


def _named(name: Any) -> Calendar:
    found = {ep.name: ep for ep in entry_points(group=ENTRY_POINT_GROUP)}
    if name not in found:
        known = ", ".join(sorted(found)) or "none installed"
        raise CalendarError(f"No System extension provides the calendar {name!r} ({known}).")
    calendar = found[name].load()
    if not isinstance(calendar, Calendar):
        raise CalendarError(f"The calendar entry point {name!r} is not a Calendar.")
    return replace(calendar, name=name)


def _no_other_keys(mapping: Any, allowed: set[str]) -> None:
    if not isinstance(mapping, dict):
        raise CalendarError(f"Expected a mapping with keys {sorted(allowed)}, got {mapping!r}.")
    if extra := set(mapping) - allowed:
        raise CalendarError(f"Unknown calendar keys {sorted(extra)}; expected {sorted(allowed)}.")
