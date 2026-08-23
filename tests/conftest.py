"""Shared fixtures.

Nothing here imports Home Assistant, so `pytest tests/test_temperature.py`
works on a bare `pip install pytest`, including on Windows where importing
Home Assistant fails on `fcntl`. Tests that do need Home Assistant must
request the `enable_custom_integrations` fixture themselves, which comes
from `pytest-homeassistant-custom-component` and is only installed in CI.

Payloads here are hand-written shapes, not recordings. Anything asserted
against a real account should be replaced with captured output from a probe
run so the fixtures stay honest about what the V3 API actually returns.
"""

import pytest


@pytest.fixture
def zone_payload() -> dict:
    """One entry as returned by GET /v3/sites/{site_id}/zones."""
    return {
        "id": "zone-1",
        "name": "Living Room",
        "adapter": {
            "deviceSerial": "SERIAL0001",
            "connected": True,
            "hasSensor": False,
            "power": 1,
            "operationMode": "cool",
            "roomTemp": 23.0,
            "spCool": 24.0,
            "spHeat": 20.0,
            "fanSpeed": "auto",
            "airDirection": "auto",
            "humidity": None,
        },
    }


@pytest.fixture
def device_profile_payload() -> list[dict]:
    """One entry as returned by GET /v3/devices/{serial}/profile."""
    return [
        {
            "numberOfFanSpeeds": 5,
            "hasVaneDir": True,
            "hasVaneSwing": True,
            "hasModeHeat": True,
            "hasModeCool": True,
            "hasModeDry": True,
            "hasModeVent": True,
            "hasModeAuto": True,
            "minimumSetPoints": {"heat": 16.0, "cool": 16.0},
            "maximumSetPoints": {"heat": 30.0, "cool": 30.0},
        }
    ]
