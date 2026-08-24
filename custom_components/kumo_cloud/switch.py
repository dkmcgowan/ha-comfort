"""Site level switches.

Only scheduling for now. This is not `/sites/{id}/toggle-schedules`, which
returns 426 on every API version tried and appears closed to this client.
Starting and stopping the running schedule season does the same job through
a route that works, and round trips cleanly.

There is deliberately no switch for the adapter's status LED. The cloud
accepts that field and ignores it, so a switch would be a control that does
nothing. It is a read-only binary sensor instead.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import KumoCloudConfigEntry, KumoCloudDataUpdateCoordinator
from .entity import KumoCloudSiteEntity

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


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
        entity = KumoCloudSchedulesSwitch(coordinator)
        if entity.unique_id in known:
            return
        known.add(entity.unique_id)
        async_add_entities([entity])

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
