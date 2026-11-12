"""A realistic full-size GoXLR status, shaped like the Utility's DaemonStatus."""

import copy

SERIAL = "S220202153DI7"

_CH = ["Mic", "LineIn", "Console", "System", "Game", "Chat", "Sample", "Music", "Headphones", "MicMonitor", "LineOut"]
_IN = ["Microphone", "Chat", "Music", "Game", "Console", "LineIn", "System", "Samples"]
_OUT = ["Headphones", "BroadcastMix", "ChatMic", "Sampler", "LineOut", "StreamMix2"]
_BUTTONS = (
    ["Fader1Mute", "Fader2Mute", "Fader3Mute", "Fader4Mute", "Bleep", "Cough"]
    + [f"EffectSelect{i}" for i in range(1, 7)]
    + ["EffectFx", "EffectMegaphone", "EffectRobot", "EffectHardTune",
       "SamplerSelectA", "SamplerSelectB", "SamplerSelectC",
       "SamplerTopLeft", "SamplerTopRight", "SamplerBottomLeft", "SamplerBottomRight", "SamplerClear"]
)
_EQ = ["Equalizer31Hz", "Equalizer63Hz", "Equalizer125Hz", "Equalizer250Hz", "Equalizer500Hz",
       "Equalizer1KHz", "Equalizer2KHz", "Equalizer4KHz", "Equalizer8KHz", "Equalizer16KHz"]
_EQM = ["Equalizer90Hz", "Equalizer250Hz", "Equalizer500Hz", "Equalizer1KHz", "Equalizer3KHz", "Equalizer8KHz"]
_PADS = ["TopLeft", "TopRight", "BottomLeft", "BottomRight"]


def _pad(samples):
    return {"function": "PlayNext", "order": "Sequential", "is_playing": False, "is_recording": False,
            "samples": [{"name": s, "start_pct": 0.0, "stop_pct": 100.0} for s in samples]}


MIXER = {
    "hardware": {
        "versions": {"firmware": [1, 3, 40, 0], "fpga_count": 1, "dice": [1, 0, 0, 0]},
        "serial_number": SERIAL, "manufactured_date": "2022-02-02", "device_type": "Full",
        "colour_way": "Black", "usb_device": {},
    },
    "fader_status": {
        f: {"channel": ch, "mute_type": "All", "mute_state": "Unmuted",
            "scribble": {"file_name": None, "bottom_text": f"Fader {f}", "left_text": None, "inverted": False}}
        for f, ch in zip("ABCD", ["Mic", "Music", "Chat", "System"])
    },
    "mic_status": {
        "mic_type": "Dynamic",
        "mic_gains": {"Dynamic": 40, "Condenser": 30, "Jack": 20},
        "equaliser": {"gain": {b: 0 for b in _EQ}, "frequency": {b: 100.0 for b in _EQ}},
        "equaliser_mini": {"gain": {b: 0 for b in _EQM}, "frequency": {b: 100.0 for b in _EQM}},
        "noise_gate": {"threshold": -30, "attack": "Gate10ms", "release": "Gate200ms", "enabled": True, "attenuation": 100},
        "compressor": {"threshold": -20, "ratio": "Ratio3_2", "attack": "Comp2ms", "release": "Comp100ms", "makeup_gain": 5},
    },
    "levels": {
        "submix_supported": True, "output_monitor": "Headphones",
        "volumes": {c: 255 if c == "Mic" else 128 for c in _CH},
        "submix": None, "bleep": -20, "deess": 30,
    },
    "router": {i: {o: o == "BroadcastMix" for o in _OUT} for i in _IN},
    "cough_button": {"is_toggle": True, "mute_type": "All", "state": "Unmuted"},
    "lighting": {
        "animation": {"supported": True, "mode": "None", "mod1": 50, "mod2": 50, "waterfall_direction": "Off"},
        "faders": {f: {"style": "Gradient", "colours": {"colour_one": "00FFFF", "colour_two": "FF00FF"}} for f in "ABCD"},
        "buttons": {b: {"off_style": "Dimmed", "colours": {"colour_one": "00FFFF", "colour_two": "000000"}} for b in _BUTTONS},
        "simple": {t: {"colour_one": "00FFFF"} for t in ["Global", "Accent", "Scribble1", "Scribble2", "Scribble3", "Scribble4"]},
        "sampler": {}, "encoders": {},
    },
    "effects": {
        "is_enabled": True, "active_preset": "Preset1",
        "preset_names": {f"Preset{i}": n for i, n in enumerate(["Clean", "Deep", "Robot", "Radio", "Chipmunk", "Hall"], 1)},
        "current": {
            "reverb": {"style": "Library", "amount": 50, "decay": 1000, "early_level": -5, "tail_level": -5, "pre_delay": 10,
                       "lo_colour": 0, "hi_colour": 0, "hi_factor": 0, "diffuse": 0, "mod_speed": 0, "mod_depth": 0, "raw_encoder": 0},
            "echo": {"style": "Quarter", "amount": 20, "feedback": 30, "tempo": 120, "delay_left": 100, "delay_right": 100,
                     "feedback_left": 30, "feedback_right": 30, "feedback_xfb_l_to_r": 0, "feedback_xfb_r_to_l": 0, "raw_encoder": 0},
            "pitch": {"style": "Wide", "amount": 0, "character": 50, "raw_encoder": 0},
            "gender": {"style": "Medium", "amount": 0, "raw_encoder": 0},
            "megaphone": {"is_enabled": False, "style": "Megaphone", "amount": 50, "post_gain": 0},
            "robot": {"is_enabled": False, "style": "Robot1", "low_gain": 0, "low_freq": 40, "low_width": 10, "mid_gain": 0,
                      "mid_freq": 100, "mid_width": 10, "high_gain": 0, "high_freq": 200, "high_width": 10,
                      "waveform": 0, "pulse_width": 50, "threshold": -20, "dry_mix": -10},
            "hard_tune": {"is_enabled": False, "style": "Natural", "amount": 50, "rate": 50, "window": 100, "source": "All"},
        },
    },
    "sampler": {
        "processing_state": {"progress": None, "last_error": None},
        "active_bank": "A", "clear_active": False, "record_buffer": 0,
        "banks": {b: {p: _pad(["intro.wav"] if (b, p) == ("A", "TopLeft") else []) for p in _PADS} for b in "ABC"},
    },
    "settings": {
        "display": {"gate": "Simple", "compressor": "Simple", "equaliser": "Simple", "equaliser_fine": "Simple"},
        "mute_hold_duration": 500, "vc_mute_also_mute_cm": False, "enable_monitor_with_fx": False,
        "reset_sampler_on_clear": True, "lock_faders": False, "fade_duration": 1000, "vod_mode": "Routable",
    },
    "button_down": {b: False for b in _BUTTONS},
    "profile_name": "Default",
    "mic_profile_name": "DEFAULT",
}

STATUS = {
    "config": {
        "http_settings": {"enabled": True, "bind_address": "0.0.0.0", "cors_enabled": False, "port": 14564},
        "daemon_version": "1.2.3", "autostart_enabled": True, "show_tray_icon": True, "tts_enabled": False,
        "allow_network_access": True, "log_level": "Info", "open_ui_on_launch": False, "platform": "windows",
        "latest_firmware": {"Full": {"version": [1, 5, 0, 22], "change_log": "Bug fixes"}, "Mini": None, "Unknown": None},
    },
    "firmware": {},
    "mixers": {SERIAL: MIXER},
    "paths": {},
    "files": {"profiles": ["Default", "Streaming"], "mic_profiles": ["DEFAULT"], "presets": ["Deep", "Hall"],
              "samples": {}, "icons": ["mic.png"]},
}


def status():
    return copy.deepcopy(STATUS)
