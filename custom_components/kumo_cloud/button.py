"""Buttons for one-shot actions on a zone.

Only one so far: clearing the filter reminder, which pairs with the filter
binary sensor and the filter reminder date sensor.

**The reset is unverified.** The endpoint comes from the app's own catalog
but has never been fired against a real account, because doing so clears a
maintenance record. If it turns out to need a different method or a body,
this is where to fix it.
"""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import KumoCloudConfigEntry, KumoCloudDevice
from .entity import KumoCloudEntity

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KumoCloudConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the buttons, including for zones added later."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _async_add_new_entities() -> None:
        new: list[KumoCloudResetFilterButton] = []
        for zone in coordinator.zones:
            adapter = zone.get("adapter")
            if not adapter:
                continue
            device = KumoCloudDevice(coordinator, zone["id"], adapter["deviceSerial"])
            unique_id = f"{device.device_serial}_reset_filter"
            if unique_id in known:
                continue
            known.add(unique_id)
            new.append(KumoCloudResetFilterButton(device))

        if new:
            async_add_entities(new)

    _async_add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_entities))


class KumoCloudResetFilterButton(KumoCloudEntity, ButtonEntity):
    """Clears the zone's filter reminder."""

    _attr_name = "Reset filter"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:air-filter"

    def __init__(self, device: KumoCloudDevice) -> None:
        """Initialize the button."""
        super().__init__(device)
        self._attr_unique_id = f"{device.device_serial}_reset_filter"

    async def async_press(self) -> None:
        """Clear the reminder, then refresh so the change is visible."""
        _LOGGER.debug("Resetting filter reminder for zone %s", self.device.zone_id)
        await self.coordinator.api.reset_filter(self.device.zone_id)
        await self.coordinator.async_request_refresh()
