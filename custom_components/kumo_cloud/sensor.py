"""Platform for Kumo Cloud sensors.

Provides standalone sensor entities for each Mitsubishi zone:
- Temperature (from indoor unit's built-in thermistor)
- Humidity (from indoor unit)
- WiFi Adapter Firmware Version (diagnostic, from /status)
- WiFi Signal Strength (diagnostic, routerRssi from /status)
- Filter Reminder (diagnostic, from /notification-preferences)

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

from .coordinator import KumoCloudConfigEntry, KumoCloudDevice
from .entity import KumoCloudEntity

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
            ]
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

class KumoCloudTemperatureSensor(KumoCloudEntity, SensorEntity):
    """Temperature from the indoor unit's built-in thermistor."""

    _attr_name = "Temperature"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, device: KumoCloudDevice) -> None:
        """Initialize the sensor."""
        super().__init__(device)
        self._attr_unique_id = f"{device.device_serial}_temperature"

    @property
    def native_value(self) -> float | None:
        """Return the room temperature reported by the indoor unit."""
        adapter = self.device.zone_data.get("adapter", {})
        return adapter.get("roomTemp")


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
    """Temperature reading from the wireless sensor itself."""

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
