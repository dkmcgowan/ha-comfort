"""Command acknowledgement at the actual coordinator ingestion boundaries.

The coordinator imports Home Assistant, which cannot be imported on Windows.
Load only the methods under test from its source, preserving their bodies,
and supply an in-memory API and clock. No cloud or equipment is contacted.
"""

import ast
import asyncio
import importlib.util
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

_SOURCE = Path(__file__).parent.parent / "custom_components" / "kumo_cloud"
_SPEC = importlib.util.spec_from_file_location("coordinator_cache", _SOURCE / "command_cache.py")
command_cache = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(command_cache)

SERIAL = "SERIAL0001"


def load_methods(class_name, names, namespace):
    """Execute the production methods without importing the HA-only module."""
    tree = ast.parse((_SOURCE / "coordinator.py").read_text(encoding="utf-8"))
    original = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                    and node.name == class_name)
    methods = [node for node in original.body
               if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name in names]
    assert {node.name for node in methods} == set(names)
    isolated = ast.ClassDef(name=class_name, bases=[], keywords=[], body=methods,
                           decorator_list=[], type_params=[])
    module = ast.Module(body=[ast.parse("from __future__ import annotations").body[0], isolated],
                        type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(_SOURCE / "coordinator.py"), "exec"),
         namespace)
    return namespace[class_name]


def make_coordinator():
    """Use real cache and coordinator methods with a fake cloud and clock."""
    clock = SimpleNamespace(now=100.0)
    namespace = {
        "asyncio": asyncio,
        "callback": lambda method: method,
        "time": SimpleNamespace(monotonic=lambda: clock.now),
        "_LOGGER": logging.getLogger(__name__),
        "SLOW_TIER_EVERY": 10,
        "with_implied_power": command_cache.with_implied_power,
    }
    push_tree = ast.parse((_SOURCE / "push.py").read_text(encoding="utf-8"))
    merge = next(node for node in push_tree.body if isinstance(node, ast.FunctionDef)
                 and node.name == "merge_device_update")
    merge_module = ast.Module(
        body=[ast.parse("from __future__ import annotations").body[0], merge], type_ignores=[]
    )
    exec(compile(ast.fix_missing_locations(merge_module), str(_SOURCE / "push.py"), "exec"),
         namespace)
    coordinator_type = load_methods(
        "KumoCloudDataUpdateCoordinator",
        ["_process_pending_commands", "_handle_push_update", "async_refresh_device",
         "_async_update_data", "cache_command"],
        namespace,
    )
    device_type = load_methods("KumoCloudDevice", ["cache_command", "cache_commands"], namespace)
    coordinator = coordinator_type()
    coordinator.cached_commands = command_cache.CommandCache()
    coordinator.devices = {SERIAL: stale_off()}
    coordinator.zones = [{"id": "zone-1", "adapter": {"deviceSerial": SERIAL}}]
    for name in ("device_profiles", "wireless_sensors", "device_statuses", "zone_notifications",
                 "device_prohibits", "device_connections", "zone_history"):
        setattr(coordinator, name, {})
    coordinator.api = SimpleNamespace(
        get_device_details=AsyncMock(side_effect=lambda serial: stale_off()),
        get_zones=AsyncMock(return_value=coordinator.zones),
        get_device_profile=AsyncMock(return_value=[]),
        get_device_status=AsyncMock(return_value={}),
        get_zone_notification_preferences=AsyncMock(return_value={}),
    )
    coordinator.site_id = "site-1"
    coordinator._refresh_count = 1
    coordinator.push = None
    coordinator._snapshot = lambda: {"devices": coordinator.devices}
    coordinator._apply_push_interval = lambda: None
    coordinator.async_update_listeners = lambda: None
    device = device_type()
    device.coordinator = coordinator
    device.device_serial = SERIAL
    return coordinator, device, clock


def stale_off():
    """Return a hand-written cloud record from before the Fan Only command."""
    return {"operationMode": "off", "power": 0, "fanSpeed": "quiet", "roomTemp": 21.0}


def run(coro):
    """Leave the session event loop unchanged for the Home Assistant CI fixtures."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_mode_then_fan_command_survives_both_stale_post_command_refreshes():
    """Issue #2: changing speed must not release an unconfirmed mode or power."""
    coordinator, device, clock = make_coordinator()
    device.cache_commands({"operationMode": "vent"})
    clock.now = 101.0
    run(coordinator.async_refresh_device(SERIAL))
    assert coordinator.cached_commands.pending_fields(SERIAL) == {"operationMode", "power"}

    clock.now = 102.0
    device.cache_commands({"fanSpeed": "low"})
    assert coordinator.cached_commands.pending_fields(SERIAL) == {
        "operationMode", "power", "fanSpeed"
    }
    clock.now = 103.0
    run(coordinator.async_refresh_device(SERIAL))

    assert coordinator.devices[SERIAL] == {
        "operationMode": "vent", "power": 1, "fanSpeed": "low", "roomTemp": 21.0
    }
    assert coordinator.cached_commands.pending_fields(SERIAL) == {
        "operationMode", "power", "fanSpeed"
    }


def test_temperature_only_push_does_not_acknowledge_inherited_optimistic_fields():
    coordinator, device, _ = make_coordinator()
    device.cache_commands({"operationMode": "vent"})
    payload = {"roomTemp": 22.0}

    coordinator._handle_push_update(SERIAL, payload)

    assert coordinator.devices[SERIAL]["roomTemp"] == 22.0
    assert coordinator.devices[SERIAL]["operationMode"] == "vent"
    assert coordinator.cached_commands.pending_fields(SERIAL) == {"operationMode", "power"}
    assert payload == {"roomTemp": 22.0}


def test_push_acknowledges_only_the_explicit_matching_field():
    coordinator, device, _ = make_coordinator()
    device.cache_commands({"operationMode": "vent"})

    coordinator._handle_push_update(SERIAL, {"power": 1})

    assert coordinator.cached_commands.pending_fields(SERIAL) == {"operationMode"}


def test_push_matching_all_pending_fields_releases_the_hold():
    coordinator, device, _ = make_coordinator()
    device.cache_commands({"operationMode": "vent"})

    coordinator._handle_push_update(SERIAL, {"operationMode": "vent", "power": 1})

    assert coordinator.cached_commands.pending_fields(SERIAL) == set()


def test_null_push_fields_are_not_acknowledgements():
    coordinator, device, _ = make_coordinator()
    device.cache_commands({"operationMode": "vent"})

    coordinator._handle_push_update(SERIAL, {"operationMode": None, "power": None})

    assert coordinator.devices[SERIAL]["operationMode"] == "vent"
    assert coordinator.cached_commands.pending_fields(SERIAL) == {"operationMode", "power"}


@pytest.mark.parametrize("refresh", ["async_refresh_device", "_async_update_data"])
def test_a_genuine_rest_echo_releases_the_hold(refresh):
    coordinator, device, _ = make_coordinator()
    device.cache_commands({"operationMode": "vent"})
    coordinator.api.get_device_details.side_effect = lambda serial: {
        "operationMode": "vent", "power": 1
    }

    method = getattr(coordinator, refresh)
    run(method(SERIAL) if refresh == "async_refresh_device" else method())

    assert coordinator.cached_commands.pending_fields(SERIAL) == set()


def test_failed_poll_does_not_acknowledge_the_previous_optimistic_record():
    coordinator, device, _ = make_coordinator()
    device.cache_commands({"operationMode": "vent"})
    coordinator.api.get_device_details.side_effect = RuntimeError("read unavailable")

    run(coordinator._async_update_data())

    assert coordinator.devices[SERIAL]["operationMode"] == "vent"
    assert coordinator.cached_commands.pending_fields(SERIAL) == {"operationMode", "power"}


def test_a_refused_command_expires_on_a_later_raw_refresh():
    coordinator, device, clock = make_coordinator()
    device.cache_commands({"operationMode": "vent"})
    clock.now = 191.0

    run(coordinator.async_refresh_device(SERIAL))

    assert coordinator.devices[SERIAL]["operationMode"] == "off"
    assert coordinator.devices[SERIAL]["power"] == 0
    assert coordinator.cached_commands.pending_fields(SERIAL) == set()
