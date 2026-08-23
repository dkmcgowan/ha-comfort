"""Services for the parts of scheduling that suit an automation.

There is no good entity shape for a weekly schedule, so these are services.
The split is deliberate: reading is a service with response data, which an
automation or a template can consume, and the write side covers the things
worth automating, switching season, enabling or disabling scheduling, and
clearing events.

Creating and editing individual events is **not** here. The payload is a
whole week of per-zone events, and expressing that through a service schema
would be worse than editing it in the Comfort app. Home Assistant's own
automations are a better tool for that job anyway.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util
import voluptuous as vol

from .const import DOMAIN
from .schedule import describe, next_event, zone_timezone

_LOGGER = logging.getLogger(__name__)

SERVICE_GET_SCHEDULES = "get_schedules"
SERVICE_SET_SEASON = "set_season"
SERVICE_SET_SCHEDULES_ENABLED = "set_schedules_enabled"
SERVICE_CLEAR_SEASON_EVENTS = "clear_season_events"

ATTR_ENTRY_ID = "config_entry_id"
ATTR_SEASON = "season"
ATTR_ENABLED = "enabled"

_ENTRY = {vol.Optional(ATTR_ENTRY_ID): cv.string}

SCHEMA_GET_SCHEDULES = vol.Schema(_ENTRY)
SCHEMA_SET_SEASON = vol.Schema({**_ENTRY, vol.Required(ATTR_SEASON): cv.string})
SCHEMA_SET_ENABLED = vol.Schema({**_ENTRY, vol.Required(ATTR_ENABLED): cv.boolean})
SCHEMA_CLEAR = vol.Schema({**_ENTRY, vol.Optional(ATTR_SEASON): cv.string})


def _coordinator(hass: HomeAssistant, call: ServiceCall):
    """Find the coordinator a call is aimed at.

    With one account configured the entry does not need naming, which is the
    common case. With several it does, because guessing would silently act
    on the wrong house.
    """
    entries = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]
    if not entries:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="no_loaded_entry"
        )

    entry_id = call.data.get(ATTR_ENTRY_ID)
    if entry_id is None:
        if len(entries) > 1:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="entry_id_required"
            )
        return entries[0].runtime_data

    for entry in entries:
        if entry.entry_id == entry_id:
            return entry.runtime_data
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="unknown_entry",
        translation_placeholders={"entry_id": entry_id},
    )


def _find_season(coordinator, name: str) -> dict[str, Any]:
    """Resolve a season by name or id."""
    for season in coordinator.seasons:
        if name in (season.get("name"), season.get("id")):
            return season
    known = ", ".join(str(season.get("name")) for season in coordinator.seasons)
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="unknown_season",
        translation_placeholders={"season": name, "known": known or "none"},
    )


async def _get_schedules(call: ServiceCall) -> ServiceResponse:
    """Return the running season's schedules, zone by zone."""
    coordinator = _coordinator(call.hass, call)
    season = coordinator.active_season
    now = dt_util.utcnow()

    zones: dict[str, Any] = {}
    for zone in coordinator.zones:
        adapter = zone.get("adapter") or {}
        entry = coordinator.zone_schedules.get(zone["id"]) or {}
        events = entry.get("events") or []
        tzinfo = zone_timezone(adapter.get("timeZone"))
        upcoming = next_event(events, now, tzinfo)
        zones[zone["name"]] = {
            "event_count": len(events),
            "events": [describe(event) for event in events],
            "next_change": upcoming[0].isoformat() if upcoming else None,
            "next_event": describe(upcoming[1]) if upcoming else None,
        }

    return {
        "season": season.get("name") if season else None,
        "season_running": season.get("isRunning") if season else None,
        "schedules_enabled": coordinator.site.get("schedulesEnabled"),
        "seasons": [
            {
                "name": item.get("name"),
                "is_running": item.get("isRunning"),
                "is_default": item.get("isDefault"),
                "has_schedules": item.get("hasSchedules"),
            }
            for item in coordinator.seasons
        ],
        "zones": zones,
    }


async def _set_season(call: ServiceCall) -> None:
    """Make a season the active one."""
    coordinator = _coordinator(call.hass, call)
    season = _find_season(coordinator, call.data[ATTR_SEASON])
    await coordinator.api.set_default_season(season["id"])
    await coordinator.async_request_refresh()


async def _set_schedules_enabled(call: ServiceCall) -> None:
    """Turn scheduling on or off for the whole site."""
    coordinator = _coordinator(call.hass, call)
    await coordinator.api.set_site_schedules_enabled(
        coordinator.site_id, call.data[ATTR_ENABLED]
    )
    await coordinator.async_request_refresh()


async def _clear_season_events(call: ServiceCall) -> None:
    """Delete every event in a season, leaving the season itself."""
    coordinator = _coordinator(call.hass, call)
    name = call.data.get(ATTR_SEASON)
    season = _find_season(coordinator, name) if name else coordinator.active_season
    if season is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="no_season"
        )
    _LOGGER.warning("Clearing every scheduled event in season %s", season.get("name"))
    await coordinator.api.clear_season_events(season["id"])
    await coordinator.async_request_refresh()


def async_register_services(hass: HomeAssistant) -> None:
    """Register the schedule services once for the integration."""
    if hass.services.has_service(DOMAIN, SERVICE_GET_SCHEDULES):
        return

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_SCHEDULES,
        _get_schedules,
        schema=SCHEMA_GET_SCHEDULES,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_SEASON, _set_season, schema=SCHEMA_SET_SEASON
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_SCHEDULES_ENABLED,
        _set_schedules_enabled,
        schema=SCHEMA_SET_ENABLED,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CLEAR_SEASON_EVENTS,
        _clear_season_events,
        schema=SCHEMA_CLEAR,
    )
