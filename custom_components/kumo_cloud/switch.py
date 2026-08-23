"""Switches for adapter settings.

Only one so far: the WiFi adapter's status LED, which the device record
reports as `ledDisabled` and which nothing surfaced.

**Writing it is unverified.** Reading `ledDisabled` is confirmed against a
real account; sending it is not. The app sets this field over its own local
channel rather than through `/devices/send-command`, so whether the cloud
command endpoint accepts it is a guess. If the switch reverts a second after
you flip it, the command was accepted and ignored, and this is the file to
fix. The state itself will always be right, because it is read.
"""

from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
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
    """Set up the switches, including for zones added later."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _async_add_new_entities() -> None:
        new: list[KumoCloudStatusLedSwitch] = []
        for zone in coordinator.zones:
            adapter = zone.get("adapter")
            if not adapter:
                continue
            device = KumoCloudDevice(coordinator, zone["id"], adapter["deviceSerial"])
            unique_id = f"{device.device_serial}_status_led"
            if unique_id in known:
                continue
            known.add(unique_id)
            new.append(KumoCloudStatusLedSwitch(device))

        if new:
            async_add_entities(new)

    _async_add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_entities))


class KumoCloudStatusLedSwitch(KumoCloudEntity, SwitchEntity):
    """The WiFi adapter's status LED.

    Presented the right way round: the API stores `ledDisabled`, so the
    switch being on means the LED is lit.
    """

    _attr_name = "Status LED"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:led-on"

    def __init__(self, device: KumoCloudDevice) -> None:
        """Initialize the switch."""
        super().__init__(device)
        self._attr_unique_id = f"{device.device_serial}_status_led"

    @property
    def is_on(self) -> bool | None:
        """Return True when the LED is lit."""
        disabled = self.device.device_data.get("ledDisabled")
        return None if disabled is None else not disabled

    @property
    def available(self) -> bool:
        """Return False when the field has never been reported."""
        return super().available and self.is_on is not None

    async def async_turn_on(self, **kwargs: object) -> None:
        """Light the LED."""
        await self._async_set(False)

    async def async_turn_off(self, **kwargs: object) -> None:
        """Darken the LED."""
        await self._async_set(True)

    async def _async_set(self, disabled: bool) -> None:
        """Send the new value and cache it so the UI does not bounce."""
        commands = {"ledDisabled": disabled}
        self.device.cache_commands(commands)
        self.async_write_ha_state()
        await self.device.send_command(commands)
        self.async_write_ha_state()
