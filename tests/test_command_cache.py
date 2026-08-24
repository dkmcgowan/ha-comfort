"""Tests for holding a just-sent value until the cloud echoes it.

This is the logic behind a bug seen in the field: switching a unit from dry
to cool showed cool, flicked back to dry for about a second, then settled on
cool. The old implementation released the held value based on a clock
comparison; these tests pin the value-based rule that replaced it.
"""

import importlib.util
import pathlib

import pytest

_PATH = (
    pathlib.Path(__file__).parent.parent
    / "custom_components"
    / "kumo_cloud"
    / "command_cache.py"
)
_SPEC = importlib.util.spec_from_file_location("kumo_command_cache", _PATH)
command_cache = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(command_cache)

CommandCache = command_cache.CommandCache
values_match = command_cache.values_match

SERIAL = "SERIAL0001"


def test_held_value_survives_a_stale_record():
    """The reported bug.

    The user picks cool. The cloud still says dry on the next update. The
    card must keep showing cool rather than flicking back.
    """
    cache = CommandCache()
    cache.remember(SERIAL, "operationMode", "cool", now=100.0)

    stale = {"operationMode": "dry", "roomTemp": 21.0}
    applied = cache.apply(SERIAL, stale, now=101.0)

    assert applied["operationMode"] == "cool"
    assert len(cache) == 1


def test_hold_releases_once_the_cloud_agrees():
    cache = CommandCache()
    cache.remember(SERIAL, "operationMode", "cool", now=100.0)

    cache.apply(SERIAL, {"operationMode": "dry"}, now=101.0)
    assert len(cache) == 1

    caught_up = cache.apply(SERIAL, {"operationMode": "cool"}, now=105.0)
    assert caught_up["operationMode"] == "cool"
    assert len(cache) == 0


def test_a_refused_command_is_not_held_forever():
    """A value the equipment rejects must stop being displayed."""
    cache = CommandCache(timeout=90.0)
    cache.remember(SERIAL, "operationMode", "cool", now=100.0)

    still_held = cache.apply(SERIAL, {"operationMode": "dry"}, now=180.0)
    assert still_held["operationMode"] == "cool"

    given_up = cache.apply(SERIAL, {"operationMode": "dry"}, now=200.0)
    assert given_up["operationMode"] == "dry"
    assert len(cache) == 0


def test_holds_are_per_device():
    cache = CommandCache()
    cache.remember(SERIAL, "operationMode", "cool", now=100.0)

    other = cache.apply("OTHER", {"operationMode": "dry"}, now=101.0)
    assert other["operationMode"] == "dry"
    assert len(cache) == 1


def test_holds_are_per_field():
    cache = CommandCache()
    cache.remember(SERIAL, "operationMode", "cool", now=100.0)
    cache.remember(SERIAL, "spCool", 22.0, now=100.0)

    record = cache.apply(SERIAL, {"operationMode": "cool", "spCool": 24.0}, now=101.0)
    # The mode landed and was released; the setpoint has not, so it is held.
    assert record["spCool"] == 22.0
    assert cache.pending_fields(SERIAL) == {"spCool"}


def test_setpoints_compare_with_a_tolerance():
    """Floats round trip inexactly, so near enough must count as landed."""
    cache = CommandCache()
    cache.remember(SERIAL, "spCool", 22.5, now=100.0)

    cache.apply(SERIAL, {"spCool": 22.5000001}, now=101.0)
    assert len(cache) == 0


def test_a_genuinely_different_setpoint_is_still_held():
    cache = CommandCache()
    cache.remember(SERIAL, "spCool", 22.5, now=100.0)

    record = cache.apply(SERIAL, {"spCool": 24.0}, now=101.0)
    assert record["spCool"] == 22.5
    assert len(cache) == 1


def test_a_missing_field_does_not_release_the_hold():
    """A partial push payload that omits the field must not count as agreement."""
    cache = CommandCache()
    cache.remember(SERIAL, "spHeat", 19.0, now=100.0)

    record = cache.apply(SERIAL, {"roomTemp": 21.0}, now=101.0)
    assert record["spHeat"] == 19.0
    assert len(cache) == 1


@pytest.mark.parametrize(
    ("reported", "wanted", "expected"),
    [
        ("cool", "cool", True),
        ("dry", "cool", False),
        (1, 1, True),
        (0, 1, False),
        (22.5, 22.5, True),
        (22.6, 22.5, True),
        (23.0, 22.5, False),
        (True, True, True),
        (False, True, False),
        # A bool and the number it equals count as agreement: if we asked for
        # power 1 and the cloud echoes true, that landed. What the bool branch
        # exists for is keeping bools off the numeric tolerance path, where
        # `abs(True - 0.8) <= 0.25` would otherwise be a false match.
        (True, 1, True),
        (1, True, True),
        (True, 0.8, False),
        (None, "cool", False),
        (None, None, True),
    ],
)
def test_values_match(reported, wanted, expected):
    assert values_match(reported, wanted) is expected


def test_power_zero_is_not_confused_with_false():
    """`power` is 0 or 1 and must compare as a number, not a truth value."""
    cache = CommandCache()
    cache.remember(SERIAL, "power", 0, now=100.0)
    cache.apply(SERIAL, {"power": 0}, now=101.0)
    assert len(cache) == 0
