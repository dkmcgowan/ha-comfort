"""API client for Kumo Cloud."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import logging
from typing import Any

import aiohttp
from aiohttp import ClientResponseError
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    API_APP_VERSION,
    API_BASE_URL,
    API_VERSION,
    TOKEN_EXPIRY_MARGIN,
    TOKEN_REFRESH_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


class KumoCloudError(HomeAssistantError):
    """Base exception for Kumo Cloud."""


class KumoCloudAuthError(KumoCloudError):
    """Authentication error."""


class KumoCloudConnectionError(KumoCloudError):
    """Connection error."""


class KumoCloudAPI:
    """Kumo Cloud API client."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the API client."""
        self.hass = hass
        self.session = async_get_clientsession(hass)
        self.base_url = API_BASE_URL
        self.username: str | None = None
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self.token_expires_at: datetime | None = None

    async def login(self, username: str, password: str) -> dict[str, Any]:
        """Login to Kumo Cloud and return user data."""
        url = f"{self.base_url}/{API_VERSION}/login"
        headers = {
            "x-app-version": API_APP_VERSION,
            "Content-Type": "application/json",
        }
        data = {
            "username": username,
            "password": password,
            "appVersion": API_APP_VERSION,
        }

        try:
            async with asyncio.timeout(30):
                async with self.session.post(
                    url, headers=headers, json=data
                ) as response:
                    if response.status == 403:
                        raise KumoCloudAuthError("Invalid username or password")
                    response.raise_for_status()
                    result = await response.json()

                    self.username = username
                    self.access_token = result["token"]["access"]
                    self.refresh_token = result["token"]["refresh"]
                    self.token_expires_at = datetime.now() + timedelta(
                        seconds=TOKEN_REFRESH_INTERVAL
                    )

                    return result

        except TimeoutError as err:
            raise KumoCloudConnectionError("Connection timeout") from err
        except ClientResponseError as err:
            if err.status == 403:
                raise KumoCloudAuthError("Invalid credentials") from err
            raise KumoCloudConnectionError(f"HTTP error: {err.status}") from err
        except KumoCloudError:
            raise
        except Exception as err:
            raise KumoCloudConnectionError(f"Unexpected error: {err}") from err

    async def refresh_access_token(self) -> None:
        """Refresh the access token."""
        if not self.refresh_token:
            raise KumoCloudAuthError("No refresh token available")

        url = f"{self.base_url}/{API_VERSION}/refresh"
        headers = {
            "x-app-version": API_APP_VERSION,
            "Content-Type": "application/json",
        }
        data = {"refresh": self.refresh_token}

        try:
            async with asyncio.timeout(30):
                async with self.session.post(
                    url, headers=headers, json=data
                ) as response:
                    if response.status == 401:
                        raise KumoCloudAuthError("Refresh token expired")
                    response.raise_for_status()
                    result = await response.json()

                    self.access_token = result["access"]
                    self.refresh_token = result["refresh"]
                    self.token_expires_at = datetime.now() + timedelta(
                        seconds=TOKEN_REFRESH_INTERVAL
                    )

        except TimeoutError as err:
            raise KumoCloudConnectionError("Connection timeout during refresh") from err
        except ClientResponseError as err:
            if err.status == 401:
                raise KumoCloudAuthError("Refresh token expired") from err
            raise KumoCloudConnectionError(
                f"HTTP error during refresh: {err.status}"
            ) from err
        except (aiohttp.ClientError, OSError) as err:
            raise KumoCloudConnectionError(f"Connection error during refresh: {err}") from err

    async def _ensure_token_valid(self) -> None:
        """Ensure access token is valid, refresh if needed."""
        if not self.access_token:
            raise KumoCloudAuthError("No access token available")

        if (
            self.token_expires_at
            and datetime.now() + timedelta(seconds=TOKEN_EXPIRY_MARGIN)
            >= self.token_expires_at
        ):
            await self.refresh_access_token()

    async def _request(
        self, method: str, endpoint: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Make an authenticated request to the API."""
        await self._ensure_token_valid()

        url = f"{self.base_url}/{API_VERSION}{endpoint}"
        headers = {
            "x-app-version": API_APP_VERSION,
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

        max_retries = 3
        base_delay = 60

        for attempt in range(max_retries + 1):
            try:
                async with asyncio.timeout(30):
                    if method.upper() == "GET":
                        async with self.session.get(url, headers=headers) as response:
                            response.raise_for_status()
                            return await response.json()
                    elif method.upper() == "POST":
                        async with self.session.post(
                            url, headers=headers, json=data
                        ) as response:
                            response.raise_for_status()
                            if response.content_type == "application/json":
                                return await response.json()
                            return {}

            except TimeoutError as err:
                if attempt < max_retries:
                    delay = base_delay * (2 ** attempt)
                    _LOGGER.warning(
                        "Request timeout (attempt %d/%d), retrying in %d seconds",
                        attempt + 1,
                        max_retries + 1,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise KumoCloudConnectionError("Request timeout") from err
            except ClientResponseError as err:
                if err.status in (401, 403):
                    raise KumoCloudAuthError("Authentication failed") from err
                if err.status == 429 and attempt < max_retries:
                    delay = base_delay * (2 ** attempt)
                    _LOGGER.warning(
                        "Rate limited (429), retrying in %d seconds (attempt %d/%d)",
                        delay,
                        attempt + 1,
                        max_retries + 1,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise KumoCloudConnectionError(f"HTTP error: {err.status}") from err
            except (aiohttp.ClientError, OSError) as err:
                # Catches DNS failures (ClientConnectorDNSError), connection refused,
                # and other low-level socket errors that aren't ClientResponseError.
                raise KumoCloudConnectionError(f"Connection error: {err}") from err

    async def get_account_info(self) -> dict[str, Any]:
        """Get account information."""
        return await self._request("GET", "/accounts/me")

    async def get_sites(self) -> list[dict[str, Any]]:
        """Get list of sites."""
        return await self._request("GET", "/sites/")

    async def get_zones(self, site_id: str) -> list[dict[str, Any]]:
        """Get list of zones for a site."""
        return await self._request("GET", f"/sites/{site_id}/zones")

    async def get_device_details(self, device_serial: str) -> dict[str, Any]:
        """Get device details."""
        return await self._request("GET", f"/devices/{device_serial}")

    async def get_device_profile(self, device_serial: str) -> list[dict[str, Any]]:
        """Get device profile information."""
        return await self._request("GET", f"/devices/{device_serial}/profile")

    async def get_wireless_sensor(self, device_serial: str) -> dict[str, Any] | None:
        """Get wireless sensor data (battery, temperature, humidity, rssi).

        Returns None if the device has no wireless sensor attached.
        Endpoint: GET /v3/devices/{deviceSerial}/sensor
        """
        return await self._request_optional("GET", f"/devices/{device_serial}/sensor")

    async def get_device_status(self, device_serial: str) -> dict[str, Any] | None:
        """Get device status (firmware version, WiFi signal, setpoint limits).

        Endpoint: GET /v3/devices/{deviceSerial}/status
        Returns: firmwareVersion, roomTempDisplayOffset, routerSsid,
                 routerRssi, minSetPoint, maxSetPoint, lastUpdated, mac.
        """
        return await self._request_optional("GET", f"/devices/{device_serial}/status")

    async def get_zone_notification_preferences(self, zone_id: str) -> dict[str, Any] | None:
        """Get zone notification preferences (filter reminders, alert settings).

        Endpoint: GET /v3/zones/{zoneId}/notification-preferences
        Returns: filterDirtyReminderInterval, filterDirtyReminderLastSent,
                 sensorLowBattery, sensorSignalLost, lowTemp, highTemp, etc.
        """
        return await self._request_optional("GET", f"/zones/{zone_id}/notification-preferences")

    async def get_device_prohibits(self, device_serial: str) -> dict[str, Any] | None:
        """Get which controls the wall remote is locked out of.

        Endpoint: GET /v3/devices/{deviceSerial}/prohibits
        Returns three blocks, `local`, `global` and `effective`, each with
        `power`, `mode` and `setpoint` booleans. `effective` is the one that
        describes what the remote can actually do right now.
        """
        return await self._request_optional("GET", f"/devices/{device_serial}/prohibits")

    async def get_device_recent_connected(self, device_serial: str) -> dict[str, Any] | None:
        """Get last connection time and firmware update state.

        Endpoint: GET /v3/devices/{deviceSerial}/recent-connected
        Returns `timestamp`, `firmwareVer` and `firmwareUpgradeTo`, the last
        being null when the adapter is up to date.
        """
        return await self._request_optional("GET", f"/devices/{device_serial}/recent-connected")

    async def get_site(self, site_id: str) -> dict[str, Any] | None:
        """Get the site record.

        Endpoint: GET /v3/sites/{siteId}
        Carries the name and address, plus `schedulesEnabled` and
        `notificationsEnabled`.
        """
        return await self._request_optional("GET", f"/sites/{site_id}")

    async def get_site_weather(self, site_id: str) -> dict[str, Any] | None:
        """Get outdoor conditions for the site's location.

        Endpoint: GET /v3/sites/{siteId}/weather
        This is an OpenWeatherMap payload for wherever the site is, which is
        what the Comfort app shows. It is not a reading from the equipment.
        """
        return await self._request_optional("GET", f"/sites/{site_id}/weather")

    async def get_active_notifications(self) -> dict[str, Any] | None:
        """Get unresolved alerts across the account.

        Endpoint: GET /v3/notifications/active
        Paginated as `{next, previous, count, data}`. Each entry carries
        `severity`, `eventType` and an optional `zoneId`.
        """
        return await self._request_optional("GET", "/notifications/active")

    async def _request_optional(self, method: str, endpoint: str) -> dict[str, Any] | None:
        """Make a request, returning None when the endpoint is absent.

        Several of these depend on hardware the account may not have, and a
        404 there is an answer rather than a failure.
        """
        try:
            return await self._request(method, endpoint)
        except KumoCloudConnectionError as err:
            if "404" in str(err):
                return None
            raise

    async def send_command(
        self, device_serial: str, commands: dict[str, Any]
    ) -> dict[str, Any]:
        """Send command to device."""
        data = {"deviceSerial": device_serial, "commands": commands}
        return await self._request("POST", "/devices/send-command", data)
