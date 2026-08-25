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
