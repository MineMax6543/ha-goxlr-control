"""Mute, effect and routing switches."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import GoXLRConfigEntry
from .client import GoXLRClient
from .const import CHANNEL_NAMES, CONF_AUTO_RECONNECT, FADERS
from .entity import GoXLREntity, GoXLRHubEntity

Getter = Callable[[dict[str, Any]], bool | None]
Command = Callable[[bool], dict[str, Any]]


def _dig(d: dict[str, Any], *path: str) -> Any:
    for p in path:
        if not isinstance(d, dict):
            return None
        d = d.get(p)
    return d


def _muted(state: Any) -> bool | None:
    return None if state is None else state != "Unmuted"


async def async_setup_entry(
    hass: HomeAssistant, entry: GoXLRConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    client = entry.runtime_data
    async_add_entities([AutoReconnectSwitch(client, hass, entry)])

    @callback
    def _add(serial: str) -> None:
        mixer = client.mixer(serial) or {}
        ents: list[SwitchEntity] = []

        for f in FADERS:
            if f in (mixer.get("fader_status") or {}):
                ents.append(FaderMuteSwitch(client, serial, f))

        ents.append(
            GenericSwitch(
                client, serial, "cough_mute", "Mic mute", "mdi:microphone-off",
                lambda m: _muted(_dig(m, "cough_button", "state")),
                lambda on: {"SetCoughMuteState": "MutedToX" if on else "Unmuted"},
            )
        )

        if mixer.get("effects"):  # full-size GoXLR only
            for key, name, icon, path, cmd in (
                ("fx", "Effects", "mdi:auto-fix", ("effects", "is_enabled"), "SetFXEnabled"),
                ("megaphone", "Megaphone", "mdi:bullhorn", ("effects", "current", "megaphone", "is_enabled"), "SetMegaphoneEnabled"),
                ("robot", "Robot", "mdi:robot", ("effects", "current", "robot", "is_enabled"), "SetRobotEnabled"),
                ("hardtune", "Hard tune", "mdi:music-note", ("effects", "current", "hard_tune", "is_enabled"), "SetHardTuneEnabled"),
            ):
                ents.append(
                    GenericSwitch(
                        client, serial, key, name, icon,
                        lambda m, path=path: _dig(m, *path),
                        lambda on, cmd=cmd: {cmd: on},
                    )
                )

        for src, outs in (mixer.get("router") or {}).items():
            for dst in outs or {}:
                ents.append(RouteSwitch(client, serial, src, dst))

        async_add_entities(ents)

    entry.async_on_unload(client.async_add_mixer_listener(_add))


class GenericSwitch(GoXLREntity, SwitchEntity):
    def __init__(
        self, client: GoXLRClient, serial: str, key: str, name: str, icon: str,
        getter: Getter, command: Command,
    ) -> None:
        super().__init__(client, serial, key, name)
        self._attr_icon = icon
        self._getter = getter
        self._command = command

    @property
    def is_on(self) -> bool | None:
        return self._getter(self.mixer)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._send(self._command(True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._send(self._command(False))


class FaderMuteSwitch(GoXLREntity, SwitchEntity):
    _attr_icon = "mdi:volume-off"

    def __init__(self, client: GoXLRClient, serial: str, fader: str) -> None:
        super().__init__(client, serial, f"fader_{fader}_mute", f"Fader {fader} mute")
        self._fader = fader

    @property
    def _status(self) -> dict[str, Any]:
        return (self.mixer.get("fader_status") or {}).get(self._fader) or {}

    @property
    def is_on(self) -> bool | None:
        return _muted(self._status.get("mute_state"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        ch = self._status.get("channel")
        return {"channel": CHANNEL_NAMES.get(ch, ch), "mute_function": self._status.get("mute_type")}

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._send({"SetFaderMuteState": [self._fader, "MutedToX"]})

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._send({"SetFaderMuteState": [self._fader, "Unmuted"]})


class RouteSwitch(GoXLREntity, SwitchEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
    _attr_icon = "mdi:transit-connection-variant"

    def __init__(self, client: GoXLRClient, serial: str, src: str, dst: str) -> None:
        super().__init__(client, serial, f"route_{src}_{dst}", f"Route {src} to {dst}")
        self._src, self._dst = src, dst

    @property
    def is_on(self) -> bool | None:
        return _dig(self.mixer, "router", self._src, self._dst)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._send({"SetRouter": [self._src, self._dst, True]})

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._send({"SetRouter": [self._src, self._dst, False]})


class AutoReconnectSwitch(GoXLRHubEntity, SwitchEntity):
    """Off = stop retrying once the connection drops (e.g. PC powered off)."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:lan-connect"

    def __init__(self, client: GoXLRClient, hass: HomeAssistant, entry: GoXLRConfigEntry) -> None:
        super().__init__(client, "auto_reconnect", "Auto reconnect")
        self._entry = entry

    @property
    def is_on(self) -> bool:
        return self._client.auto_reconnect

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._set(False)

    def _set(self, enabled: bool) -> None:
        self.hass.config_entries.async_update_entry(
            self._entry, options={**self._entry.options, CONF_AUTO_RECONNECT: enabled}
        )
        self._client.set_auto_reconnect(enabled)
        self.async_write_ha_state()
