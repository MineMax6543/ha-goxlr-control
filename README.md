# GoXLR Control for Home Assistant

Local-push control of a TC-Helicon GoXLR / GoXLR Mini through the
[GoXLR Utility](https://github.com/GoXLR-on-Linux/goxlr-utility) on Windows or Linux.
It covers everything the Utility exposes: mixing, routing, mic processing, effects,
the sampler, lighting, the fader screens, profiles, physical button presses and the
Utility's own settings.

It doesn't need any Python libraries beyond what Home Assistant already ships, and it uses
no polling. The one exception is the opt-in mic level monitoring described below.

## Why this one doesn't lose control after a few days

| Problem | What this integration does |
|---|---|
| The websocket silently dies (PC sleeps, Wi-Fi blip, router drops idle TCP) and the client never notices | WS ping/pong heartbeat every 20 s **and** an app-level watchdog: no traffic for 60 s means the connection is torn down and rebuilt |
| The daemon restarts or the PC reboots | A supervisor loop reconnects with capped backoff (1 s up to 30 s). Setup never fails because the PC is off. |
| The Utility drops state updates for clients that fall behind, so the state drifts | Full resync on every reconnect, whenever a patch can't be applied, and every 5 minutes |
| Commands fail while the push channel is reconnecting | Commands use plain HTTP, independent of the websocket |
| The GoXLR is unplugged or plugged in later | Entities go unavailable and come back; newly connected mixers get their entities created on the fly |

It also stays light with ~300 entities: an entity writes its state only when *its own*
value changed, so turning one knob doesn't rewrite every entity.

## Requirements

1. GoXLR Utility running on the PC.
2. **Network access enabled** in the Utility. Turn on *Allow Network Access* in the Utility
   settings and restart the Utility. Otherwise it only listens on `localhost`. You can also
   enable it from the PC itself:
   ```sh
   curl -X POST -H 'Content-Type: application/json' \
     -d '{"Daemon":{"SetAllowNetworkAccess":true}}' http://localhost:14564/api/command
   ```
3. Port 14564/TCP allowed through the PC's firewall.
4. Recommended: give the PC a DHCP reservation (static IP). If its IP changes, use
   **Settings → Devices & services → GoXLR Control → ⋮ → Reconfigure**.

## Install (HACS)

1. HACS → ⋮ → *Custom repositories* → add `https://github.com/MineMax6543/ha-goxlr-control`,
   category *Integration*.
2. Install **GoXLR Control** and restart Home Assistant.
3. *Settings → Devices & services → Add integration → GoXLR Control*. Enter the PC's IP, port `14564`.

Manual install: copy `custom_components/goxlr_control` into your HA `config/custom_components/`.

## Devices

You get two devices:

- **GoXLR Utility** (hub): the app on your PC. It always exists, even while the PC is off.
- **GoXLR** / **GoXLR Mini**: the mixer, linked to the hub.

Controls that only exist on the full-size GoXLR (effects, sampler, fader screens) aren't
created for a Mini.

Advanced controls are **disabled by default** to keep things tidy (marked *off* below).
To enable them, open the device page, click *+N entities not shown*, and enable the ones you want.

## Entities

### Mixing
| Entity | Notes |
|---|---|
| *Channel* volume | Mic, Line in, Console, System, Game, Chat, Sample, Music, Headphones, Mic monitor, Line out (0–100 %) |
| Fader A–D mute | Mutes to the fader's mute target. Attributes show the channel, target and whether it's muted to all. |
| Mic mute | The mute (cough) button. Needs *Mic mute button mode* = Toggle (you get a clear error otherwise). |
| Fader A–D channel | Which channel each fader controls |
| Fader A–D mute target | Everything / Stream / Voice chat / Headphones / Line out (+ stream mix 2 options when supported) |
| Headphone mix | Which mix you hear in your headphones (devices with submix support) |
| Mix B (submix) | Turn the second mix on/off |
| *Channel* volume (mix B), *Channel* mix B linked, *Output* source mix | Submix details (*off*) |
| Route *input* to *output* | The full routing matrix (*off*). Invalid routes are left out. |
| Lock faders when muted to all | |

### Microphone
| Entity | Notes |
|---|---|
| Mic type | Dynamic (XLR) / Condenser (XLR, +48 V phantom power) / 3.5 mm jack |
| Mic gain | 0–72 dB for the active mic type |
| Noise gate, Noise gate threshold / attenuation | Attack and release are *off* |
| Compressor threshold / ratio / makeup gain | Attack and release are *off* |
| De-esser, Bleep volume | |
| EQ *band* gain / frequency | 10 bands (full) or 6 bands (Mini) (*off*). Neighbouring bands can't cross. |
| Mic mute button mode / target, Mute-to-all hold duration | |
| Voice chat mute-to-all also mutes chat mic | |
| Profile, Mic profile, Save profile, Save mic profile | |

### Mic level monitoring (opt-in)
The Utility only reports the mic level when asked, so this is **off by default**. Turn on
**Mic level monitoring** to enable:

- **Speaking** (binary sensor): turns on as soon as you go above the **Speaking threshold**
  (default −40 dBFS) and stays on for 1 s after you go quiet, so it doesn't flicker between
  words. Use it for an "on air" light.
- **Mic level** (sensor, dBFS, *off*): rounded to whole dB and updated at most once a second.
  It changes constantly while you talk, so if you enable it, consider excluding it from the
  recorder.

While monitoring is on, the level is read 4 times a second over the existing websocket.
When it's off, nothing is polled.

### Effects (full-size only)
| Entity | Notes |
|---|---|
| Effects, Megaphone, Robot, Hard tune | On/off |
| Effect preset | Slots 1–6, shown with their names |
| Reverb / Echo / Pitch / Gender / Megaphone / Hard tune amount | Pitch and gender limits follow the selected style. With Hard tune on, pitch snaps to octaves. |
| Reverb / Echo / Pitch / Gender / Megaphone / Robot / Hard tune style, Hard tune source | |
| Mic monitoring follows effects | |
| Save effect preset to library, Load library preset into active slot, Effect preset name | Loading replaces unsaved changes in the active slot |
| Reverb decay, echo tempo, robot bands … | All fine-tuning parameters (*off*) |

### Sampler (full-size only)
| Entity | Notes |
|---|---|
| Sampler bank | A / B / C |
| Play / Stop *pad* sample | Acts on the active bank. Play is unavailable on empty pads. |
| Sampler *pad* playing | With the pad's sample names as an attribute |
| Sampler fade-out duration | |
| Per bank and pad playback mode / order, pre-record buffer, clear behaviour | (*off*) |

### Lighting and screens
| Entity | Notes |
|---|---|
| Lighting (light) | Set a colour or brightness to colour the whole device. Off turns all LEDs black. On restores the previous colour, or your profile's colour scheme if it had several colours. |
| Restore profile lighting | Reloads the profile's colours |
| Lighting animation | Rainbow retro / bright / dark, Simple, Ripple (Ripple isn't available on the Mini) |
| Lighting waterfall, gradient mod 1 / 2, Fader *X* light style | (*off*). These show as unavailable when the current animation mode doesn't use them. |
| Fader A–D screen text | The small fader screens (full-size only) |
| Fader A–D screen number / icon / inverted | (*off*) |

### Physical buttons → automations
Every button on the device is an **event** entity (fader mutes, bleep, mic mute, effect
buttons, sampler pads, sampler bank and clear buttons). Each one fires:

- `pressed` when the button goes down
- `long_press` while it's still held, after the mute hold duration (500 ms by default)
- `short_press` on release, if it wasn't a long press
- `released` on every release

```yaml
automation:
  - alias: Sampler clear button toggles desk lamp
    triggers:
      - trigger: state
        entity_id: event.goxlr_sampler_clear_button
        attribute: event_type
        to: short_press
    actions:
      - action: light.toggle
        target:
          entity_id: light.desk_lamp
```

The physical buttons still do their normal job on the GoXLR. These events let Home Assistant
react as well.

### Firmware
**Firmware** (update entity) shows when the Utility knows of newer firmware. Installing is
deliberately left to the Utility: an interrupted firmware flash can brick the mixer, so
someone should be at the PC when it runs.

### GoXLR Utility (hub device)
| Entity | Notes |
|---|---|
| Connection | Stays available, so you can alert on outages |
| Auto reconnect | See below |
| Open Utility window | Opens the UI on the PC |
| Start on login, Show tray icon, Speak button presses | Utility settings |
| Open window on launch, Log level | (*off*) |
| Utility version | Diagnostic |

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

## Raw commands: everything else

Two actions can send **any** Utility command, for the few things that don't make sense as
entities (sample file management, per-button colours, creating or deleting profiles, …).
Command names and arguments match the
[GoXLR Utility API](https://github.com/GoXLR-on-Linux/goxlr-utility/blob/main/ipc/src/lib.rs).

```yaml
# Colour fader A red/black
action: goxlr_control.send_command
data:
  device_id: <your GoXLR device>
  command: {"SetFaderColours": ["A", "FF0000", "000000"]}

# Other examples:
#   {"SetButtonColours": ["Cough", "FF0000", null]}
#   {"SaveProfileAs": "Streaming backup"}
#   {"SetSampleStartPercent": ["A", "TopLeft", 0, 12.5]}
#   {"SetElementDisplayMode": ["Equaliser", "Advanced"]}

# Utility-level command
action: goxlr_control.send_utility_command
data:
  command: {"SetSampleGainPct": ["intro.wav", 80]}
```

Both actions return the Utility's response when called with `response_variable`.

### Intentionally not exposed as entities
| Command | Why |
|---|---|
| Allow network access | Turning it off would cut Home Assistant off from the Utility |
| Stop Utility | It can't be started again remotely |
| Firmware update | An interrupted flash can brick the mixer (see Firmware above) |
| Delete profile / mic profile, recover defaults | Destructive. Available through `send_command` if you really need them. |
| Shutdown / sleep / wake command lists, UI display modes, language, activator path | Utility UI configuration with no use in automations |

## Development

```sh
pip install pytest-homeassistant-custom-component
pytest
```
The tests run the integration inside a real Home Assistant instance against a fake GoXLR daemon.
They cover the config flow, every entity loading, command round-trips, mic monitoring, button
events, lighting, the GoXLR Mini, an outage with recovery, and the auto-reconnect toggle.
