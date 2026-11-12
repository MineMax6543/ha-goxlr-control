"""Diagnostics download."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import GoXLRConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: GoXLRConfigEntry
) -> dict[str, Any]:
    client = entry.runtime_data
    return {"connected": client.connected, "status": client.status}
