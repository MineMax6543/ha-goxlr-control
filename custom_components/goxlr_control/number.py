"""Sliders: volumes, mic processing, effect parameters, sampler and lighting."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import GoXLRConfigEntry
from .client import GoXLRClient
from .const import (
    CHANNEL_NAMES,
    CHANNELS,
    EQ_BANDS,
    EQ_BANDS_MINI,
    GENDER_RANGES,
    MIC_LEVEL_MIN,
    SUBMIX_CHANNELS,
)
from .entity import GoXLREntity, Mixer, add_mixer_entities, dig, is_full
from .mic_monitor import get_monitor

DB = "dB"
CONFIG = EntityCategory.CONFIG


@dataclass(frozen=True, kw_only=True)
class GXNumberDescription(NumberEntityDescription):
    value_fn: Callable[[Mixer], Any]
    command_fn: Callable[[Mixer, float], Any]
    exists_fn: Callable[[Mixer], bool] | None = None
    available_fn: Callable[[Mixer], bool] | None = None
    # Dynamic (min, max, step) for ranges that depend on another setting.
    range_fn: Callable[[Mixer], tuple[float, float, float]] | None = None


def _n(
    key: str, name: str, path: tuple, cmd: str | Callable[[Mixer, float], Any],
    lo: float, hi: float, step: float = 1, unit: str | None = None, *,
    icon: str | None = None, config: bool = False, enabled: bool = True,
    exists: Callable[[Mixer], bool] | None = None,
    available: Callable[[Mixer], bool] | None = None,
    range_fn: Callable[[Mixer], tuple[float, float, float]] | None = None,
    mode: NumberMode = NumberMode.SLIDER,
) -> GXNumberDescription:
    command = cmd if callable(cmd) else (lambda m, v, c=cmd: {c: int(round(v))})
    return GXNumberDescription(
        key=key, name=name, icon=icon,
        native_min_value=lo, native_max_value=hi, native_step=step,
        native_unit_of_measurement=unit, mode=mode,
        entity_category=CONFIG if config else None,
        entity_registry_enabled_default=enabled,
        value_fn=lambda m, p=path: dig(m, *p),
        command_fn=command, exists_fn=exists, available_fn=available, range_fn=range_fn,
    )


def _pct_of_255(v: Any) -> float | None:
    return None if v is None else round(v * 100 / 255)


def _to_255(v: float) -> int:
    return max(0, min(255, round(v * 255 / 100)))


def _pitch_range(m: Mixer) -> tuple[float, float, float]:
    """Pitch limits depend on style and on Hard tune (then it snaps to octaves)."""
    narrow = dig(m, "effects", "current", "pitch", "style") == "Narrow"
    if dig(m, "effects", "current", "hard_tune", "is_enabled"):
        return (-1, 1, 1) if narrow else (-2, 2, 1)
    return (-24, 24, 2) if narrow else (-24, 24, 1)


def _gender_range(m: Mixer) -> tuple[float, float, float]:
    r = GENDER_RANGES.get(dig(m, "effects", "current", "gender", "style"), 12)
    return (-r, r, 1)


def _submix_on(m: Mixer) -> bool:
    return dig(m, "levels", "submix") is not None


def _submix_supported(m: Mixer) -> bool:
    return bool(dig(m, "levels", "submix_supported"))


def _mixer_numbers(m: Mixer) -> list[GXNumberDescription]:
    d: list[GXNumberDescription] = []
    E = ("effects", "current")

    # Volumes (mix A) and mix B (submix) volumes.
    for ch in CHANNELS:
        d.append(GXNumberDescription(
            key=f"volume_{ch}", name=f"{CHANNEL_NAMES[ch]} volume", icon="mdi:volume-high",
            native_min_value=0, native_max_value=100, native_step=1,
            native_unit_of_measurement=PERCENTAGE, mode=NumberMode.SLIDER,
            value_fn=lambda m, ch=ch: _pct_of_255(dig(m, "levels", "volumes", ch)),
            command_fn=lambda m, v, ch=ch: {"SetVolume": [ch, _to_255(v)]},
        ))
    for ch in SUBMIX_CHANNELS:
        d.append(GXNumberDescription(
            key=f"submix_volume_{ch}", name=f"{CHANNEL_NAMES[ch]} volume (mix B)",
            icon="mdi:volume-high", native_min_value=0, native_max_value=100, native_step=1,
            native_unit_of_measurement=PERCENTAGE, mode=NumberMode.SLIDER,
            entity_registry_enabled_default=False,
            value_fn=lambda m, ch=ch: _pct_of_255(dig(m, "levels", "submix", "inputs", ch, "volume")),
            command_fn=lambda m, v, ch=ch: {"SetSubMixVolume": [ch, _to_255(v)]},
            exists_fn=_submix_supported, available_fn=_submix_on,
        ))

    # Microphone.
    d.append(GXNumberDescription(
        key="mic_gain", name="Mic gain", icon="mdi:microphone-plus",
        native_min_value=0, native_max_value=72, native_step=1,
        native_unit_of_measurement=DB, mode=NumberMode.SLIDER, entity_category=CONFIG,
        value_fn=lambda m: dig(m, "mic_status", "mic_gains", dig(m, "mic_status", "mic_type")),
        command_fn=lambda m, v: {
            "SetMicrophoneGain": [dig(m, "mic_status", "mic_type"), int(round(v))]
        },
    ))
    full = is_full(m)
    eq_key, bands = ("equaliser", EQ_BANDS) if full else ("equaliser_mini", EQ_BANDS_MINI)
    gain_cmd, freq_cmd = ("SetEqGain", "SetEqFreq") if full else ("SetEqMiniGain", "SetEqMiniFreq")
    for band, (label, lo, hi) in bands.items():
        d.append(_n(
            f"eq_gain_{band}", f"EQ {label} gain", ("mic_status", eq_key, "gain", band),
            lambda m, v, b=band, c=gain_cmd: {c: [b, int(round(v))]},
            -9, 9, 1, DB, icon="mdi:tune-vertical-variant", config=True, enabled=False,
        ))
        d.append(_n(
            f"eq_freq_{band}", f"EQ {label} frequency", ("mic_status", eq_key, "frequency", band),
            lambda m, v, b=band, c=freq_cmd: {c: [b, float(v)]},
            lo, hi, 1, "Hz", icon="mdi:sine-wave", config=True, enabled=False,
            mode=NumberMode.BOX,
        ))
    G, C = ("mic_status", "noise_gate"), ("mic_status", "compressor")
    d += [
        _n("gate_threshold", "Noise gate threshold", (*G, "threshold"), "SetGateThreshold",
           -59, 0, 1, DB, icon="mdi:gate", config=True),
        _n("gate_attenuation", "Noise gate attenuation", (*G, "attenuation"),
           "SetGateAttenuation", 0, 100, 1, PERCENTAGE, icon="mdi:gate", config=True),
        _n("compressor_threshold", "Compressor threshold", (*C, "threshold"),
           "SetCompressorThreshold", -40, 0, 1, DB, icon="mdi:arrow-collapse-vertical",
           config=True),
        _n("compressor_makeup_gain", "Compressor makeup gain", (*C, "makeup_gain"),
           "SetCompressorMakeupGain", -6, 24, 1, DB, icon="mdi:arrow-collapse-vertical",
           config=True),
        _n("deesser", "De-esser", ("levels", "deess"), "SetDeeser", 0, 100, 1, PERCENTAGE,
           icon="mdi:waveform", config=True),
        _n("bleep_volume", "Bleep volume", ("levels", "bleep"), "SetSwearButtonVolume",
           -34, 0, 1, DB, icon="mdi:volume-mute", config=True),
    ]

    # Effects (full-size only; exists_fn = value present).
    R, EC, P, GE = (*E, "reverb"), (*E, "echo"), (*E, "pitch"), (*E, "gender")
    MG, RB, HT = (*E, "megaphone"), (*E, "robot"), (*E, "hard_tune")
    d += [
        _n("reverb_amount", "Reverb amount", (*R, "amount"), "SetReverbAmount", 0, 100, 1,
           PERCENTAGE, icon="mdi:waves"),
        _n("echo_amount", "Echo amount", (*EC, "amount"), "SetEchoAmount", 0, 100, 1,
           PERCENTAGE, icon="mdi:surround-sound"),
        _n("pitch_amount", "Pitch amount", (*P, "amount"), "SetPitchAmount", -24, 24, 1,
           icon="mdi:music-accidental-sharp", range_fn=_pitch_range),
        _n("gender_amount", "Gender amount", (*GE, "amount"), "SetGenderAmount", -50, 50, 1,
           icon="mdi:account-voice", range_fn=_gender_range),
        _n("megaphone_amount", "Megaphone amount", (*MG, "amount"), "SetMegaphoneAmount",
           0, 100, 1, PERCENTAGE, icon="mdi:bullhorn"),
        _n("hardtune_amount", "Hard tune amount", (*HT, "amount"), "SetHardTuneAmount",
           0, 100, 1, PERCENTAGE, icon="mdi:music-note"),
    ]
    fine: list[tuple] = [
        # key, name, path, command, lo, hi, step, unit, icon
        ("reverb_decay", "Reverb decay", (*R, "decay"), "SetReverbDecay", 10, 20000, 10, UnitOfTime.MILLISECONDS, "mdi:waves"),
        ("reverb_early_level", "Reverb early level", (*R, "early_level"), "SetReverbEarlyLevel", -25, 0, 1, DB, "mdi:waves"),
        ("reverb_tail_level", "Reverb tail level", (*R, "tail_level"), "SetReverbTailLevel", -25, 0, 1, DB, "mdi:waves"),
        ("reverb_pre_delay", "Reverb pre-delay", (*R, "pre_delay"), "SetReverbPreDelay", 0, 100, 1, UnitOfTime.MILLISECONDS, "mdi:waves"),
        ("reverb_low_colour", "Reverb low colour", (*R, "lo_colour"), "SetReverbLowColour", -50, 50, 1, None, "mdi:waves"),
        ("reverb_high_colour", "Reverb high colour", (*R, "hi_colour"), "SetReverbHighColour", -50, 50, 1, None, "mdi:waves"),
        ("reverb_high_factor", "Reverb high factor", (*R, "hi_factor"), "SetReverbHighFactor", -25, 25, 1, None, "mdi:waves"),
        ("reverb_diffuse", "Reverb diffuse", (*R, "diffuse"), "SetReverbDiffuse", -50, 50, 1, None, "mdi:waves"),
        ("reverb_mod_speed", "Reverb modulation speed", (*R, "mod_speed"), "SetReverbModSpeed", -25, 25, 1, None, "mdi:waves"),
        ("reverb_mod_depth", "Reverb modulation depth", (*R, "mod_depth"), "SetReverbModDepth", -25, 25, 1, None, "mdi:waves"),
        ("echo_feedback", "Echo feedback", (*EC, "feedback"), "SetEchoFeedback", 0, 100, 1, PERCENTAGE, "mdi:surround-sound"),
        ("echo_tempo", "Echo tempo", (*EC, "tempo"), "SetEchoTempo", 45, 300, 1, "BPM", "mdi:metronome"),
        ("echo_delay_left", "Echo delay left", (*EC, "delay_left"), "SetEchoDelayLeft", 0, 2500, 10, UnitOfTime.MILLISECONDS, "mdi:surround-sound"),
        ("echo_delay_right", "Echo delay right", (*EC, "delay_right"), "SetEchoDelayRight", 0, 2500, 10, UnitOfTime.MILLISECONDS, "mdi:surround-sound"),
        ("echo_feedback_left", "Echo feedback left", (*EC, "feedback_left"), "SetEchoFeedbackLeft", 0, 100, 1, PERCENTAGE, "mdi:surround-sound"),
        ("echo_feedback_right", "Echo feedback right", (*EC, "feedback_right"), "SetEchoFeedbackRight", 0, 100, 1, PERCENTAGE, "mdi:surround-sound"),
        ("echo_crossfeed_left_right", "Echo crossfeed left to right", (*EC, "feedback_xfb_l_to_r"), "SetEchoFeedbackXFBLtoR", 0, 100, 1, PERCENTAGE, "mdi:surround-sound"),
        ("echo_crossfeed_right_left", "Echo crossfeed right to left", (*EC, "feedback_xfb_r_to_l"), "SetEchoFeedbackXFBRtoL", 0, 100, 1, PERCENTAGE, "mdi:surround-sound"),
        ("pitch_character", "Pitch character", (*P, "character"), "SetPitchCharacter", 0, 100, 1, PERCENTAGE, "mdi:music-accidental-sharp"),
        ("megaphone_post_gain", "Megaphone post gain", (*MG, "post_gain"), "SetMegaphonePostGain", -20, 20, 1, DB, "mdi:bullhorn"),
        ("robot_waveform", "Robot waveform", (*RB, "waveform"), "SetRobotWaveform", 0, 3, 1, None, "mdi:robot"),
        ("robot_pulse_width", "Robot pulse width", (*RB, "pulse_width"), "SetRobotPulseWidth", 0, 100, 1, PERCENTAGE, "mdi:robot"),
        ("robot_threshold", "Robot threshold", (*RB, "threshold"), "SetRobotThreshold", -36, 0, 1, DB, "mdi:robot"),
        ("robot_dry_mix", "Robot dry mix", (*RB, "dry_mix"), "SetRobotDryMix", -36, 0, 1, DB, "mdi:robot"),
        ("hardtune_rate", "Hard tune rate", (*HT, "rate"), "SetHardTuneRate", 0, 100, 1, PERCENTAGE, "mdi:music-note"),
        ("hardtune_window", "Hard tune window", (*HT, "window"), "SetHardTuneWindow", 0, 600, 1, UnitOfTime.MILLISECONDS, "mdi:music-note"),
    ]
    for rng, label, frange in (("Low", "low", (0, 88)), ("Medium", "mid", (86, 184)), ("High", "high", (182, 240))):
        fine += [
            (f"robot_{label}_gain", f"Robot {label} gain", (*RB, f"{label}_gain"), lambda m, v, r=rng: {"SetRobotGain": [r, int(round(v))]}, -12, 12, 1, DB, "mdi:robot"),
            (f"robot_{label}_frequency", f"Robot {label} frequency", (*RB, f"{label}_freq"), lambda m, v, r=rng: {"SetRobotFreq": [r, int(round(v))]}, *frange, 1, None, "mdi:robot"),
            (f"robot_{label}_width", f"Robot {label} width", (*RB, f"{label}_width"), lambda m, v, r=rng: {"SetRobotWidth": [r, int(round(v))]}, 0, 32, 1, None, "mdi:robot"),
        ]
    for key, name, path, cmd, lo, hi, step, unit, icon in fine:
        d.append(_n(key, name, path, cmd, lo, hi, step, unit, icon=icon, config=True, enabled=False))

    # Sampler, buttons and lighting settings.
    anim = ("lighting", "animation")
    d += [
        _n("sampler_fade_duration", "Sampler fade-out duration", ("settings", "fade_duration"),
           "SetSamplerFadeDuration", 0, 20000, 100, UnitOfTime.MILLISECONDS,
           icon="mdi:timer-sand", config=True, exists=lambda m: m.get("sampler") is not None,
           mode=NumberMode.BOX),
        _n("sampler_pre_record", "Sampler pre-record buffer", ("sampler", "record_buffer"),
           "SetSamplerPreBufferDuration", 0, 30000, 100, UnitOfTime.MILLISECONDS,
           icon="mdi:record-rec", config=True, enabled=False, mode=NumberMode.BOX),
        _n("mute_hold_duration", "Mute-to-all hold duration", ("settings", "mute_hold_duration"),
           "SetMuteHoldDuration", 0, 5000, 50, UnitOfTime.MILLISECONDS, icon="mdi:timer-outline",
           config=True, mode=NumberMode.BOX),
        _n("animation_mod1", "Lighting gradient mod 1", (*anim, "mod1"), "SetAnimationMod1",
           0, 100, 1, PERCENTAGE, icon="mdi:gradient-horizontal", config=True, enabled=False,
           exists=lambda m: bool(dig(m, *anim, "supported")),
           available=lambda m: dig(m, *anim, "mode") not in (None, "None")),
        _n("animation_mod2", "Lighting gradient mod 2", (*anim, "mod2"), "SetAnimationMod2",
           0, 100, 1, PERCENTAGE, icon="mdi:gradient-horizontal", config=True, enabled=False,
           exists=lambda m: bool(dig(m, *anim, "supported")),
           available=lambda m: dig(m, *anim, "mode") in ("RainbowBright", "RainbowDark")),
    ]
    return d


async def async_setup_entry(
    hass: HomeAssistant, entry: GoXLRConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    def build(client: GoXLRClient, serial: str, mixer: Mixer) -> list[Entity]:
        ents: list[Entity] = [
            GoXLRNumber(client, serial, desc)
            for desc in _mixer_numbers(mixer)
            if (desc.exists_fn(mixer) if desc.exists_fn else desc.value_fn(mixer) is not None)
        ]
        ents.append(SpeakingThresholdNumber(client, serial, get_monitor(hass, entry, serial)))
        return ents

    add_mixer_entities(entry, build, async_add_entities)


class GoXLRNumber(GoXLREntity, NumberEntity):
    entity_description: GXNumberDescription

    def __init__(self, client: GoXLRClient, serial: str, desc: GXNumberDescription) -> None:
        super().__init__(client, serial, desc.key, description=desc)

    def _range(self) -> tuple[float, float, float] | None:
        fn = self.entity_description.range_fn
        return fn(self.mixer) if fn else None

    @property
    def native_min_value(self) -> float:
        r = self._range()
        return r[0] if r else self.entity_description.native_min_value

    @property
    def native_max_value(self) -> float:
        r = self._range()
        return r[1] if r else self.entity_description.native_max_value

    @property
    def native_step(self) -> float | None:
        r = self._range()
        return r[2] if r else self.entity_description.native_step

    @property
    def native_value(self) -> float | None:
        return self.entity_description.value_fn(self.mixer)

    async def async_set_native_value(self, value: float) -> None:
        await self._send(self.entity_description.command_fn(self.mixer, value))


class SpeakingThresholdNumber(GoXLREntity, NumberEntity):
    """Level above which the "Speaking" sensor turns on (stored in HA)."""

    _attr_entity_category = CONFIG
    _attr_icon = "mdi:account-voice"
    _attr_native_min_value = MIC_LEVEL_MIN
    _attr_native_max_value = 0
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "dBFS"
    _attr_mode = NumberMode.SLIDER

    def __init__(self, client: GoXLRClient, serial: str, monitor: Any) -> None:
        super().__init__(client, serial, "speaking_threshold", "Speaking threshold")
        self._monitor = monitor

    @property
    def available(self) -> bool:
        return True  # a local setting; editable even while disconnected

    @property
    def native_value(self) -> float:
        return self._monitor.threshold

    async def async_set_native_value(self, value: float) -> None:
        self._monitor.set_threshold(value)
        self.async_write_ha_state()
