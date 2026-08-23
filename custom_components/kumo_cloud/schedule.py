"""Working out when a zone's schedule next changes something.

An event looks like::

    {"id": "...", "days": ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"],
     "startTime": "2230", "operationMode": "cool", "fanSpeed": "auto",
     "airDirection": "horizontal", "spCool": 21.5, "spHeat": 22}

`days` are two letter codes and `startTime` is "HHMM" local to the zone.
There is no date: an event repeats on the named weekdays forever, so "next"
means searching forward from now for the first matching weekday and time.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# The API's weekday codes, in Python's Monday-first order.
DAY_CODES = ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")


def parse_start_time(value: str | None) -> tuple[int, int] | None:
    """Turn "2230" into (22, 30). Returns None if it is not four digits."""
    if not value or len(value) != 4 or not value.isdigit():
        return None
    hour, minute = int(value[:2]), int(value[2:])
    if hour > 23 or minute > 59:
        return None
    return hour, minute


def zone_timezone(name: str | None) -> ZoneInfo | None:
    """Resolve the zone's IANA timezone, if it has a usable one."""
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def next_occurrence(
    event: dict[str, Any], now: datetime, tzinfo: ZoneInfo | None
) -> datetime | None:
    """Return when this event next fires, or None if it never can.

    Searches eight days forward rather than seven, so an event scheduled
    for later today is found before the same weekday next week.
    """
    parsed = parse_start_time(event.get("startTime"))
    if parsed is None:
        return None
    hour, minute = parsed

    days = {day for day in event.get("days") or [] if day in DAY_CODES}
    if not days:
        return None

    local_now = now.astimezone(tzinfo) if tzinfo else now
    for offset in range(8):
        candidate = (local_now + timedelta(days=offset)).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        if candidate <= local_now:
            continue
        if DAY_CODES[candidate.weekday()] in days:
            return candidate
    return None


def next_event(
    events: list[dict[str, Any]], now: datetime, tzinfo: ZoneInfo | None
) -> tuple[datetime, dict[str, Any]] | None:
    """Return the soonest upcoming event and when it fires."""
    upcoming: list[tuple[datetime, dict[str, Any]]] = []
    for event in events:
        when = next_occurrence(event, now, tzinfo)
        if when is not None:
            upcoming.append((when, event))
    if not upcoming:
        return None
    return min(upcoming, key=lambda pair: pair[0])


def describe(event: dict[str, Any]) -> dict[str, Any]:
    """Summarize an event for entity attributes, dropping empty fields."""
    described: dict[str, Any] = {}
    for field, name in (
        ("operationMode", "operation_mode"),
        ("fanSpeed", "fan_speed"),
        ("airDirection", "air_direction"),
        ("spCool", "cool_setpoint"),
        ("spHeat", "heat_setpoint"),
        ("startTime", "start_time"),
    ):
        if event.get(field) is not None:
            described[name] = event[field]
    if event.get("days"):
        described["days"] = event["days"]
    return described
