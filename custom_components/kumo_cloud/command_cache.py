"""Holds a just-sent value in place until the cloud reports it back.

The cloud can lag the equipment by up to a minute. Without this, moving a
slider or changing a mode shows the new value, then snaps back to the old
one on the next update, then forward again once the cloud agrees. The card
visibly flickers.

**The rule is: hold the value until the server reports that same value,
then let go. Give up after a timeout.**

An earlier version compared the client's clock against the server's
`updatedAt` and dropped the held value as soon as `updatedAt` was the newer
of the two. That fails two ways. Any clock skew between the machine running
Home Assistant and the cloud makes it drop immediately, and `updatedAt`
moves whenever the record changes for any reason, not only when the command
lands, so an unrelated telemetry update releases the hold early. Both let
the old value flash back. Comparing the value has no clock in it.

No Home Assistant imports here, so this is directly testable.
"""

from __future__ import annotations

from typing import Any

# How long a value is held while the cloud catches up. Long enough to cover
# the observed lag, short enough that a command the equipment refused stops
# being displayed reasonably soon.
DEFAULT_TIMEOUT = 90.0

# Setpoints round trip as floats, so compare with a tolerance rather than for
# equality. Half the smallest step the equipment accepts.
SETPOINT_TOLERANCE = 0.25


def values_match(reported: Any, wanted: Any) -> bool:
    """Return whether the cloud is now reporting the value we asked for."""
    if isinstance(wanted, bool) or isinstance(reported, bool):
        return reported == wanted
    if isinstance(wanted, int | float) and isinstance(reported, int | float):
        return abs(reported - wanted) <= SETPOINT_TOLERANCE
    return reported == wanted


class CommandCache:
    """Per device, per field, the value we are waiting for the cloud to echo."""

    def __init__(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        """Initialize an empty cache."""
        self._timeout = timeout
        self._pending: dict[tuple[str, str], tuple[float, Any]] = {}

    def __len__(self) -> int:
        """Return how many values are being held."""
        return len(self._pending)

    def remember(self, serial: str, field: str, value: Any, now: float) -> None:
        """Record a value we just asked for.

        `now` is a monotonic reading. Nothing here is ever compared against a
        server timestamp, because the two clocks are not the same clock.
        """
        self._pending[(serial, field)] = (now, value)

    def apply(self, serial: str, record: dict[str, Any], now: float) -> dict[str, Any]:
        """Overlay held values onto a device record, releasing what has landed.

        Mutates and returns `record`, which is the freshly fetched or pushed
        state for this device.
        """
        for key in list(self._pending):
            held_serial, field = key
            if held_serial != serial:
                continue

            sent_at, wanted = self._pending[key]

            if values_match(record.get(field), wanted):
                del self._pending[key]
                continue

            if now - sent_at > self._timeout:
                del self._pending[key]
                continue

            record[field] = wanted

        return record

    def pending_fields(self, serial: str) -> set[str]:
        """Return the fields currently held for one device, for diagnostics."""
        return {field for held, field in self._pending if held == serial}
