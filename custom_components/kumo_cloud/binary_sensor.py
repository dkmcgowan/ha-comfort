"""Binary sensors for state the indoor unit reports about itself.

`displayConfig` on the device record mirrors the indicator lights on the
unit's own display: filter, defrost, hot adjust and standby. The filter flag
in particular is the unit's opinion, which is a different thing from the
filter reminder in the zone's notification preferences. That reminder is a
30 day calendar, so it fires whether or not the filter is actually dirty.

Everything here is read only.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import KumoCloudConfigEntry, KumoCloudDevice
from .entity import KumoCloudEntity

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class KumoBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a Kumo Cloud binary sensor."""

    value_fn: Callable[[KumoCloudDevice], bool | None]
    attributes_fn: Callable[[KumoCloudDevice], dict[str, Any]] | None = None


def _display_flag(name: str) -> Callable[[KumoCloudDevice], bool | None]:
    """Read one flag out of the unit's displayConfig."""

    def read(device: KumoCloudDevice) -> bool | None:
        config = device.display_config
        return config.get(name) if name in config else None

    return read


def _connected(device: KumoCloudDevice) -> bool | None:
    """Report whether the adapter is talking to the cloud.

    Read from the zone's session history, which tracks real events: every
    zone here closed a session within two minutes of a WiFi channel change.
    The `connected` field on the device record is not that. It read false on
    all four adapters at once, on one cloud-side write, for half a day,
    while every one of them was reporting live room temperatures. Reported
    as an attribute so the disagreement stays visible.

    Nothing decides entity availability from either. See `connection.py`.
    """
    online = device.coordinator.device_online(device.device_serial)
    if online is not None:
        return online
    value = device.device_data.get("connected")
    if value is None:
        value = device.zone_data.get("adapter", {}).get("connected")
    return value


def _connected_attributes(device: KumoCloudDevice) -> dict[str, Any]:
    """Expose both sources, since they routinely disagree."""
    flag = device.device_data.get("connected")
    if flag is None:
        flag = device.zone_data.get("adapter", {}).get("connected")
    return {
        "open_session": device.coordinator.device_online(device.device_serial),
        "cloud_connected_flag": flag,
    }


def _update_available(device: KumoCloudDevice) -> bool | None:
    """Report whether the adapter has a firmware upgrade waiting."""
    connection = device.connection_data
    if connection is None:
        return None
    return connection.get("firmwareUpgradeTo") is not None


def _has_fault(device: KumoCloudDevice) -> bool | None:
    """Report whether the unit is signalling an error.

    `unusualFigures` carries the detail when something is wrong and is null
    otherwise. `twoFiguresCode` is the two character code the unit displays,
    and reads "A0" when everything is fine.
    """
    data = device.device_data
    if not data:
        return None
    if data.get("unusualFigures"):
        return True
    code = data.get("twoFiguresCode")
    return None if code is None else code not in ("A0", "00", "")


def _hold_active(device: KumoCloudDevice) -> bool | None:
    """Report whether a hold is overriding the schedule on this zone.

    A hold is the app's temporary override: it pins settings until
    `endTime`. The zone record carries the whole thing, so this costs no
    extra request.
    """
    hold = device.hold
    if not hold:
        return None
    return bool(hold.get("enabled"))


def _hold_attributes(device: KumoCloudDevice) -> dict[str, Any]:
    """Expose when the hold ends and what it is pinning.

    The setting fields are null when the hold does not override them, so
    they are dropped rather than reported as empty.
    """
    hold = device.hold
    if not hold:
        return {}
    attributes: dict[str, Any] = {
        "end_time": hold.get("endTime"),
        "hold_type": hold.get("holdType") or hold.get("type"),
    }
    for field, name in (
        ("operationMode", "operation_mode"),
        ("fanSpeed", "fan_speed"),
        ("airDirection", "air_direction"),
        ("spCool", "cool_setpoint"),
        ("spHeat", "heat_setpoint"),
    ):
        if hold.get(field) is not None:
            attributes[name] = hold[field]
    return attributes


def _schedule_active(device: KumoCloudDevice) -> bool | None:
    """Report whether a schedule is running on this zone."""
    value = device.zone_data.get("hasActiveSchedule")
    return None if value is None else bool(value)


# The flags worth a place on a dashboard are the ones that mean something is
# wrong or something is overriding the schedule. The rest describe a normal
# operating cycle, read false almost always, and are registered disabled;
# turn them on per entity when chasing a problem.
DESCRIPTIONS: tuple[KumoBinarySensorDescription, ...] = (
    KumoBinarySensorDescription(
        key="hold",
        name="Hold",
        icon="mdi:pause-octagon-outline",
        value_fn=_hold_active,
        attributes_fn=_hold_attributes,
    ),
    KumoBinarySensorDescription(
        key="schedule_active",
        entity_registry_enabled_default=False,
        name="Schedule active",
        icon="mdi:calendar-clock",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_schedule_active,
    ),
    KumoBinarySensorDescription(
        key="filter_dirty",
        name="Filter",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_display_flag("filter"),
    ),
    KumoBinarySensorDescription(
        key="defrost",
        entity_registry_enabled_default=False,
        name="Defrost",
        icon="mdi:snowflake-melt",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_display_flag("defrost"),
    ),
    KumoBinarySensorDescription(
        key="standby",
        entity_registry_enabled_default=False,
        name="Standby",
        icon="mdi:power-standby",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_display_flag("standby"),
    ),
    KumoBinarySensorDescription(
        key="hot_adjust",
        entity_registry_enabled_default=False,
        name="Hot adjust",
        icon="mdi:thermometer-chevron-up",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_display_flag("hotAdjust"),
    ),
    KumoBinarySensorDescription(
        key="fault",
        name="Fault",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_has_fault,
    ),
    KumoBinarySensorDescription(
        key="connected",
        name="Cloud connection",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_connected,
        attributes_fn=_connected_attributes,
    ),
    KumoBinarySensorDescription(
        key="firmware_update",
        entity_registry_enabled_default=False,
        name="Firmware update",
        device_class=BinarySensorDeviceClass.UPDATE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_update_available,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KumoCloudConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensors, including for zones added later."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _async_add_new_entities() -> None:
        new: list[KumoCloudBinarySensor] = []

        for zone in coordinator.zones:
            adapter = zone.get("adapter")
            if not adapter:
                continue

            device = KumoCloudDevice(coordinator, zone["id"], adapter["deviceSerial"])
            for description in DESCRIPTIONS:
                unique_id = f"{device.device_serial}_{description.key}"
                if unique_id in known:
                    continue
                known.add(unique_id)
                new.append(KumoCloudBinarySensor(device, description))

        if new:
            _LOGGER.debug("Adding %d new binary sensor entities", len(new))
            async_add_entities(new)

    _async_add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_entities))


class KumoCloudBinarySensor(KumoCloudEntity, BinarySensorEntity):
    """One flag the indoor unit reports about itself."""

    entity_description: KumoBinarySensorDescription

    def __init__(
        self, device: KumoCloudDevice, description: KumoBinarySensorDescription
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(device)
        self.entity_description = description
        self._attr_unique_id = f"{device.device_serial}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        """Return the flag's current state."""
        return self.entity_description.value_fn(self.device)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the description's attributes, if it defines any."""
        if self.entity_description.attributes_fn is None:
            return {}
        return self.entity_description.attributes_fn(self.device)

    @property
    def available(self) -> bool:
        """Return False when the source field is missing entirely.

        A flag that has never been reported is different from a flag that is
        off, and showing it as off would be a quiet lie.
        """
        return super().available and self.is_on is not None
