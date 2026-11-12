"""Free text: fader screen (scribble strip) text/number, effect preset name."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.text import TextEntity, TextEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import GoXLRConfigEntry
from .client import GoXLRClient
from .const import FADERS
from .entity import GoXLREntity, Mixer, add_mixer_entities, dig


@dataclass(frozen=True, kw_only=True)
class GXTextDescription(TextEntityDescription):
    value_fn: Callable[[Mixer], str | None]
    command_fn: Callable[[str], Any]
    exists_fn: Callable[[Mixer], bool]


def _texts() -> list[GXTextDescription]:
    d: list[GXTextDescription] = []
    for f in FADERS:
        has_screen = lambda m, f=f: dig(m, "fader_status", f, "scribble") is not None  # noqa: E731
        d += [
            GXTextDescription(
                key=f"fader_{f}_screen_text", name=f"Fader {f} screen text",
                icon="mdi:form-textbox", native_max=255,
                entity_category=EntityCategory.CONFIG,
                value_fn=lambda m, f=f: dig(m, "fader_status", f, "scribble", "bottom_text") or "",
                command_fn=lambda v, f=f: {"SetScribbleText": [f, v]},
                exists_fn=has_screen,
            ),
            GXTextDescription(
                key=f"fader_{f}_screen_number", name=f"Fader {f} screen number",
                icon="mdi:numeric", native_max=255, entity_category=EntityCategory.CONFIG,
                entity_registry_enabled_default=False,
                value_fn=lambda m, f=f: dig(m, "fader_status", f, "scribble", "left_text") or "",
                command_fn=lambda v, f=f: {"SetScribbleNumber": [f, v]},
                exists_fn=has_screen,
            ),
        ]
    d.append(GXTextDescription(
        key="effect_preset_name", name="Effect preset name", icon="mdi:rename",
        native_min=1, native_max=255, entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        value_fn=lambda m: dig(m, "effects", "preset_names", dig(m, "effects", "active_preset")),
        command_fn=lambda v: {"RenameActivePreset": v},
        exists_fn=lambda m: m.get("effects") is not None,
    ))
    return d


async def async_setup_entry(
    hass: HomeAssistant, entry: GoXLRConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    def build(client: GoXLRClient, serial: str, mixer: Mixer) -> list[Entity]:
        return [GoXLRText(client, serial, d) for d in _texts() if d.exists_fn(mixer)]

    add_mixer_entities(entry, build, async_add_entities)


class GoXLRText(GoXLREntity, TextEntity):
    entity_description: GXTextDescription

    def __init__(self, client: GoXLRClient, serial: str, desc: GXTextDescription) -> None:
        super().__init__(client, serial, desc.key, description=desc)

    @property
    def native_value(self) -> str | None:
        return self.entity_description.value_fn(self.mixer)

    async def async_set_value(self, value: str) -> None:
        await self._send(self.entity_description.command_fn(value))
