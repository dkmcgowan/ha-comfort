"""The Fault sensor follows the unit's status code, not `unusualFigures`.

Every unit on one account reported `unusualFigures` 32768 while showing A0
with nothing wrong, which lit Fault on all of them.
"""

from types import SimpleNamespace

import pytest

pytest.importorskip("homeassistant", reason="Home Assistant is not importable here")

from custom_components.kumo_cloud.binary_sensor import _has_fault


def _device(data):
    return SimpleNamespace(device_data=data)


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({"twoFiguresCode": "A0", "unusualFigures": 32768}, False),
        ({"twoFiguresCode": "A0", "unusualFigures": None}, False),
        ({"twoFiguresCode": "00"}, False),
        ({"twoFiguresCode": "E6", "unusualFigures": 32768}, True),
        ({"twoFiguresCode": "P8"}, True),
        ({"unusualFigures": 32768}, None),
        ({}, None),
    ],
)
def test_has_fault(data, expected):
    assert _has_fault(_device(data)) is expected
