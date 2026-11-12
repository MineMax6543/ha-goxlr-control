"""Channel volume sliders."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import GoXLRConfigEntry
from .client import GoXLRClient
from .const import CHANNEL_NAMES, CHANNELS
from .entity import GoXLREntity


async def async_setup_entry(
    hass: HomeAssistant, entry: GoXLRConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    client = entry.runtime_data

    @callback
    def _add(serial: str) -> None:
        volumes = ((client.mixer(serial) or {}).get("levels") or {}).get("volumes") or {}
        async_add_entities(
            VolumeNumber(client, serial, ch) for ch in CHANNELS if ch in volumes
        )

    entry.async_on_unload(client.async_add_mixer_listener(_add))


class VolumeNumber(GoXLREntity, NumberEntity):
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:volume-high"

    def __init__(self, client: GoXLRClient, serial: str, channel: str) -> None:
        super().__init__(client, serial, f"volume_{channel}", f"{CHANNEL_NAMES[channel]} volume")
        self._channel = channel

    @property
    def native_value(self) -> float | None:
        raw = ((self.mixer.get("levels") or {}).get("volumes") or {}).get(self._channel)
        return None if raw is None else round(raw * 100 / 255)

    async def async_set_native_value(self, value: float) -> None:
        raw = max(0, min(255, round(value * 255 / 100)))
        await self._send({"SetVolume": [self._channel, raw]})
