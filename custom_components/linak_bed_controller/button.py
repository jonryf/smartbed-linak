"""Representation of Idasen Desk buttons."""

from dataclasses import dataclass
import logging
from bleak.exc import BleakError

from .const import DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.exceptions import HomeAssistantError

from . import BedCoordinator, BedData

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class LinakBedButtonDescription(ButtonEntityDescription):
    """Describes a Linak Bed button entity."""
    command: str


CONSUMABLE_BUTTON_DESCRIPTIONS = [
    LinakBedButtonDescription(
        key="set_flat",
        name="Set Flat",
        command="set_flat",
    ),
]



async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the cover platform for the bed."""
    data: BedData = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([BedFlatButton( data.coordinator, description)] for description in CONSUMABLE_BUTTON_DESCRIPTIONS)


class BedFlatButton(CoordinatorEntity[BedCoordinator], ButtonEntity):
    """Defines a Bed flat button."""

    entity_description: LinakBedButtonDescription

    def __init__(
        self,
        coordinator: BedCoordinator,
        entity_description: LinakBedButtonDescription,
    ) -> None:
        """Initialize the IdasenDesk button entity."""
        super().__init__(f"{entity_description.key}-{coordinator.address}", coordinator)
        self.entity_description = entity_description
        self._bed = coordinator.bed


    async def async_press(self) -> None:
        """Triggers the IdasenDesk button press service."""
        try:
            await self._bed.set_flat()
        except BleakError as err:
            raise HomeAssistantError("Failed to stop moving: Bluetooth error") from err

    @property
    def available(self) -> bool:
        """Connect/disconnect buttons should always be available."""
        return True
