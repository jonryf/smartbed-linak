"""Config flow for Linak Bed Controller integration."""

from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS, CONF_NAME

from .const import DOMAIN, SERVICE_CONTROL

_LOGGER = logging.getLogger(__name__)

_MAC_RE = re.compile(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$")


def _default_name(service_info: BluetoothServiceInfoBleak) -> str:
    return service_info.name or f"Linak Bed {service_info.address[-5:].replace(':', '')}"


class LinakBedConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Linak Bed Controller."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered: dict[str, BluetoothServiceInfoBleak] = {}

    def _is_address_configured(self, address: str) -> bool:
        """Match existing entries by address too: pre-1.0 entries lack a unique_id."""
        return any(
            entry.data.get(CONF_ADDRESS, "").upper() == address.upper()
            for entry in self._async_current_entries(include_ignore=True)
        )

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a discovered Linak control box."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        if self._is_address_configured(discovery_info.address):
            return self.async_abort(reason="already_configured")
        self._discovery_info = discovery_info
        self.context["title_placeholders"] = {"name": _default_name(discovery_info)}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm adding a discovered device."""
        assert self._discovery_info is not None
        default_name = _default_name(self._discovery_info)
        if user_input is not None:
            name = user_input.get(CONF_NAME) or default_name
            return self.async_create_entry(
                title=name,
                data={CONF_ADDRESS: self._discovery_info.address, CONF_NAME: name},
            )
        return self.async_show_form(
            step_id="bluetooth_confirm",
            data_schema=vol.Schema({vol.Optional(CONF_NAME, default=default_name): str}),
            description_placeholders={"name": default_name},
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user pick from discovered devices."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            service_info = self._discovered[address]
            name = user_input.get(CONF_NAME) or _default_name(service_info)
            return self.async_create_entry(
                title=name, data={CONF_ADDRESS: address, CONF_NAME: name}
            )

        for service_info in bluetooth.async_discovered_service_info(self.hass):
            if self._is_address_configured(service_info.address):
                continue
            if SERVICE_CONTROL not in service_info.service_uuids:
                continue
            self._discovered[service_info.address] = service_info

        if not self._discovered:
            return await self.async_step_manual()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(
                        {
                            address: f"{_default_name(info)} ({address})"
                            for address, info in self._discovered.items()
                        }
                    ),
                    vol.Optional(CONF_NAME): str,
                }
            ),
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manual address entry, for a bed that isn't advertising right now."""
        errors: dict[str, str] = {}
        if user_input is not None:
            address = user_input[CONF_ADDRESS].strip().upper()
            if not _MAC_RE.match(address):
                errors["base"] = "invalid_address"
            else:
                await self.async_set_unique_id(address, raise_on_progress=False)
                self._abort_if_unique_id_configured()
                if self._is_address_configured(address):
                    return self.async_abort(reason="already_configured")
                name = user_input.get(CONF_NAME) or f"Linak Bed {address[-5:].replace(':', '')}"
                return self.async_create_entry(
                    title=name, data={CONF_ADDRESS: address, CONF_NAME: name}
                )
        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): str,
                    vol.Optional(CONF_NAME): str,
                }
            ),
            errors=errors,
        )
