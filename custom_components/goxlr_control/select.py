"""Profile, mic profile, effect preset and fader assignment selects."""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import GoXLRConfigEntry
from .client import GoXLRClient
from .const import CHANNEL_NAMES, CHANNELS, FADERS
from .entity import GoXLREntity

PRESETS = tuple(f"Preset{i}" for i in range(1, 7))


async def async_setup_entry(
    hass: HomeAssistant, entry: GoXLRConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    client = entry.runtime_data

    @callback
    def _add(serial: str) -> None:
        mixer = client.mixer(serial) or {}
        ents: list[SelectEntity] = [
            ProfileSelect(client, serial, mic=False),
            ProfileSelect(client, serial, mic=True),
        ]
        ents += [
            FaderChannelSelect(client, serial, f)
            for f in FADERS
            if f in (mixer.get("fader_status") or {})
        ]
        if mixer.get("effects"):
            ents.append(EffectPresetSelect(client, serial))
        async_add_entities(ents)

    entry.async_on_unload(client.async_add_mixer_listener(_add))


class ProfileSelect(GoXLREntity, SelectEntity):
    def __init__(self, client: GoXLRClient, serial: str, mic: bool) -> None:
        super().__init__(
            client, serial, "mic_profile" if mic else "profile",
            "Mic profile" if mic else "Profile",
        )
        self._attr_icon = "mdi:microphone-settings" if mic else "mdi:tune-variant"
        self._files_key = "mic_profiles" if mic else "profiles"
        self._status_key = "mic_profile_name" if mic else "profile_name"
        self._cmd = "LoadMicProfile" if mic else "LoadProfile"

    @property
    def options(self) -> list[str]:
        opts = sorted(self._client.files.get(self._files_key) or [], key=str.casefold)
        current = self.mixer.get(self._status_key)
        if current and current not in opts:
            opts.append(current)
        return opts

    @property
    def current_option(self) -> str | None:
        return self.mixer.get(self._status_key)

    async def async_select_option(self, option: str) -> None:
        # bool = persist as the active profile across daemon restarts.
        await self._send({self._cmd: [option, True]})


class FaderChannelSelect(GoXLREntity, SelectEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:tune-vertical"
    _attr_options = [CHANNEL_NAMES[c] for c in CHANNELS]

    def __init__(self, client: GoXLRClient, serial: str, fader: str) -> None:
        super().__init__(client, serial, f"fader_{fader}_channel", f"Fader {fader} channel")
        self._fader = fader

    @property
    def current_option(self) -> str | None:
        ch = ((self.mixer.get("fader_status") or {}).get(self._fader) or {}).get("channel")
        return CHANNEL_NAMES.get(ch)

    async def async_select_option(self, option: str) -> None:
        channel = next(k for k, v in CHANNEL_NAMES.items() if v == option)
        await self._send({"SetFader": [self._fader, channel]})


class EffectPresetSelect(GoXLREntity, SelectEntity):
    _attr_icon = "mdi:account-voice"

    def __init__(self, client: GoXLRClient, serial: str) -> None:
        super().__init__(client, serial, "effect_preset", "Effect preset")

    def _labels(self) -> dict[str, str]:
        """Preset key -> unique display label ("1: Name")."""
        names: dict[str, Any] = (self.mixer.get("effects") or {}).get("preset_names") or {}
        return {p: f"{i}: {names.get(p) or p}" for i, p in enumerate(PRESETS, 1)}

    @property
    def options(self) -> list[str]:
        return list(self._labels().values())

    @property
    def current_option(self) -> str | None:
        return self._labels().get((self.mixer.get("effects") or {}).get("active_preset"))

    async def async_select_option(self, option: str) -> None:
        preset = next(k for k, v in self._labels().items() if v == option)
        await self._send({"SetActiveEffectPreset": preset})
