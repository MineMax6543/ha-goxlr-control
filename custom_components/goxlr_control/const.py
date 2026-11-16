"""Constants for GoXLR Control Plus.

Every option list and range here comes from the GoXLR Utility source
(goxlr-types / profile crates), so values sent are always accepted.
"""

DOMAIN = "goxlr_control"
DEFAULT_PORT = 14564

# --- connection tuning --------------------------------------------------------
# Websocket protocol-level heartbeat (the daemon answers WS pings with pongs).
HEARTBEAT_SECONDS = 20
# If nothing at all (including pongs/app replies) arrives for this long, the
# connection is considered dead and torn down, even if TCP still looks open.
STALE_SECONDS = 60
# Full state resync interval. The daemon silently drops patches for clients
# that lag behind, so a periodic resync guarantees we never drift for long.
RESYNC_SECONDS = 300
# Reconnect backoff bounds.
BACKOFF_MIN = 1
BACKOFF_MAX = 30
# Coalesce bursts of patches (e.g. turning a knob) into one state write.
NOTIFY_DELAY = 0.05
REQUEST_TIMEOUT = 10

# --- options stored on the config entry ---------------------------------------
CONF_AUTO_RECONNECT = "auto_reconnect"
# Per mixer: f"{CONF_MIC_MONITOR}_{serial}" / f"{CONF_SPEAKING_THRESHOLD}_{serial}"
CONF_MIC_MONITOR = "mic_level_monitoring"
CONF_SPEAKING_THRESHOLD = "speaking_threshold"

# --- mic level monitoring -----------------------------------------------------
MIC_POLL_INTERVAL = 0.25  # seconds between level reads while monitoring is on
MIC_SENSOR_MIN_INTERVAL = 1.0  # level sensor publishes at most once per second
MIC_SPEAKING_RELEASE = 1.0  # "Speaking" stays on this long after you go quiet
MIC_LEVEL_MIN = -72.2  # dBFS floor reported by the daemon
DEFAULT_SPEAKING_THRESHOLD = -40

# --- physical buttons -----------------------------------------------------------
DEFAULT_LONG_PRESS_MS = 500  # fallback when the mixer has no mute hold duration
EVENT_PRESSED = "pressed"
EVENT_RELEASED = "released"
EVENT_SHORT_PRESS = "short_press"
EVENT_LONG_PRESS = "long_press"

# --- labels -----------------------------------------------------------------------
CHANNELS = (
    "Mic", "LineIn", "Console", "System", "Game", "Chat",
    "Sample", "Music", "Headphones", "MicMonitor", "LineOut",
)
CHANNEL_NAMES = {
    "Mic": "Mic", "LineIn": "Line in", "Console": "Console", "System": "System",
    "Game": "Game", "Chat": "Chat", "Sample": "Sample", "Music": "Music",
    "Headphones": "Headphones", "MicMonitor": "Mic monitor", "LineOut": "Line out",
}
SUBMIX_CHANNELS = ("Mic", "LineIn", "Console", "System", "Game", "Chat", "Sample", "Music")
FADERS = ("A", "B", "C", "D")

INPUT_NAMES = {
    "Microphone": "Mic", "Chat": "Chat", "Music": "Music", "Game": "Game",
    "Console": "Console", "LineIn": "Line in", "System": "System", "Samples": "Samples",
}
OUTPUT_NAMES = {
    "Headphones": "Headphones", "BroadcastMix": "Stream mix", "ChatMic": "Chat mic",
    "Sampler": "Sampler", "LineOut": "Line out", "StreamMix2": "Stream mix 2",
}
MUTE_FUNCTION_NAMES = {
    "All": "Everything", "ToStream": "Stream", "ToVoiceChat": "Voice chat",
    "ToPhones": "Headphones", "ToLineOut": "Line out", "ToStream2": "Stream mix 2",
    "ToStreams": "Both stream mixes",
}
MIC_TYPE_NAMES = {
    "Dynamic": "Dynamic (XLR)",
    "Condenser": "Condenser (XLR, +48 V phantom power)",
    "Jack": "3.5 mm jack",
}
GATE_TIMES = (
    10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120, 130, 140, 150, 160, 170, 180,
    190, 200, 250, 300, 350, 400, 450, 500, 550, 600, 650, 700, 750, 800, 850, 900,
    950, 1000, 1100, 1200, 1300, 1400, 1500, 1600, 1700, 1800, 1900, 2000,
)
GATE_TIME_NAMES = {f"Gate{t}ms": f"{t} ms" for t in GATE_TIMES}
COMP_RATIOS = (
    "1_0", "1_1", "1_2", "1_4", "1_6", "1_8", "2_0", "2_5", "3_2", "4_0",
    "5_6", "8_0", "16_0", "32_0", "64_0",
)
COMP_RATIO_NAMES = {f"Ratio{r}": f"{r.replace('_', '.')}:1" for r in COMP_RATIOS}
COMP_ATTACK_NAMES = {
    f"Comp{t}ms": f"{t} ms"
    for t in (0, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14, 16, 18, 20, 23, 26, 30, 35, 40)
}
COMP_RELEASE_NAMES = {
    f"Comp{t}ms": f"{t} ms"
    for t in (0, 15, 25, 35, 45, 55, 65, 75, 85, 100, 115, 140, 170, 230, 340, 680,
              1000, 1500, 2000, 3000)
}
# EQ bands -> (label, min Hz, max Hz). Neighbouring bands may not cross; the
# daemon rejects that with a clear error.
EQ_BANDS = {
    "Equalizer31Hz": ("31 Hz", 30, 300), "Equalizer63Hz": ("63 Hz", 30, 300),
    "Equalizer125Hz": ("125 Hz", 30, 300), "Equalizer250Hz": ("250 Hz", 30, 300),
    "Equalizer500Hz": ("500 Hz", 300, 2000), "Equalizer1KHz": ("1 kHz", 300, 2000),
    "Equalizer2KHz": ("2 kHz", 300, 2000), "Equalizer4KHz": ("4 kHz", 2000, 18000),
    "Equalizer8KHz": ("8 kHz", 2000, 18000), "Equalizer16KHz": ("16 kHz", 2000, 18000),
}
EQ_BANDS_MINI = {
    "Equalizer90Hz": ("90 Hz", 30, 90), "Equalizer250Hz": ("250 Hz", 100, 300),
    "Equalizer500Hz": ("500 Hz", 310, 800), "Equalizer1KHz": ("1 kHz", 800, 2500),
    "Equalizer3KHz": ("3 kHz", 2600, 5000), "Equalizer8KHz": ("8 kHz", 5100, 18000),
}
EFFECT_PRESETS = tuple(f"Preset{i}" for i in range(1, 7))
REVERB_STYLES = {
    "Library": "Library", "DarkBloom": "Dark bloom", "MusicClub": "Music club",
    "RealPlate": "Real plate", "Chapel": "Chapel", "HockeyArena": "Hockey arena",
}
ECHO_STYLES = {
    "Quarter": "Quarter", "Eighth": "Eighth", "Triplet": "Triplet",
    "PingPong": "Ping pong", "ClassicSlap": "Classic slap", "MultiTap": "Multi tap",
}
PITCH_STYLES = {"Narrow": "Narrow", "Wide": "Wide"}
GENDER_STYLES = {"Narrow": "Narrow", "Medium": "Medium", "Wide": "Wide"}
GENDER_RANGES = {"Narrow": 12, "Medium": 25, "Wide": 50}
MEGAPHONE_STYLES = {
    "Megaphone": "Megaphone", "Radio": "Radio", "OnThePhone": "On the phone",
    "Overdrive": "Overdrive", "BuzzCutt": "Buzz cutt", "Tweed": "Tweed",
}
ROBOT_STYLES = {"Robot1": "Robot 1", "Robot2": "Robot 2", "Robot3": "Robot 3"}
HARDTUNE_STYLES = {"Natural": "Natural", "Medium": "Medium", "Hard": "Hard"}
HARDTUNE_SOURCES = {
    "All": "All", "Music": "Music", "Game": "Game", "LineIn": "Line in", "System": "System",
}
SAMPLE_BANKS = ("A", "B", "C")
SAMPLE_PADS = {
    "TopLeft": "Top left", "TopRight": "Top right",
    "BottomLeft": "Bottom left", "BottomRight": "Bottom right",
}
SAMPLE_PLAYBACK_MODES = {
    "PlayNext": "Play next", "PlayStop": "Play / stop", "PlayFade": "Play / fade out",
    "StopOnRelease": "Stop on release", "FadeOnRelease": "Fade out on release",
    "Loop": "Loop",
}
SAMPLE_PLAY_ORDERS = {"Sequential": "Sequential", "Random": "Random"}
ANIMATION_MODES = {
    "None": "None", "RetroRainbow": "Rainbow retro", "RainbowBright": "Rainbow bright",
    "RainbowDark": "Rainbow dark", "Simple": "Simple", "Ripple": "Ripple",
}
WATERFALL_DIRECTIONS = {"Down": "Down", "Up": "Up", "Off": "Off"}
FADER_DISPLAY_STYLES = {
    "TwoColour": "Two colour", "Gradient": "Gradient",
    "Meter": "Meter", "GradientMeter": "Gradient meter",
}
VOD_MODES = {"Routable": "Routable", "StreamNoMusic": "Stream without music"}
LOG_LEVELS = {
    "Off": "Off", "Error": "Error", "Warn": "Warning", "Info": "Info",
    "Debug": "Debug", "Trace": "Trace",
}

# Physical buttons -> friendly name. The Mini only has the first six.
BUTTONS_MINI = {
    "Fader1Mute": "Fader A mute button", "Fader2Mute": "Fader B mute button",
    "Fader3Mute": "Fader C mute button", "Fader4Mute": "Fader D mute button",
    "Bleep": "Bleep button", "Cough": "Mic mute button",
}
BUTTONS_FULL = {
    **BUTTONS_MINI,
    **{f"EffectSelect{i}": f"Effect preset {i} button" for i in range(1, 7)},
    "EffectFx": "Effects button", "EffectMegaphone": "Megaphone button",
    "EffectRobot": "Robot button", "EffectHardTune": "Hard tune button",
    "SamplerSelectA": "Sampler bank A button", "SamplerSelectB": "Sampler bank B button",
    "SamplerSelectC": "Sampler bank C button",
    "SamplerTopLeft": "Sampler top left button", "SamplerTopRight": "Sampler top right button",
    "SamplerBottomLeft": "Sampler bottom left button",
    "SamplerBottomRight": "Sampler bottom right button",
    "SamplerClear": "Sampler clear button",
}
