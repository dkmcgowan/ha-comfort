"""Diagnostics support for Kumo Cloud."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry

from .const import DOMAIN
from .coordinator import KumoCloudConfigEntry

# Keys redacted from any nested dict before the diagnostics blob is exposed.
TO_REDACT = {
    "username",
    "password",
    "access",
    "access_token",
    "refresh",
    "refresh_token",
    "token",
    "deviceSerial",
    "serialNumber",
    "cryptoSerial",
    "mac",
    "macAddress",
    "ssid",
    "routerSsid",
    "ipAddress",
    # The site record carries a postal address, and the weather payload
    # carries the coordinates it was looked up from. Both locate the house.
    "address",
    "address2",
    "city",
    "state",
    "zip",
    "coord",
    "mak",
    "baseMAK",
    "installerName",
    "installerNumber",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: KumoCloudConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    return {
        "config_entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "zones": async_redact_data(coordinator.zones, TO_REDACT),
        "devices": async_redact_data(coordinator.devices, TO_REDACT),
        "device_profiles": async_redact_data(coordinator.device_profiles, TO_REDACT),
        "device_statuses": async_redact_data(coordinator.device_statuses, TO_REDACT),
        "wireless_sensors": async_redact_data(coordinator.wireless_sensors, TO_REDACT),
        "zone_notifications": async_redact_data(
            coordinator.zone_notifications, TO_REDACT
        ),
        "device_prohibits": async_redact_data(coordinator.device_prohibits, TO_REDACT),
        "device_connections": async_redact_data(
            coordinator.device_connections, TO_REDACT
        ),
        "site": async_redact_data(coordinator.site, TO_REDACT),
        "site_weather": async_redact_data(coordinator.site_weather, TO_REDACT),
        "active_alerts": async_redact_data(coordinator.active_alerts, TO_REDACT),
    }


async def async_get_device_diagnostics(
    hass: HomeAssistant,
    entry: KumoCloudConfigEntry,
    device: DeviceEntry,
) -> dict[str, Any]:
    """Return diagnostics for a single Mitsubishi indoor unit."""
    coordinator = entry.runtime_data

    serial = next(
        (identifier for domain, identifier in device.identifiers if domain == DOMAIN),
        None,
    )
    if serial is None:
        return {"error": "device serial not found in identifiers"}

    return {
        "device_info": {
            "name": device.name,
            "model": device.model,
            "sw_version": device.sw_version,
            "manufacturer": device.manufacturer,
        },
        "device_data": async_redact_data(
            coordinator.devices.get(serial, {}), TO_REDACT
        ),
        "device_status": async_redact_data(
            coordinator.device_statuses.get(serial, {}), TO_REDACT
        ),
        "device_profile": async_redact_data(
            coordinator.device_profiles.get(serial, []), TO_REDACT
        ),
        "wireless_sensor": async_redact_data(
            coordinator.wireless_sensors.get(serial, {}), TO_REDACT
        ),
    }
