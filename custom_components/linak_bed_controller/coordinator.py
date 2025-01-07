"""Coordinator for the bed integration."""

from __future__ import annotations

import logging

from homeassistant.components import bluetooth
from .lib.bed import Bed
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


class BedCoordinator(DataUpdateCoordinator[int | None]):
    """Class to manage updates for the Bed."""

    def __init__(
        self,
        hass: HomeAssistant,
        logger: logging.Logger,
        name: str,
        address: str,
    ) -> None:
        """Init BedCoordinator."""

        super().__init__(hass, logger, name=name)
        self._address = address
        self._expected_connected = False

        self.bed = Bed(self._address, name, _LOGGER, hass)

    async def async_connect(self) -> bool:
        """Connect to desk."""
        _LOGGER.warning("Trying to connect %s", self._address)
        self._expected_connected = True
        ble_device = bluetooth.async_ble_device_from_address(
            self.hass, self._address, connectable=True
        )
        if ble_device is None:
            _LOGGER.warning("No BLEDevice for %s", self._address)
            return False
        _LOGGER.warning("Connected (!) to %s", self._address)

        await self.bed.set_ble_device(ble_device)

        return True

    async def async_disconnect(self) -> None:
        """Disconnect from desk."""
        self._expected_connected = False
        _LOGGER.debug("Disconnecting from %s", self._address)
        await self.bed.disconnect_callback()

    async def async_connect_if_expected(self) -> None:
        """Ensure that the desk is connected if that is the expected state."""
        if self._expected_connected:
            await self.async_connect()
