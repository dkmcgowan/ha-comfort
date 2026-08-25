"""Deciding when a disconnected adapter should make its entities unavailable.

The cloud flips an adapter's `connected` flag the moment a beat is missed,
and flips it back the same way. Following that directly means the climate
entity drops to unavailable for a blip nobody would otherwise have noticed,
which breaks any automation reading it and leaves a hole in the history.

So a drop is held for a grace period. If the adapter is back before the
grace expires, nothing outside this module ever saw it go. If it is not, the
entities do go unavailable, which by then is the truth rather than a guess.

No Home Assistant imports here, so this is directly testable.
"""

from __future__ import annotations


class ConnectionGrace:
    """Tracks how long the cloud has called each adapter disconnected."""

    def __init__(self, grace: float) -> None:
        """Initialize with how many seconds a drop is tolerated for."""
        self._grace = grace
        self._since: dict[str, float] = {}

    def note(self, serial: str, connected: bool, now: float) -> str | None:
        """Record what the cloud currently says about one adapter.

        Returns "dropped" the first time it is called disconnected,
        "restored" when it comes back from that, and None when nothing
        changed, so the caller can log the edges and stay quiet in between.
        """
        if connected:
            return "restored" if self._since.pop(serial, None) is not None else None
        if serial in self._since:
            return None
        self._since[serial] = now
        return "dropped"

    def available(self, serial: str, now: float) -> bool:
        """Return whether the adapter should still be treated as reachable."""
        since = self._since.get(serial)
        if since is None:
            return True
        return (now - since) < self._grace

    def disconnected_for(self, serial: str, now: float) -> float | None:
        """Return how long the adapter has been down, or None if it is up."""
        since = self._since.get(serial)
        return None if since is None else now - since

    def forget(self, serials: set[str]) -> None:
        """Drop bookkeeping for adapters no longer on the site."""
        for serial in set(self._since) - serials:
            del self._since[serial]
