"""Shared base entity for the bed's platforms."""

from __future__ import annotations

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import BedCoordinator


class BedEntity(CoordinatorEntity[BedCoordinator]):
    """Base for all entities of one bed."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: BedCoordinator, unique_id_suffix: str) -> None:
        super().__init__(coordinator)
        self._bed = coordinator.bed
        self._attr_unique_id = f"{coordinator.address}_{unique_id_suffix}"
        self._attr_device_info = DeviceInfo(
            name=coordinator.bed.name,
            manufacturer="LINAK",
            connections={(dr.CONNECTION_BLUETOOTH, coordinator.address)},
        )

    @property
    def available(self) -> bool:
        return self._bed.is_connected
