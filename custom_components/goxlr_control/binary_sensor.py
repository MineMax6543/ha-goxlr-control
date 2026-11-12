"""Connection, speaking detection and sampler playback state."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import GoXLRConfigEntry
from .client import GoXLRClient
from .const import SAMPLE_PADS
from .entity import GoXLRHubEntity, GoXLREntity, Mixer, add_mixer_entities, dig
from .mic_monitor import MicMonitor, get_monitor


async def async_setup_entry(
    hass: HomeAssistant, entry: GoXLRConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([ConnectedSensor(entry.runtime_data, "connected", "Connection")])

    def build(client: GoXLRClient, serial: str, mixer: Mixer) -> list[Entity]:
        ents: list[Entity] = [SpeakingSensor(client, serial, get_monitor(hass, entry, serial))]
        if mixer.get("sampler") is not None:
            ents += [SamplePlayingSensor(client, serial, pad) for pad in SAMPLE_PADS]
        return ents

    add_mixer_entities(entry, build, async_add_entities)


class ConnectedSensor(GoXLRHubEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self) -> bool:
        return self._client.connected


class SpeakingSensor(GoXLREntity, BinarySensorEntity):
    """On while you're talking (needs "Mic level monitoring" switched on)."""

    _attr_device_class = BinarySensorDeviceClass.SOUND
    _attr_icon = "mdi:account-voice"

    def __init__(self, client: GoXLRClient, serial: str, monitor: MicMonitor) -> None:
        super().__init__(client, serial, "speaking", "Speaking")
        self._monitor = monitor

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._monitor.async_add_listener(self._handle_update))

    @property
    def available(self) -> bool:
        return super().available and self._monitor.enabled

    @property
    def is_on(self) -> bool:
        return self._monitor.speaking

    @property
    def extra_state_attributes(self) -> dict[str, float]:
        return {"threshold": self._monitor.threshold}


class SamplePlayingSensor(GoXLREntity, BinarySensorEntity):
    """Whether the pad in the active sampler bank is playing."""

    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, client: GoXLRClient, serial: str, pad: str) -> None:
        super().__init__(
            client, serial, f"sampler_{pad}_playing", f"Sampler {SAMPLE_PADS[pad].lower()} playing"
        )
        self._pad = pad

    @property
    def _button(self) -> dict:
        m = self.mixer
        return dig(m, "sampler", "banks", dig(m, "sampler", "active_bank"), self._pad) or {}

    @property
    def is_on(self) -> bool:
        return bool(self._button.get("is_playing"))

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "bank": dig(self.mixer, "sampler", "active_bank"),
            "samples": [s.get("name") for s in self._button.get("samples") or []],
        }
