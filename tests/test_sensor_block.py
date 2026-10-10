"""The coordinator's side of the wireless sensor block.

Which zones are asked for it, and what an answer does to the stored record.
Needs Home Assistant, so it only runs where that imports (CI).
"""

import pytest

pytest.importorskip("homeassistant", reason="Home Assistant is not importable here")

from custom_components.kumo_cloud import coordinator as coord


def make_coordinator(zones, sensors=None):
    """Build a coordinator with just the state these paths touch, no hass."""
    c = object.__new__(coord.KumoCloudDataUpdateCoordinator)
    c.zones = zones
    c.wireless_sensors = dict(sensors or {})
    c.device_prohibits = {}
    c._last_push = None
    c.updates = 0
    c._snapshot = lambda: {}
    c.async_update_listeners = lambda: setattr(c, "updates", c.updates + 1)
    return c


ZONES = [
    {"adapter": {"deviceSerial": "SERIAL0001", "hasSensor": True}},
    {"adapter": {"deviceSerial": "SERIAL0002", "hasSensor": False}},
    {"adapter": {"deviceSerial": "SERIAL0003"}},
    {"name": "no adapter"},
]


def test_only_zones_with_a_sensor_are_asked():
    """Asking a unit with no sensor would cost an answer wait for nothing."""
    assert make_coordinator(ZONES)._sensor_serials() == ["SERIAL0001"]


def test_an_answer_replaces_the_frozen_reading():
    """The live failure: the poll kept returning the old temperature."""
    c = make_coordinator(
        ZONES, {"SERIAL0001": {"battery": 80, "rssi": -49, "temperature": 24.9, "humidity": 51.1}}
    )

    c._handle_push_block("SERIAL0001", "sensor", {"temperature": 23.4, "humidity": 50.6})

    assert c.wireless_sensors["SERIAL0001"] == {
        "battery": 80,
        "rssi": -49,
        "temperature": 23.4,
        "humidity": 50.6,
    }
    assert c.updates == 1


def test_an_answer_with_no_readings_changes_nothing():
    """An empty or unfamiliar answer must not blank what is known."""
    before = {"battery": 80, "temperature": 24.9}
    c = make_coordinator(ZONES, {"SERIAL0001": dict(before)})

    c._handle_push_block("SERIAL0001", "sensor", {"something": 1})

    assert c.wireless_sensors["SERIAL0001"] == before
    assert c.updates == 0


def test_a_null_field_does_not_clear_it():
    """Same rule as device pushes: null means not included."""
    c = make_coordinator(ZONES, {"SERIAL0001": {"battery": 80, "temperature": 24.9}})

    c._handle_push_block("SERIAL0001", "sensor", {"battery": None, "temperature": 23.4})

    assert c.wireless_sensors["SERIAL0001"] == {"battery": 80, "temperature": 23.4}
