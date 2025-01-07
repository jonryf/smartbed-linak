"""Bed entities."""

from __future__ import annotations

from typing import Any, cast

from bleak.exc import BleakError

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
    CoverState
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import BedCoordinator, BedData
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the cover platform for the bed."""
    data: BedData = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            BedHeadRest(data.mac_address, data.device_info, data.coordinator),
            BedFootRest(data.mac_address, data.device_info, data.coordinator),
        ]
    )


class BedHeadRest(CoordinatorEntity[BedCoordinator], CoverEntity):
    """Representation of Bed device."""

    _attr_device_class = CoverDeviceClass.DAMPER
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_POSITION
    )
    _attr_has_entity_name = True
    _attr_name = None
    _attr_translation_key = "bed_head_rest"

    def __init__(
        self,
        address: str,
        device_info: DeviceInfo,
        coordinator: BedCoordinator,
    ) -> None:
        """Initialize an Idasen Desk cover."""
        super().__init__(coordinator)
        self._bed = coordinator.bed
        self._attr_unique_id = address + "_head"
        self._attr_device_info = device_info

        self._attr_current_cover_position = self._bed.head_position

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available

    @property
    def is_closed(self) -> bool:
        """Return if the cover is closed."""
        return self.current_cover_position == 0

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        try:
            await self._bed.set_flat_head()
            self._update_state(CoverState.CLOSED)
        except BleakError as err:
            raise HomeAssistantError("Failed to move down: Bluetooth error") from err

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        try:
            await self._bed.set_max_head()
            self._update_state(CoverState.OPEN)
        except BleakError as err:
            raise HomeAssistantError("Failed to move up: Bluetooth error") from err

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover."""
        try:
            await self._bed.stop()
        except BleakError as err:
            raise HomeAssistantError("Failed to stop moving: Bluetooth error") from err

    @callback
    def _update_state(self, state: str | None) -> None:
        """Update the cover state."""
        if state is None:
            # Reset the state to `unknown`
            self._attr_is_closed = None
        else:
            self._attr_is_closed = state == CoverState.CLOSED
        self._attr_is_opening = state == CoverState.OPENING
        self._attr_is_closing = state == CoverState.CLOSING


    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move the cover shutter to a specific position."""
        try:
            position_percentage = int(kwargs[ATTR_POSITION])
            self._update_state(
                CoverState.CLOSED
                if position_percentage <= 100
                else CoverState.OPEN
            )
            await self._bed.move_head_rest_to(position_percentage)

            self._attr_current_cover_position = position_percentage
            self.async_write_ha_state()
        except BleakError as err:
            raise HomeAssistantError(
                "Failed to move to specified position: Bluetooth error"
            ) from err

    @callback
    def _handle_coordinator_update(self, *args: Any) -> None:
        """Handle data update."""
        self._attr_current_cover_position = self._bed.head_position
        self.async_write_ha_state()

    @property
    def current_cover_position(self) -> int | None:
        """Position of the cover."""
        return int(self._bed.head_position)


class BedFootRest(CoordinatorEntity[BedCoordinator], CoverEntity):
    """Representation of Bed device."""

    _attr_device_class = CoverDeviceClass.DAMPER
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_POSITION
    )
    _attr_has_entity_name = True
    _attr_name = None
    _attr_translation_key = "bed_foot_rest"

    def __init__(
        self,
        address: str,
        device_info: DeviceInfo,
        coordinator: BedCoordinator,
    ) -> None:
        """Initialize an Idasen Desk cover."""
        super().__init__(coordinator)
        self._bed = coordinator.bed
        self._attr_unique_id = address + "_foot"
        self._attr_device_info = device_info

        self._attr_current_cover_position = self._bed.feet_position

    @callback
    def _update_state(self, state: str | None) -> None:
        """Update the cover state."""
        if state is None:
            # Reset the state to `unknown`
            self._attr_is_closed = None
        else:
            self._attr_is_closed = state == CoverState.CLOSED
        self._attr_is_opening = state == CoverState.OPENING
        self._attr_is_closing = state == CoverState.CLOSING


    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available

    @property
    def is_closed(self) -> bool:
        """Return if the cover is closed."""
        return self.current_cover_position == 0

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        try:
            await self._bed.set_flat_foot()
            self._update_state(CoverState.CLOSED)
        except BleakError as err:
            raise HomeAssistantError("Failed to move down: Bluetooth error") from err

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        try:
            await self._bed.set_max_foot()
            self._update_state(CoverState.OPEN)
        except BleakError as err:
            raise HomeAssistantError("Failed to move up: Bluetooth error") from err

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover."""
        try:
            await self._bed.stop()
        except BleakError as err:
            raise HomeAssistantError("Failed to stop moving: Bluetooth error") from err

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move the cover shutter to a specific position."""
        try:
            position_percentage = int(kwargs[ATTR_POSITION])
            self._update_state(
                CoverState.CLOSED
                if position_percentage <= 100
                else CoverState.OPEN
            )
            await self._bed.move_foot_rest_to(position_percentage)
            self._attr_current_cover_position = position_percentage
            self.async_write_ha_state()
        except BleakError as err:
            raise HomeAssistantError(
                "Failed to move to specified position: Bluetooth error"
            ) from err

    @callback
    def _handle_coordinator_update(self, *args: Any) -> None:
        """Handle data update."""
        self._attr_current_cover_position = self._bed.feet_position
        self.async_write_ha_state()
