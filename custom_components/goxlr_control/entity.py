"""Base entities and small helpers for GoXLR Control."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription

from .client import GoXLRClient, GoXLRError
from .const import DOMAIN

Mixer = dict[str, Any]


def dig(data: Any, *path: Any) -> Any:
    """Safe nested lookup: dig(m, "levels", "volumes", "Mic") -> value | None."""
    for key in path:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def is_full(mixer: Mixer) -> bool:
    """Full-size GoXLR (effects, sampler, scribble screens). False for the Mini."""
    return dig(mixer, "hardware", "device_type") != "Mini"


def version_str(version: Any) -> str | None:
    """VersionNumber is serialised as [major, minor, patch|null, build|null]."""
    if isinstance(version, list):
        return ".".join(str(p) for p in version if p is not None) or None
    return str(version) if version else None


# Newer Home Assistant links child devices by device id; older ones only by
# identifier tuple. Use whichever this version supports.
_HAS_VIA_DEVICE_ID = "via_device_id" in DeviceInfo.__annotations__


def mixer_device_info(client: GoXLRClient, serial: str) -> DeviceInfo:
    mixer = client.mixer(serial) or {}
    mini = not is_full(mixer)
    info = DeviceInfo(
        identifiers={(DOMAIN, serial)},
        manufacturer="TC-Helicon",
        model="GoXLR Mini" if mini else "GoXLR",
        name="GoXLR Mini" if mini else "GoXLR",
        serial_number=serial,
        sw_version=version_str(dig(mixer, "hardware", "versions", "firmware")),
    )
    if _HAS_VIA_DEVICE_ID:
        if client.hub_device_id:
            info["via_device_id"] = client.hub_device_id
    else:
        info["via_device"] = (DOMAIN, client.entry_id)
    return info


class _GatedEntity(Entity):
    """Writes state only when this entity's own visible state changed.

    Every patch notifies every entity; without this gate, turning one knob
    would rewrite ~200 entity states 20 times a second.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _client: GoXLRClient
    _fingerprint: Any = object()

    async def async_added_to_hass(self) -> None:
        self._fingerprint = object()
        self.async_on_remove(self._client.async_add_listener(self._handle_update))

    @callback
    def _handle_update(self) -> None:
        try:
            fp = (
                self.available
                and (
                    self.state,
                    self.capability_attributes,
                    self.state_attributes,
                    self.extra_state_attributes,
                )
            )
        except Exception:  # noqa: BLE001 - never let one entity break updates
            fp = object()
        if fp != self._fingerprint:
            self._fingerprint = fp
            self.async_write_ha_state()


class GoXLREntity(_GatedEntity):
    """Push-updated entity bound to one mixer serial."""

    def __init__(
        self,
        client: GoXLRClient,
        serial: str,
        key: str,
        name: str | None = None,
        description: EntityDescription | None = None,
    ) -> None:
        self._client = client
        self._serial = serial
        if description is not None:
            self.entity_description = description
        if name is not None:
            self._attr_name = name
        self._attr_unique_id = f"{serial}_{key}"
        self._attr_device_info = mixer_device_info(client, serial)

    @property
    def mixer(self) -> Mixer:
        return self._client.mixer(self._serial) or {}

    @property
    def available(self) -> bool:
        if not (self._client.connected and self._client.mixer(self._serial) is not None):
            return False
        check: Callable[[Mixer], bool] | None = getattr(
            getattr(self, "entity_description", None), "available_fn", None
        )
        return check(self.mixer) if check else True

    async def _send(self, command: Any) -> None:
        try:
            await self._client.async_command(self._serial, command)
        except GoXLRError as err:
            raise HomeAssistantError(f"GoXLR: {err}") from err


class GoXLRHubEntity(_GatedEntity):
    """Entity on the GoXLR Utility hub device."""

    def __init__(
        self,
        client: GoXLRClient,
        key: str,
        name: str | None = None,
        description: EntityDescription | None = None,
    ) -> None:
        self._client = client
        if description is not None:
            self.entity_description = description
        if name is not None:
            self._attr_name = name
        self._attr_unique_id = f"{client.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, client.entry_id)})

    @property
    def config(self) -> dict[str, Any]:
        return (self._client.status or {}).get("config") or {}

    async def _send(self, command: Any) -> None:
        try:
            await self._client.async_utility_command(command)
        except GoXLRError as err:
            raise HomeAssistantError(f"GoXLR Utility: {err}") from err


def add_mixer_entities(
    entry: Any,
    build: Callable[[GoXLRClient, str, Mixer], list[Entity]],
    async_add_entities: Callable[[list[Entity]], None],
) -> None:
    """Create a platform's entities for every mixer, now and when hot-plugged."""
    client: GoXLRClient = entry.runtime_data

    @callback
    def _add(serial: str) -> None:
        async_add_entities(build(client, serial, client.mixer(serial) or {}))

    entry.async_on_unload(client.async_add_mixer_listener(_add))
