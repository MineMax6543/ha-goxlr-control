"""Dropdowns: profiles, fader setup, mic, effects, sampler, lighting, settings."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import GoXLRConfigEntry
from .client import GoXLRClient
from .const import (
    ANIMATION_MODES,
    CHANNEL_NAMES,
    COMP_ATTACK_NAMES,
    COMP_RATIO_NAMES,
    COMP_RELEASE_NAMES,
    ECHO_STYLES,
    EFFECT_PRESETS,
    FADER_DISPLAY_STYLES,
    FADERS,
    GATE_TIME_NAMES,
    GENDER_STYLES,
    HARDTUNE_SOURCES,
    HARDTUNE_STYLES,
    LOG_LEVELS,
    MEGAPHONE_STYLES,
    MIC_TYPE_NAMES,
    MUTE_FUNCTION_NAMES,
    OUTPUT_NAMES,
    PITCH_STYLES,
    REVERB_STYLES,
    ROBOT_STYLES,
    SAMPLE_BANKS,
    SAMPLE_PADS,
    SAMPLE_PLAY_ORDERS,
    SAMPLE_PLAYBACK_MODES,
    VOD_MODES,
    WATERFALL_DIRECTIONS,
)
from .entity import GoXLRHubEntity, GoXLREntity, Mixer, add_mixer_entities, dig, is_full

CONFIG = EntityCategory.CONFIG
NO_ICON = "None"  # option label for "no scribble icon"

# (mixer, client) -> {raw value: label}
OptionsFn = Callable[[Mixer, GoXLRClient], dict[str, str]]


@dataclass(frozen=True, kw_only=True)
class GXSelectDescription(SelectEntityDescription):
    options_fn: OptionsFn
    value_fn: Callable[[Mixer], Any]
    command_fn: Callable[[Mixer, str], Any]
    exists_fn: Callable[[Mixer], bool] | None = None
    available_fn: Callable[[Mixer], bool] | None = None


def _s(
    key: str, name: str, options: dict[str, str] | OptionsFn, path: tuple | Callable[[Mixer], Any],
    cmd: str | Callable[[Mixer, str], Any], *, icon: str | None = None, config: bool = False,
    enabled: bool = True, exists: Callable[[Mixer], bool] | None = None,
    available: Callable[[Mixer], bool] | None = None,
) -> GXSelectDescription:
    return GXSelectDescription(
        key=key, name=name, icon=icon,
        entity_category=CONFIG if config else None,
        entity_registry_enabled_default=enabled,
        options_fn=options if callable(options) else (lambda m, c, o=options: o),
        value_fn=path if callable(path) else (lambda m, p=path: dig(m, *p)),
        command_fn=cmd if callable(cmd) else (lambda m, raw, c=cmd: {c: raw}),
        exists_fn=exists, available_fn=available,
    )


def _files(kind: str) -> OptionsFn:
    def options(m: Mixer, client: GoXLRClient) -> dict[str, str]:
        names = sorted(client.files.get(kind) or [], key=str.casefold)
        return {n: n for n in names}
    return options


def _preset_labels(m: Mixer, client: GoXLRClient) -> dict[str, str]:
    names = dig(m, "effects", "preset_names") or {}
    return {p: f"{i}: {names.get(p) or p}" for i, p in enumerate(EFFECT_PRESETS, 1)}


def _mute_targets(m: Mixer, client: GoXLRClient) -> dict[str, str]:
    """Stream mix 2 targets only exist on devices with submix support."""
    if dig(m, "levels", "submix_supported"):
        return MUTE_FUNCTION_NAMES
    return {k: v for k, v in MUTE_FUNCTION_NAMES.items() if k not in ("ToStream2", "ToStreams")}


def _outputs(m: Mixer, client: GoXLRClient) -> dict[str, str]:
    return {k: v for k, v in OUTPUT_NAMES.items() if k != "StreamMix2" or dig(m, "levels", "submix_supported")}


def _animations(m: Mixer, client: GoXLRClient) -> dict[str, str]:
    if is_full(m):
        return ANIMATION_MODES
    return {k: v for k, v in ANIMATION_MODES.items() if k != "Ripple"}  # not on Mini


def _icons(m: Mixer, client: GoXLRClient) -> dict[str, str]:
    icons = sorted(client.files.get("icons") or [], key=str.casefold)
    return {NO_ICON: "None", **{i: i for i in icons}}


def _library_current(m: Mixer) -> str | None:
    active = dig(m, "effects", "active_preset")
    return dig(m, "effects", "preset_names", active)


def _cough_mode_command(m: Mixer, raw: str) -> Any:
    return {"SetCoughIsHold": raw == "hold"}


def _mixer_selects(m: Mixer) -> list[GXSelectDescription]:
    E = ("effects", "current")
    sub_ok = lambda m: bool(dig(m, "levels", "submix_supported"))  # noqa: E731
    sub_on = lambda m: dig(m, "levels", "submix") is not None  # noqa: E731
    anim = ("lighting", "animation")
    d = [
        # Profiles (True = make it the active profile across Utility restarts).
        _s("profile", "Profile", _files("profiles"), ("profile_name",),
           lambda m, raw: {"LoadProfile": [raw, True]}, icon="mdi:tune-variant"),
        _s("mic_profile", "Mic profile", _files("mic_profiles"), ("mic_profile_name",),
           lambda m, raw: {"LoadMicProfile": [raw, True]}, icon="mdi:microphone-settings"),
        # Monitoring / mixes.
        _s("monitor_mix", "Headphone mix", _outputs, ("levels", "output_monitor"),
           "SetMonitorMix", icon="mdi:headphones", exists=sub_ok),
        # Microphone.
        _s("mic_type", "Mic type", MIC_TYPE_NAMES, ("mic_status", "mic_type"),
           "SetMicrophoneType", icon="mdi:microphone", config=True),
        _s("gate_attack", "Noise gate attack", GATE_TIME_NAMES,
           ("mic_status", "noise_gate", "attack"), "SetGateAttack", icon="mdi:gate",
           config=True, enabled=False),
        _s("gate_release", "Noise gate release", GATE_TIME_NAMES,
           ("mic_status", "noise_gate", "release"), "SetGateRelease", icon="mdi:gate",
           config=True, enabled=False),
        _s("compressor_ratio", "Compressor ratio", COMP_RATIO_NAMES,
           ("mic_status", "compressor", "ratio"), "SetCompressorRatio",
           icon="mdi:arrow-collapse-vertical", config=True),
        _s("compressor_attack", "Compressor attack", COMP_ATTACK_NAMES,
           ("mic_status", "compressor", "attack"), "SetCompressorAttack",
           icon="mdi:arrow-collapse-vertical", config=True, enabled=False),
        _s("compressor_release", "Compressor release", COMP_RELEASE_NAMES,
           ("mic_status", "compressor", "release"), "SetCompressorReleaseTime",
           icon="mdi:arrow-collapse-vertical", config=True, enabled=False),
        # Mute button.
        _s("cough_mute_function", "Mic mute button target", _mute_targets,
           ("cough_button", "mute_type"), "SetCoughMuteFunction", icon="mdi:microphone-off",
           config=True),
        _s("cough_button_mode", "Mic mute button mode", {"toggle": "Toggle", "hold": "Hold"},
           lambda m: None if dig(m, "cough_button", "is_toggle") is None
           else ("toggle" if dig(m, "cough_button", "is_toggle") else "hold"),
           _cough_mode_command, icon="mdi:gesture-tap-hold", config=True),
        _s("vod_mode", "VOD mode", VOD_MODES, ("settings", "vod_mode"), "SetVodMode",
           icon="mdi:video", config=True, enabled=False),
        # Effects (full-size only).
        _s("effect_preset", "Effect preset", _preset_labels, ("effects", "active_preset"),
           "SetActiveEffectPreset", icon="mdi:account-voice"),
        _s("effect_library", "Load library preset into active slot", _files("presets"),
           _library_current, "LoadEffectPreset", icon="mdi:folder-music", config=True,
           exists=lambda m: m.get("effects") is not None),
        _s("reverb_style", "Reverb style", REVERB_STYLES, (*E, "reverb", "style"),
           "SetReverbStyle", icon="mdi:waves"),
        _s("echo_style", "Echo style", ECHO_STYLES, (*E, "echo", "style"), "SetEchoStyle",
           icon="mdi:surround-sound"),
        _s("pitch_style", "Pitch style", PITCH_STYLES, (*E, "pitch", "style"),
           "SetPitchStyle", icon="mdi:music-accidental-sharp"),
        _s("gender_style", "Gender style", GENDER_STYLES, (*E, "gender", "style"),
           "SetGenderStyle", icon="mdi:account-voice"),
        _s("megaphone_style", "Megaphone style", MEGAPHONE_STYLES,
           (*E, "megaphone", "style"), "SetMegaphoneStyle", icon="mdi:bullhorn"),
        _s("robot_style", "Robot style", ROBOT_STYLES, (*E, "robot", "style"),
           "SetRobotStyle", icon="mdi:robot"),
        _s("hardtune_style", "Hard tune style", HARDTUNE_STYLES, (*E, "hard_tune", "style"),
           "SetHardTuneStyle", icon="mdi:music-note"),
        _s("hardtune_source", "Hard tune source", HARDTUNE_SOURCES,
           (*E, "hard_tune", "source"), "SetHardTuneSource", icon="mdi:music-note",
           config=True),
        # Sampler (full-size only).
        _s("sampler_bank", "Sampler bank", {b: f"Bank {b}" for b in SAMPLE_BANKS},
           ("sampler", "active_bank"), "SetActiveSamplerBank", icon="mdi:folder-play"),
        # Lighting.
        _s("animation_mode", "Lighting animation", _animations, (*anim, "mode"),
           "SetAnimationMode", icon="mdi:animation-play",
           exists=lambda m: bool(dig(m, *anim, "supported"))),
        _s("animation_waterfall", "Lighting waterfall", WATERFALL_DIRECTIONS,
           (*anim, "waterfall_direction"), "SetAnimationWaterfall",
           icon="mdi:arrow-up-down", config=True, enabled=False,
           exists=lambda m: bool(dig(m, *anim, "supported")),
           available=lambda m: dig(m, *anim, "mode") not in (None, "None", "RetroRainbow")),
    ]
    for f in FADERS:
        d += [
            _s(f"fader_{f}_channel", f"Fader {f} channel",
               {c: n for c, n in CHANNEL_NAMES.items()}, ("fader_status", f, "channel"),
               lambda m, raw, f=f: {"SetFader": [f, raw]}, icon="mdi:tune-vertical",
               config=True),
            _s(f"fader_{f}_mute_function", f"Fader {f} mute target", _mute_targets,
               ("fader_status", f, "mute_type"),
               lambda m, raw, f=f: {"SetFaderMuteFunction": [f, raw]},
               icon="mdi:volume-off", config=True),
            _s(f"fader_{f}_display_style", f"Fader {f} light style", FADER_DISPLAY_STYLES,
               ("lighting", "faders", f, "style"),
               lambda m, raw, f=f: {"SetFaderDisplayStyle": [f, raw]},
               icon="mdi:led-strip-variant", config=True, enabled=False),
            _s(f"fader_{f}_screen_icon", f"Fader {f} screen icon", _icons,
               lambda m, f=f: (dig(m, "fader_status", f, "scribble", "file_name") or NO_ICON)
               if dig(m, "fader_status", f, "scribble") is not None else None,
               lambda m, raw, f=f: {"SetScribbleIcon": [f, None if raw == NO_ICON else raw]},
               icon="mdi:image-frame", config=True, enabled=False),
        ]
    for out, label in OUTPUT_NAMES.items():
        d.append(_s(
            f"submix_output_{out}", f"{label} source mix", {"A": "Mix A", "B": "Mix B"},
            ("levels", "submix", "outputs", out),
            lambda m, raw, o=out: {"SetSubMixOutputMix": [o, raw]}, icon="mdi:call-split",
            config=True, enabled=False,
            exists=lambda m, o=out: sub_ok(m)
            and o in (dig(m, "router", "Microphone") or OUTPUT_NAMES)
            and (o != "Sampler" or m.get("sampler") is not None),
            available=sub_on,
        ))
    for bank in SAMPLE_BANKS:
        for pad, pad_label in SAMPLE_PADS.items():
            base = ("sampler", "banks", bank, pad)
            d += [
                _s(f"sampler_{bank}_{pad}_mode", f"Sampler {bank} {pad_label.lower()} playback",
                   SAMPLE_PLAYBACK_MODES, (*base, "function"),
                   lambda m, raw, b=bank, p=pad: {"SetSamplerFunction": [b, p, raw]},
                   icon="mdi:play-box-outline", config=True, enabled=False),
                _s(f"sampler_{bank}_{pad}_order", f"Sampler {bank} {pad_label.lower()} order",
                   SAMPLE_PLAY_ORDERS, (*base, "order"),
                   lambda m, raw, b=bank, p=pad: {"SetSamplerOrder": [b, p, raw]},
                   icon="mdi:shuffle-variant", config=True, enabled=False),
            ]
    return d


async def async_setup_entry(
    hass: HomeAssistant, entry: GoXLRConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    client = entry.runtime_data
    async_add_entities([LogLevelSelect(client)])

    def build(client: GoXLRClient, serial: str, mixer: Mixer) -> list[Entity]:
        return [
            GoXLRSelect(client, serial, desc)
            for desc in _mixer_selects(mixer)
            if (desc.exists_fn(mixer) if desc.exists_fn else desc.value_fn(mixer) is not None)
        ]

    add_mixer_entities(entry, build, async_add_entities)


class GoXLRSelect(GoXLREntity, SelectEntity):
    entity_description: GXSelectDescription

    def __init__(self, client: GoXLRClient, serial: str, desc: GXSelectDescription) -> None:
        super().__init__(client, serial, desc.key, description=desc)

    def _map(self) -> dict[str, str]:
        return self.entity_description.options_fn(self.mixer, self._client)

    @property
    def options(self) -> list[str]:
        mapping = self._map()
        labels = list(mapping.values())
        # Keep an unknown current value visible instead of showing "unknown".
        raw = self.entity_description.value_fn(self.mixer)
        if raw is not None and raw not in mapping and str(raw) not in labels:
            labels.append(str(raw))
        return labels

    @property
    def current_option(self) -> str | None:
        raw = self.entity_description.value_fn(self.mixer)
        if raw is None:
            return None
        return self._map().get(raw, str(raw))

    async def async_select_option(self, option: str) -> None:
        raw = next((k for k, v in self._map().items() if v == option), None)
        if raw is None:
            current = self.entity_description.value_fn(self.mixer)
            if current is None or str(current) != option:
                raise HomeAssistantError(f"Unknown option: {option}")
            raw = current
        await self._send(self.entity_description.command_fn(self.mixer, raw))


class LogLevelSelect(GoXLRHubEntity, SelectEntity):
    _attr_entity_category = CONFIG
    _attr_entity_registry_enabled_default = False
    _attr_icon = "mdi:math-log"
    _attr_options = list(LOG_LEVELS.values())

    def __init__(self, client: GoXLRClient) -> None:
        super().__init__(client, "log_level", "Log level")

    @property
    def available(self) -> bool:
        return self._client.connected

    @property
    def current_option(self) -> str | None:
        level = self.config.get("log_level")
        return LOG_LEVELS.get(level, level)

    async def async_select_option(self, option: str) -> None:
        raw = next(k for k, v in LOG_LEVELS.items() if v == option)
        await self._send({"SetLogLevel": raw})
