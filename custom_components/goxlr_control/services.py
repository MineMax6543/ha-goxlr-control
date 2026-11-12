"""Raw command actions: reach every Utility feature, even ones without entities.

goxlr_control.send_command          - any GoXLR (mixer) command, e.g.
    {"SetScribbleText": ["A", "ON AIR"]}
goxlr_control.send_utility_command  - any Utility (daemon) command, e.g.
    {"SetSampleGainPct": ["intro.wav", 80]}
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError, HomeAssistantError
from homeassistant.helpers import config_validation as cv, device_registry as dr

from .client import GoXLRClient, GoXLRError
from .const import DOMAIN

COMMAND = vol.Any(dict, str)

SEND_COMMAND_SCHEMA = vol.Schema(
    {vol.Required("device_id"): cv.string, vol.Required("command"): COMMAND}
)
SEND_UTILITY_SCHEMA = vol.Schema(
    {vol.Optional("config_entry_id"): cv.string, vol.Required("command"): COMMAND}
)


def _loaded_clients(hass: HomeAssistant) -> dict[str, GoXLRClient]:
    return {
        e.entry_id: e.runtime_data
        for e in hass.config_entries.async_entries(DOMAIN)
        if e.state is ConfigEntryState.LOADED
    }


def async_setup_services(hass: HomeAssistant) -> None:
    async def send_command(call: ServiceCall) -> ServiceResponse:
        device = dr.async_get(hass).async_get(call.data["device_id"])
        serial = next((i[1] for i in (device.identifiers if device else ()) if i[0] == DOMAIN), None)
        client = next(
            (c for c in _loaded_clients(hass).values() if serial and c.mixer(serial) is not None),
            None,
        )
        if client is None or serial is None:
            raise ServiceValidationError(
                "Pick a connected GoXLR device (not the GoXLR Utility hub device)."
            )
        try:
            result = await client.async_command(serial, call.data["command"])
        except GoXLRError as err:
            raise HomeAssistantError(f"GoXLR: {err}") from err
        return {"result": result}

    async def send_utility_command(call: ServiceCall) -> ServiceResponse:
        clients = _loaded_clients(hass)
        entry_id = call.data.get("config_entry_id")
        if entry_id:
            client = clients.get(entry_id)
        elif len(clients) == 1:
            client = next(iter(clients.values()))
        else:
            client = None
        if client is None:
            raise ServiceValidationError(
                "Pick which GoXLR Utility to use (config_entry_id) or check it's loaded."
            )
        try:
            result = await client.async_utility_command(call.data["command"])
        except GoXLRError as err:
            raise HomeAssistantError(f"GoXLR Utility: {err}") from err
        return {"result": result}

    hass.services.async_register(
        DOMAIN, "send_command", send_command, SEND_COMMAND_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, "send_utility_command", send_utility_command, SEND_UTILITY_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
