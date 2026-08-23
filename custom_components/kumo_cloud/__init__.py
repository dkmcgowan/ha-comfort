"""The Kumo Cloud integration."""

from __future__ import annotations

import logging

import aiohttp
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .api import KumoCloudAPI, KumoCloudAuthError, KumoCloudConnectionError
from .const import CONF_ACCESS_TOKEN, CONF_REFRESH_TOKEN, CONF_SITE_ID
from .coordinator import KumoCloudConfigEntry, KumoCloudDataUpdateCoordinator
from .services import async_register_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.SENSOR,
]

async def async_setup_entry(hass: HomeAssistant, entry: KumoCloudConfigEntry) -> bool:
    """Set up Kumo Cloud from a config entry."""
    api = KumoCloudAPI(hass)

    if CONF_ACCESS_TOKEN in entry.data:
        api.username = entry.data[CONF_USERNAME]
        api.access_token = entry.data[CONF_ACCESS_TOKEN]
        api.refresh_token = entry.data[CONF_REFRESH_TOKEN]

    try:
        if not api.access_token:
            await api.login(entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])
        else:
            try:
                await api.get_account_info()
            except KumoCloudAuthError:
                await api.login(entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])

    except KumoCloudAuthError as err:
        raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err
    except (KumoCloudConnectionError, aiohttp.ClientError, OSError) as err:
        raise ConfigEntryNotReady(f"Unable to connect: {err}") from err

    coordinator = KumoCloudDataUpdateCoordinator(hass, api, entry.data[CONF_SITE_ID])
    await coordinator.async_config_entry_first_refresh()

    # After the first poll, because the push channel subscribes per device
    # and the device list comes from that poll. A push channel that will not
    # open is not an error; the coordinator keeps polling.
    await coordinator.async_start_push()
    entry.async_on_unload(coordinator.async_stop_push)

    entry.runtime_data = coordinator

    async_register_services(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: KumoCloudConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
