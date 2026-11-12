"""End-to-end tests against a fake GoXLR Utility daemon."""

import asyncio
import copy
import json

from aiohttp import web
import pytest

from homeassistant import config_entries
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.goxlr_control import client as client_mod
from custom_components.goxlr_control.const import DOMAIN

STATUS = {
    "mixers": {
        "S220202153DI7": {
            "hardware": {"device_type": "Full", "versions": {"firmware": [1, 5, 0, 22]}},
            "fader_status": {
                f: {"channel": ch, "mute_type": "All", "mute_state": "Unmuted"}
                for f, ch in zip("ABCD", ["Mic", "Music", "Chat", "System"])
            },
            "levels": {"volumes": {"Mic": 255, "Music": 128, "Headphones": 200}},
            "router": {"Microphone": {"Headphones": False, "BroadcastMix": True}},
            "cough_button": {"is_toggle": False, "mute_type": "All", "state": "Unmuted"},
            "effects": {
                "is_enabled": True,
                "active_preset": "Preset1",
                "preset_names": {"Preset1": "Clean", "Preset2": "Deep"},
                "current": {"megaphone": {"is_enabled": False}, "robot": {"is_enabled": False}, "hard_tune": {"is_enabled": False}},
            },
            "profile_name": "Default",
            "mic_profile_name": "DEFAULT",
        }
    },
    "files": {"profiles": ["Default", "Streaming"], "mic_profiles": ["DEFAULT"]},
}
SERIAL = "S220202153DI7"


class FakeDaemon:
    def __init__(self):
        self.status = copy.deepcopy(STATUS)
        self.sockets: list[web.WebSocketResponse] = []
        self.commands: list = []
        self.up = True

    async def ws(self, request):
        if not self.up:
            raise web.HTTPServiceUnavailable()
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.sockets.append(ws)
        async for msg in ws:
            req = json.loads(msg.data)
            data = {"Status": self.status} if req["data"] == "GetStatus" else "Ok"
            await ws.send_json({"id": req["id"], "data": data})
        return ws

    async def get_devices(self, request):
        return web.json_response(self.status)

    async def command(self, request):
        body = await request.json()
        self.commands.append(body)
        _, cmd = body["Command"]
        ops = []
        mixer = self.status["mixers"][SERIAL]
        if "SetVolume" in cmd:
            ch, v = cmd["SetVolume"]
            mixer["levels"]["volumes"][ch] = v
            ops.append({"op": "replace", "path": f"/mixers/{SERIAL}/levels/volumes/{ch}", "value": v})
        if "SetFaderMuteState" in cmd:
            f, s = cmd["SetFaderMuteState"]
            mixer["fader_status"][f]["mute_state"] = s
            ops.append({"op": "replace", "path": f"/mixers/{SERIAL}/fader_status/{f}/mute_state", "value": s})
        if "LoadProfile" in cmd:
            mixer["profile_name"] = cmd["LoadProfile"][0]
            ops.append({"op": "replace", "path": f"/mixers/{SERIAL}/profile_name", "value": mixer["profile_name"]})
        for ws in self.sockets:
            if not ws.closed:
                await ws.send_json({"id": 2**64 - 1, "data": {"Patch": ops}})
        return web.json_response("Ok")

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


async def test_full_flow(hass: HomeAssistant, daemon: FakeDaemon) -> None:
    # Config flow
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "127.0.0.1", "port": daemon.port}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]

    vol = "number.goxlr_mic_volume"
    await _until(hass, lambda: hass.states.get(vol) is not None and hass.states.get(vol).state == "100", "entities")

    assert hass.states.get("number.goxlr_music_volume").state == "50"
    assert hass.states.get("switch.goxlr_fader_a_mute").state == STATE_OFF
    assert hass.states.get("switch.goxlr_fader_a_mute").attributes["channel"] == "Mic"
    assert hass.states.get("select.goxlr_profile").state == "Default"
    assert hass.states.get("select.goxlr_effect_preset").state == "1: Clean"
    assert hass.states.get("switch.goxlr_effects").state == STATE_ON
    assert hass.states.get("binary_sensor.goxlr_utility_connection").state == STATE_ON

    # Controls round-trip through the daemon and come back as patches
    await hass.services.async_call("number", "set_value", {"entity_id": vol, "value": 40}, blocking=True)
    assert daemon.commands[-1] == {"Command": [SERIAL, {"SetVolume": ["Mic", 102]}]}
    await _until(hass, lambda: hass.states.get(vol).state == "40", "volume patch")

    await hass.services.async_call("switch", "turn_on", {"entity_id": "switch.goxlr_fader_a_mute"}, blocking=True)
    await _until(hass, lambda: hass.states.get("switch.goxlr_fader_a_mute").state == STATE_ON, "mute patch")

    await hass.services.async_call("select", "select_option", {"entity_id": "select.goxlr_profile", "option": "Streaming"}, blocking=True)
    assert daemon.commands[-1] == {"Command": [SERIAL, {"LoadProfile": ["Streaming", True]}]}
    await _until(hass, lambda: hass.states.get("select.goxlr_profile").state == "Streaming", "profile patch")

    # Daemon goes away (PC asleep / Utility restarted) -> unavailable, then recovers
    await daemon.drop()
    await _until(hass, lambda: hass.states.get(vol).state == STATE_UNAVAILABLE, "unavailable")
    assert hass.states.get("binary_sensor.goxlr_utility_connection").state == STATE_OFF
    daemon.status["mixers"][SERIAL]["levels"]["volumes"]["Mic"] = 0
    daemon.up = True
    await _until(hass, lambda: hass.states.get(vol).state == "0", "recovery with fresh state")
    assert hass.states.get("binary_sensor.goxlr_utility_connection").state == STATE_ON

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_cannot_connect(hass: HomeAssistant, socket_enabled) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"host": "127.0.0.1", "port": 1})
    assert result["errors"] == {"base": "cannot_connect"}


async def test_auto_reconnect_toggle(hass: HomeAssistant, daemon: FakeDaemon) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "127.0.0.1", "port": daemon.port}
    )
    entry = result["result"]
    conn = "binary_sensor.goxlr_utility_connection"
    toggle = "switch.goxlr_utility_auto_reconnect"
    await _until(hass, lambda: hass.states.get(conn).state == STATE_ON, "connected")
    assert hass.states.get(toggle).state == STATE_ON

    # Turn off retrying: stays connected while the PC is up...
    await hass.services.async_call("switch", "turn_off", {"entity_id": toggle}, blocking=True)
    assert entry.options["auto_reconnect"] is False
    assert hass.states.get(conn).state == STATE_ON

    # ...but once the PC goes away it does not come back on its own.
    await daemon.drop()
    await _until(hass, lambda: hass.states.get(conn).state == STATE_OFF, "disconnected")
    daemon.up = True
    await asyncio.sleep(1.5)  # many backoff periods (0.1-0.2 s in tests)
    await hass.async_block_till_done()
    assert hass.states.get(conn).state == STATE_OFF
    assert hass.states.get(toggle).state == STATE_OFF  # toggle itself stays usable

    # Turning it back on reconnects immediately.
    await hass.services.async_call("switch", "turn_on", {"entity_id": toggle}, blocking=True)
    await _until(hass, lambda: hass.states.get(conn).state == STATE_ON, "reconnected", timeout=2)

    # Setting survives a reload (= HA restart).
    await hass.services.async_call("switch", "turn_off", {"entity_id": toggle}, blocking=True)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(toggle).state == STATE_OFF
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
