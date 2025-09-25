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
        """Connect to bed."""
        _LOGGER.info("Attempting to connect to bed: %s", self._address)
        self._expected_connected = True
        
        # Get fresh BLE device from Home Assistant's Bluetooth integration
        if self.bed.client is not None and self.bed.client.is_connected:
            _LOGGER.debug("Already connected to bed, skipping connection...")
            return True

        elif self.bed.client is not None and not self.bed.client.is_connected:
            _LOGGER.debug("Not connected to bed, attempting to connect...")

        ble_device = bluetooth.async_ble_device_from_address(
            self.hass, self._address, connectable=True
        )
        if ble_device is None:
            _LOGGER.warning("No BLE device found for address: %s", self._address)
            return False
        
        _LOGGER.debug("BLE device found, initiating connection...")
        
        try:
            await self.bed.set_ble_device(ble_device)
            _LOGGER.info("Successfully connected to bed: %s", self._address)
            return True
        except Exception as ex:
            _LOGGER.error("Failed to connect to bed %s: %s", self._address, ex)
            self._expected_connected = False
            return False

    async def async_disconnect(self) -> None:
        """Disconnect from bed."""
        self._expected_connected = False
        _LOGGER.debug("Disconnecting from %s", self._address)
        await self.bed.async_cleanup()

    async def async_connect_if_expected(self) -> None:
        """Ensure that the desk is connected if that is the expected state."""
        if self._expected_connected:
            await self.async_connect()
