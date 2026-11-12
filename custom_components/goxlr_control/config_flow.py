"""Config flow for GoXLR Control."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client import GoXLRError, async_fetch_status
from .const import DEFAULT_PORT, DOMAIN

_LOGGER = logging.getLogger(__name__)


def _schema(host: str = "", port: int = DEFAULT_PORT, **_: Any) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=host): str,
            vol.Required(CONF_PORT, default=port): vol.All(int, vol.Range(1, 65535)),
        }
    )


class GoXLRConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def _validate(self, user_input: dict[str, Any]) -> str | None:
        try:
            await async_fetch_status(
                async_get_clientsession(self.hass),
                user_input[CONF_HOST],
                user_input[CONF_PORT],
            )
        except (aiohttp.ClientError, TimeoutError, GoXLRError):
            return "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected error validating GoXLR Utility")
            return "unknown"
        return None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_HOST] = user_input[CONF_HOST].strip()
            await self.async_set_unique_id(f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}")
            self._abort_if_unique_id_configured()
            if not (error := await self._validate(user_input)):
                return self.async_create_entry(
                    title=f"GoXLR Utility ({user_input[CONF_HOST]})", data=user_input
                )
            errors["base"] = error
        return self.async_show_form(
            step_id="user",
            data_schema=_schema(**(user_input or {})),
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_HOST] = user_input[CONF_HOST].strip()
            if not (error := await self._validate(user_input)):
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}",
                    title=f"GoXLR Utility ({user_input[CONF_HOST]})",
                    data_updates=user_input,
                )
            errors["base"] = error
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_schema(entry.data[CONF_HOST], entry.data[CONF_PORT]),
            errors=errors,
        )
