"""Base entity for GoXLR Control."""

from __future__ import annotations

from typing import Any

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .client import GoXLRClient, GoXLRError
from .const import DOMAIN


class GoXLREntity(Entity):
    """Push-updated entity bound to one mixer serial."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, client: GoXLRClient, serial: str, key: str, name: str) -> None:
        self._client = client
        self._serial = serial
        self._attr_unique_id = f"{serial}_{key}"
        self._attr_name = name
        hw = (client.mixer(serial) or {}).get("hardware") or {}
        mini = hw.get("device_type") == "Mini"
        firmware = (hw.get("versions") or {}).get("firmware")
        if isinstance(firmware, list):
            firmware = ".".join(str(p) for p in firmware)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, serial)},
            manufacturer="TC-Helicon",
            model="GoXLR Mini" if mini else "GoXLR",
            name="GoXLR Mini" if mini else "GoXLR",
            serial_number=serial,
            sw_version=str(firmware) if firmware else None,
            via_device=(DOMAIN, client.entry_id),
        )

    @property
    def mixer(self) -> dict[str, Any]:
        return self._client.mixer(self._serial) or {}

    @property
    def available(self) -> bool:
        return self._client.connected and self._client.mixer(self._serial) is not None

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._client.async_add_listener(self.async_write_ha_state))

    async def _send(self, command: dict[str, Any]) -> None:
        try:
            await self._client.async_command(self._serial, command)
        except GoXLRError as err:
            raise HomeAssistantError(f"GoXLR command failed: {err}") from err


class GoXLRHubEntity(Entity):
    """Entity on the Utility hub device; always available."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, client: GoXLRClient, key: str, name: str) -> None:
        self._client = client
        self._attr_unique_id = f"{client.entry_id}_{key}"
        self._attr_name = name
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, client.entry_id)})

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._client.async_add_listener(self.async_write_ha_state))
