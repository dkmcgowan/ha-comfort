"""Tests for holding a briefly dropped adapter available.

Written after a zone's climate entity was reported unavailable for hours at
a time while every sensor on the same unit kept working. Two things caused
that shape and both are covered here and in the coordinator: the cloud's
`connected` flag flapping, and a failed device read blanking the record.

`connection.py` imports no Home Assistant, so it is loaded straight off disk
the way `test_command_cache.py` does it.
"""

import importlib.util
import pathlib

import pytest

_PATH = (
    pathlib.Path(__file__).parent.parent
    / "custom_components"
    / "kumo_cloud"
    / "connection.py"
)
_SPEC = importlib.util.spec_from_file_location("kumo_connection", _PATH)
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

ConnectionGrace = _MODULE.ConnectionGrace

GRACE = 900.0


@pytest.fixture
def grace() -> object:
    """Return a tracker using the shipping grace period."""
    return ConnectionGrace(GRACE)


def test_a_device_never_reported_down_is_available(grace):
    """An adapter nothing has been said about counts as reachable."""
    assert grace.available("SERIAL0001", 0.0) is True


def test_a_fresh_drop_stays_available(grace):
    """The entity does not follow the first disconnected report."""
    grace.note("SERIAL0001", False, 0.0)
    assert grace.available("SERIAL0001", 60.0) is True


def test_a_drop_that_outlasts_the_grace_goes_unavailable(grace):
    """A real outage is reported once it has lasted long enough."""
    grace.note("SERIAL0001", False, 0.0)
    assert grace.available("SERIAL0001", GRACE + 1.0) is False


def test_the_grace_is_measured_from_the_first_report(grace):
    """Repeated disconnected reports do not restart the clock.

    Otherwise an adapter that is polled while down would never be reported
    unavailable, because every poll would push the deadline out again.
    """
    for moment in (0.0, 300.0, 600.0):
        grace.note("SERIAL0001", False, moment)
    assert grace.available("SERIAL0001", GRACE + 1.0) is False


def test_coming_back_inside_the_grace_leaves_no_trace(grace):
    """A blip that recovers never makes the entity unavailable."""
    grace.note("SERIAL0001", False, 0.0)
    grace.note("SERIAL0001", True, 120.0)
    assert grace.available("SERIAL0001", 121.0) is True


def test_coming_back_after_the_grace_restores_availability(grace):
    """An adapter that returns is available again immediately."""
    grace.note("SERIAL0001", False, 0.0)
    assert grace.available("SERIAL0001", GRACE + 1.0) is False
    grace.note("SERIAL0001", True, GRACE + 2.0)
    assert grace.available("SERIAL0001", GRACE + 3.0) is True


def test_edges_are_reported_once(grace):
    """The caller logs on the edges, so only the edges are announced."""
    assert grace.note("SERIAL0001", False, 0.0) == "dropped"
    assert grace.note("SERIAL0001", False, 60.0) is None
    assert grace.note("SERIAL0001", True, 120.0) == "restored"
    assert grace.note("SERIAL0001", True, 180.0) is None


def test_devices_are_tracked_separately(grace):
    """One zone dropping says nothing about another."""
    grace.note("SERIAL0001", False, 0.0)
    assert grace.available("SERIAL0002", GRACE + 1.0) is True
    assert grace.available("SERIAL0001", GRACE + 1.0) is False


def test_disconnected_for_reports_the_outage_length(grace):
    """Used for the log line and for diagnostics."""
    assert grace.disconnected_for("SERIAL0001", 0.0) is None
    grace.note("SERIAL0001", False, 100.0)
    assert grace.disconnected_for("SERIAL0001", 400.0) == 300.0


def test_a_removed_zone_is_forgotten(grace):
    """Bookkeeping for hardware taken off the site does not accumulate."""
    grace.note("SERIAL0001", False, 0.0)
    grace.forget({"SERIAL0002"})
    assert grace.available("SERIAL0001", GRACE + 1.0) is True


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
