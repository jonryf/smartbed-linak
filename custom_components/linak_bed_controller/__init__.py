"""The Linak Bed Controller integration."""

from __future__ import annotations

import logging

from attr import dataclass
from bleak.exc import BleakError

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth.match import ADDRESS, BluetoothCallbackMatcher
from .coordinator import BedCoordinator
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_NAME,
    CONF_ADDRESS,
    EVENT_HOMEASSISTANT_STOP,
    Platform,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN

PLATFORMS: list[Platform] = [Platform.COVER, Platform.BUTTON]

_LOGGER = logging.getLogger(__name__)


@dataclass
class BedData:
    """Data for the Linak Bed Controller integration."""

    mac_address: str
    device_info: DeviceInfo
    coordinator: BedCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up IKEA Idasen from a config entry."""
    address: str = entry.data[CONF_ADDRESS].upper()

    coordinator = BedCoordinator(hass, _LOGGER, entry.title, address)
    device_info = DeviceInfo(
        name=entry.title,
        connections={(dr.CONNECTION_BLUETOOTH, address)},
    )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = BedData(
        address, device_info, coordinator
    )

    try:
        if not await coordinator.async_connect():
            raise ConfigEntryNotReady(
                f"Unable to connect to bed {address} - No connection"
            )  # noqa: TRY301
    except (TimeoutError, BleakError, Exception) as ex:
        _LOGGER.warning("Unable to connect to bed {address}", ex)
        raise ConfigEntryNotReady(f"Unable to connect to bed {address} - Error") from ex

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    @callback
    def _async_bluetooth_callback(
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        """Update from a Bluetooth callback to ensure that a new BLEDevice is fetched."""
        _LOGGER.debug("Bluetooth callback triggered")
        hass.async_create_task(coordinator.async_connect_if_expected())

    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            _async_bluetooth_callback,
            BluetoothCallbackMatcher({ADDRESS: address}),
            bluetooth.BluetoothScanningMode.ACTIVE,
        )
    )

    async def _async_stop(event: Event) -> None:
        """Close the connection."""
        await coordinator.async_disconnect()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_stop)
    )
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    data: BedData = hass.data[DOMAIN][entry.entry_id]
    if entry.title != data.device_info[ATTR_NAME]:
        await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        data: BedData = hass.data[DOMAIN].pop(entry.entry_id)
        await data.coordinator.async_disconnect()
        bluetooth.async_rediscover_address(hass, data.address)

    return unload_ok
