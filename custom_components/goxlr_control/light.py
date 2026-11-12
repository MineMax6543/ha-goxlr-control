"""Whole-device lighting as one RGB light.

* Set a colour/brightness -> every LED takes that colour (SetGlobalColour).
* Turn off -> all LEDs black.
* Turn on without a colour -> restores what was there before: the same single
  colour if the lighting was uniform, otherwise the profile's full colour scheme.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import GoXLRConfigEntry
from .client import GoXLRClient
from .entity import GoXLREntity, Mixer, add_mixer_entities, dig

BLACK = "000000"


def _colours(data: Any) -> list[str]:
    """Every colour string in the lighting tree (colour_one/two/three)."""
    out: list[str] = []
    if isinstance(data, dict):
        for key, value in data.items():
            if key.startswith("colour_") and isinstance(value, str):
                out.append(value.upper().lstrip("#"))
            else:
                out += _colours(value)
    return out


def _rgb(hex_colour: str | None) -> tuple[int, int, int] | None:
    try:
        h = (hex_colour or "").lstrip("#")
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return None


async def async_setup_entry(
    hass: HomeAssistant, entry: GoXLRConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    def build(client: GoXLRClient, serial: str, mixer: Mixer) -> list[Entity]:
        if dig(mixer, "lighting", "simple", "Global") is None:
            return []
        return [LightingLight(client, serial)]

    add_mixer_entities(entry, build, async_add_entities)


class LightingLight(GoXLREntity, LightEntity):
    _attr_color_mode = ColorMode.RGB
    _attr_supported_color_modes = {ColorMode.RGB}
    _attr_icon = "mdi:led-strip-variant"

    def __init__(self, client: GoXLRClient, serial: str) -> None:
        super().__init__(client, serial, "lighting", "Lighting")
        self._restore_colour: str | None = None

    @property
    def _global(self) -> tuple[int, int, int] | None:
        return _rgb(dig(self.mixer, "lighting", "simple", "Global", "colour_one"))

    @property
    def is_on(self) -> bool:
        return any(c != BLACK for c in _colours(self.mixer.get("lighting")))

    @property
    def brightness(self) -> int | None:
        rgb = self._global
        return max(rgb) if rgb and max(rgb) else (255 if self.is_on else None)

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        rgb = self._global
        if not rgb or not max(rgb):
            return None
        peak = max(rgb)
        return tuple(round(c * 255 / peak) for c in rgb)  # type: ignore[return-value]

    async def async_turn_on(self, **kwargs: Any) -> None:
        if ATTR_RGB_COLOR not in kwargs and ATTR_BRIGHTNESS not in kwargs:
            if self.is_on:
                return
            if self._restore_colour:
                await self._send({"SetGlobalColour": self._restore_colour})
            else:
                await self._send({"LoadProfileColours": self.mixer.get("profile_name")})
            return
        rgb = kwargs.get(ATTR_RGB_COLOR) or self.rgb_color or (255, 255, 255)
        bri = kwargs.get(ATTR_BRIGHTNESS, self.brightness or 255)
        scaled = (round(c * bri / 255) for c in rgb)
        await self._send({"SetGlobalColour": "".join(f"{c:02X}" for c in scaled)})

    async def async_turn_off(self, **kwargs: Any) -> None:
        colours = {c for c in _colours(self.mixer.get("lighting")) if c != BLACK}
        # Uniform lighting -> remember that colour; otherwise restore the profile.
        self._restore_colour = colours.pop() if len(colours) == 1 else None
        await self._send({"SetGlobalColour": BLACK})
