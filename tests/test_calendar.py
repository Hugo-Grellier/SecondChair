"""The campaign calendar (CAL-01..09): v3 test cases on the declarative definition."""

from datetime import date, timedelta

import pytest

from secondchair.calendar import Calendar, CalendarError, from_config
from secondchair_pf2e.calendar import ABSALOM

AR = ABSALOM
MONTHS = ["Abadius", "Calistril", "Pharast", "Gozran", "Desnus", "Sarenith",
          "Erastus", "Arodus", "Rova", "Lamashan", "Neth", "Kuthona"]  # fmt: skip


# v3 test cases (pf2e-open-campaign, tools/tests/test_dates.py), ported (BVE-01, CAL-07)


def test_months_and_leap_years() -> None:
    assert [AR.display(f"4726-{m:02d}-01").split()[1] for m in range(1, 13)] == MONTHS
    assert AR.is_leap(4724) and not AR.is_leap(4726) and AR.is_leap(4700)
    assert AR.is_date("4724-02-29") and not AR.is_date("4726-02-29") and AR.is_date("4700-02-29")
    assert AR.is_date("4726-04-30") and not AR.is_date("4726-04-31")
    assert not AR.is_date("4726-13-01")
    for bad in ("4726-4-14", "26-04-14", "4726-04-14T10", "", None, "4726-00-10", "4726-04"):
        assert not AR.is_date(bad), bad


def test_partial_dates_sort_at_period_start() -> None:
    assert AR.is_date("4726-04", partial=True) and AR.is_date("4726", partial=True)
    assert AR.is_date(4726, partial=True)
    assert not AR.is_date("4726-13", partial=True) and not AR.is_date("4726-00", partial=True)
    ordered = sorted(["4726-04-14", "4726-04", "4726", "4725-12-31", "4726-04-01"], key=AR.sort_key)
    assert ordered == ["4725-12-31", "4726", "4726-04", "4726-04-01", "4726-04-14"]


def test_add_and_diff() -> None:
    assert AR.add("4726-04-14", "10d") == "4726-04-24"
    assert AR.add("4726-04-25", "1w") == "4726-05-02"
    assert AR.add("4726-12-31", "1d") == "4727-01-01"
    assert AR.add("4724-02-28", "1d") == "4724-02-29"
    assert AR.add("4726-02-28", "1d") == "4726-03-01"
    assert AR.add("4726-03-01", "-1d") == "4726-02-28"
    assert AR.add("4726-01-10", "+0d") == "4726-01-10"
    assert AR.add(date(4726, 4, 14), "0d") == "4726-04-14"  # an unquoted YAML date
    assert AR.diff("4726-01-01", "4727-01-01") == 365
    assert AR.diff("4724-01-01", "4725-01-01") == 366
    assert AR.diff("4726-04-24", "4726-04-14") == -10
    for bad in ("10", "d", "+-3d", "3 d"):
        with pytest.raises(CalendarError):
            AR.add("4726-04-14", bad)
    with pytest.raises(CalendarError, match="4726-02-30"):
        AR.add("4726-02-30", "1d")


def test_display() -> None:
    assert AR.display("4726-09-14") == "14 Rova 4726 AR"
    assert AR.display("4726-09") == "Rova 4726 AR" and AR.display("4726") == "4726 AR"


# Absalom Reckoning (CAL-08, CAL-09)


def test_1_abadius_4726_is_oathday() -> None:
    assert AR.weekday_name("4726-01-01") == "Oathday"


def test_calistril_gains_a_day_every_4_years_including_4800() -> None:
    for year in (4720, 4724, 4796, 4800, 4900, 5000):
        assert AR.is_date(f"{year}-02-29"), year
        assert AR.diff(f"{year}-01-01", f"{year + 1}-01-01") == 366
    for year in (4721, 4722, 4723, 4801):
        assert not AR.is_date(f"{year}-02-29"), year
    assert AR.add("4800-02-28", "1d") == "4800-02-29"


def test_week_agrees_with_the_pf2e_clock_before_4800() -> None:
    # The PF2e clock is Gregorian + 2700 years, Moonday = Monday. Checked against the stdlib
    # from 1 Pharast 4600 (Gregorian has no 29 February 1900) to 28 Calistril 4800.
    names = ("Moonday", "Toilday", "Wealday", "Oathday", "Fireday", "Starday", "Sunday")
    day, last = date(1900, 3, 1), date(2100, 2, 28)
    while day <= last:
        absalom = f"{day.year + 2700:04d}-{day.month:02d}-{day.day:02d}"
        assert AR.weekday_name(absalom) == names[day.weekday()], absalom
        day += timedelta(days=37)
    assert AR.weekday_name("4800-02-28") == names[last.weekday()]
    # From 29 Calistril 4800 on, the Core follows Paizo and the PF2e clock is a day behind.
    assert AR.weekday_name("4800-03-01") != names[date(2100, 3, 1).weekday()]


# Durations (CAL-05)


@pytest.mark.parametrize("duration", ["1m", "2y", "1mo"])
def test_month_or_year_durations_are_refused(duration: str) -> None:
    with pytest.raises(CalendarError, match="days and weeks only"):
        AR.add("4726-04-14", duration)


def test_days_of_a_positive_duration() -> None:
    assert AR.days("7d") == 7 and AR.days("2w") == 14
    for bad in ("0d", "-1d", "+1d", "1m"):
        with pytest.raises(CalendarError):
            AR.days(bad)


# A declared calendar (CAL-02, CAL-03), shaped like the sample campaign's (ADR 0014):
# 10 months, a 6-day week, a one-day festival month, a leap interval other than 4.

SAMPLE = {
    "months": [
        {"name": "Thaw", "days": 36},
        {"name": "Seedfall", "days": 36},
        {"name": "Bloom", "days": 37},
        {"name": "Highsun", "days": 36},
        {"name": "Lanternnight", "days": 1},
        {"name": "Ember", "days": 36},
        {"name": "Reaping", "days": 36},
        {"name": "Mist", "days": 36},
        {"name": "Frost", "days": 36},
        {"name": "Deepwinter", "days": 35},
    ],
    "leap": {"interval": 5, "first_year": 2, "month": 5},
    "week": {
        "days": ["Oneday", "Twoday", "Threeday", "Fourday", "Fiveday", "Restday"],
        "anchor": {"date": "0300-01-01", "weekday": 3},
    },
    "era": "AF",
}


def test_a_declared_calendar_validates_and_round_trips_dates() -> None:
    cal = from_config(SAMPLE)
    assert isinstance(cal, Calendar)
    assert cal.is_leap(2) and cal.is_leap(-3) and cal.is_leap(302) and not cal.is_leap(300)
    assert cal.is_date("0302-05-02") and not cal.is_date("0300-05-02")
    assert cal.diff("0300-01-01", "0301-01-01") == 325
    assert cal.diff("0302-01-01", "0303-01-01") == 326
    assert cal.add("0300-04-36", "1d") == "0300-05-01"
    assert cal.add("0300-05-01", "1d") == "0300-06-01"
    assert cal.add("0300-01-01", "1w") == "0300-01-07"
    assert cal.weekday_name("0300-01-01") == "Threeday"
    assert cal.weekday_name("0300-01-07") == "Threeday"
    assert cal.weekday_name("0299-10-35") == "Twoday"
    assert cal.display("0302-05-02") == "2 Lanternnight 302 AF"
    start = "-0007-01-01"  # across common and leap years, and year 0
    for n in range(0, 15 * 326, 7):
        later = cal.add(start, f"{n}d")
        assert cal.is_date(later)
        assert cal.diff(start, later) == n
        assert cal.add(later, f"-{n}d") == start


def test_year_zero_and_negative_years_exist() -> None:
    assert AR.add("-0001-12-31", "1d") == "0000-01-01"
    assert AR.is_leap(0) and AR.is_leap(-4) and not AR.is_leap(-1)
    assert AR.diff("-0001-01-01", "0001-01-01") == 365 + 366
    assert AR.display("-0010") == "-10 AR"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"months": []}, "months"),
        ({"months": [{"name": "A", "days": 0}]}, "days"),
        ({"leap": {"interval": 0, "first_year": 0, "month": 1}}, "interval"),
        ({"leap": {"interval": 4, "first_year": 0, "month": 11}}, "leap month"),
        ({"week": {"days": [], "anchor": {"date": "0300-01-01", "weekday": 1}}}, "week"),
        ({"week": {"days": ["A"], "anchor": {"date": "0300-01-01", "weekday": 2}}}, "weekday"),
        ({"week": {"days": ["A"], "anchor": {"date": "0300-11-01", "weekday": 1}}}, "0300-11-01"),
        ({"era": ""}, "era"),
        ({"seasons": 4}, "seasons"),
    ],
)
def test_an_invalid_declared_calendar_is_refused(change: dict, message: str) -> None:
    with pytest.raises(CalendarError, match=message):
        from_config({**SAMPLE, **change})


# Named calendars and label overrides (CAL-03, CAL-04)


def test_a_named_calendar_comes_from_a_system_extension() -> None:
    assert from_config("absalom") == ABSALOM
    assert from_config({"name": "absalom"}) == ABSALOM
    with pytest.raises(CalendarError, match="gregorian"):
        from_config("gregorian")


def test_overriding_labels_changes_display_only() -> None:
    months = [*MONTHS[:8], "Rova-fr", *MONTHS[9:]]
    weekdays = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    fr = from_config({"name": "absalom", "labels": {"months": months, "weekdays": weekdays}})
    assert fr.display("4726-09-14") == "14 Rova-fr 4726 AR"
    assert fr.weekday_name("4726-01-01") == "Jeudi"
    for value in ("4726-09-14", "4724-02-29", "4726-09"):
        assert fr.canonical(value, partial=True) == AR.canonical(value, partial=True) == value
    assert fr.add("4726-09-14", "3w") == AR.add("4726-09-14", "3w") == "4726-10-05"
    with pytest.raises(CalendarError, match="12"):
        from_config({"name": "absalom", "labels": {"months": ["Only one"]}})
