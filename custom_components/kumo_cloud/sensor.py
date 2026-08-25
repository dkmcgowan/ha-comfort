"""Platform for Kumo Cloud sensors.

Provides standalone sensor entities for each Mitsubishi zone:
- Temperature (the room reading the unit controls against, offset included,
  converted the way the Comfort app converts it)
- Humidity (from indoor unit)
- WiFi Adapter Firmware Version (diagnostic, from /status)
- WiFi Signal Strength (diagnostic, routerRssi from /status)
- Filter Reminder (diagnostic, from /notification-preferences)

Most of the diagnostic sensors are registered disabled. They are here for
the day something is wrong, and a dozen of them per zone buries the handful
anyone looks at daily. The ones left enabled are the ones that answer "is
this zone healthy": WiFi signal, both wireless sensor readings, active
alerts and connection uptime. Turn the rest on per entity, or per device
from the device page, when you need them.

For zones with a wireless sensor (PAC-USWHS003-TH-1) attached:
- Wireless Sensor Battery (%)
- Wireless Sensor Signal Strength (RSSI dBm)
- Wireless Sensor Temperature (from the remote sensor itself)
- Wireless Sensor Humidity (from the remote sensor itself)

API endpoints discovered via Proxyman traffic capture of the Comfort app:
- /v3/devices/{serial}/sensor  (wireless sensor data)
- /v3/devices/{serial}/status  (firmware, WiFi signal, router info)
- /v3/zones/{zoneId}/notification-preferences  (filter reminders)
"""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .connection import summarize_history
from .coordinator import (
    KumoCloudConfigEntry,
    KumoCloudDataUpdateCoordinator,
    KumoCloudDevice,
)
from .entity import KumoCloudEntity, KumoCloudSiteEntity
from .schedule import describe, next_event, zone_timezone
from .temperature import c_delta_to_f, c_to_f

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KumoCloudConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Kumo Cloud sensor devices.

    Entities are added on every coordinator refresh, not only at setup.
    Pairing a wireless sensor in the Comfort app flips the zone's `hasSensor`
    flag long after Home Assistant started, and adding a zone appears the
    same way. Building the list once meant neither ever showed up until the
    config entry was reloaded by hand.
    """
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _async_add_new_entities() -> None:
        """Create entities for anything we have not seen before."""
        new: list[SensorEntity] = []

        for entity in build_site_sensors(coordinator):
            if entity.unique_id not in known:
                known.add(entity.unique_id)
                new.append(entity)

        for zone in coordinator.zones:
            adapter = zone.get("adapter")
            if not adapter:
                continue

            device = KumoCloudDevice(coordinator, zone["id"], adapter["deviceSerial"])

            candidates: list[SensorEntity] = [
                KumoCloudTemperatureSensor(device),
                KumoCloudHumiditySensor(device),
                KumoCloudFirmwareSensor(device),
                KumoCloudWiFiSignalSensor(device),
                KumoCloudFilterReminderSensor(device),
                KumoCloudStatusCodeSensor(device),
                KumoCloudSetpointLimitSensor(device, "minimum"),
                KumoCloudSetpointLimitSensor(device, "maximum"),
                KumoCloudRemoteLockoutSensor(device),
                KumoCloudAlertSensor(device),
                KumoCloudConnectionSensor(device),
                KumoCloudTempOffsetSensor(device),
            ]
            # Only zones that actually have a timetable get the schedule
            # sensor. On an account that runs no schedules there is nothing
            # for it to say and it sat at Unknown forever, which reads as
            # broken rather than as empty. This callback runs on every
            # refresh, so the sensor appears within a poll of the first
            # event being saved in the Comfort app.
            if device.schedule_events:
                candidates.append(KumoCloudNextScheduleSensor(device))
            if adapter.get("hasSensor", False):
                candidates += [
                    KumoCloudWirelessBatterySensor(device),
                    KumoCloudWirelessSignalSensor(device),
                    KumoCloudWirelessTemperatureSensor(device),
                    KumoCloudWirelessHumiditySensor(device),
                ]

            for entity in candidates:
                if entity.unique_id not in known:
                    known.add(entity.unique_id)
                    new.append(entity)

        if new:
            _LOGGER.debug("Adding %d new sensor entities", len(new))
            async_add_entities(new)

    _async_add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_entities))


# =============================================================================
# Indoor unit sensors
# =============================================================================


class MitsubishiTemperatureMixin:
    """Report a Mitsubishi temperature the way Mitsubishi displays it.

    The cloud stores every temperature in Celsius, in half-degree steps.
    Left as a Celsius native value, Home Assistant converts it to Fahrenheit
    by arithmetic and lands between Mitsubishi's own steps: 22.0 C becomes
    71.6, which rounds to 72, while the Comfort app and the unit's remote
    both show 71. Confirmed on 2026-08-25 against all four zones, with the
    display offsets cleared.

    So the conversion is done here, off the lookup table in
    `temperature.py`, and the entity presents an already-converted native
    value. This is the same table the climate entity uses, which is what
    stops the two from disagreeing about the same reading.

    A Celsius system gets the stored value untouched, which is already what
    the app shows there.
    """

    _attr_device_class = SensorDeviceClass.TEMPERATURE

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit this system displays temperatures in."""
        return self.hass.config.units.temperature_unit

    @property
    def suggested_display_precision(self) -> int:
        """Return whole degrees in Fahrenheit, halves in Celsius."""
        if self.native_unit_of_measurement == UnitOfTemperature.FAHRENHEIT:
            return 0
        return 1

    def _display(self, celsius: float | None) -> float | None:
        """Convert a stored Celsius reading for display."""
        if celsius is None:
            return None
        if self.native_unit_of_measurement == UnitOfTemperature.FAHRENHEIT:
            return c_to_f(celsius)
        return celsius


class KumoCloudTemperatureSensor(
    MitsubishiTemperatureMixin, KumoCloudEntity, SensorEntity
):
    """The room temperature the unit is working from.

    This is `roomTemp`, which is what the climate entity shows as its
    current temperature and what the equipment controls against. It is not
    a raw thermistor reading: where a wireless sensor is paired it is that
    sensor's measurement, and either way it already has the adapter's
    display offset added. Read live on 2026-08-25, one zone reported 23.5
    here against a wireless sensor at 21.10, with an offset of 2.5. The
    other three matched the same way, to the half degree the offset is
    stored in.

    So the pairing to expect on a zone with a wireless sensor is this one
    plus `Wireless Sensor Temperature`. They will not match to the decimal
    even with the offset cleared, because `roomTemp` is the sensor rounded
    to the half degree it is stored in, and only then converted. A zone
    reading 21.8 on its sensor stores 22.0 here and displays 71. The unit's
    own thermistor is not separately reported; `tempSource` and
    `activeThermistor` are null on every unit seen.
    """

    _attr_name = "Temperature"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, device: KumoCloudDevice) -> None:
        """Initialize the sensor."""
        super().__init__(device)
        self._attr_unique_id = f"{device.device_serial}_temperature"

    @property
    def native_value(self) -> float | None:
        """Return the room temperature reported by the indoor unit."""
        adapter = self.device.zone_data.get("adapter", {})
        return self._display(adapter.get("roomTemp"))


class KumoCloudHumiditySensor(KumoCloudEntity, SensorEntity):
    """Humidity from the indoor unit."""

    _attr_name = "Humidity"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_state_class = SensorStateClass.MEASUREMENT
    # The API reports five decimals. Keep the raw value as the state and let
    # the display round, so history stays smooth but the card stays readable.
    _attr_suggested_display_precision = 0

    def __init__(self, device: KumoCloudDevice) -> None:
        """Initialize the sensor."""
        super().__init__(device)
        self._attr_unique_id = f"{device.device_serial}_humidity"

    @property
    def native_value(self) -> float | None:
        """Return the humidity reported by the indoor unit."""
        adapter = self.device.zone_data.get("adapter", {})
        device_data = self.device.device_data
        return device_data.get("humidity", adapter.get("humidity"))


# =============================================================================
# Diagnostic sensors from /devices/{serial}/status
# =============================================================================

class KumoCloudFirmwareSensor(KumoCloudEntity, SensorEntity):
    """WiFi adapter firmware version."""

    _attr_name = "Firmware"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_icon = "mdi:chip"

    def __init__(self, device: KumoCloudDevice) -> None:
        """Initialize the sensor."""
        super().__init__(device)
        self._attr_unique_id = f"{device.device_serial}_firmware"

    @property
    def native_value(self) -> str | None:
        """Return the WiFi adapter's firmware version."""
        status = self.device.device_status_data
        if status is None:
            return None
        return status.get("firmwareVersion")


class KumoCloudWiFiSignalSensor(KumoCloudEntity, SensorEntity):
    """WiFi adapter signal strength to the router."""

    _attr_name = "WiFi Signal"
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, device: KumoCloudDevice) -> None:
        """Initialize the sensor."""
        super().__init__(device)
        self._attr_unique_id = f"{device.device_serial}_wifi_rssi"

    @property
    def native_value(self) -> int | None:
        """Return the WiFi adapter's signal strength to the router."""
        status = self.device.device_status_data
        if status is None:
            return None
        return status.get("routerRssi")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Include router SSID as an attribute."""
        status = self.device.device_status_data
        if status and status.get("routerSsid"):
            return {"router_ssid": status["routerSsid"]}
        return {}


class KumoCloudFilterReminderSensor(KumoCloudEntity, SensorEntity):
    """Last filter dirty reminder date."""

    _attr_name = "Filter Reminder"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_icon = "mdi:air-filter"

    def __init__(self, device: KumoCloudDevice) -> None:
        """Initialize the sensor."""
        super().__init__(device)
        self._attr_unique_id = f"{device.device_serial}_filter_reminder"

    @property
    def native_value(self) -> datetime | None:
        """Return when the last filter reminder was sent."""
        notifications = self.device.zone_notification_data
        if notifications is None:
            return None
        last_sent = notifications.get("filterDirtyReminderLastSent")
        if last_sent:
            try:
                return datetime.fromisoformat(last_sent.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                return None
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Include reminder interval as an attribute."""
        notifications = self.device.zone_notification_data
        if notifications:
            attrs = {}
            interval = notifications.get("filterDirtyReminderInterval")
            if interval is not None:
                attrs["reminder_interval_days"] = interval
            enabled = notifications.get("filterDirty")
            if enabled is not None:
                attrs["reminders_enabled"] = enabled
            return attrs
        return {}


# =============================================================================
# Wireless sensor entities (PAC-USWHS003-TH-1)
# =============================================================================

class KumoCloudWirelessBatterySensor(KumoCloudEntity, SensorEntity):
    """Battery level of the wireless temperature/humidity sensor."""

    _attr_name = "Wireless Sensor Battery"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, device: KumoCloudDevice) -> None:
        """Initialize the sensor."""
        super().__init__(device)
        self._attr_unique_id = f"{device.device_serial}_wireless_battery"

    @property
    def native_value(self) -> int | None:
        """Return the wireless sensor's battery level."""
        sensor_data = self.device.wireless_sensor_data
        if sensor_data is None:
            return None
        return sensor_data.get("battery")


class KumoCloudWirelessSignalSensor(KumoCloudEntity, SensorEntity):
    """Signal strength (RSSI) of the wireless sensor to the WiFi adapter."""

    _attr_name = "Wireless Sensor Signal"
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, device: KumoCloudDevice) -> None:
        """Initialize the sensor."""
        super().__init__(device)
        self._attr_unique_id = f"{device.device_serial}_wireless_rssi"

    @property
    def native_value(self) -> int | None:
        """Return the wireless sensor's signal strength to the adapter."""
        sensor_data = self.device.wireless_sensor_data
        if sensor_data is None:
            return None
        return sensor_data.get("rssi")


class KumoCloudWirelessTemperatureSensor(KumoCloudEntity, SensorEntity):
    """Temperature reading from the wireless sensor itself.

    Deliberately not put through the Mitsubishi lookup table the room
    temperature uses. This is the sensor's own measurement, reported to two
    decimals and on no particular grid, so it is a real continuous reading
    and ordinary arithmetic is the right conversion for it. The table maps
    the half-degree steps `roomTemp` is quantized to, and has nothing to say
    about a value in between them.

    The consequence is that this sits a few tenths off `Temperature` even
    with the display offset cleared, and that is correct rather than a
    rounding bug: 21.8 here is stored as 22.0 there and shown as 71.
    """

    _attr_name = "Wireless Sensor Temperature"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    def __init__(self, device: KumoCloudDevice) -> None:
        """Initialize the sensor."""
        super().__init__(device)
        self._attr_unique_id = f"{device.device_serial}_wireless_temperature"

    @property
    def native_value(self) -> float | None:
        """Return the temperature measured by the wireless sensor."""
        sensor_data = self.device.wireless_sensor_data
        if sensor_data is None:
            return None
        temp = sensor_data.get("temperature")
        if temp is not None:
            return round(temp, 1)
        return None


class KumoCloudWirelessHumiditySensor(KumoCloudEntity, SensorEntity):
    """Humidity reading from the wireless sensor itself."""

    _attr_name = "Wireless Sensor Humidity"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    def __init__(self, device: KumoCloudDevice) -> None:
        """Initialize the sensor."""
        super().__init__(device)
        self._attr_unique_id = f"{device.device_serial}_wireless_humidity"

    @property
    def native_value(self) -> float | None:
        """Return the humidity measured by the wireless sensor."""
        sensor_data = self.device.wireless_sensor_data
        if sensor_data is None:
            return None
        humidity = sensor_data.get("humidity")
        if humidity is not None:
            return round(humidity, 1)
        return None


# =============================================================================
# Diagnostics the API reports but nothing used to surface
# =============================================================================


class KumoCloudStatusCodeSensor(KumoCloudEntity, SensorEntity):
    """The two character code the indoor unit shows on its own display."""

    _attr_name = "Status code"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_icon = "mdi:alert-circle-outline"

    def __init__(self, device: KumoCloudDevice) -> None:
        """Initialize the sensor."""
        super().__init__(device)
        self._attr_unique_id = f"{device.device_serial}_status_code"

    @property
    def native_value(self) -> str | None:
        """Return the code. A0 is the healthy one."""
        return self.device.device_data.get("twoFiguresCode")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the fault detail alongside the code."""
        unusual = self.device.device_data.get("unusualFigures")
        return {"unusual_figures": unusual} if unusual else {}


class KumoCloudSetpointLimitSensor(
    MitsubishiTemperatureMixin, KumoCloudEntity, SensorEntity
):
    """One end of the adapter's configured setpoint range.

    This is the limit stored on the adapter, which is not the same as the
    range the hardware supports. The two differ per unit: on one account the
    profile allows heat down to 10 C while the adapter is set to 16 C.

    Read only for now. The Comfort app changes these over its local socket
    rather than the cloud API, and the account preference that gates the
    feature, `isMinMaxSetpointsEnabled`, is off by default.
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, device: KumoCloudDevice, bound: str) -> None:
        """Initialize for either the minimum or the maximum bound."""
        super().__init__(device)
        self._bound = bound
        self._attr_name = f"{bound.capitalize()} setpoint limit"
        self._attr_unique_id = f"{device.device_serial}_{bound}_setpoint_limit"

    @property
    def native_value(self) -> float | None:
        """Return the configured bound."""
        status = self.device.device_status_data
        if status is None:
            return None
        field = "minSetPoint" if self._bound == "minimum" else "maxSetPoint"
        return self._display(status.get(field))


class KumoCloudTempOffsetSensor(KumoCloudEntity, SensorEntity):
    """The correction the adapter applies to its reported room temperature.

    Read only. The cloud accepts a new value through both the device patch
    and the command endpoint, returns 200 for each, and leaves it unchanged.
    Set it in the Comfort app; this reports it.

    Worth knowing when a zone's temperature looks wrong: the room reading
    already has this added, so a non-zero offset explains a gap between the
    unit and a wireless sensor in the same room.

    **This is a difference between two temperatures, not a temperature.**
    Declaring the temperature device class made Home Assistant convert it
    the way it converts a reading, by scaling *and shifting*, so an offset
    of 0 C was displayed as 32 F. There is no delta device class to use
    instead, so the class is left off and the conversion done here, by
    Mitsubishi's own rule rather than by arithmetic: one Fahrenheit step is
    half a Celsius degree, so a difference doubles. See `c_delta_to_f`.
    """

    _attr_name = "Temperature offset"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:thermometer-plus"

    def __init__(self, device: KumoCloudDevice) -> None:
        """Initialize the sensor."""
        super().__init__(device)
        self._attr_unique_id = f"{device.device_serial}_temp_offset"

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit the rest of this system is displayed in."""
        return self.hass.config.units.temperature_unit

    @property
    def native_value(self) -> float | None:
        """Return the configured offset, as a difference in that unit."""
        status = self.device.device_status_data
        if status is None:
            return None
        offset = status.get("roomTempDisplayOffset")
        if offset is None:
            return None
        if self.native_unit_of_measurement == UnitOfTemperature.FAHRENHEIT:
            return c_delta_to_f(offset)
        return offset


class KumoCloudRemoteLockoutSensor(KumoCloudEntity, SensorEntity):
    """What the wall remote is currently locked out of.

    `/devices/{serial}/prohibits` reports `local`, `global` and `effective`
    blocks, each with `power`, `mode` and `setpoint`. Only `effective`
    describes what the remote can actually do, so that is the state; the
    other two are attributes for anyone working out where a lock came from.
    """

    _attr_name = "Remote lockout"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_icon = "mdi:remote-off"

    def __init__(self, device: KumoCloudDevice) -> None:
        """Initialize the sensor."""
        super().__init__(device)
        self._attr_unique_id = f"{device.device_serial}_remote_lockout"

    @property
    def native_value(self) -> str | None:
        """Return the locked controls, or "none"."""
        prohibits = self.device.prohibits_data
        if prohibits is None:
            return None
        effective = prohibits.get("effective") or {}
        locked = sorted(name for name, value in effective.items() if value)
        return ", ".join(locked) if locked else "none"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the local and global blocks separately."""
        prohibits = self.device.prohibits_data
        if prohibits is None:
            return {}
        return {
            "local": prohibits.get("local"),
            "global": prohibits.get("global"),
        }


class KumoCloudAlertSensor(KumoCloudEntity, SensorEntity):
    """Count of unresolved alerts that apply to this zone."""

    _attr_name = "Active alerts"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:bell-alert-outline"

    def __init__(self, device: KumoCloudDevice) -> None:
        """Initialize the sensor."""
        super().__init__(device)
        self._attr_unique_id = f"{device.device_serial}_active_alerts"

    @property
    def native_value(self) -> int:
        """Return how many alerts are open."""
        return len(self.device.alerts)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose what the alerts are."""
        return {
            "alerts": [
                {
                    "severity": alert.get("severity"),
                    "event_type": alert.get("eventType"),
                    "created_at": alert.get("createdAt"),
                }
                for alert in self.device.alerts
            ]
        }


class KumoCloudConnectionSensor(KumoCloudEntity, SensorEntity):
    """When the adapter last came online, with its recent history.

    `/zones/{id}/connection-history` returns rows of
    `{start, end, isConnected, uptime}`, newest first. **Each row is a
    connected session, not an outage.** `isConnected` marks only the open
    row, so every closed row reads false whatever happened during it, and
    `uptime` is that session's length. The outages are the gaps between
    sessions, which is what the attributes here report.

    Read the other way round, the rows look like days of downtime on an
    adapter that was working the whole time. The arithmetic is what settles
    it: as outages they sum to more than the window they cover.
    """

    _attr_name = "Connected since"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:lan-connect"

    def __init__(self, device: KumoCloudDevice) -> None:
        """Initialize the sensor."""
        super().__init__(device)
        self._attr_unique_id = f"{device.device_serial}_connected_since"

    @property
    def native_value(self) -> datetime | None:
        """Return the start of the current connected stretch."""
        for row in self.device.connection_history:
            if row.get("isConnected") and row.get("end") is None:
                return _parse_timestamp(row.get("start"))
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose how much of the window the adapter was actually reachable.

        The figures are the point of this entity: a zone that reconnects
        twenty times a day for two minutes each is a different problem from
        one that goes away for an afternoon, and a count of sessions does
        not tell them apart.
        """
        history = self.device.connection_history
        if not history:
            return {}

        rows = []
        for row in history:
            start = _parse_timestamp(row.get("start"))
            if start is None:
                continue
            end = _parse_timestamp(row.get("end"))
            rows.append(
                {
                    "start": start.timestamp(),
                    "end": None if end is None else end.timestamp(),
                }
            )

        attributes: dict[str, Any] = dict(
            summarize_history(rows, dt_util.utcnow().timestamp())
        )
        attributes["recent_sessions"] = [
            {
                "start": row.get("start"),
                "end": row.get("end"),
                "length": row.get("uptime"),
            }
            for row in history[:10]
        ]
        return attributes


class KumoCloudNextScheduleSensor(KumoCloudEntity, SensorEntity):
    """When this zone's schedule next changes something.

    Events carry weekdays and a time but no date, so the next occurrence is
    worked out by searching forward from now in the zone's own timezone.

    Created only for a zone that has events, because there is no honest
    state for a zone with none. `kumo_cloud.get_schedules` reports what the
    account holds either way, including whether the season is running.
    """

    _attr_name = "Next schedule change"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:calendar-arrow-right"

    def __init__(self, device: KumoCloudDevice) -> None:
        """Initialize the sensor."""
        super().__init__(device)
        self._attr_unique_id = f"{device.device_serial}_next_schedule"

    def _next(self) -> tuple[datetime, dict[str, Any]] | None:
        """Find the soonest upcoming event."""
        events = self.device.schedule_events
        if not events:
            return None
        adapter = self.device.zone_data.get("adapter") or {}
        name = self.device.device_data.get("timeZone") or adapter.get("timeZone")
        tzinfo = zone_timezone(name)
        return next_event(events, dt_util.utcnow(), tzinfo)

    @property
    def native_value(self) -> datetime | None:
        """Return when the next event fires."""
        found = self._next()
        return None if found is None else found[0]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Describe the upcoming event and how many are configured."""
        attributes: dict[str, Any] = {"event_count": len(self.device.schedule_events)}
        season = self.coordinator.active_season
        if season:
            attributes["season"] = season.get("name")
            attributes["season_running"] = season.get("isRunning")
        found = self._next()
        if found is not None:
            attributes.update(describe(found[1]))
        return attributes


def _parse_timestamp(value: str | None) -> datetime | None:
    """Parse an API timestamp, tolerating the trailing Z."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


# =============================================================================
# Site level sensors
# =============================================================================


class KumoCloudOutdoorSensor(KumoCloudSiteEntity, SensorEntity):
    """Outdoor conditions where the site is.

    This comes from `/sites/{id}/weather`, which is the weather service the
    Comfort app itself displays. It is **not** a reading from the equipment.
    A Kumo Station would report a real outdoor coil temperature through
    `kumo-properties.outdoorAirTemperature`, but that field stays null
    without one.
    """

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: KumoCloudDataUpdateCoordinator,
        key: str,
        name: str,
        device_class: SensorDeviceClass,
        unit: str,
    ) -> None:
        """Initialize one outdoor reading."""
        super().__init__(coordinator)
        self._key = key
        self._attr_name = name
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit
        self._attr_suggested_display_precision = 0
        self._attr_unique_id = f"{coordinator.site_id}_outdoor_{key}"

    @property
    def native_value(self) -> float | None:
        """Return the reading from the weather payload."""
        return (self.coordinator.site_weather.get("main") or {}).get(self._key)

    @property
    def available(self) -> bool:
        """Return False until the weather payload has arrived."""
        return super().available and self.native_value is not None


def build_site_sensors(
    coordinator: KumoCloudDataUpdateCoordinator,
) -> list[SensorEntity]:
    """Return the site level sensors."""
    return [
        KumoCloudOutdoorSensor(
            coordinator,
            "temp",
            "Outdoor temperature",
            SensorDeviceClass.TEMPERATURE,
            UnitOfTemperature.CELSIUS,
        ),
        KumoCloudOutdoorSensor(
            coordinator,
            "humidity",
            "Outdoor humidity",
            SensorDeviceClass.HUMIDITY,
            PERCENTAGE,
        ),
    ]
