"""The Kumo Cloud integration."""

from __future__ import annotations

import logging

import aiohttp
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .api import KumoCloudAPI, KumoCloudAuthError, KumoCloudConnectionError
from .coordinator import KumoCloudConfigEntry, KumoCloudDataUpdateCoordinator
from .const import CONF_SITE_ID

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.CLIMATE, Platform.SENSOR]

async def async_setup_entry(hass: HomeAssistant, entry: KumoCloudConfigEntry) -> bool:
    """Set up Kumo Cloud from a config entry."""

    api = KumoCloudAPI(hass)

    if "access_token" in entry.data:
        api.username = entry.data[CONF_USERNAME]
        api.access_token = entry.data["access_token"]
        api.refresh_token = entry.data["refresh_token"]

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

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: KumoCloudConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
