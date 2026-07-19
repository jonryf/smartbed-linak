"""Cover entities for the head and foot rest of the bed."""

from __future__ import annotations

from typing import Any

from bleak.exc import BleakError

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BedConfigEntry
from .entity import BedEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BedConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the cover platform for the bed."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            BedSectionCover(coordinator, "head", "Bed Head Rest"),
            BedSectionCover(coordinator, "foot", "Bed Foot Rest"),
        ]
    )


class BedSectionCover(BedEntity, CoverEntity):
    """One motorized section (head or foot rest) of the bed."""

    _attr_device_class = CoverDeviceClass.DAMPER
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_POSITION
    )

    def __init__(self, coordinator, motor_name: str, name: str) -> None:
        super().__init__(coordinator, motor_name)
        self._motor_name = motor_name
        self._motor = coordinator.bed.head if motor_name == "head" else coordinator.bed.foot
        self._attr_name = name

    @property
    def current_cover_position(self) -> int | None:
        pct = self._motor.position_pct
        return None if pct is None else round(pct)

    @property
    def is_closed(self) -> bool | None:
        position = self.current_cover_position
        return None if position is None else position == 0

    @property
    def is_opening(self) -> bool:
        return self._motor.is_moving_up

    @property
    def is_closing(self) -> bool:
        return self._motor.is_moving_down

    async def async_open_cover(self, **kwargs: Any) -> None:
        await self._move_to(100)

    async def async_close_cover(self, **kwargs: Any) -> None:
        await self._move_to(0)

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        await self._move_to(int(kwargs[ATTR_POSITION]))

    async def async_stop_cover(self, **kwargs: Any) -> None:
        await self._bed.stop(self._motor_name)

    async def _move_to(self, position: int) -> None:
        if not await self.coordinator.async_ensure_connected():
            raise HomeAssistantError(f"{self._bed.name} is not reachable")
        try:
            await self._bed.move_to(**{self._motor_name: position})
        except BleakError as err:
            raise HomeAssistantError("Failed to move: Bluetooth error") from err
