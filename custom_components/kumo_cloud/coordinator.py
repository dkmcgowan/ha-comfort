"""Data update coordinator and per-device wrapper for Kumo Cloud."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import logging
import time
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import KumoCloudAPI, KumoCloudAuthError, KumoCloudConnectionError
from .const import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PUSH_SCAN_INTERVAL,
    PUSH_STALE_AFTER,
)
from .push import KumoCloudPush, merge_device_update

type KumoCloudConfigEntry = ConfigEntry["KumoCloudDataUpdateCoordinator"]

_LOGGER = logging.getLogger(__name__)

# Firmware state, remote lockout and the setpoint limits change on the order
# of days, not minutes, and every one of them costs a request per unit on a
# cloud API with no published rate limit. Fetch them every Nth refresh.
SLOW_TIER_EVERY = 10

class KumoCloudDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Kumo Cloud data."""

    def __init__(self, hass: HomeAssistant, api: KumoCloudAPI, site_id: str) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.api = api
        self.site_id = site_id
        self.zones: list[dict[str, Any]] = []
        self.devices: dict[str, dict[str, Any]] = {}
        self.device_profiles: dict[str, list[dict[str, Any]]] = {}
        self.wireless_sensors: dict[str, dict[str, Any]] = {}
        self.device_statuses: dict[str, dict[str, Any]] = {}
        self.zone_notifications: dict[str, dict[str, Any]] = {}
        self.device_prohibits: dict[str, dict[str, Any]] = {}
        self.device_connections: dict[str, dict[str, Any]] = {}
        self.zone_history: dict[str, list[dict[str, Any]]] = {}
        self.site: dict[str, Any] = {}
        self.site_weather: dict[str, Any] = {}
        self.active_alerts: list[dict[str, Any]] = []
        self.seasons: list[dict[str, Any]] = []
        self.zone_schedules: dict[str, dict[str, Any]] = {}

        # Counts refreshes so the slow tier can run every Nth one.
        self._refresh_count = 0

        # Live updates. Stays None when the push channel could not be opened,
        # in which case everything below falls back to polling alone.
        self.push: KumoCloudPush | None = None
        self._last_push: float | None = None

        # Instance variable to store cached commands
        self.cached_commands: dict[tuple[str, str], tuple[str, Any]] = {}

    def _process_pending_commands(self, device_serial: str, device_detail: dict[str, Any]) -> None:
        """Process cached commands and cull outdated commands for a device."""
        # Check if the device already exists and the updatedAt matches
        if device_serial in self.devices and "updatedAt" in device_detail:
            self.cull_cached_commands(device_serial, device_detail.get("updatedAt"))

        # Reapply cached commands to the device details
        for (cached_device_serial, command), (_, command_value) in self.cached_commands.items():
            if cached_device_serial == device_serial:
                device_detail[command] = command_value

    # ---- Push channel --------------------------------------------------

    async def async_start_push(self) -> None:
        """Open the live update channel, if it will open.

        Called after the first poll so the device list is known. Failure is
        not fatal and is not raised: the integration polls exactly as it did
        before this existed.
        """
        push = KumoCloudPush(
            access_token_provider=lambda: self.api.access_token,
            token_refresher=self.api.refresh_access_token,
            on_device_update=self._handle_push_update,
        )
        if await push.async_start(self._serials()):
            self.push = push
            self._apply_push_interval()
            _LOGGER.debug("Push channel open, poll interval now %s", self.update_interval)

    async def async_stop_push(self) -> None:
        """Close the live update channel."""
        if self.push is not None:
            await self.push.async_stop()
            self.push = None

    def _serials(self) -> list[str]:
        """Return every adapter serial on the site."""
        return [
            zone["adapter"]["deviceSerial"]
            for zone in self.zones
            if zone.get("adapter")
        ]

    @property
    def push_healthy(self) -> bool:
        """Return whether push is connected and has been delivering.

        A connected socket that has said nothing for a long time is not
        obviously working, and the difference matters because it decides how
        often we poll.
        """
        if self.push is None or not self.push.connected:
            return False
        if self._last_push is None:
            return False
        return (time.monotonic() - self._last_push) < PUSH_STALE_AFTER

    def _apply_push_interval(self) -> None:
        """Slow the poll to a heartbeat while push is healthy."""
        wanted = timedelta(
            seconds=PUSH_SCAN_INTERVAL if self.push_healthy else DEFAULT_SCAN_INTERVAL
        )
        if self.update_interval != wanted:
            self.update_interval = wanted
            _LOGGER.debug("Poll interval now %s", wanted)

    @callback
    def _handle_push_update(self, serial: str, payload: dict[str, Any]) -> None:
        """Apply one pushed device payload and tell the entities.

        Writes into both the device record and the matching zone adapter,
        because different properties read from different places.
        """
        self._last_push = time.monotonic()

        if serial not in self.devices:
            # A device we have not polled yet. The next refresh will pick it
            # up properly; merging into nothing would produce a partial
            # record that entities would read as missing fields.
            return

        merged = merge_device_update(self.devices[serial], payload)
        # Anything the user just asked for outranks what the cloud reports
        # until the cloud catches up, same rule the poll follows.
        self._process_pending_commands(serial, merged)
        self.devices[serial] = merged

        for zone in self.zones:
            adapter = zone.get("adapter")
            if adapter and adapter.get("deviceSerial") == serial:
                zone["adapter"] = merge_device_update(adapter, payload)
                break

        self.data = self._snapshot()
        self._apply_push_interval()
        self.async_update_listeners()

    def _snapshot(self) -> dict[str, Any]:
        """Return the coordinator's data dict.

        Built in one place because there are two callers, the poll and the
        single device refresh, and when they were written out separately the
        second one quietly went stale every time a field was added.
        """
        return {
            "zones": self.zones,
            "devices": self.devices,
            "device_profiles": self.device_profiles,
            "wireless_sensors": self.wireless_sensors,
            "device_statuses": self.device_statuses,
            "zone_notifications": self.zone_notifications,
            "device_prohibits": self.device_prohibits,
            "device_connections": self.device_connections,
            "zone_history": self.zone_history,
            "site": self.site,
            "site_weather": self.site_weather,
            "active_alerts": self.active_alerts,
            "seasons": self.seasons,
            "zone_schedules": self.zone_schedules,
        }

    @property
    def site_name(self) -> str:
        """Return the site's name, falling back to something printable."""
        return self.site.get("name") or "Kumo Cloud site"

    async def _async_update_schedules(self) -> None:
        """Load the running season's schedules, keyed by zone.

        Only the running season is fetched. An account can hold several, but
        the others are not driving anything, and each one is another request.
        """
        season = self.active_season
        if season is None:
            self.zone_schedules = {}
            return

        try:
            schedules = await self.api.get_season_schedules(season["id"])
        except (KumoCloudConnectionError, aiohttp.ClientError, OSError, TimeoutError) as err:
            _LOGGER.debug("Failed to fetch schedules: %s", err)
            return

        self.zone_schedules = {
            entry["zone"]["id"]: entry
            for entry in schedules
            if isinstance(entry.get("zone"), dict) and entry["zone"].get("id")
        }

    @property
    def active_season(self) -> dict[str, Any] | None:
        """Return the running season, falling back to the default one."""
        for season in self.seasons:
            if season.get("isRunning"):
                return season
        for season in self.seasons:
            if season.get("isDefault"):
                return season
        return self.seasons[0] if self.seasons else None

    async def _async_update_site_data(self) -> None:
        """Fetch the two account-wide extras.

        Neither is per zone, so this is two requests however many units the
        account has. Failures are logged and dropped: outdoor weather and the
        alert list are nice to have, and neither is worth failing a refresh
        that otherwise succeeded.
        """
        site, weather, alerts, seasons = await asyncio.gather(
            self.api.get_site(self.site_id),
            self.api.get_site_weather(self.site_id),
            self.api.get_active_notifications(),
            self.api.get_schedule_seasons(self.site_id),
            return_exceptions=True,
        )

        if isinstance(seasons, list):
            self.seasons = seasons
            await self._async_update_schedules()
        elif isinstance(seasons, Exception):
            _LOGGER.debug("Failed to fetch schedule seasons: %s", seasons)

        if isinstance(site, dict):
            self.site = site
        elif isinstance(site, Exception):
            _LOGGER.debug("Failed to fetch site record: %s", site)

        if isinstance(weather, dict):
            self.site_weather = weather
        elif isinstance(weather, Exception):
            _LOGGER.debug("Failed to fetch site weather: %s", weather)

        if isinstance(alerts, dict):
            self.active_alerts = alerts.get("data") or []
        elif isinstance(alerts, Exception):
            _LOGGER.debug("Failed to fetch active alerts: %s", alerts)

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from Kumo Cloud."""
        try:
            slow_tier = self._refresh_count % SLOW_TIER_EVERY == 0
            self._refresh_count += 1

            # Get zones for the site
            zones = await self.api.get_zones(self.site_id)

            # Get device details for each zone
            devices = {}
            device_profiles = {}
            wireless_sensors = {}
            device_statuses = {}
            zone_notifications = {}
            device_prohibits = dict(self.device_prohibits)
            device_connections = dict(self.device_connections)
            zone_history = dict(self.zone_history)

            if slow_tier:
                await self._async_update_site_data()

            for zone in zones:
                if zone.get("adapter"):
                    device_serial = zone["adapter"]["deviceSerial"]
                    zone_id = zone["id"]
                    has_sensor = zone["adapter"].get("hasSensor", False)

                    # Build task list - fetch everything in parallel
                    task_keys = ["detail", "profile", "status", "notifications"]
                    tasks = [
                        self.api.get_device_details(device_serial),
                        self.api.get_device_profile(device_serial),
                        self.api.get_device_status(device_serial),
                        self.api.get_zone_notification_preferences(zone_id),
                    ]
                    # Also fetch wireless sensor data if the zone has one
                    if has_sensor:
                        task_keys.append("sensor")
                        tasks.append(self.api.get_wireless_sensor(device_serial))

                    if slow_tier:
                        task_keys += ["prohibits", "connection", "history"]
                        tasks += [
                            self.api.get_device_prohibits(device_serial),
                            self.api.get_device_recent_connected(device_serial),
                            self.api.get_zone_connection_history(zone_id),
                        ]

                    results = await asyncio.gather(*tasks, return_exceptions=True)

                    # Process results by key
                    result_map = {}
                    for key, result in zip(task_keys, results, strict=True):
                        if isinstance(result, Exception):
                            _LOGGER.debug(
                                "Failed to fetch %s for %s: %s", key, device_serial, result
                            )
                            result_map[key] = None
                        else:
                            result_map[key] = result

                    device_detail = result_map.get("detail") or {}

                    # Process pending commands for the device
                    self._process_pending_commands(device_serial, device_detail)

                    devices[device_serial] = device_detail
                    device_profiles[device_serial] = result_map.get("profile") or []

                    if result_map.get("status"):
                        device_statuses[device_serial] = result_map["status"]

                    if result_map.get("notifications"):
                        zone_notifications[zone_id] = result_map["notifications"]

                    if has_sensor and result_map.get("sensor"):
                        wireless_sensors[device_serial] = result_map["sensor"]

                    # Slow tier results are carried over from the previous
                    # refresh on the cycles where they were not fetched.
                    if result_map.get("prohibits"):
                        device_prohibits[device_serial] = result_map["prohibits"]
                    if result_map.get("connection"):
                        device_connections[device_serial] = result_map["connection"]
                    if result_map.get("history"):
                        zone_history[zone_id] = result_map["history"].get("data") or []

            # Store the data for access by entities
            self.zones = zones
            self.devices = devices
            self.device_profiles = device_profiles
            self.wireless_sensors = wireless_sensors
            self.device_statuses = device_statuses
            self.zone_notifications = zone_notifications
            self.device_prohibits = device_prohibits
            self.device_connections = device_connections
            self.zone_history = zone_history

            # A zone added since the last poll needs subscribing to, and a
            # push channel that has gone quiet or dropped needs the poll to
            # speed back up.
            if self.push is not None:
                await self.push.async_set_serials(self._serials())
            self._apply_push_interval()

            return self._snapshot()

        except KumoCloudAuthError:
            # Reactive token refresh: a 401 surfaced mid-poll, despite
            # `api._ensure_token_valid` doing proactive refresh on each call.
            # Try to refresh once and replay the poll; if that fails, give up
            # and let HA mark the entry stale / trigger a re-auth flow.
            try:
                await self.api.refresh_access_token()
                return await self._async_update_data()
            except KumoCloudAuthError as refresh_err:
                raise UpdateFailed(
                    f"Authentication failed: {refresh_err}"
                ) from refresh_err
            except (
                TimeoutError,
                KumoCloudConnectionError,
                aiohttp.ClientError,
                OSError,
            ) as refresh_err:
                raise UpdateFailed(
                    f"Error during token refresh: {refresh_err}"
                ) from refresh_err
        except KumoCloudConnectionError as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err
        except (TimeoutError, aiohttp.ClientError, OSError) as err:
            raise UpdateFailed(f"Connection error: {err}") from err

    async def async_refresh_device(self, device_serial: str) -> None:
        """Refresh a specific device's data immediately."""
        try:
            # Get fresh device details
            device_detail = await self.api.get_device_details(device_serial)

            # Process pending commands for the device
            self._process_pending_commands(device_serial, device_detail)

            # Update the cached device data
            self.devices[device_serial] = device_detail

            # Also update the zone data if it contains the same info
            for zone in self.zones:
                if zone.get("adapter") and zone["adapter"]["deviceSerial"] == device_serial:
                    # Update adapter data with fresh device data
                    zone["adapter"].update(
                        {
                            "roomTemp": device_detail.get("roomTemp"),
                            "operationMode": device_detail.get("operationMode"),
                            "power": device_detail.get("power"),
                            "fanSpeed": device_detail.get("fanSpeed"),
                            "airDirection": device_detail.get("airDirection"),
                            "spCool": device_detail.get("spCool"),
                            "spHeat": device_detail.get("spHeat"),
                            "humidity": device_detail.get("humidity"),
                        }
                    )
                    break

            # Update the coordinator's data dict
            self.data = self._snapshot()

            # Notify all listeners that data has been updated
            self.async_update_listeners()

            _LOGGER.debug("Refreshed device %s data", device_serial)

        except (
            TimeoutError,
            KumoCloudAuthError,
            KumoCloudConnectionError,
            aiohttp.ClientError,
            OSError,
        ) as err:
            _LOGGER.warning("Failed to refresh device %s: %s", device_serial, err)

    def cache_command(self, device_serial: str, command: str, value: Any) -> None:
        """Cache a command with its value and timestamp."""
        current_time = datetime.now(UTC).isoformat()
        self.cached_commands[(device_serial, command)] = (current_time, value)
        _LOGGER.debug("Cached command in device data: %s at %s", command, current_time)

    def cull_cached_commands(self, device_serial: str, date: str) -> None:
        """Drop this device's cached commands stamped at or before the given date."""
        to_remove = []
        input_date = datetime.fromisoformat(date)

        for key, value in self.cached_commands.items():
            cached_device_serial, _command = key
            cached_date, _ = value
            cached_date_obj = datetime.fromisoformat(cached_date)

            # Check if the device_serial matches and the input date is on or after the cached date
            if cached_device_serial == device_serial and input_date >= cached_date_obj:
                to_remove.append(key)
            else:
                # Log details if the condition fails
                _LOGGER.debug(
                    "Skipping cached command: cached_device_serial=%s, device_serial=%s, "
                    "input_date=%s, cached_date_obj=%s, date=%s, cached_date=%s",
                    cached_device_serial,
                    device_serial,
                    input_date,
                    cached_date_obj,
                    date,
                    cached_date,
                )

        # Remove the matching keys
        for key in to_remove:
            del self.cached_commands[key]

        # Log the culled and remaining commands
        remaining_count = len(self.cached_commands)
        _LOGGER.debug(
            "Culled %d cached commands for device %s on or after %s. Remaining cached commands: %d",
            len(to_remove), device_serial, date, remaining_count
        )

class KumoCloudDevice:
    """Representation of a Kumo Cloud device."""

    def __init__(
        self,
        coordinator: KumoCloudDataUpdateCoordinator,
        zone_id: str,
        device_serial: str,
    ) -> None:
        """Initialize the device."""
        self.coordinator = coordinator
        self.zone_id = zone_id
        self.device_serial = device_serial
        self._zone_data: dict[str, Any] | None = None
        self._device_data: dict[str, Any] | None = None
        self._profile_data: list[dict[str, Any]] | None = None

    @property
    def zone_data(self) -> dict[str, Any]:
        """Get the zone data."""
        # Always get fresh data from coordinator
        for zone in self.coordinator.zones:
            if zone["id"] == self.zone_id:
                return zone
        return {}

    @property
    def device_data(self) -> dict[str, Any]:
        """Get the device data."""
        # Always get fresh data from coordinator
        return self.coordinator.devices.get(self.device_serial, {})

    @property
    def profile_data(self) -> list[dict[str, Any]]:
        """Get the device profile data."""
        # Always get fresh data from coordinator
        return self.coordinator.device_profiles.get(self.device_serial, [])

    @property
    def has_wireless_sensor(self) -> bool:
        """Return True if this device has a wireless sensor attached."""
        zone = self.zone_data
        adapter = zone.get("adapter", {})
        return adapter.get("hasSensor", False)

    @property
    def wireless_sensor_data(self) -> dict[str, Any] | None:
        """Get the wireless sensor data (battery, temp, humidity, rssi)."""
        return self.coordinator.wireless_sensors.get(self.device_serial)

    @property
    def device_status_data(self) -> dict[str, Any] | None:
        """Get device status data (firmware, WiFi signal, router info)."""
        return self.coordinator.device_statuses.get(self.device_serial)

    @property
    def zone_notification_data(self) -> dict[str, Any] | None:
        """Get zone notification preferences (filter reminders, alert settings)."""
        return self.coordinator.zone_notifications.get(self.zone_id)

    @property
    def prohibits_data(self) -> dict[str, Any] | None:
        """Get the wall remote lockout state."""
        return self.coordinator.device_prohibits.get(self.device_serial)

    @property
    def connection_data(self) -> dict[str, Any] | None:
        """Get last connection time and pending firmware upgrade."""
        return self.coordinator.device_connections.get(self.device_serial)

    @property
    def display_config(self) -> dict[str, Any]:
        """Get what the indoor unit is showing on its own display.

        Carries `filter`, `defrost`, `hotAdjust` and `standby`. The filter
        flag is the unit's own opinion, unlike the reminder date in the zone
        notification preferences, which is just a 30 day calendar.
        """
        return self.device_data.get("displayConfig") or {}

    @property
    def hold(self) -> dict[str, Any]:
        """Get the zone's hold, the app's temporary override.

        Shape: `{enabled, type, holdType, endTime, operationMode, fanSpeed,
        airDirection, spCool, spHeat}`. The setting fields are the values the
        hold applies, and are null when the hold is not overriding them.
        """
        return self.zone_data.get("holdMode") or {}

    @property
    def has_active_schedule(self) -> bool:
        """Return whether a schedule is running on this zone."""
        return bool(self.zone_data.get("hasActiveSchedule"))

    @property
    def schedule(self) -> dict[str, Any]:
        """Get this zone's schedule within the running season."""
        return self.coordinator.zone_schedules.get(self.zone_id) or {}

    @property
    def schedule_events(self) -> list[dict[str, Any]]:
        """Get this zone's scheduled events."""
        return self.schedule.get("events") or []

    @property
    def connection_history(self) -> list[dict[str, Any]]:
        """Get the zone's connection history, newest first."""
        return self.coordinator.zone_history.get(self.zone_id, [])

    @property
    def alerts(self) -> list[dict[str, Any]]:
        """Get active alerts that name this zone, plus account-wide ones."""
        return [
            alert
            for alert in self.coordinator.active_alerts
            if alert.get("zoneId") in (None, self.zone_id)
        ]

    @property
    def available(self) -> bool:
        """Return True if device is available."""
        adapter = self.zone_data.get("adapter", {})
        device_data = self.device_data

        # Check both adapter and device data for connection status
        adapter_connected = adapter.get("connected", False)
        device_connected = device_data.get("connected", adapter_connected)

        return device_connected

    @property
    def name(self) -> str:
        """Return the name of the device."""
        return self.zone_data.get("name", f"Zone {self.zone_id}")

    @property
    def unique_id(self) -> str:
        """Return a unique ID for the device."""
        return f"{self.device_serial}_{self.zone_id}"

    async def send_command(self, commands: dict[str, Any]) -> None:
        """Send a command to the device and refresh status."""
        try:
            response = await self.coordinator.api.send_command(self.device_serial, commands)
            _LOGGER.debug(
                "Sent command to device %s: %s, Response: %s",
                self.device_serial,
                commands,
                response,
            )

            # Wait a moment for the command to be processed
            await asyncio.sleep(1)

            # Refresh this specific device's data immediately
            await self.coordinator.async_refresh_device(self.device_serial)

        except (
            TimeoutError,
            KumoCloudAuthError,
            KumoCloudConnectionError,
            aiohttp.ClientError,
            OSError,
        ) as err:
            _LOGGER.error(
                "Failed to send command to device %s: %s", self.device_serial, err
            )
            raise

    def cache_command(self, command: str, value: Any) -> None:
        """Cache a command with its value and timestamp in the coordinator."""
        self.coordinator.cache_command(self.device_serial, command, value)

    def cache_commands(self, commands: dict[str, Any]) -> None:
        """Cache multiple commands with their values and timestamps in the coordinator."""
        for command, value in commands.items():
            self.cache_command(command, value)
