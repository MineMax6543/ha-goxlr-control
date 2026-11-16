"""End-to-end tests against a fake GoXLR Utility daemon."""

import asyncio
import json

from aiohttp import web
import pytest

from homeassistant import config_entries
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event

from custom_components.goxlr_control import client as client_mod, mic_monitor
from custom_components.goxlr_control.advanced import ADVANCED_GROUPS, group_for_key
from custom_components.goxlr_control.const import DOMAIN

from .fixtures import SERIAL, status


class FakeDaemon:
    def __init__(self):
        self.status = status()
        self.sockets: list[web.WebSocketResponse] = []
        self.commands: list = []
        self.up = True
        self.mic_level = -60.0

    @property
    def mixer(self):
        return self.status["mixers"][SERIAL]

    async def ws(self, request):
        if not self.up:
            raise web.HTTPServiceUnavailable()
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.sockets.append(ws)
        async for msg in ws:
            req = json.loads(msg.data)
            if req["data"] == "GetStatus":
                data = {"Status": self.status}
            elif isinstance(req["data"], dict) and "GetMicLevel" in req["data"]:
                data = {"MicLevel": self.mic_level}
            else:
                data = "Ok"
            await ws.send_json({"id": req["id"], "data": data})
        return ws

    async def get_devices(self, request):
        return web.json_response(self.status)

    async def command(self, request):
        body = await request.json()
        self.commands.append(body)
        if "Command" not in body:
            return web.json_response("Ok")
        _, cmd = body["Command"]
        m, ops = self.mixer, []

        def set_(path, value):
            node = self.status
            parts = path.strip("/").split("/")
            for p in parts[:-1]:
                node = node[p]
            node[parts[-1]] = value
            ops.append({"op": "replace", "path": path, "value": value})

        base = f"/mixers/{SERIAL}"
        if "SetVolume" in cmd:
            ch, v = cmd["SetVolume"]
            set_(f"{base}/levels/volumes/{ch}", v)
        elif "SetFaderMuteState" in cmd:
            f, s = cmd["SetFaderMuteState"]
            set_(f"{base}/fader_status/{f}/mute_state", s)
        elif "LoadProfile" in cmd:
            set_(f"{base}/profile_name", cmd["LoadProfile"][0])
        elif "SetHardTuneEnabled" in cmd:
            set_(f"{base}/effects/current/hard_tune/is_enabled", cmd["SetHardTuneEnabled"])
        elif "SetGlobalColour" in cmd:
            # Mirrors the Utility's Profile::set_global_colour: colour index 0 of
            # every target except the encoders; fade meters get index 1 and
            # index 0 goes black; secondary colours are left alone.
            c = cmd["SetGlobalColour"]
            light = m["lighting"]
            for v in light["simple"].values():
                v["colour_one"] = c
            for group in ("buttons", "sampler"):
                for v in light[group].values():
                    v["colours"]["colour_one"] = c
            for v in light["faders"].values():
                v["colours"]["colour_one"], v["colours"]["colour_two"] = "000000", c
            ops.append({"op": "replace", "path": f"{base}/lighting", "value": light})
        elif "LoadProfileColours" in cmd:
            fresh = status()["mixers"][SERIAL]["lighting"]
            set_(f"{base}/lighting", fresh)
        await self.push(ops)
        return web.json_response("Ok")

    async def push(self, ops):
        for ws in self.sockets:
            if not ws.closed:
                await ws.send_json({"id": 2**64 - 1, "data": {"Patch": ops}})

    async def drop(self):
        self.up = False
        for ws in self.sockets:
            await ws.close()
        self.sockets.clear()


@pytest.fixture
async def daemon(socket_enabled, monkeypatch):
    monkeypatch.setattr(client_mod, "BACKOFF_MIN", 0.1)
    monkeypatch.setattr(client_mod, "BACKOFF_MAX", 0.2)
    monkeypatch.setattr(client_mod, "NOTIFY_DELAY", 0)
    monkeypatch.setattr(mic_monitor, "MIC_POLL_INTERVAL", 0.05)
    monkeypatch.setattr(mic_monitor, "MIC_SPEAKING_RELEASE", 0.3)
    d = FakeDaemon()
    app = web.Application()
    app.router.add_get("/api/websocket", d.ws)
    app.router.add_get("/api/get-devices", d.get_devices)
    app.router.add_post("/api/command", d.command)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    d.port = site._server.sockets[0].getsockname()[1]
    yield d
    await runner.cleanup()


async def _until(hass, cond, what, timeout=5):
    for _ in range(int(timeout / 0.05)):
        await hass.async_block_till_done()
        if cond():
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"timed out: {what}")


async def _setup(hass, daemon):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "127.0.0.1", "port": daemon.port}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    await _until(hass, lambda: any(e.entity_id.endswith("mic_volume") and (s := hass.states.get(e.entity_id)) and s.state == "100" for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)), "entities")
    return entry


async def _call(hass, domain, service, entity_id, **data):
    await hass.services.async_call(domain, service, {"entity_id": entity_id, **data}, blocking=True)


def _device(hass, entry, ident):
    """Find our device by identifier (works on old and new HA versions)."""
    return next(
        d for d in dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
        if (DOMAIN, ident) in d.identifiers
    )


def _state(hass, entity_id):
    s = hass.states.get(entity_id)
    assert s is not None, f"missing {entity_id}"
    return s


async def test_core_controls_and_recovery(hass: HomeAssistant, daemon: FakeDaemon) -> None:
    entry = await _setup(hass, daemon)
    vol = "number.goxlr_mic_volume"

    assert _state(hass, "number.goxlr_music_volume").state == "50"
    assert _state(hass, "switch.goxlr_fader_a_mute").state == STATE_OFF
    assert _state(hass, "switch.goxlr_fader_a_mute").attributes["channel"] == "Mic"
    assert _state(hass, "select.goxlr_profile").state == "Default"
    assert _state(hass, "select.goxlr_effect_preset").state == "1: Clean"
    assert _state(hass, "switch.goxlr_effects").state == STATE_ON
    assert _state(hass, "binary_sensor.goxlr_utility_connection").state == STATE_ON
    assert _state(hass, "sensor.goxlr_utility_utility_version").state == "1.2.3"
    fw = _state(hass, "update.goxlr_firmware")
    assert fw.state == STATE_ON  # 1.3.40.0 installed, 1.5.0.22 available
    assert fw.attributes["installed_version"] == "1.3.40.0"

    await _call(hass, "number", "set_value", vol, value=40)
    assert daemon.commands[-1] == {"Command": [SERIAL, {"SetVolume": ["Mic", 102]}]}
    await _until(hass, lambda: _state(hass, vol).state == "40", "volume patch")

    await _call(hass, "switch", "turn_on", "switch.goxlr_fader_a_mute")
    await _until(hass, lambda: _state(hass, "switch.goxlr_fader_a_mute").state == STATE_ON, "mute")

    await _call(hass, "select", "select_option", "select.goxlr_profile", option="Streaming")
    assert daemon.commands[-1] == {"Command": [SERIAL, {"LoadProfile": ["Streaming", True]}]}

    await _call(hass, "select", "select_option", "select.goxlr_compressor_ratio", option="4.0:1")
    assert daemon.commands[-1] == {"Command": [SERIAL, {"SetCompressorRatio": "Ratio4_0"}]}

    await _call(hass, "button", "press", "button.goxlr_save_profile")
    assert daemon.commands[-1] == {"Command": [SERIAL, {"SaveProfile": []}]}

    await _call(hass, "button", "press", "button.goxlr_play_top_left_sample")
    assert daemon.commands[-1] == {"Command": [SERIAL, {"PlayNextSample": ["A", "TopLeft"]}]}
    # Pad without samples can't be played.
    assert _state(hass, "button.goxlr_play_top_right_sample").state == STATE_UNAVAILABLE

    await _call(hass, "text", "set_value", "text.goxlr_fader_a_screen_text", value="ON AIR")
    assert daemon.commands[-1] == {"Command": [SERIAL, {"SetScribbleText": ["A", "ON AIR"]}]}

    await _call(hass, "button", "press", "button.goxlr_utility_open_utility_window")
    assert daemon.commands[-1] == {"Daemon": "OpenUi"}

    await _call(hass, "switch", "turn_off", "switch.goxlr_utility_start_on_login")
    assert daemon.commands[-1] == {"Daemon": {"SetAutoStartEnabled": False}}

    # Outage and recovery.
    await daemon.drop()
    await _until(hass, lambda: _state(hass, vol).state == STATE_UNAVAILABLE, "unavailable")
    daemon.mixer["levels"]["volumes"]["Mic"] = 0
    daemon.up = True
    await _until(hass, lambda: _state(hass, vol).state == "0", "recovery with fresh state")

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def _configure(hass, entry, groups):
    """Run the Configure (options) dialog with the given advanced groups ticked."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {g: g in groups for g in ADVANCED_GROUPS}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    await _until(hass, lambda: _state(hass, "number.goxlr_mic_volume").state == "100", "reload")


async def test_advanced_groups(hass: HomeAssistant, daemon: FakeDaemon) -> None:
    """Every hidden entity belongs to a group, every group has entities,
    and Configure switches whole groups on and off."""
    entry = await _setup(hass, daemon)
    reg = er.async_get(hass)

    def ents():
        return er.async_entries_for_config_entry(reg, entry.entry_id)

    def key(e):
        return e.unique_id.split("_", 1)[1]

    hidden = [e for e in ents() if e.disabled_by is not None]
    assert hidden
    assert not [e.entity_id for e in hidden if group_for_key(key(e)) is None]
    assert not [e.entity_id for e in ents() if e.disabled_by is None and group_for_key(key(e))]
    used = {group_for_key(key(e)) for e in hidden}
    assert used == set(ADVANCED_GROUPS), set(ADVANCED_GROUPS) - used
    # The always-on companions of grouped entities stay visible.
    for always_on in ("switch.goxlr_robot", "select.goxlr_robot_style", "select.goxlr_profile",
                      "text.goxlr_fader_a_screen_text", "switch.goxlr_mix_b_submix"):
        assert hass.states.get(always_on) is not None, always_on

    await _call(hass, "switch", "turn_off", "switch.goxlr_utility_auto_reconnect")
    await _configure(hass, entry, {"routing", "eq"})
    assert entry.options["advanced_groups"] == ["eq", "routing"]
    assert entry.options["auto_reconnect"] is False  # other options kept
    by_group = lambda g: [e for e in ents() if group_for_key(key(e)) == g]  # noqa: E731
    assert all(e.disabled_by is None for e in by_group("routing") + by_group("eq"))
    assert all(e.disabled_by is not None for e in by_group("effects_fine"))
    assert _state(hass, "switch.goxlr_route_mic_to_headphones").state == STATE_OFF

    # Untick routing: hidden again; EQ untouched.
    await _configure(hass, entry, {"eq"})
    assert all(e.disabled_by is not None for e in by_group("routing"))
    assert all(e.disabled_by is None for e in by_group("eq"))
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_every_entity_loads(hass: HomeAssistant, daemon: FakeDaemon) -> None:
    """Enable every advanced group and check no entity errors."""
    entry = await _setup(hass, daemon)
    reg = er.async_get(hass)
    await _configure(hass, entry, set(ADVANCED_GROUPS))
    assert not [e for e in er.async_entries_for_config_entry(reg, entry.entry_id) if e.disabled_by]

    entries = er.async_entries_for_config_entry(reg, entry.entry_id)
    ids = {e.entity_id for e in entries}
    unavailable = sorted(i for i in ids if hass.states.get(i) is None or hass.states.get(i).state == STATE_UNAVAILABLE)
    # Only things that are legitimately off in this fixture may be unavailable:
    # mix B (submix disabled), mic level (monitoring off), animation params (mode None),
    # and pads without samples.
    allowed = ("mix_b", "source_mix", "speaking", "mic_level", "gradient_mod", "waterfall", "_sample")
    unexpected = [i for i in unavailable if not any(a in i for a in allowed)]
    assert not unexpected, unexpected
    print(f"\n{len(ids)} entities, {len(unavailable)} legitimately unavailable")
    assert len(ids) > 200

    # Mixer device hangs off the Utility hub device.
    dev = _device(hass, entry, SERIAL)
    hub = _device(hass, entry, entry.entry_id)
    assert dev.via_device_id == hub.id
    assert dev.sw_version == "1.3.40.0"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_mic_monitoring_and_speaking(hass: HomeAssistant, daemon: FakeDaemon) -> None:
    entry = await _setup(hass, daemon)
    speaking = "binary_sensor.goxlr_speaking"
    assert _state(hass, speaking).state == STATE_UNAVAILABLE  # opt-in: off by default
    assert not any(isinstance(c, dict) and "GetMicLevel" in str(c) for c in daemon.commands)

    await _call(hass, "switch", "turn_on", "switch.goxlr_mic_level_monitoring")
    assert entry.options[f"mic_level_monitoring_{SERIAL}"] is True
    await _until(hass, lambda: _state(hass, speaking).state == STATE_OFF, "quiet")

    daemon.mic_level = -20.0  # above default threshold (-40)
    await _until(hass, lambda: _state(hass, speaking).state == STATE_ON, "speaking")
    daemon.mic_level = -60.0
    await _until(hass, lambda: _state(hass, speaking).state == STATE_OFF, "released")

    # Raise the threshold so -30 no longer counts as speaking.
    await _call(hass, "number", "set_value", "number.goxlr_speaking_threshold", value=-25)
    daemon.mic_level = -30.0
    await asyncio.sleep(0.4)
    await hass.async_block_till_done()
    assert _state(hass, speaking).state == STATE_OFF

    await _call(hass, "switch", "turn_off", "switch.goxlr_mic_level_monitoring")
    await _until(hass, lambda: _state(hass, speaking).state == STATE_UNAVAILABLE, "monitor off")
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_button_events(hass: HomeAssistant, daemon: FakeDaemon) -> None:
    entry = await _setup(hass, daemon)
    ent = "event.goxlr_sampler_top_left_button"
    fired: list[str] = []
    async_track_state_change_event(
        hass, [ent], lambda ev: fired.append(ev.data["new_state"].attributes.get("event_type"))
    )
    path = f"/mixers/{SERIAL}/button_down/SamplerTopLeft"

    # Quick tap: pressed + released inside one patch burst must not be lost.
    await daemon.push([{"op": "replace", "path": path, "value": True}])
    await daemon.push([{"op": "replace", "path": path, "value": False}])
    await _until(hass, lambda: len(fired) >= 3, "tap events")
    assert fired == ["pressed", "released", "short_press"]

    fired.clear()
    await daemon.push([{"op": "replace", "path": path, "value": True}])
    await asyncio.sleep(0.7)  # mute hold duration is 500 ms
    await daemon.push([{"op": "replace", "path": path, "value": False}])
    await _until(hass, lambda: len(fired) >= 3, "hold events")
    assert fired == ["pressed", "long_press", "released"]
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_lighting_light(hass: HomeAssistant, daemon: FakeDaemon) -> None:
    entry = await _setup(hass, daemon)
    light = "light.goxlr_lighting"
    assert _state(hass, light).state == STATE_ON
    assert tuple(_state(hass, light).attributes["rgb_color"]) == (0, 255, 255)

    # Profile colours -> off -> on restores the profile's colour scheme.
    await _call(hass, "light", "turn_off", light)
    assert daemon.commands[-1] == {"Command": [SERIAL, {"SetGlobalColour": "000000"}]}
    await _until(hass, lambda: _state(hass, light).state == STATE_OFF, "off")
    await _call(hass, "light", "turn_on", light)
    assert daemon.commands[-1] == {"Command": [SERIAL, {"LoadProfileColours": "Default"}]}
    await _until(hass, lambda: _state(hass, light).state == STATE_ON, "back on (profile)")

    # A colour set from Home Assistant -> off -> on restores that colour.
    await _call(hass, "light", "turn_on", light, rgb_color=[255, 0, 0], brightness=128)
    assert daemon.commands[-1] == {"Command": [SERIAL, {"SetGlobalColour": "800000"}]}
    await _until(hass, lambda: _state(hass, light).attributes.get("brightness") == 128, "red")
    await _call(hass, "light", "turn_off", light)
    await _until(hass, lambda: _state(hass, light).state == STATE_OFF, "off again")
    await _call(hass, "light", "turn_on", light)
    assert daemon.commands[-1] == {"Command": [SERIAL, {"SetGlobalColour": "800000"}]}
    await _until(hass, lambda: _state(hass, light).state == STATE_ON, "back on (colour)")

    # The remembered colour survives a Home Assistant restart (reload).
    await _call(hass, "light", "turn_off", light)
    await _until(hass, lambda: _state(hass, light).state == STATE_OFF, "off before reload")
    assert await hass.config_entries.async_reload(entry.entry_id)
    await _until(hass, lambda: _state(hass, light).state == STATE_OFF, "reloaded")
    await _call(hass, "light", "turn_on", light)
    assert daemon.commands[-1] == {"Command": [SERIAL, {"SetGlobalColour": "800000"}]}

    # Brightness only, while off: uses the remembered colour, not white.
    await _call(hass, "light", "turn_off", light)
    await _until(hass, lambda: _state(hass, light).state == STATE_OFF, "off for brightness")
    await _call(hass, "light", "turn_on", light, brightness=255)
    assert daemon.commands[-1] == {"Command": [SERIAL, {"SetGlobalColour": "FF0000"}]}
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_rules_and_dynamic_ranges(hass: HomeAssistant, daemon: FakeDaemon) -> None:
    entry = await _setup(hass, daemon)
    pitch = "number.goxlr_pitch_amount"
    assert _state(hass, pitch).attributes["min"] == -24
    await _call(hass, "switch", "turn_on", "switch.goxlr_hard_tune")
    # With Hard tune on, Wide pitch is limited to +/-2 octave steps.
    await _until(hass, lambda: _state(hass, pitch).attributes["max"] == 2, "pitch range")

    # Mic mute in Hold mode gives a helpful error instead of a daemon failure.
    daemon.mixer["cough_button"]["is_toggle"] = False
    await daemon.push([{"op": "replace", "path": f"/mixers/{SERIAL}/cough_button/is_toggle", "value": False}])
    await _until(hass, lambda: _state(hass, "select.goxlr_mic_mute_button_mode").state == "Hold", "hold")
    with pytest.raises(HomeAssistantError, match="Hold mode"):
        await _call(hass, "switch", "turn_on", "switch.goxlr_mic_mute")

    # Raw command action reaches anything without an entity.
    dev = _device(hass, entry, SERIAL)
    resp = await hass.services.async_call(
        DOMAIN, "send_command",
        {"device_id": dev.id, "command": {"SetFaderColours": ["A", "FF0000", "000000"]}},
        blocking=True, return_response=True,
    )
    assert resp == {"result": "Ok"}
    assert daemon.commands[-1] == {"Command": [SERIAL, {"SetFaderColours": ["A", "FF0000", "000000"]}]}
    await hass.services.async_call(
        DOMAIN, "send_utility_command", {"command": {"SetSampleGainPct": ["intro.wav", 80]}},
        blocking=True,
    )
    assert daemon.commands[-1] == {"Daemon": {"SetSampleGainPct": ["intro.wav", 80]}}
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_auto_reconnect_toggle(hass: HomeAssistant, daemon: FakeDaemon) -> None:
    entry = await _setup(hass, daemon)
    conn = "binary_sensor.goxlr_utility_connection"
    toggle = "switch.goxlr_utility_auto_reconnect"
    assert _state(hass, toggle).state == STATE_ON

    await _call(hass, "switch", "turn_off", toggle)
    assert entry.options["auto_reconnect"] is False
    assert _state(hass, conn).state == STATE_ON

    await daemon.drop()
    await _until(hass, lambda: _state(hass, conn).state == STATE_OFF, "disconnected")
    daemon.up = True
    await asyncio.sleep(1.5)
    await hass.async_block_till_done()
    assert _state(hass, conn).state == STATE_OFF
    assert _state(hass, toggle).state == STATE_OFF

    await _call(hass, "switch", "turn_on", toggle)
    await _until(hass, lambda: _state(hass, conn).state == STATE_ON, "reconnected", timeout=2)

    await _call(hass, "switch", "turn_off", toggle)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert _state(hass, toggle).state == STATE_OFF
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_cannot_connect(hass: HomeAssistant, socket_enabled) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"host": "127.0.0.1", "port": 1})
    assert result["errors"] == {"base": "cannot_connect"}


async def test_goxlr_mini(hass: HomeAssistant, daemon: FakeDaemon) -> None:
    """The Mini has no effects, sampler or screens: those entities must not exist."""
    m = daemon.mixer
    m["hardware"]["device_type"] = "Mini"
    m["effects"] = None
    m["sampler"] = None
    for f in m["fader_status"].values():
        f["scribble"] = None
    entry = await _setup(hass, daemon)
    ids = {e.entity_id for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)}
    assert not [i for i in ids if any(k in i for k in ("effect", "reverb", "robot", "sampler", "screen", "megaphone"))]
    events = sorted(i for i in ids if i.startswith("event."))
    assert len(events) == 6, events
    assert "number.goxlr_mini_eq_90_hz_gain" in ids
    assert _state(hass, "number.goxlr_mini_mic_volume").state == "100"
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_brand_images_served(hass: HomeAssistant, hass_client, socket_enabled) -> None:
    """Home Assistant serves our bundled icon and logo (no brands-repo PR needed)."""
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, "brands", {})
    client = await hass_client()
    for image in ("icon.png", "icon@2x.png", "logo.png", "dark_logo.png"):
        resp = await client.get(f"/api/brands/integration/{DOMAIN}/{image}")
        assert resp.status == 200, image
        assert resp.content_type == "image/png"
        assert (await resp.read())[:8] == b"\x89PNG\r\n\x1a\n"
