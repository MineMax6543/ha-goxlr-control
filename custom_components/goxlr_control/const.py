"""Constants for GoXLR Control."""

DOMAIN = "goxlr_control"
DEFAULT_PORT = 14564

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

CHANNELS = (
    "Mic", "LineIn", "Console", "System", "Game", "Chat",
    "Sample", "Music", "Headphones", "MicMonitor", "LineOut",
)
CHANNEL_NAMES = {
    "Mic": "Mic", "LineIn": "Line in", "Console": "Console", "System": "System",
    "Game": "Game", "Chat": "Chat", "Sample": "Sample", "Music": "Music",
    "Headphones": "Headphones", "MicMonitor": "Mic monitor", "LineOut": "Line out",
}
FADERS = ("A", "B", "C", "D")

CONF_AUTO_RECONNECT = "auto_reconnect"
