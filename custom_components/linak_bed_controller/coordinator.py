"""Coordinator: owns the bed connection and reconnection policy."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable

from bleak_retry_connector import close_stale_connections_by_address

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .bed_ble import LinakBed
from .const import (
    CONF_RAW_MAX_FOOT,
    CONF_RAW_MAX_HEAD,
    DEFAULT_RAW_MAX_FOOT,
    DEFAULT_RAW_MAX_HEAD,
    DOMAIN,
    RAW_MAX_SAVE_DELAY,
    RECONNECT_INITIAL_DELAY,
    RECONNECT_MAX_DELAY,
)

_LOGGER = logging.getLogger(__name__)


class BedCoordinator(DataUpdateCoordinator[None]):
    """Push-based coordinator for one Linak control box."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, address: str) -> None:
        super().__init__(
            hass, _LOGGER, config_entry=entry, name=f"{DOMAIN}-{entry.title}"
        )
        self.address = address
        self.bed = LinakBed(
            address,
            entry.title,
            raw_max_head=entry.options.get(CONF_RAW_MAX_HEAD, DEFAULT_RAW_MAX_HEAD),
            raw_max_foot=entry.options.get(CONF_RAW_MAX_FOOT, DEFAULT_RAW_MAX_FOOT),
        )
        self._reconnect_task: asyncio.Task | None = None
        self._reconnect_now = asyncio.Event()
        self._cancel_save: Callable[[], None] | None = None
        self._shutdown = False
        self.bed.register_state_callback(self._on_bed_state)
        self.bed.set_disconnect_listener(self._on_bed_disconnect)
        self.bed.set_raw_max_listener(self._on_raw_max_learned)

    # ------------------------------------------------------------ lifecycle

    async def async_connect(self) -> bool:
        """Try one connection attempt; True on success."""
        try:
            # Free the control box's single BLE slot if a stale link survived
            # an unclean restart of HA or a proxy.
            await close_stale_connections_by_address(self.address)
            ble_device = bluetooth.async_ble_device_from_address(
                self.hass, self.address, connectable=True
            )
            if ble_device is None:
                _LOGGER.debug("%s: no connectable BLE device found", self.address)
                return False
            await self.bed.connect(ble_device)
        except Exception as ex:  # noqa: BLE001 - any failure means "retry later"
            _LOGGER.debug("%s: connection attempt failed: %s", self.address, ex)
            return False
        return True

    async def async_ensure_connected(self) -> bool:
        """Connect on demand so commands still work while reconnect backs off."""
        if self.bed.is_connected:
            return True
        return await self.async_connect()

    async def async_shutdown_bed(self) -> None:
        self._shutdown = True
        if self._reconnect_task:
            self._reconnect_task.cancel()
            self._reconnect_task = None
        if self._cancel_save:
            self._cancel_save()
            self._cancel_save = None
            self._save_raw_max()
        await self.bed.async_shutdown()

    # ---------------------------------------------------------- reconnection

    @callback
    def async_nudge_reconnect(self) -> None:
        """Reconnect now: wake a backing-off loop, or start one."""
        if self._shutdown or self.bed.is_connected:
            return
        self._reconnect_now.set()
        if self._reconnect_task and not self._reconnect_task.done():
            return
        self._reconnect_task = self.config_entry.async_create_background_task(
            self.hass, self._reconnect_loop(), name=f"{DOMAIN}-reconnect"
        )

    async def _reconnect_loop(self) -> None:
        delay = RECONNECT_INITIAL_DELAY
        while not self._shutdown and not self.bed.is_connected:
            if await self.async_connect():
                _LOGGER.info("%s: reconnected", self.bed.name)
                return
            delay = min(delay * 2, RECONNECT_MAX_DELAY)
            # Back off, but let an advertisement (the bed is provably
            # reachable again) cut the wait short.
            self._reconnect_now.clear()
            with contextlib.suppress(asyncio.TimeoutError, TimeoutError):
                await asyncio.wait_for(self._reconnect_now.wait(), timeout=delay)

    def _on_bed_disconnect(self) -> None:
        if not self._shutdown:
            self.async_nudge_reconnect()

    # -------------------------------------------------------------- updates

    def _on_bed_state(self) -> None:
        self.async_set_updated_data(None)

    def _on_raw_max_learned(self) -> None:
        """Schedule persisting the learned range, debounced.

        During the first travel past the stored range this fires per position
        notification; writing the config entry every time would hammer storage.
        """
        if self._shutdown:
            return
        if self._cancel_save:
            self._cancel_save()
        self._cancel_save = async_call_later(self.hass, RAW_MAX_SAVE_DELAY, self._delayed_save)

    @callback
    def _delayed_save(self, _now) -> None:
        self._cancel_save = None
        self._save_raw_max()

    def _save_raw_max(self) -> None:
        options = {
            **self.config_entry.options,
            CONF_RAW_MAX_HEAD: self.bed.head.raw_max,
            CONF_RAW_MAX_FOOT: self.bed.foot.raw_max,
        }
        if options != dict(self.config_entry.options):
            self.hass.config_entries.async_update_entry(self.config_entry, options=options)
