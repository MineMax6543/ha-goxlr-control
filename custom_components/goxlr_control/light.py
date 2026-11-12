"""Whole-device lighting as one RGB light.

* Set a colour/brightness -> every LED takes that colour (SetGlobalColour).
* Turn off -> SetGlobalColour("000000").
* Turn on without a colour -> restores what was there before turning off:
  the colour you last set from Home Assistant, or otherwise the colour
  scheme saved in the active profile (LoadProfileColours).

On/off is read from the *global* colour target. SetGlobalColour deliberately
leaves the effect knob rings and the secondary (dimmed) button colours alone,
so the rest of the lighting tree never becomes all-black and can't be used to
decide whether the light is off.
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
from homeassistant.helpers.restore_state import RestoredExtraData, RestoreEntity

from . import GoXLRConfigEntry
from .client import GoXLRClient
from .entity import GoXLREntity, Mixer, add_mixer_entities, dig

BLACK = "000000"


def _rgb(hex_colour: str | None) -> tuple[int, int, int] | None:
    h = (hex_colour or "").lstrip("#")
    if len(h) != 6:
        return None
    try:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return None


def _hex(rgb: tuple[int, ...]) -> str:
    return "".join(f"{max(0, min(255, round(c))):02X}" for c in rgb)


def _normalise(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    """Full-brightness version of a colour (brightness is tracked separately)."""
    peak = max(rgb)
    return tuple(round(c * 255 / peak) for c in rgb) if peak else (255, 255, 255)  # type: ignore[return-value]


async def async_setup_entry(
    hass: HomeAssistant, entry: GoXLRConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    def build(client: GoXLRClient, serial: str, mixer: Mixer) -> list[Entity]:
        if dig(mixer, "lighting", "simple", "Global") is None:
            return []
        return [LightingLight(client, serial)]

    add_mixer_entities(entry, build, async_add_entities)


class LightingLight(GoXLREntity, LightEntity, RestoreEntity):
    _attr_color_mode = ColorMode.RGB
    _attr_supported_color_modes = {ColorMode.RGB}
    _attr_icon = "mdi:led-strip-variant"

    def __init__(self, client: GoXLRClient, serial: str) -> None:
        super().__init__(client, serial, "lighting", "Lighting")
        # Last colour Home Assistant set, and what "on" will restore
        # (a hex colour, or None = the profile's saved colour scheme).
        self._set_colour: str | None = None
        self._restore_colour: str | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (data := await self.async_get_last_extra_data()) is not None:
            stored = data.as_dict()
            self._set_colour = stored.get("set_colour")
            self._restore_colour = stored.get("restore_colour")

    @property
    def extra_restore_state_data(self) -> RestoredExtraData:
        return RestoredExtraData(
            {"set_colour": self._set_colour, "restore_colour": self._restore_colour}
        )

    @property
    def _global_hex(self) -> str | None:
        value = dig(self.mixer, "lighting", "simple", "Global", "colour_one")
        return value.upper().lstrip("#") if isinstance(value, str) else None

    @property
    def is_on(self) -> bool | None:
        g = self._global_hex
        return None if g is None else g != BLACK

    @property
    def brightness(self) -> int | None:
        rgb = _rgb(self._global_hex)
        return max(rgb) if rgb and max(rgb) else None

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        rgb = _rgb(self._global_hex)
        return _normalise(rgb) if rgb and max(rgb) else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "turn_on_restores": (
                f"#{self._restore_colour}" if self._restore_colour else "profile colours"
            )
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        if ATTR_RGB_COLOR not in kwargs and ATTR_BRIGHTNESS not in kwargs:
            if self.is_on:
                return
            if self._restore_colour:
                await self._send({"SetGlobalColour": self._restore_colour})
            else:
                await self._send({"LoadProfileColours": self.mixer.get("profile_name")})
            return

        # Base colour: requested > current > remembered > white.
        if ATTR_RGB_COLOR in kwargs:
            base = tuple(kwargs[ATTR_RGB_COLOR])
        elif self.rgb_color:
            base = self.rgb_color
        elif (remembered := _rgb(self._restore_colour)) and max(remembered):
            base = _normalise(remembered)
        else:
            base = (255, 255, 255)
        bri = kwargs.get(ATTR_BRIGHTNESS)
        if bri is None:
            bri = self.brightness or 255
        colour = _hex(tuple(c * bri / 255 for c in base))
        self._set_colour = colour
        await self._send({"SetGlobalColour": colour})

    async def async_turn_off(self, **kwargs: Any) -> None:
        current = self._global_hex
        if current and current != BLACK:
            # Still showing the colour we set -> bring that back; otherwise the
            # lighting came from the profile (or the Utility UI) -> reload it.
            self._restore_colour = current if current == self._set_colour else None
        await self._send({"SetGlobalColour": BLACK})
        self.async_write_ha_state()  # persist the restore choice right away
