"""Button entities for the bed."""

from __future__ import annotations

from bleak.exc import BleakError

from homeassistant.components.button import ButtonEntity
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
    """Set up the button platform for the bed."""
    async_add_entities([BedFlatButton(entry.runtime_data)])


class BedFlatButton(BedEntity, ButtonEntity):
    """Move both sections to the flat position."""

    _attr_name = "Set Flat"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "set_flat")

    async def async_press(self) -> None:
        if not await self.coordinator.async_ensure_connected():
            raise HomeAssistantError(f"{self._bed.name} is not reachable")
        try:
            await self._bed.move_to(head=0, foot=0)
        except BleakError as err:
            raise HomeAssistantError("Failed to move flat: Bluetooth error") from err
