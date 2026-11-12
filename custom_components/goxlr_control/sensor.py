"""Mic level (opt-in) and Utility version."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import GoXLRConfigEntry
from .client import GoXLRClient
from .entity import GoXLRHubEntity, GoXLREntity, Mixer, add_mixer_entities
from .mic_monitor import MicMonitor, get_monitor


async def async_setup_entry(
    hass: HomeAssistant, entry: GoXLRConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([UtilityVersionSensor(entry.runtime_data, "utility_version", "Utility version")])

    def build(client: GoXLRClient, serial: str, mixer: Mixer) -> list[Entity]:
        return [MicLevelSensor(client, serial, get_monitor(hass, entry, serial))]

    add_mixer_entities(entry, build, async_add_entities)


class MicLevelSensor(GoXLREntity, SensorEntity):
    """Live mic level in dBFS (needs "Mic level monitoring" switched on).

    Disabled by default: it changes every second while you talk, which adds up
    in the recorder. Enable it if you want graphs.
    """

    _attr_native_unit_of_measurement = "dBFS"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:microphone"
    _attr_entity_registry_enabled_default = False
    _attr_suggested_display_precision = 0

    def __init__(self, client: GoXLRClient, serial: str, monitor: MicMonitor) -> None:
        super().__init__(client, serial, "mic_level", "Mic level")
        self._monitor = monitor

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._monitor.async_add_listener(self._handle_update))

    @property
    def available(self) -> bool:
        return super().available and self._monitor.enabled

    @property
    def native_value(self) -> float | None:
        return self._monitor.level


class UtilityVersionSensor(GoXLRHubEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:information-outline"

    @property
    def available(self) -> bool:
        return self._client.connected

    @property
    def native_value(self) -> str | None:
        return self.config.get("daemon_version")
