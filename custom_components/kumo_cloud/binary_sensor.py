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


def _display_flag(name: str) -> Callable[[KumoCloudDevice], bool | None]:
    """Read one flag out of the unit's displayConfig."""

    def read(device: KumoCloudDevice) -> bool | None:
        config = device.display_config
        return config.get(name) if name in config else None

    return read


def _connected(device: KumoCloudDevice) -> bool | None:
    """Report whether the adapter is talking to the cloud.

    Read from the device record, not from `kumo-properties`, which has a
    `connected` field of its own that means something else entirely and
    reads false on hardware that is plainly online.
    """
    value = device.device_data.get("connected")
    if value is None:
        value = device.zone_data.get("adapter", {}).get("connected")
    return value


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


DESCRIPTIONS: tuple[KumoBinarySensorDescription, ...] = (
    KumoBinarySensorDescription(
        key="filter_dirty",
        name="Filter",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_display_flag("filter"),
    ),
    KumoBinarySensorDescription(
        key="defrost",
        name="Defrost",
        icon="mdi:snowflake-melt",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_display_flag("defrost"),
    ),
    KumoBinarySensorDescription(
        key="standby",
        name="Standby",
        icon="mdi:power-standby",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_display_flag("standby"),
    ),
    KumoBinarySensorDescription(
        key="hot_adjust",
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
    ),
    KumoBinarySensorDescription(
        key="firmware_update",
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
    def available(self) -> bool:
        """Return False when the source field is missing entirely.

        A flag that has never been reported is different from a flag that is
        off, and showing it as off would be a quiet lie.
        """
        return super().available and self.is_on is not None
