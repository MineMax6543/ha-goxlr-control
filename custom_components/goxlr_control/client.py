"""Self-healing connection to the GoXLR Utility daemon.

Design goals (why the connection never "gives up"):
  * One supervisor task loops forever: connect -> sync -> stream -> on ANY
    failure tear down and reconnect with capped exponential backoff.
  * WebSocket heartbeat + an application-level stale watchdog detect half-open
    sockets (PC slept, Wi-Fi blip, daemon restarted) that otherwise hang forever.
  * Full state resync on every (re)connect, on any patch that fails to apply,
    and periodically, because the daemon drops patches for lagging clients.
  * Commands go over plain HTTP so they work independently of the push channel.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import copy
import itertools
import logging
import time
from typing import Any

import aiohttp

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.util.json import json_loads

from .const import (
    BACKOFF_MAX,
    BACKOFF_MIN,
    HEARTBEAT_SECONDS,
    NOTIFY_DELAY,
    REQUEST_TIMEOUT,
    RESYNC_SECONDS,
    STALE_SECONDS,
)

_LOGGER = logging.getLogger(__name__)


class GoXLRError(Exception):
    """Communication or command error."""


class _PatchError(Exception):
    """A JSON patch could not be applied."""


async def async_fetch_status(
    session: aiohttp.ClientSession, host: str, port: int
) -> dict[str, Any]:
    """One-shot HTTP status fetch (used by the config flow)."""
    async with asyncio.timeout(REQUEST_TIMEOUT):
        async with session.get(f"http://{host}:{port}/api/get-devices") as resp:
            resp.raise_for_status()
            data = await resp.json(content_type=None)
    if not isinstance(data, dict) or "mixers" not in data:
        raise GoXLRError("Unexpected response from GoXLR Utility")
    return data


class GoXLRClient:
    """Maintains a live mirror of the daemon status."""

    def __init__(
        self,
        hass: HomeAssistant,
        session: aiohttp.ClientSession,
        host: str,
        port: int,
        auto_reconnect: bool = True,
    ) -> None:
        self._hass = hass
        self._session = session
        self._base = f"http://{host}:{port}"
        self.status: dict[str, Any] | None = None
        self.connected = False
        # When False, a dropped connection is not retried until re-enabled.
        self.auto_reconnect = auto_reconnect
        self._wake = asyncio.Event()
        self._ids = itertools.count(1)
        self._listeners: set[CALLBACK_TYPE] = set()
        self._mixer_listeners: set[Callable[[str], None]] = set()
        self._known_serials: set[str] = set()
        self._notify_handle: asyncio.TimerHandle | None = None
        self._resync_requested = False
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._stopping = False
        self.entry_id = ""  # set by the integration setup
        self.hub_device_id: str | None = None  # set by the integration setup
        self.advanced_groups: set[str] = set()  # set by the integration setup
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._patch_listeners: set[Callable[[list[dict[str, Any]]], None]] = set()

    # ------------------------------------------------------------------ API
    def mixer(self, serial: str) -> dict[str, Any] | None:
        """Return the live status of one mixer, or None if absent."""
        if not self.status:
            return None
        return self.status.get("mixers", {}).get(serial)

    @property
    def files(self) -> dict[str, Any]:
        return (self.status or {}).get("files") or {}

    @callback
    def async_add_listener(self, cb: CALLBACK_TYPE) -> CALLBACK_TYPE:
        """Call `cb` whenever state or connectivity changes."""
        self._listeners.add(cb)
        return lambda: self._listeners.discard(cb)

    @callback
    def async_add_mixer_listener(self, cb: Callable[[str], None]) -> CALLBACK_TYPE:
        """Call `cb(serial)` for every mixer, now and whenever a new one appears."""
        self._mixer_listeners.add(cb)
        for serial in self._known_serials:
            cb(serial)
        return lambda: self._mixer_listeners.discard(cb)

    @callback
    def async_add_patch_listener(
        self, cb: Callable[[list[dict[str, Any]]], None]
    ) -> CALLBACK_TYPE:
        """Call `cb(ops)` synchronously for every applied patch (not coalesced).

        Used for physical button events, where a fast tap must never be lost
        to the notification debounce.
        """
        self._patch_listeners.add(cb)
        return lambda: self._patch_listeners.discard(cb)

    async def async_command(self, serial: str, command: Any) -> Any:
        """Send a GoXLRCommand to one mixer over HTTP."""
        return _check(await self._request({"Command": [serial, command]}))

    async def async_utility_command(self, command: Any) -> Any:
        """Send a DaemonCommand (Utility-level setting) over HTTP."""
        return _check(await self._request({"Daemon": command}))

    async def async_ws_request(self, data: Any, timeout: float = 2.0) -> Any:
        """Request/response over the live websocket (cheap; used for polling)."""
        ws = self._ws
        if ws is None or ws.closed or not self.connected:
            raise GoXLRError("not connected")
        req_id = next(self._ids)
        fut: asyncio.Future[Any] = self._hass.loop.create_future()
        self._pending[req_id] = fut
        try:
            await ws.send_json({"id": req_id, "data": data})
            async with asyncio.timeout(timeout):
                return _check(await fut)
        except (aiohttp.ClientError, ConnectionError, TimeoutError) as err:
            raise GoXLRError(f"request failed: {err!r}") from err
        finally:
            self._pending.pop(req_id, None)

    @callback
    def set_auto_reconnect(self, enabled: bool) -> None:
        """Enable/disable retrying. Enabling triggers an immediate attempt."""
        self.auto_reconnect = enabled
        if enabled:
            self._wake.set()
        self._schedule_notify()

    async def async_run(self) -> None:
        """Supervisor loop. Runs until cancelled; never exits on errors.

        The first attempt always happens (even with auto reconnect off), so a
        Home Assistant restart still connects if the PC happens to be on.
        """
        backoff = BACKOFF_MIN
        while not self._stopping:
            self._wake.clear()
            started = time.monotonic()
            try:
                await self._session_loop()
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001 - must survive anything
                _LOGGER.debug("GoXLR connection to %s ended: %r", self._base, err)
            finally:
                self._ws = None
                self._fail_pending()
                self._set_connected(False)
            if self._stopping:
                break
            # A connection that stayed healthy for a while resets the backoff.
            if time.monotonic() - started > 60:
                backoff = BACKOFF_MIN
            if not self.auto_reconnect:
                _LOGGER.info("GoXLR auto reconnect is off; not retrying %s", self._base)
                await self._wake.wait()
                backoff = BACKOFF_MIN
                continue
            try:
                async with asyncio.timeout(backoff):
                    await self._wake.wait()  # re-enabling cuts the wait short
                backoff = BACKOFF_MIN
            except TimeoutError:
                backoff = min(backoff * 2, BACKOFF_MAX)

    async def async_stop(self) -> None:
        self._stopping = True
        self._wake.set()
        if self._notify_handle:
            self._notify_handle.cancel()
            self._notify_handle = None
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()

    # ------------------------------------------------------------ internals
    async def _request(self, body: dict[str, Any]) -> Any:
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.post(
                    f"{self._base}/api/command", json=body
                ) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        raise GoXLRError(f"HTTP {resp.status}: {text[:200]}")
                    return await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise GoXLRError(f"GoXLR Utility unreachable: {err}") from err

    async def _session_loop(self) -> None:
        async with asyncio.timeout(REQUEST_TIMEOUT):
            ws = await self._session.ws_connect(
                f"{self._base}/api/websocket",
                heartbeat=HEARTBEAT_SECONDS,
                autoping=True,
                max_msg_size=0,
            )
        self._ws = ws
        try:
            _LOGGER.debug("Connected to GoXLR Utility at %s", self._base)
            await self._send(ws, "GetStatus")
            connected_at = last_rx = last_sync = time.monotonic()

            while True:
                try:
                    msg = await ws.receive(timeout=HEARTBEAT_SECONDS)
                except TimeoutError:
                    msg = None

                now = time.monotonic()
                if msg is not None:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        last_rx = now
                        self._handle(msg.data)
                    elif msg.type in (aiohttp.WSMsgType.PING, aiohttp.WSMsgType.PONG):
                        last_rx = now
                    elif msg.type in (
                        aiohttp.WSMsgType.CLOSE,
                        aiohttp.WSMsgType.CLOSING,
                        aiohttp.WSMsgType.CLOSED,
                        aiohttp.WSMsgType.ERROR,
                    ):
                        raise GoXLRError(f"websocket closed ({msg.type!r})")
                else:
                    # Idle: an application-level ping guarantees traffic so the
                    # stale detector below has something to measure.
                    await self._send(ws, "Ping")

                if not self.connected and now - connected_at > REQUEST_TIMEOUT:
                    raise GoXLRError("no initial status received")
                if now - last_rx > STALE_SECONDS:
                    raise GoXLRError("connection stale")
                if self._resync_requested or now - last_sync > RESYNC_SECONDS:
                    self._resync_requested = False
                    last_sync = now
                    await self._send(ws, "GetStatus")
        finally:
            if not ws.closed:
                await ws.close()

    async def _send(self, ws: aiohttp.ClientWebSocketResponse, data: Any) -> None:
        await ws.send_json({"id": next(self._ids), "data": data})

    @callback
    def _handle(self, raw: str) -> None:
        try:
            payload = json_loads(raw)
        except ValueError:
            return
        if not isinstance(payload, dict):
            return
        data = payload.get("data")
        fut = self._pending.pop(payload.get("id"), None)
        if fut is not None:
            if not fut.done():
                fut.set_result(data)
            return
        if not isinstance(data, dict):
            return  # "Ok" etc.
        if "Status" in data:
            self.status = data["Status"]
            self._set_connected(True)
            self._mixers_changed()
            self._schedule_notify()
        elif "Patch" in data:
            if self.status is None:
                self._resync_requested = True
                return
            try:
                self.status = _apply_patch(self.status, data["Patch"])
            except _PatchError as err:
                _LOGGER.debug("Patch failed (%s), resyncing", err)
                self._resync_requested = True
                return
            for cb in list(self._patch_listeners):
                cb(data["Patch"])
            self._mixers_changed()
            self._schedule_notify()
        elif "Error" in data:
            _LOGGER.debug("GoXLR Utility error: %s", data["Error"])

    @callback
    def _fail_pending(self) -> None:
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(GoXLRError("connection lost"))
        self._pending.clear()

    @callback
    def _mixers_changed(self) -> None:
        serials = set((self.status or {}).get("mixers", {}))
        new = serials - self._known_serials
        self._known_serials |= serials
        for serial in new:
            _LOGGER.debug("GoXLR mixer discovered: %s", serial)
            for cb in list(self._mixer_listeners):
                cb(serial)

    @callback
    def _set_connected(self, value: bool) -> None:
        if self.connected != value:
            self.connected = value
            if value:
                _LOGGER.info("GoXLR Utility at %s connected", self._base)
            else:
                _LOGGER.info("GoXLR Utility at %s disconnected, retrying", self._base)
            self._schedule_notify()

    @callback
    def _schedule_notify(self) -> None:
        if self._notify_handle is None and not self._stopping:
            self._notify_handle = self._hass.loop.call_later(NOTIFY_DELAY, self._notify)

    @callback
    def _notify(self) -> None:
        self._notify_handle = None
        for cb in list(self._listeners):
            cb()


def _check(result: Any) -> Any:
    """Raise if the daemon answered with DaemonResponse::Error."""
    if isinstance(result, dict) and "Error" in result:
        raise GoXLRError(str(result["Error"]))
    return result


# ------------------------------------------------------------- JSON patch
def _parse_pointer(path: str) -> list[str]:
    if path == "":
        return []
    if not path.startswith("/"):
        raise _PatchError(f"bad pointer {path!r}")
    return [p.replace("~1", "/").replace("~0", "~") for p in path[1:].split("/")]


def _resolve(doc: Any, parts: list[str]) -> Any:
    for part in parts:
        doc = doc[int(part)] if isinstance(doc, list) else doc[part]
    return doc


def _add(doc: Any, parts: list[str], value: Any, replace: bool) -> Any:
    if not parts:
        return value
    parent = _resolve(doc, parts[:-1])
    key = parts[-1]
    if isinstance(parent, dict):
        if replace and key not in parent:
            raise _PatchError(f"replace of missing key {key!r}")
        parent[key] = value
    elif isinstance(parent, list):
        if key == "-":
            parent.append(value)
        elif replace:
            parent[int(key)] = value
        else:
            parent.insert(int(key), value)
    else:
        raise _PatchError("parent is not a container")
    return doc


def _remove(doc: Any, parts: list[str]) -> Any:
    if not parts:
        raise _PatchError("cannot remove root")
    parent = _resolve(doc, parts[:-1])
    key = parts[-1]
    if isinstance(parent, list):
        del parent[int(key)]
    else:
        del parent[key]
    return doc


def _apply_patch(doc: Any, ops: list[dict[str, Any]]) -> Any:
    """Minimal RFC 6902 implementation (in place). Raises _PatchError."""
    try:
        for op in ops:
            kind = op["op"]
            parts = _parse_pointer(op["path"])
            if kind == "add":
                doc = _add(doc, parts, op["value"], replace=False)
            elif kind == "replace":
                doc = _add(doc, parts, op["value"], replace=True)
            elif kind == "remove":
                doc = _remove(doc, parts)
            elif kind == "move":
                src = _parse_pointer(op["from"])
                value = _resolve(doc, src)
                doc = _remove(doc, src)
                doc = _add(doc, parts, value, replace=False)
            elif kind == "copy":
                value = copy.deepcopy(_resolve(doc, _parse_pointer(op["from"])))
                doc = _add(doc, parts, value, replace=False)
            elif kind == "test":
                if _resolve(doc, parts) != op["value"]:
                    raise _PatchError("test failed")
            else:
                raise _PatchError(f"unknown op {kind!r}")
    except _PatchError:
        raise
    except (KeyError, IndexError, ValueError, TypeError) as err:
        raise _PatchError(repr(err)) from err
    return doc
