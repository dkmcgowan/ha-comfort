"""Tests for working out when a schedule event next fires.

`schedule.py` has no Home Assistant or third party imports, so it is loaded
off disk like the other pure modules.
"""

from datetime import datetime
import importlib.util
import pathlib
from zoneinfo import ZoneInfo

import pytest

_PATH = pathlib.Path(__file__).parent.parent / "custom_components" / "kumo_cloud" / "schedule.py"
_SPEC = importlib.util.spec_from_file_location("kumo_schedule", _PATH)
schedule = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(schedule)

NY = ZoneInfo("America/New_York")

# The real event from the account this was built against.
NIGHTLY = {
    "id": "9e36c845",
    "days": ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"],
    "startTime": "2230",
    "operationMode": "cool",
    "fanSpeed": "auto",
    "airDirection": "horizontal",
    "spCool": 21.5,
    "spHeat": 22,
}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2230", (22, 30)),
        ("0000", (0, 0)),
        ("0905", (9, 5)),
        ("2359", (23, 59)),
        ("2400", None),
        ("2360", None),
        ("930", None),
        ("", None),
        (None, None),
        ("abcd", None),
    ],
)
def test_parse_start_time(value, expected):
    assert schedule.parse_start_time(value) == expected


def test_next_occurrence_later_today():
    """An event at 22:30 with 'now' at 18:00 fires today, not next week."""
    now = datetime(2026, 8, 23, 18, 0, tzinfo=NY)
    found = schedule.next_occurrence(NIGHTLY, now, NY)
    assert found == datetime(2026, 8, 23, 22, 30, tzinfo=NY)


def test_next_occurrence_rolls_to_tomorrow():
    """Past today's time, so the next one is tomorrow."""
    now = datetime(2026, 8, 23, 23, 0, tzinfo=NY)
    found = schedule.next_occurrence(NIGHTLY, now, NY)
    assert found == datetime(2026, 8, 24, 22, 30, tzinfo=NY)


def test_next_occurrence_skips_to_the_named_weekday():
    """A weekday-only event from a Sunday lands on Monday."""
    weekdays = {**NIGHTLY, "days": ["Mo", "Tu", "We", "Th", "Fr"]}
    now = datetime(2026, 8, 23, 12, 0, tzinfo=NY)  # a Sunday
    found = schedule.next_occurrence(weekdays, now, NY)
    assert found == datetime(2026, 8, 24, 22, 30, tzinfo=NY)
    assert found.strftime("%a") == "Mon"


def test_a_single_weekday_a_week_out():
    """The eight day search window still finds a once-weekly event."""
    sunday_only = {**NIGHTLY, "days": ["Su"]}
    now = datetime(2026, 8, 23, 23, 0, tzinfo=NY)  # Sunday, after the time
    found = schedule.next_occurrence(sunday_only, now, NY)
    assert found == datetime(2026, 8, 30, 22, 30, tzinfo=NY)


def test_no_days_never_fires():
    assert schedule.next_occurrence({**NIGHTLY, "days": []}, datetime.now(NY), NY) is None


def test_unknown_day_codes_are_ignored():
    assert (
        schedule.next_occurrence({**NIGHTLY, "days": ["Xx"]}, datetime.now(NY), NY) is None
    )


def test_bad_start_time_never_fires():
    assert (
        schedule.next_occurrence({**NIGHTLY, "startTime": "99"}, datetime.now(NY), NY)
        is None
    )


def test_next_event_picks_the_soonest():
    morning = {**NIGHTLY, "id": "morning", "startTime": "0600"}
    now = datetime(2026, 8, 23, 1, 0, tzinfo=NY)
    when, event = schedule.next_event([NIGHTLY, morning], now, NY)
    assert event["id"] == "morning"
    assert when == datetime(2026, 8, 23, 6, 0, tzinfo=NY)


def test_next_event_with_nothing_scheduled():
    assert schedule.next_event([], datetime.now(NY), NY) is None


def test_zone_timezone_resolution():
    assert schedule.zone_timezone("America/New_York") == NY
    assert schedule.zone_timezone("Not/AZone") is None
    assert schedule.zone_timezone(None) is None
    assert schedule.zone_timezone("") is None


def test_describe_drops_empty_fields():
    described = schedule.describe({**NIGHTLY, "spHeat": None})
    assert described["operation_mode"] == "cool"
    assert described["cool_setpoint"] == 21.5
    assert "heat_setpoint" not in described
    assert described["days"] == NIGHTLY["days"]


def test_utc_now_is_converted_to_the_zone():
    """A UTC 'now' must be judged in the zone's local time.

    03:00 UTC is 23:00 the previous evening in New York, which is after the
    22:30 event, so the answer is the following evening rather than that
    same morning.
    """
    utc_now = datetime(2026, 8, 24, 3, 0, tzinfo=ZoneInfo("UTC"))
    found = schedule.next_occurrence(NIGHTLY, utc_now, NY)
    assert found == datetime(2026, 8, 24, 22, 30, tzinfo=NY)
