# GoXLR Control for Home Assistant

Local-push control of a TC-Helicon GoXLR / GoXLR Mini through the
[GoXLR Utility](https://github.com/GoXLR-on-Linux/goxlr-utility) (Windows & Linux).
It doesn't need any Python libraries beyond what Home Assistant already ships, and it uses no polling.

## Why this one doesn't lose control after a few days

| Problem | What this integration does |
|---|---|
| Websocket silently dies (PC sleeps, Wi-Fi blip, router drops idle TCP) and the client never notices | WS ping/pong heartbeat every 20 s **and** an app-level watchdog: no traffic for 60 s means the connection is torn down and rebuilt |
| Daemon restarts / PC reboots | Supervisor loop reconnects **forever** with capped backoff (1 s up to 30 s). Setup never fails because the PC is off. |
| The Utility drops state updates for clients that fall behind, so the state drifts | Full resync on every reconnect, whenever a patch can't be applied, and every 5 minutes |
| Commands fail while the push channel is reconnecting | Commands use plain HTTP, independent of the websocket |
| GoXLR unplugged / plugged in later | Entities go unavailable and come back; newly connected mixers get their entities created on the fly |

There's also a **Connection** binary sensor that stays available. Use it to alert on outages.

## Auto reconnect toggle

If your PC's power is cut when it's off, you may not want Home Assistant to keep retrying.
Turn off `switch.goxlr_utility_auto_reconnect`:

- **Off:** stays connected while the PC is on. Once the connection drops, it stops retrying.
- **On:** retries until it reconnects. Switching it on triggers an immediate attempt.
- The setting is remembered across restarts. With it off, Home Assistant still makes **one**
  attempt at startup, so it connects if the PC is already on.

Example: link it to the smart plug that powers the PC.

```yaml
automation:
  - alias: GoXLR follows PC power
    triggers:
      - trigger: state
        entity_id: switch.pc_power_plug
        to: ["on", "off"]
    actions:
      - action: "switch.turn_{{ trigger.to_state.state }}"
        target:
          entity_id: switch.goxlr_utility_auto_reconnect
```

## Requirements

1. GoXLR Utility running on the PC.
2. **Network access enabled** in the Utility. Turn on *Allow Network Access* in the
   Utility's settings and restart the Utility. Otherwise it only listens on `localhost`.
   You can also enable it from the PC itself:
   ```sh
   curl -X POST -H 'Content-Type: application/json' \
     -d '{"Daemon":{"SetAllowNetworkAccess":true}}' http://localhost:14564/api/command
   ```
3. Port 14564/TCP allowed through the PC's firewall.
4. Recommended: give the PC a DHCP reservation (static IP). If its IP changes, use
   **Settings → Devices & services → GoXLR Control → ⋮ → Reconfigure**.

## Install (HACS)

1. Push this folder to a GitHub repo and update the URLs in `custom_components/goxlr_control/manifest.json`.
2. HACS → ⋮ → *Custom repositories* → add the repo URL, category *Integration*.
3. Install **GoXLR Control** and restart Home Assistant.
4. *Settings → Devices & services → Add integration → GoXLR Control*. Enter the PC's IP, port `14564`.

Manual install: copy `custom_components/goxlr_control` into your HA `config/custom_components/`.

## Entities (per mixer)

| Entity | Notes |
|---|---|
| `number.*_volume` | Every channel, 0–100 % |
| `switch.*_fader_X_mute` | Fader A–D mute (attribute `channel` shows what's on the fader) |
| `switch.*_mic_mute` | Cough/mute button |
| `switch.*_effects`, `_megaphone`, `_robot`, `_hard_tune` | Full-size GoXLR only |
| `select.*_profile`, `select.*_mic_profile` | Load profiles |
| `select.*_effect_preset` | Full-size GoXLR only |
| `select.*_fader_X_channel` | Assign channels to faders |
| `switch.*_route_<in>_to_<out>` | Routing matrix (**disabled by default**; enable the ones you need) |

On the **GoXLR Utility** hub device (always present):

| Entity | Notes |
|---|---|
| `switch.goxlr_utility_auto_reconnect` | Retry on/off (see above) |
| `binary_sensor.goxlr_utility_connection` | Connected to the Utility |

## Development

```sh
pip install pytest-homeassistant-custom-component
pytest
```
The tests run the integration inside a real Home Assistant instance against a fake GoXLR
daemon. They cover the config flow, all entity types, command round-trips, and an outage
followed by recovery.
