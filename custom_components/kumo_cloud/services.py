"""Services for the parts of scheduling that suit an automation.

There is no good entity shape for a weekly schedule, so these are services.
The split is deliberate: reading is a service with response data, which an
automation or a template can consume, and the write side covers the things
worth automating, switching season, enabling or disabling scheduling, and
clearing events.

`set_schedule` replaces one zone's timetable outright rather than editing
individual events, because that is what the API does: a POST to a season's
schedules overwrites the named zone's events. An empty list clears them.

Every route and body here was verified against a real account, including
the two that had to be corrected after the first attempt: `reset-filter` is
a PATCH, and `clean` needs the schedule ids in its body.
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
SERVICE_SET_SCHEDULE = "set_schedule"
SERVICE_SET_HOLD = "set_hold"
ATTR_HOLD_TYPE = "hold_type"
HOLD_TYPES = ["until_next_event", "permanent"]

ATTR_ENTRY_ID = "config_entry_id"
ATTR_SEASON = "season"
ATTR_ENABLED = "enabled"
ATTR_ZONE = "zone"
ATTR_EVENTS = "events"
ATTR_DAYS = "days"
ATTR_START_TIME = "start_time"
ATTR_OPERATION_MODE = "operation_mode"
ATTR_FAN_SPEED = "fan_speed"
ATTR_AIR_DIRECTION = "air_direction"
ATTR_COOL_SETPOINT = "cool_setpoint"
ATTR_HEAT_SETPOINT = "heat_setpoint"

# The API's own vocabulary, so these pass straight through.
DAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
MODES = ["cool", "heat", "dry", "vent", "auto", "off"]

_ENTRY = {vol.Optional(ATTR_ENTRY_ID): cv.string}

EVENT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DAYS): vol.All(cv.ensure_list, [vol.In(DAYS)], vol.Length(min=1)),
        # "HHMM", which is what the API stores.
        vol.Required(ATTR_START_TIME): vol.Match(r"^([01]\d|2[0-3])[0-5]\d$"),
        vol.Required(ATTR_OPERATION_MODE): vol.In(MODES),
        vol.Optional(ATTR_FAN_SPEED): cv.string,
        vol.Optional(ATTR_AIR_DIRECTION): cv.string,
        vol.Optional(ATTR_COOL_SETPOINT): vol.Coerce(float),
        vol.Optional(ATTR_HEAT_SETPOINT): vol.Coerce(float),
    }
)

SCHEMA_GET_SCHEDULES = vol.Schema(_ENTRY)
SCHEMA_SET_SEASON = vol.Schema({**_ENTRY, vol.Required(ATTR_SEASON): cv.string})
SCHEMA_SET_ENABLED = vol.Schema({**_ENTRY, vol.Required(ATTR_ENABLED): cv.boolean})
SCHEMA_CLEAR = vol.Schema({**_ENTRY, vol.Optional(ATTR_SEASON): cv.string})
SCHEMA_SET_SCHEDULE = vol.Schema(
    {
        **_ENTRY,
        vol.Required(ATTR_ZONE): cv.string,
        vol.Required(ATTR_EVENTS): vol.All(cv.ensure_list, [EVENT_SCHEMA]),
    }
)
SCHEMA_SET_HOLD = vol.Schema(
    {
        **_ENTRY,
        vol.Required(ATTR_ENABLED): cv.boolean,
        # No zone means every zone, which is how Away mode behaves.
        vol.Optional(ATTR_ZONE): cv.string,
        vol.Optional(ATTR_HOLD_TYPE): vol.In(HOLD_TYPES),
        vol.Optional(ATTR_OPERATION_MODE): vol.In(MODES),
        vol.Optional(ATTR_FAN_SPEED): cv.string,
        vol.Optional(ATTR_AIR_DIRECTION): cv.string,
        vol.Optional(ATTR_COOL_SETPOINT): vol.Coerce(float),
        vol.Optional(ATTR_HEAT_SETPOINT): vol.Coerce(float),
    }
)


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
    """Start or stop the running season, which is how scheduling is toggled.

    Not `/sites/{id}/toggle-schedules`, which is closed to this client on
    every API version tried. Starting and stopping the season achieves the
    same thing and does work.
    """
    coordinator = _coordinator(call.hass, call)
    season = coordinator.active_season
    if season is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="no_season"
        )
    await coordinator.api.set_season_running(season["id"], call.data[ATTR_ENABLED])
    await coordinator.async_request_refresh()


async def _set_schedule(call: ServiceCall) -> None:
    """Replace one zone's scheduled events.

    This replaces rather than appends: whatever is passed becomes the zone's
    whole timetable, and an empty list clears it.
    """
    coordinator = _coordinator(call.hass, call)
    season = coordinator.active_season
    if season is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="no_season"
        )

    wanted = call.data[ATTR_ZONE]
    zone_id = next(
        (zone["id"] for zone in coordinator.zones if wanted in (zone["name"], zone["id"])),
        None,
    )
    if zone_id is None:
        known = ", ".join(zone["name"] for zone in coordinator.zones)
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unknown_zone",
            translation_placeholders={"zone": wanted, "known": known},
        )

    events = [
        {
            "days": event[ATTR_DAYS],
            "startTime": event[ATTR_START_TIME],
            "operationMode": event[ATTR_OPERATION_MODE],
            "fanSpeed": event.get(ATTR_FAN_SPEED, "auto"),
            "airDirection": event.get(ATTR_AIR_DIRECTION, "auto"),
            "spCool": event.get(ATTR_COOL_SETPOINT),
            "spHeat": event.get(ATTR_HEAT_SETPOINT),
        }
        for event in call.data[ATTR_EVENTS]
    ]

    await coordinator.api.set_zone_schedules(
        season["id"], [{"zone": zone_id, "events": events}]
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
    schedule_ids = [
        entry["id"]
        for entry in coordinator.zone_schedules.values()
        if entry.get("id")
    ]
    if not schedule_ids:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="no_schedules"
        )

    _LOGGER.warning(
        "Clearing every scheduled event in season %s across %d zones",
        season.get("name"),
        len(schedule_ids),
    )
    await coordinator.api.clear_season_events(season["id"], schedule_ids)
    await coordinator.async_request_refresh()


async def _set_hold(call: ServiceCall) -> None:
    """Apply or clear a hold, which is what the app calls Away mode.

    A hold pins settings on a zone until it expires. `until_next_event`
    releases at the next scheduled change; `permanent` stays until cleared.
    Turning it off restores normal operation.
    """
    coordinator = _coordinator(call.hass, call)

    wanted = call.data.get(ATTR_ZONE)
    if wanted:
        targets = [
            zone
            for zone in coordinator.zones
            if wanted in (zone["name"], zone["id"])
        ]
        if not targets:
            known = ", ".join(zone["name"] for zone in coordinator.zones)
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_zone",
                translation_placeholders={"zone": wanted, "known": known},
            )
    else:
        targets = [zone for zone in coordinator.zones if zone.get("adapter")]

    enabled = call.data[ATTR_ENABLED]
    zones: list[dict[str, Any]] = []
    for zone in targets:
        adapter = zone.get("adapter") or {}
        # Every settings field has to be present, so anything the caller did
        # not give falls back to what the zone is doing now.
        zones.append(
            {
                "id": zone["id"],
                "enabled": enabled,
                "type": "hold",
                "holdType": call.data.get(ATTR_HOLD_TYPE, "until_next_event"),
                "operationMode": call.data.get(
                    ATTR_OPERATION_MODE, adapter.get("operationMode")
                ),
                "fanSpeed": call.data.get(ATTR_FAN_SPEED, adapter.get("fanSpeed")),
                "airDirection": call.data.get(
                    ATTR_AIR_DIRECTION, adapter.get("airDirection")
                ),
                "spCool": call.data.get(ATTR_COOL_SETPOINT, adapter.get("spCool")),
                "spHeat": call.data.get(ATTR_HEAT_SETPOINT, adapter.get("spHeat")),
            }
        )

    _LOGGER.debug("Setting hold enabled=%s on %d zones", enabled, len(zones))
    await coordinator.api.set_hold(coordinator.site_id, zones, enabled)
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
    hass.services.async_register(
        DOMAIN, SERVICE_SET_SCHEDULE, _set_schedule, schema=SCHEMA_SET_SCHEDULE
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_HOLD, _set_hold, schema=SCHEMA_SET_HOLD
    )
