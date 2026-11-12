"""Physical GoXLR buttons as Home Assistant event entities.

Each button fires:
  pressed      - the moment it goes down
  long_press   - while still held, after the mixer's mute hold duration
  short_press  - on release, if long_press didn't fire
  released     - on release, always

Events are taken straight from the daemon's patches (not the debounced state
updates), so even very quick taps are never lost.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later

from . import GoXLRConfigEntry
from .client import GoXLRClient
from .const import (
    BUTTONS_FULL,
    BUTTONS_MINI,
    DEFAULT_LONG_PRESS_MS,
    EVENT_LONG_PRESS,
    EVENT_PRESSED,
    EVENT_RELEASED,
    EVENT_SHORT_PRESS,
)
from .entity import GoXLREntity, Mixer, add_mixer_entities, dig, is_full


async def async_setup_entry(
    hass: HomeAssistant, entry: GoXLRConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    def build(client: GoXLRClient, serial: str, mixer: Mixer) -> list[Entity]:
        if mixer.get("button_down") is None:
            return []
        buttons = BUTTONS_FULL if is_full(mixer) else BUTTONS_MINI
        return [ButtonEvent(client, serial, b, name) for b, name in buttons.items()]

    add_mixer_entities(entry, build, async_add_entities)


class ButtonEvent(GoXLREntity, EventEntity):
    _attr_device_class = EventDeviceClass.BUTTON
    _attr_event_types = [EVENT_PRESSED, EVENT_RELEASED, EVENT_SHORT_PRESS, EVENT_LONG_PRESS]

    def __init__(self, client: GoXLRClient, serial: str, button: str, name: str) -> None:
        super().__init__(client, serial, f"button_{button}", name)
        self._button = button
        self._path = f"/mixers/{serial}/button_down/{button}"
        self._map_path = f"/mixers/{serial}/button_down"
        self._down = bool(dig(client.mixer(serial), "button_down", button))
        self._long_fired = False
        self._cancel_long: CALLBACK_TYPE | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._client.async_add_patch_listener(self._on_patch))
        self.async_on_remove(self._cancel_timer)

    @callback
    def _on_patch(self, ops: list[dict[str, Any]]) -> None:
        for op in ops:
            path = op.get("path")
            if op.get("op") not in ("replace", "add"):
                continue
            if path == self._path:
                self._set_down(bool(op.get("value")))
            elif path == self._map_path and isinstance(op.get("value"), dict):
                self._set_down(bool(op["value"].get(self._button)))

    @callback
    def _set_down(self, down: bool) -> None:
        if down == self._down:
            return
        self._down = down
        if down:
            self._long_fired = False
            self._fire(EVENT_PRESSED)
            hold_ms = dig(self.mixer, "settings", "mute_hold_duration") or DEFAULT_LONG_PRESS_MS
            self._cancel_long = async_call_later(self.hass, hold_ms / 1000, self._on_long)
        else:
            self._cancel_timer()
            self._fire(EVENT_RELEASED)
            if not self._long_fired:
                self._fire(EVENT_SHORT_PRESS)

    @callback
    def _on_long(self, _now: Any) -> None:
        self._cancel_long = None
        if self._down:
            self._long_fired = True
            self._fire(EVENT_LONG_PRESS)

    @callback
    def _cancel_timer(self) -> None:
        if self._cancel_long is not None:
            self._cancel_long()
            self._cancel_long = None

    @callback
    def _fire(self, event_type: str) -> None:
        self._trigger_event(event_type)
        self.async_write_ha_state()
