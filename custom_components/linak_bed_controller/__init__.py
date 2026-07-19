"""The Linak Bed Controller integration."""

from __future__ import annotations

import logging

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth.match import ADDRESS, BluetoothCallbackMatcher
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady

from .coordinator import BedCoordinator

PLATFORMS: list[Platform] = [Platform.COVER, Platform.BUTTON]

_LOGGER = logging.getLogger(__name__)

BedConfigEntry = ConfigEntry[BedCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: BedConfigEntry) -> bool:
    """Set up a Linak bed from a config entry."""
    address: str = entry.data[CONF_ADDRESS].upper()

    # Entries created by pre-1.0 versions have no unique_id; set it so the
    # duplicate guards in the config flow can match them.
    if entry.unique_id is None:
        hass.config_entries.async_update_entry(entry, unique_id=address)

    coordinator = BedCoordinator(hass, entry, address)
    entry.runtime_data = coordinator

    if not await coordinator.async_connect():
        raise ConfigEntryNotReady(f"Unable to connect to bed {address}")

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    @callback
    def _async_bluetooth_callback(
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        """Nudge a reconnect when the bed advertises while we are disconnected."""
        coordinator.async_nudge_reconnect()

    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            _async_bluetooth_callback,
            BluetoothCallbackMatcher({ADDRESS: address}),
            bluetooth.BluetoothScanningMode.PASSIVE,
        )
    )

    async def _async_stop(event: Event) -> None:
        await coordinator.async_shutdown_bed()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_stop)
    )
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: BedConfigEntry) -> None:
    """Reload when the entry title changes (options updates don't need one)."""
    if entry.title != entry.runtime_data.bed.name:
        await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: BedConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.async_shutdown_bed()
        bluetooth.async_rediscover_address(hass, entry.data[CONF_ADDRESS].upper())
    return unload_ok
