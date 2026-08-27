"""Tests for reading the cloud's connection signals.

Written after every zone's climate entity went unavailable overnight while
the Comfort app showed nothing wrong. The cause was the `connected` field on
the device record, which reads false on all four adapters at once, on one
cloud-side write, while they are reporting live room temperatures.
Availability no longer looks at it, so what is left to test here is reading
the session history, which does track real events.

`connection.py` imports no Home Assistant, so it is loaded straight off disk
the way `test_command_cache.py` does it.
"""

import importlib.util
import pathlib

_PATH = (
    pathlib.Path(__file__).parent.parent
    / "custom_components"
    / "kumo_cloud"
    / "connection.py"
)
_SPEC = importlib.util.spec_from_file_location("kumo_connection", _PATH)
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

has_open_session = _MODULE.has_open_session


class TestHasOpenSession:
    """The one connection signal that has held up against the hardware.

    Pinned against the live account on 2026-08-26: all four zones had an
    open session running for between one and six days while the device
    record called every one of them disconnected.
    """

    def test_no_history_is_not_an_answer(self):
        """The history is on the slow tier, so a zone can have none yet."""
        assert has_open_session([]) is None

    def test_an_open_row_means_connected(self):
        """`end` absent and `isConnected` set is the live session."""
        rows = [{"start": 100.0, "end": None, "isConnected": True}]
        assert has_open_session(rows) is True

    def test_every_row_closed_means_disconnected(self):
        """Nothing open is the cloud saying the adapter is off the network."""
        rows = [
            {"start": 100.0, "end": 200.0, "isConnected": False},
            {"start": 0.0, "end": 90.0, "isConnected": False},
        ]
        assert has_open_session(rows) is False

    def test_the_open_row_is_found_among_closed_ones(self):
        """Rows arrive newest first, but the position is not relied on."""
        rows = [
            {"start": 300.0, "end": None, "isConnected": True},
            {"start": 100.0, "end": 200.0, "isConnected": False},
        ]
        assert has_open_session(rows) is True

    def test_a_closed_row_flagged_connected_is_not_open(self):
        """Both halves are required, since only the open row carries the flag."""
        rows = [{"start": 100.0, "end": 200.0, "isConnected": True}]
        assert has_open_session(rows) is False


class TestSummarizeHistory:
    """Reading connection history as sessions rather than as outages.

    Pinned against a live account on 2026-08-25. Read as outages, one zone's
    rows summed to several times the window they covered, which is the
    contradiction that caught the mistake. Read as sessions the same rows
    give 99.67 percent availability, and the 2 minute gaps between them are
    the reconnects.
    """

    def test_no_history_says_nothing(self):
        """A zone the slow tier has not reached yet."""
        summary = _MODULE.summarize_history([], 1000.0)
        assert summary["outages"] == 0
        assert summary["availability_percent"] is None

    def test_one_open_session_is_a_clean_run(self):
        """The common case: connected since setup, never dropped."""
        summary = _MODULE.summarize_history([{"start": 0.0, "end": None}], 3600.0)
        assert summary["sessions"] == 1
        assert summary["outages"] == 0
        assert summary["downtime_minutes"] == 0.0
        assert summary["availability_percent"] == 100.0

    def test_the_gap_between_sessions_is_the_outage(self):
        """Two sessions 120 seconds apart is one 2 minute outage."""
        rows = [
            {"start": 0.0, "end": 1800.0},
            {"start": 1920.0, "end": None},
        ]
        summary = _MODULE.summarize_history(rows, 3600.0)
        assert summary["outages"] == 1
        assert summary["downtime_minutes"] == 2.0
        assert summary["longest_outage_minutes"] == 2.0

    def test_a_long_session_is_not_a_long_outage(self):
        """The bug this replaced: a 46 hour session read as 46 hours down."""
        rows = [{"start": 0.0, "end": 165_600.0}, {"start": 165_720.0, "end": None}]
        summary = _MODULE.summarize_history(rows, 169_200.0)
        assert summary["downtime_minutes"] == 2.0
        assert summary["availability_percent"] > 99.0

    def test_rows_arrive_newest_first_and_are_sorted(self):
        """The API returns them newest first; order must not change the sum."""
        forward = _MODULE.summarize_history(
            [{"start": 0.0, "end": 1800.0}, {"start": 1920.0, "end": None}], 3600.0
        )
        backward = _MODULE.summarize_history(
            [{"start": 1920.0, "end": None}, {"start": 0.0, "end": 1800.0}], 3600.0
        )
        assert forward == backward

    def test_many_short_outages_are_counted_separately(self):
        """Twenty reconnects a day is a different problem from one long gap."""
        rows = []
        for index in range(5):
            base = index * 3720.0
            rows.append({"start": base, "end": base + 3600.0})
        summary = _MODULE.summarize_history(rows, 5 * 3720.0)
        assert summary["outages"] == 4
        assert summary["longest_outage_minutes"] == 2.0
        assert summary["downtime_minutes"] == 8.0

    def test_touching_sessions_are_not_an_outage(self):
        """The cloud splits a run at midnight with no gap; that is not a drop."""
        rows = [{"start": 0.0, "end": 1800.0}, {"start": 1800.0, "end": None}]
        summary = _MODULE.summarize_history(rows, 3600.0)
        assert summary["outages"] == 0
        assert summary["availability_percent"] == 100.0

    def test_rows_without_a_start_are_skipped(self):
        """Defensive: the API has surprised us on field presence before."""
        rows = [{"start": None, "end": 100.0}, {"start": 0.0, "end": None}]
        summary = _MODULE.summarize_history(rows, 3600.0)
        assert summary["sessions"] == 1
