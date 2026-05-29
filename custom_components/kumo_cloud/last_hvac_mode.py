"""Per-entity memory of the last non-OFF HVAC mode.

When a user turns a Mitsubishi unit OFF and then back ON via the HA UI,
the unit's reported `operationMode` no longer tells us what the user had
it set to before. This module keeps a small in-memory map of the last
active mode per entity so `async_turn_on()` can restore it instead of
defaulting to e.g. cool.

The store is not persisted across HA restarts -- if HA restarts while a
unit is OFF, we fall back to the existing "default to cool" behavior.
"""

from __future__ import annotations

from homeassistant.components.climate.const import HVACMode
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_STORE_KEY = "last_hvac_mode"


def _store(hass: HomeAssistant) -> dict[str, str]:
    return hass.data.setdefault(DOMAIN, {}).setdefault(_STORE_KEY, {})


def remember(hass: HomeAssistant, identifier: str, mode: HVACMode | None) -> None:
    """Remember the last active (non-OFF) HVAC mode for an entity."""
    if not identifier or not mode or mode == HVACMode.OFF:
        return
    _store(hass)[identifier] = mode.value


def recall(
    hass: HomeAssistant, identifier: str, available_modes: list[HVACMode]
) -> HVACMode | None:
    """Return the cached mode if still in the entity's available modes."""
    if not identifier:
        return None
    value = _store(hass).get(identifier)
    if not value:
        return None
    for mode in available_modes:
        if mode != HVACMode.OFF and mode.value == value:
            return mode
    return None
