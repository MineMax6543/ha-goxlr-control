"""Connectivity sensor on the hub device (always available)."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import GoXLRConfigEntry
from .entity import GoXLRHubEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: GoXLRConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([ConnectedSensor(entry.runtime_data, "connected", "Connection")])


class ConnectedSensor(GoXLRHubEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self) -> bool:
        return self._client.connected
