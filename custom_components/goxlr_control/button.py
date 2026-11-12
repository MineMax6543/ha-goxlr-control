"""One-shot actions: save profiles/presets, play/stop sampler pads, open the UI."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import GoXLRConfigEntry
from .client import GoXLRClient
from .const import SAMPLE_PADS
from .entity import GoXLRHubEntity, GoXLREntity, Mixer, add_mixer_entities, dig


@dataclass(frozen=True, kw_only=True)
class GXButtonDescription(ButtonEntityDescription):
    command_fn: Callable[[Mixer], Any]
    exists_fn: Callable[[Mixer], bool]
    available_fn: Callable[[Mixer], bool] | None = None


def _pad_has_samples(pad: str) -> Callable[[Mixer], bool]:
    def check(m: Mixer) -> bool:
        bank = dig(m, "sampler", "active_bank")
        return bool(dig(m, "sampler", "banks", bank, pad, "samples"))
    return check


def _buttons() -> list[GXButtonDescription]:
    has_fx = lambda m: m.get("effects") is not None  # noqa: E731
    has_sampler = lambda m: m.get("sampler") is not None  # noqa: E731
    d = [
        # Unit-like tuple variants serialise as {"Name": []}.
        GXButtonDescription(
            key="save_profile", name="Save profile", icon="mdi:content-save",
            entity_category=EntityCategory.CONFIG,
            command_fn=lambda m: {"SaveProfile": []}, exists_fn=lambda m: True,
        ),
        GXButtonDescription(
            key="save_mic_profile", name="Save mic profile", icon="mdi:content-save",
            entity_category=EntityCategory.CONFIG,
            command_fn=lambda m: {"SaveMicProfile": []}, exists_fn=lambda m: True,
        ),
        GXButtonDescription(
            key="save_effect_preset", name="Save effect preset to library",
            icon="mdi:content-save", entity_category=EntityCategory.CONFIG,
            command_fn=lambda m: {"SaveActivePreset": []}, exists_fn=has_fx,
        ),
        GXButtonDescription(
            key="restore_profile_colours", name="Restore profile lighting",
            icon="mdi:palette", entity_category=EntityCategory.CONFIG,
            command_fn=lambda m: {"LoadProfileColours": m.get("profile_name")},
            exists_fn=lambda m: True,
        ),
    ]
    for pad, label in SAMPLE_PADS.items():
        d += [
            GXButtonDescription(
                key=f"sampler_{pad}_play", name=f"Play {label.lower()} sample",
                icon="mdi:play",
                command_fn=lambda m, p=pad: {
                    "PlayNextSample": [dig(m, "sampler", "active_bank"), p]
                },
                exists_fn=has_sampler, available_fn=_pad_has_samples(pad),
            ),
            GXButtonDescription(
                key=f"sampler_{pad}_stop", name=f"Stop {label.lower()} sample",
                icon="mdi:stop",
                command_fn=lambda m, p=pad: {
                    "StopSamplePlayback": [dig(m, "sampler", "active_bank"), p]
                },
                exists_fn=has_sampler,
            ),
        ]
    return d


async def async_setup_entry(
    hass: HomeAssistant, entry: GoXLRConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([OpenUiButton(entry.runtime_data, "open_ui", "Open Utility window")])

    def build(client: GoXLRClient, serial: str, mixer: Mixer) -> list[Entity]:
        return [GoXLRButton(client, serial, d) for d in _buttons() if d.exists_fn(mixer)]

    add_mixer_entities(entry, build, async_add_entities)


class GoXLRButton(GoXLREntity, ButtonEntity):
    entity_description: GXButtonDescription

    def __init__(self, client: GoXLRClient, serial: str, desc: GXButtonDescription) -> None:
        super().__init__(client, serial, desc.key, description=desc)

    async def async_press(self) -> None:
        await self._send(self.entity_description.command_fn(self.mixer))


class OpenUiButton(GoXLRHubEntity, ButtonEntity):
    """Opens the GoXLR Utility window on the PC."""

    _attr_icon = "mdi:open-in-app"

    @property
    def available(self) -> bool:
        return self._client.connected

    async def async_press(self) -> None:
        await self._send("OpenUi")
