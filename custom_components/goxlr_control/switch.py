"""On/off controls: mutes, effects, routing, mic, settings, Utility options."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import GoXLRConfigEntry
from .client import GoXLRClient
from .const import (
    CHANNEL_NAMES,
    CONF_AUTO_RECONNECT,
    FADERS,
    INPUT_NAMES,
    MUTE_FUNCTION_NAMES,
    OUTPUT_NAMES,
    SUBMIX_CHANNELS,
)
from .entity import GoXLRHubEntity, GoXLREntity, Mixer, add_mixer_entities, dig
from .mic_monitor import MicMonitor, get_monitor

CONFIG = EntityCategory.CONFIG
# The daemon refuses this route (chat would loop back into itself).
INVALID_ROUTES = {("Chat", "ChatMic")}


@dataclass(frozen=True, kw_only=True)
class GXSwitchDescription(SwitchEntityDescription):
    value_fn: Callable[[Mixer], bool | None]
    command_fn: Callable[[Mixer, bool], Any]
    exists_fn: Callable[[Mixer], bool] | None = None
    available_fn: Callable[[Mixer], bool] | None = None


def _sw(
    key: str, name: str, path: tuple | Callable[[Mixer], bool | None],
    cmd: str | Callable[[Mixer, bool], Any], *, icon: str | None = None,
    config: bool = False, enabled: bool = True,
    exists: Callable[[Mixer], bool] | None = None,
    available: Callable[[Mixer], bool] | None = None,
) -> GXSwitchDescription:
    return GXSwitchDescription(
        key=key, name=name, icon=icon,
        entity_category=CONFIG if config else None,
        entity_registry_enabled_default=enabled,
        value_fn=path if callable(path) else (lambda m, p=path: dig(m, *p)),
        command_fn=cmd if callable(cmd) else (lambda m, on, c=cmd: {c: on}),
        exists_fn=exists, available_fn=available,
    )


def _muted(state: Any) -> bool | None:
    return None if state is None else state != "Unmuted"


def _cough_command(m: Mixer, on: bool) -> Any:
    if dig(m, "cough_button", "is_toggle") is False:
        raise HomeAssistantError(
            "The GoXLR mic mute button is in Hold mode, which can only be muted by holding "
            "the physical button. Set 'Mic mute button mode' to Toggle to control it here."
        )
    return {"SetCoughMuteState": "MutedToX" if on else "Unmuted"}


def _mixer_switches(m: Mixer) -> list[GXSwitchDescription]:
    E = ("effects", "current")
    sub_ok = lambda m: bool(dig(m, "levels", "submix_supported"))  # noqa: E731
    sub_on = lambda m: dig(m, "levels", "submix") is not None  # noqa: E731
    d = [
        _sw("cough_mute", "Mic mute", lambda m: _muted(dig(m, "cough_button", "state")),
            _cough_command, icon="mdi:microphone-off"),
        # Effects (full-size only).
        _sw("fx", "Effects", ("effects", "is_enabled"), "SetFXEnabled", icon="mdi:auto-fix"),
        _sw("megaphone", "Megaphone", (*E, "megaphone", "is_enabled"), "SetMegaphoneEnabled",
            icon="mdi:bullhorn"),
        _sw("robot", "Robot", (*E, "robot", "is_enabled"), "SetRobotEnabled", icon="mdi:robot"),
        _sw("hardtune", "Hard tune", (*E, "hard_tune", "is_enabled"), "SetHardTuneEnabled",
            icon="mdi:music-note"),
        _sw("monitor_with_fx", "Mic monitoring follows effects",
            ("settings", "enable_monitor_with_fx"), "SetMonitorWithFx",
            icon="mdi:headphones-settings", config=True,
            exists=lambda m: m.get("effects") is not None),
        # Mic.
        _sw("noise_gate", "Noise gate", ("mic_status", "noise_gate", "enabled"),
            "SetGateActive", icon="mdi:gate", config=True),
        # Mixing.
        _sw("submix", "Mix B (submix)", sub_on, "SetSubMixEnabled", icon="mdi:call-split",
            config=True, exists=sub_ok),
        _sw("lock_faders", "Lock faders when muted to all", ("settings", "lock_faders"), "SetLockFaders",
            icon="mdi:lock", config=True),
        _sw("vc_mute_also_mute_cm", "Voice chat mute-to-all also mutes chat mic",
            ("settings", "vc_mute_also_mute_cm"), "SetVCMuteAlsoMuteCM",
            icon="mdi:account-voice-off", config=True),
        # Sampler.
        _sw("sampler_reset_on_clear", "Sampler clear resets pad playback",
            ("settings", "reset_sampler_on_clear"), "SetSamplerResetOnClear",
            icon="mdi:eraser", config=True, enabled=False,
            exists=lambda m: m.get("sampler") is not None),
    ]
    for ch in SUBMIX_CHANNELS:
        d.append(_sw(
            f"submix_linked_{ch}", f"{CHANNEL_NAMES[ch]} mix B linked",
            ("levels", "submix", "inputs", ch, "linked"),
            lambda m, on, ch=ch: {"SetSubMixLinked": [ch, on]}, icon="mdi:link-variant",
            config=True, enabled=False, exists=sub_ok, available=sub_on,
        ))
    for f in FADERS:
        d.append(_sw(
            f"fader_{f}_screen_inverted", f"Fader {f} screen inverted",
            ("fader_status", f, "scribble", "inverted"),
            lambda m, on, f=f: {"SetScribbleInvert": [f, on]}, icon="mdi:invert-colors",
            config=True, enabled=False,
        ))
    for src, outs in (m.get("router") or {}).items():
        for dst in outs or {}:
            if (src, dst) in INVALID_ROUTES:
                continue
            if dst == "Sampler" and m.get("sampler") is None:
                continue  # the Mini reports a Sampler output but has no sampler
            d.append(_sw(
                f"route_{src}_{dst}",
                f"Route {INPUT_NAMES.get(src, src)} to {OUTPUT_NAMES.get(dst, dst)}",
                ("router", src, dst),
                lambda m, on, s=src, t=dst: {"SetRouter": [s, t, on]},
                icon="mdi:transit-connection-variant", config=True, enabled=False,
            ))
    return d


async def async_setup_entry(
    hass: HomeAssistant, entry: GoXLRConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    client = entry.runtime_data
    async_add_entities([
        AutoReconnectSwitch(client, entry),
        UtilitySwitch(client, "autostart", "Start on login", "autostart_enabled",
                      "SetAutoStartEnabled", "mdi:power"),
        UtilitySwitch(client, "tray_icon", "Show tray icon", "show_tray_icon",
                      "SetShowTrayIcon", "mdi:tray"),
        UtilitySwitch(client, "tts", "Speak button presses", "tts_enabled",
                      "SetTTSEnabled", "mdi:account-voice"),
        UtilitySwitch(client, "open_ui_on_launch", "Open window on launch",
                      "open_ui_on_launch", "SetUiLaunchOnLoad", "mdi:application-outline",
                      enabled=False),
    ])

    def build(client: GoXLRClient, serial: str, mixer: Mixer) -> list[Entity]:
        ents: list[Entity] = [
            GoXLRSwitch(client, serial, desc)
            for desc in _mixer_switches(mixer)
            if (desc.exists_fn(mixer) if desc.exists_fn else desc.value_fn(mixer) is not None)
        ]
        ents += [
            FaderMuteSwitch(client, serial, f)
            for f in FADERS if dig(mixer, "fader_status", f) is not None
        ]
        ents.append(MicMonitoringSwitch(client, serial, get_monitor(hass, entry, serial)))
        return ents

    add_mixer_entities(entry, build, async_add_entities)


class GoXLRSwitch(GoXLREntity, SwitchEntity):
    entity_description: GXSwitchDescription

    def __init__(self, client: GoXLRClient, serial: str, desc: GXSwitchDescription) -> None:
        super().__init__(client, serial, desc.key, description=desc)

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.mixer)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._send(self.entity_description.command_fn(self.mixer, True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._send(self.entity_description.command_fn(self.mixer, False))


class FaderMuteSwitch(GoXLREntity, SwitchEntity):
    """Mutes the fader to its configured target (see "Fader X mute target")."""

    _attr_icon = "mdi:volume-off"

    def __init__(self, client: GoXLRClient, serial: str, fader: str) -> None:
        super().__init__(client, serial, f"fader_{fader}_mute", f"Fader {fader} mute")
        self._fader = fader

    @property
    def _status(self) -> dict[str, Any]:
        return dig(self.mixer, "fader_status", self._fader) or {}

    @property
    def is_on(self) -> bool | None:
        return _muted(self._status.get("mute_state"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        ch = self._status.get("channel")
        target = self._status.get("mute_type")
        return {
            "channel": CHANNEL_NAMES.get(ch, ch),
            "mute_target": MUTE_FUNCTION_NAMES.get(target, target),
            "muted_to_all": self._status.get("mute_state") == "MutedToAll",
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._send({"SetFaderMuteState": [self._fader, "MutedToX"]})

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._send({"SetFaderMuteState": [self._fader, "Unmuted"]})


class MicMonitoringSwitch(GoXLREntity, SwitchEntity):
    """Opt-in: poll the live mic level (feeds "Mic level" and "Speaking")."""

    _attr_entity_category = CONFIG
    _attr_icon = "mdi:waveform"

    def __init__(self, client: GoXLRClient, serial: str, monitor: MicMonitor) -> None:
        super().__init__(client, serial, "mic_level_monitoring", "Mic level monitoring")
        self._monitor = monitor

    @property
    def available(self) -> bool:
        return True  # a local setting; can be changed while disconnected

    @property
    def is_on(self) -> bool:
        return self._monitor.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._monitor.set_enabled(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._monitor.set_enabled(False)
        self.async_write_ha_state()


class UtilitySwitch(GoXLRHubEntity, SwitchEntity):
    """A GoXLR Utility (app-level) setting."""

    _attr_entity_category = CONFIG

    def __init__(
        self, client: GoXLRClient, key: str, name: str, field: str, command: str, icon: str,
        enabled: bool = True,
    ) -> None:
        super().__init__(client, key, name)
        self._field = field
        self._command = command
        self._attr_icon = icon
        self._attr_entity_registry_enabled_default = enabled

    @property
    def available(self) -> bool:
        # tts_enabled is null on platforms without text-to-speech.
        return self._client.connected and self.config.get(self._field) is not None

    @property
    def is_on(self) -> bool | None:
        return self.config.get(self._field)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._send({self._command: True})

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._send({self._command: False})


class AutoReconnectSwitch(GoXLRHubEntity, SwitchEntity):
    """Off = stop retrying once the connection drops (e.g. PC powered off)."""

    _attr_entity_category = CONFIG
    _attr_icon = "mdi:lan-connect"

    def __init__(self, client: GoXLRClient, entry: GoXLRConfigEntry) -> None:
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
