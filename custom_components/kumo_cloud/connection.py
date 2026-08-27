"""Reading what the cloud says about an adapter's connection.

**The `connected` field on the device record is not a liveness signal, and
nothing here decides availability from it.** Measured against the live
account on 2026-08-26: all four adapters read `connected: false`, all four
carried the identical `updatedAt` to within 600 milliseconds, all four had
an open session in `/zones/{id}/connection-history` that had been running
for between one and six days, and all four were reporting current room
temperatures. A field that flips on every adapter at once, on the same
cloud-side write, while the hardware is plainly talking, is a record of
something else. The Comfort app shows nothing wrong the whole time.

That flag is what entity availability used to key on, first directly and
then behind a grace period. Both were wrong in the same way: the units
disappeared from Home Assistant overnight while the app worked, and came
back the moment anything touched a unit and the cloud wrote `true` again.
The grace only changed how long it took. So the gate is gone. An entity is
unavailable when Home Assistant cannot say what the state is, not when a
vendor field reads false.

What is left here reads the connection history, which does track real
events: every zone closed a session within two minutes of a WiFi channel
change. It feeds the diagnostic sensors, and nothing else.

No Home Assistant imports here, so this is directly testable.
"""

from __future__ import annotations


def has_open_session(rows: list[dict]) -> bool | None:
    """Return whether the zone's history shows a session still running.

    This is the honest answer to "is the adapter on the network", as far as
    the cloud has one. Returns None when there is no history to read, which
    is not the same as a no: the history sits on the slow poll tier, so a
    zone can go a while after startup without any.
    """
    if not rows:
        return None
    return any(row.get("isConnected") and row.get("end") is None for row in rows)


def summarize_history(
    rows: list[dict], now: float
) -> dict[str, float | int | None]:
    """Turn `/zones/{id}/connection-history` into outage figures.

    **Each row is a connected session, not an outage.** `isConnected` marks
    only the currently open row; every closed row reads false whatever
    happened during it. The outages are the *gaps between* sessions.

    This was read the other way round at first, which turned a healthy
    adapter into one that looked down for days. The arithmetic settles it:
    read as outages, the rows sum to far more than the window they cover,
    which cannot happen. Read as sessions they sum to just under it, and the
    shortfall is the downtime.

    `rows` are `{start, end, isConnected, uptime}` with `start` and `end` as
    epoch seconds, `end` None on the open row. `now` is epoch seconds.
    Returns durations in minutes and availability as a percentage.
    """
    sessions = sorted(
        (row["start"], row["end"] if row.get("end") is not None else now)
        for row in rows
        if row.get("start") is not None
    )
    if not sessions:
        return {
            "sessions": 0,
            "outages": 0,
            "downtime_minutes": None,
            "longest_outage_minutes": None,
            "availability_percent": None,
        }

    window = now - sessions[0][0]
    gaps = []
    previous_end = None
    for start, end in sessions:
        if previous_end is not None and start > previous_end:
            gaps.append(start - previous_end)
        previous_end = max(previous_end or end, end)

    downtime = sum(gaps)
    return {
        "sessions": len(sessions),
        "outages": len(gaps),
        "downtime_minutes": round(downtime / 60, 1),
        "longest_outage_minutes": round(max(gaps) / 60, 1) if gaps else 0.0,
        "availability_percent": (
            round(100.0 * (window - downtime) / window, 2) if window > 0 else None
        ),
        "window_hours": round(window / 3600, 1),
    }
