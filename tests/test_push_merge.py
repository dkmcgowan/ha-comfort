"""Tests for merging pushed device payloads over cached state.

`push.py` imports socketio but no Home Assistant, so it is loaded straight
off disk for the same reason `test_temperature.py` does it: the package's
`__init__.py` pulls in Home Assistant, which cannot be imported on Windows.
"""

import importlib.util
import pathlib
import sys

import pytest

_PATH = pathlib.Path(__file__).parent.parent / "custom_components" / "kumo_cloud" / "push.py"
_SPEC = importlib.util.spec_from_file_location("kumo_push", _PATH)
push = importlib.util.module_from_spec(_SPEC)
sys.modules["kumo_push"] = push
_SPEC.loader.exec_module(push)

merge_device_update = push.merge_device_update


# A full snapshot as the socket sends it on subscribe, trimmed.
SNAPSHOT = {
    "deviceSerial": "SERIAL0001",
    "roomTemp": 20.5,
    "operationMode": "dry",
    "power": 1,
    "spCool": 22.5,
    "spHeat": 15.5,
    "fanSpeed": "auto",
    "airDirection": "horizontal",
    "twoFiguresCode": "A0",
    "unusualFigures": None,
}


def test_delta_updates_only_what_it_carries():
    delta = {"deviceSerial": "SERIAL0001", "roomTemp": 21.0}
    merged = merge_device_update(SNAPSHOT, delta)
    assert merged["roomTemp"] == 21.0
    assert merged["spCool"] == 22.5
    assert merged["operationMode"] == "dry"


def test_null_in_a_delta_does_not_clear_a_setpoint():
    """The live failure this guards against.

    Two of four adapters sent `spHeat: null` in a delta one second after a
    snapshot had given them real setpoints. Applying it would blank the
    user's heat setpoint until the next poll.
    """
    delta = {"deviceSerial": "SERIAL0001", "roomTemp": 21.0, "spHeat": None}
    merged = merge_device_update(SNAPSHOT, delta)
    assert merged["spHeat"] == 15.5


def test_zero_and_false_are_not_treated_as_missing():
    """Only None means absent. `power: 0` is a real value."""
    delta = {"deviceSerial": "SERIAL0001", "power": 0, "statusDisplay": 0}
    merged = merge_device_update(SNAPSHOT, delta)
    assert merged["power"] == 0
    assert merged["statusDisplay"] == 0


def test_empty_string_survives():
    merged = merge_device_update(SNAPSHOT, {"twoFiguresCode": ""})
    assert merged["twoFiguresCode"] == ""


def test_new_keys_are_added():
    merged = merge_device_update(SNAPSHOT, {"connected": True, "date": "2026-08-23T14:00:00Z"})
    assert merged["connected"] is True
    assert merged["date"] == "2026-08-23T14:00:00Z"


def test_the_original_is_not_mutated():
    before = dict(SNAPSHOT)
    merge_device_update(SNAPSHOT, {"roomTemp": 99.0})
    assert before == SNAPSHOT


def test_empty_update_changes_nothing():
    assert merge_device_update(SNAPSHOT, {}) == SNAPSHOT


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (({"deviceSerial": "A"},), 1),
        (([{"deviceSerial": "A"}],), 1),
        (([{"deviceSerial": "A"}, {"deviceSerial": "B"}],), 2),
        ((None,), 0),
        (("not a payload",), 0),
        ((), 0),
    ],
)
def test_payload_flattening(args, expected):
    """The server sends a list of one, but accept a bare dict too."""
    assert len(push._iter_payloads(args)) == expected
