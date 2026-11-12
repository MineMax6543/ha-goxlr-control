"""Opt-in live mic level monitoring.

The daemon only reports the mic level when asked, so this polls it, but only
while "Mic level monitoring" is switched on. It drives two entities:

* Speaking (binary sensor): on as soon as the level crosses the threshold, and
  held for MIC_SPEAKING_RELEASE seconds after you go quiet so it doesn't
  flicker between words. Ideal for "on air" lights.
* Mic level (sensor, dBFS): rounded to whole dB and published at most once per
  second to keep the recorder database small.
"""

from __future__ import annotations

import asyncio
import time

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback

from .client import GoXLRClient, GoXLRError
from .const import (
    CONF_MIC_MONITOR,
    CONF_SPEAKING_THRESHOLD,
    DEFAULT_SPEAKING_THRESHOLD,
    MIC_POLL_INTERVAL,
    MIC_SENSOR_MIN_INTERVAL,
    MIC_SPEAKING_RELEASE,
)


class MicMonitor:
    """Per-mixer mic level poller with persisted settings."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: GoXLRClient, serial: str
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._client = client
        self._serial = serial
        self._enabled_key = f"{CONF_MIC_MONITOR}_{serial}"
        self._threshold_key = f"{CONF_SPEAKING_THRESHOLD}_{serial}"
        self.enabled: bool = entry.options.get(self._enabled_key, False)
        self.threshold: float = entry.options.get(self._threshold_key, DEFAULT_SPEAKING_THRESHOLD)
        self.level: float | None = None
        self.speaking = False
        self._listeners: set[CALLBACK_TYPE] = set()
        self._task: asyncio.Task | None = None
        self._last_loud = 0.0
        self._last_publish = 0.0
        if self.enabled:
            self._start()
        entry.async_on_unload(self._stop)

    @callback
    def async_add_listener(self, cb: CALLBACK_TYPE) -> CALLBACK_TYPE:
        self._listeners.add(cb)
        return lambda: self._listeners.discard(cb)

    @property
    def active(self) -> bool:
        return self.enabled and self._client.connected

    @callback
    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        self._persist(self._enabled_key, enabled)
        if enabled:
            self._start()
        else:
            self._stop()
        self._notify()

    @callback
    def set_threshold(self, value: float) -> None:
        self.threshold = value
        self._persist(self._threshold_key, value)
        self._notify()

    # ------------------------------------------------------------ internals
    def _persist(self, key: str, value: object) -> None:
        self._hass.config_entries.async_update_entry(
            self._entry, options={**self._entry.options, key: value}
        )

    @callback
    def _start(self) -> None:
        if self._task is None:
            self._task = self._entry.async_create_background_task(
                self._hass, self._run(), f"goxlr_mic_monitor_{self._serial}"
            )

    @callback
    def _stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None
        self.level = None
        self.speaking = False

    @callback
    def _notify(self) -> None:
        for cb in list(self._listeners):
            cb()

    async def _run(self) -> None:
        while True:
            level: float | None = None
            if self._client.connected:
                try:
                    result = await self._client.async_ws_request({"GetMicLevel": self._serial})
                    if isinstance(result, dict) and "MicLevel" in result:
                        level = float(result["MicLevel"])
                except (GoXLRError, TypeError, ValueError):
                    level = None
            self._update(level)
            await asyncio.sleep(MIC_POLL_INTERVAL if level is not None else 1.0)

    @callback
    def _update(self, level: float | None) -> None:
        now = time.monotonic()
        changed = False
        if level is None:
            if self.level is not None or self.speaking:
                self.level, self.speaking, changed = None, False, True
        else:
            if level >= self.threshold:
                self._last_loud = now
            speaking = self._last_loud > 0 and now - self._last_loud < MIC_SPEAKING_RELEASE
            if speaking != self.speaking:
                self.speaking, changed = speaking, True
            rounded = float(round(level))
            if rounded != self.level and (
                self.level is None or now - self._last_publish >= MIC_SENSOR_MIN_INTERVAL
            ):
                self.level, self._last_publish, changed = rounded, now, True
        if changed:
            self._notify()


def get_monitor(hass: HomeAssistant, entry: ConfigEntry, serial: str) -> MicMonitor:
    """One shared MicMonitor per mixer, created by whichever platform asks first."""
    client: GoXLRClient = entry.runtime_data
    monitors: dict[str, MicMonitor] = client.__dict__.setdefault("mic_monitors", {})
    if serial not in monitors:
        monitors[serial] = MicMonitor(hass, entry, client, serial)
    return monitors[serial]
