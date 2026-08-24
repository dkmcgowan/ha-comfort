"""Switches, per site and per zone.

The site switch is scheduling. It is not `/sites/{id}/toggle-schedules`,
which returns 426 on every API version tried and appears closed to this
client; starting and stopping the running season does the same job through
a route that works.

The zone switches are the adapter's status LED and the three wall remote
lockouts. Both go through `/devices/{serial}/relay-command`, which is a
separate path from `/devices/send-command` and is the one that carries
adapter settings. Both were verified by changing the real value and reading
it back.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import (
    KumoCloudConfigEntry,
    KumoCloudDataUpdateCoordinator,
    KumoCloudDevice,
)
from .entity import KumoCloudEntity, KumoCloudSiteEntity

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1

# The three things the wall remote can be locked out of. The API wants all
# three keys on every write, so a switch for one has to send the other two
# back unchanged.
PROHIBIT_CONTROLS = ("power", "mode", "setpoint")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KumoCloudConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the site level switches."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _async_add_new_entities() -> None:
        new: list[SwitchEntity] = []

        site_switch = KumoCloudSchedulesSwitch(coordinator)
        if site_switch.unique_id not in known:
            known.add(site_switch.unique_id)
            new.append(site_switch)

        for zone in coordinator.zones:
            adapter = zone.get("adapter")
            if not adapter:
                continue
            device = KumoCloudDevice(coordinator, zone["id"], adapter["deviceSerial"])
            candidates: list[SwitchEntity] = [KumoCloudStatusLedSwitch(device)]
            candidates += [
                KumoCloudProhibitSwitch(device, control) for control in PROHIBIT_CONTROLS
            ]
            for entity in candidates:
                if entity.unique_id not in known:
                    known.add(entity.unique_id)
                    new.append(entity)

        if new:
            _LOGGER.debug("Adding %d new switch entities", len(new))
            async_add_entities(new)

    _async_add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_entities))


class KumoCloudSchedulesSwitch(KumoCloudSiteEntity, SwitchEntity):
    """Whether the site's schedules are running."""

    _attr_name = "Schedules"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: KumoCloudDataUpdateCoordinator) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.site_id}_schedules_enabled"

    @property
    def is_on(self) -> bool | None:
        """Return whether the active season is running."""
        season = self.coordinator.active_season
        if season is None:
            return None
        return bool(season.get("isRunning"))

    @property
    def available(self) -> bool:
        """Return False until a season has been read."""
        return super().available and self.coordinator.active_season is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Name the season being started and stopped."""
        season = self.coordinator.active_season
        if season is None:
            return {}
        return {
            "season": season.get("name"),
            "has_schedules": season.get("hasSchedules"),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Start the season."""
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop the season."""
        await self._async_set(False)

    async def _async_set(self, running: bool) -> None:
        """Start or stop, then refresh so the state is the server's."""
        season = self.coordinator.active_season
        if season is None:
            return
        _LOGGER.debug("Setting season %s running=%s", season.get("name"), running)
        await self.coordinator.api.set_season_running(season["id"], running)
        await self.coordinator.async_request_refresh()


class KumoCloudStatusLedSwitch(KumoCloudEntity, SwitchEntity):
    """The WiFi adapter's status light.

    Presented the right way round: the API stores `ledDisabled`, so the
    switch being on means the light is lit.
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
        """Return True when the light is lit."""
        disabled = self.device.device_data.get("ledDisabled")
        return None if disabled is None else not disabled

    @property
    def available(self) -> bool:
        """Return False when the field has never been reported."""
        return super().available and self.is_on is not None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Light the LED."""
        await self._async_set(False)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Darken the LED."""
        await self._async_set(True)

    async def _async_set(self, disabled: bool) -> None:
        """Send it, holding the new value until the cloud agrees."""
        self.device.cache_command("ledDisabled", disabled)
        self.async_write_ha_state()
        await self.coordinator.api.set_status_led(self.device.device_serial, disabled)
        await self.coordinator.async_request_refresh()


class KumoCloudProhibitSwitch(KumoCloudEntity, SwitchEntity):
    """Locks the wall remote out of one control.

    On means locked. `effective` is what the unit is actually enforcing, so
    that is the state; a lock can also come from `global`, which this switch
    does not set and cannot clear.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:remote-off"

    def __init__(self, device: KumoCloudDevice, control: str) -> None:
        """Initialize for one of power, mode or setpoint."""
        super().__init__(device)
        self._control = control
        self._attr_name = f"Lock remote {control}"
        self._attr_unique_id = f"{device.device_serial}_prohibit_{control}"

    @property
    def is_on(self) -> bool | None:
        """Return whether this control is currently locked."""
        prohibits = self.device.prohibits_data
        if prohibits is None:
            return None
        return bool((prohibits.get("effective") or {}).get(self._control))

    @property
    def available(self) -> bool:
        """Return False until the lockout state has been read."""
        return super().available and self.device.prohibits_data is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Show where the lock comes from, since global overrides local."""
        prohibits = self.device.prohibits_data or {}
        return {
            "local": (prohibits.get("local") or {}).get(self._control),
            "global": (prohibits.get("global") or {}).get(self._control),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Lock this control."""
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Unlock this control."""
        await self._async_set(False)

    async def _async_set(self, locked: bool) -> None:
        """Send all three values, because the API requires the whole block."""
        prohibits = self.device.prohibits_data or {}
        local = dict(prohibits.get("local") or {})
        payload = {
            control: bool(local.get(control, False)) for control in PROHIBIT_CONTROLS
        }
        payload[self._control] = locked

        _LOGGER.debug("Setting %s lockout on %s", payload, self.device.device_serial)
        await self.coordinator.api.set_prohibits(self.device.device_serial, payload)
        await self.coordinator.async_refresh_prohibits(self.device.device_serial)
