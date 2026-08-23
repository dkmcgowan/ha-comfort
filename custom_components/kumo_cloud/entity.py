"""Base entity for the Kumo Cloud integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import KumoCloudDataUpdateCoordinator, KumoCloudDevice


class KumoCloudEntity(CoordinatorEntity[KumoCloudDataUpdateCoordinator]):
    """Base for every Kumo Cloud entity.

    Provides shared device_info so climate + sensors for the same indoor
    unit group under one HA device, and enables `has_entity_name` so each
    entity's friendly name composes with the device name automatically.
    """

    _attr_has_entity_name = True

    def __init__(self, device: KumoCloudDevice) -> None:
        """Initialize with the device wrapper (carries the coordinator)."""
        super().__init__(device.coordinator)
        self.device = device

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info shared by every entity for this unit."""
        zone_data = self.device.zone_data
        device_data = self.device.device_data
        model_info = device_data.get("model", {}) if device_data else {}

        return DeviceInfo(
            identifiers={(DOMAIN, self.device.device_serial)},
            name=zone_data.get("name", "Kumo Cloud Device"),
            manufacturer="Mitsubishi Electric",
            model=model_info.get("materialDescription"),
            sw_version=model_info.get("serialProfile"),
            serial_number=device_data.get("serialNumber") if device_data else None,
            via_device=(DOMAIN, self.device.coordinator.site_id),
        )


class KumoCloudSiteEntity(CoordinatorEntity[KumoCloudDataUpdateCoordinator]):
    """Base for entities that belong to the site rather than to one unit.

    Outdoor conditions are the obvious case: they describe where the house
    is, not what any single indoor unit is doing, so hanging them off one
    arbitrary zone would be misleading. The site also becomes the `via_device`
    parent for every indoor unit, which gives the device page a sensible tree.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: KumoCloudDataUpdateCoordinator) -> None:
        """Initialize against the coordinator."""
        super().__init__(coordinator)

    @property
    def device_info(self) -> DeviceInfo:
        """Return the site's device entry."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.site_id)},
            name=self.coordinator.site_name,
            manufacturer="Mitsubishi Electric",
            model="Kumo Cloud site",
            entry_type=DeviceEntryType.SERVICE,
        )
