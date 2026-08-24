"""Tests for the Auto Dry request body.

Auto Dry cannot be read back from anywhere, so a wrong body here would fail
silently: the cloud answers 200 and echoes whatever it was sent. These pin
the shape against what the Comfort app sends.

Needs Home Assistant, which `api.py` imports and which will not install on
Windows, so this runs in CI and skips locally.
"""

import asyncio

import pytest

pytest.importorskip("homeassistant")

from custom_components.kumo_cloud.api import KumoCloudAPI


class Recorder:
    """Stands in for the client, capturing what relay_command was given."""

    def __init__(self):
        """Start with nothing recorded."""
        self.calls = []

    async def relay_command(self, device_serial, payload):
        """Record instead of sending."""
        self.calls.append((device_serial, payload))
        return {}


def run(coro):
    """Run one coroutine on its own loop.

    Not `asyncio.run`, which clears the current event loop on the way out
    and breaks the fixtures every later test depends on. See
    `test_push_blocks.run`.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def set_auto_dry(**kwargs):
    """Call the method with a recorder standing in for self."""
    recorder = Recorder()
    run(KumoCloudAPI.set_auto_dry(recorder, "SERIAL0001", **kwargs))
    return recorder.calls[0]


def test_enable_alone_sends_only_enable():
    """Absent fields are left alone rather than sent as defaults."""
    serial, payload = set_auto_dry(enable=True)

    assert serial == "SERIAL0001"
    assert payload == {"adapter": {"autodry": {"enable": True}}}


def test_block_key_is_lowercase():
    """It is `autodry` going out and `autoDry` coming back.

    The app's own inconsistency. Sending the wrong one is accepted and
    discarded, which is unusually hard to notice here.
    """
    _, payload = set_auto_dry(enable=True)

    assert "autodry" in payload["adapter"]
    assert "autoDry" not in payload["adapter"]


def test_disable_is_sent_not_omitted():
    """False is a value, and must not be dropped as falsy."""
    _, payload = set_auto_dry(enable=False)

    assert payload["adapter"]["autodry"] == {"enable": False}


def test_optional_fields_use_the_api_spelling():
    """`targetHumid`, not `target_humidity`, which is the service's name."""
    _, payload = set_auto_dry(enable=True, target_humid=50, overcool=2, offset=1)

    assert payload["adapter"]["autodry"] == {
        "enable": True,
        "targetHumid": 50,
        "overcool": 2,
        "offset": 1,
    }


def test_a_zero_optional_is_still_sent():
    """Zero is meaningful for overcool and offset, and must survive."""
    _, payload = set_auto_dry(enable=True, overcool=0, offset=0)

    assert payload["adapter"]["autodry"] == {
        "enable": True,
        "overcool": 0,
        "offset": 0,
    }
