"""Firmware update notice (read-only).

Shows when the GoXLR Utility knows of newer firmware. Installing is left to the
Utility on purpose: a firmware flash that's interrupted can brick the mixer, so
it should be started by someone sitting in front of it.
"""

from __future__ import annotations

from homeassistant.components.update import UpdateDeviceClass, UpdateEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import GoXLRConfigEntry
from .client import GoXLRClient
from .entity import GoXLREntity, Mixer, add_mixer_entities, dig, version_str


async def async_setup_entry(
    hass: HomeAssistant, entry: GoXLRConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    def build(client: GoXLRClient, serial: str, mixer: Mixer) -> list[Entity]:
        return [FirmwareUpdate(client, serial)]

    add_mixer_entities(entry, build, async_add_entities)


class FirmwareUpdate(GoXLREntity, UpdateEntity):
    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, client: GoXLRClient, serial: str) -> None:
        super().__init__(client, serial, "firmware", "Firmware")

    @property
    def _latest(self) -> dict | None:
        device_type = dig(self.mixer, "hardware", "device_type")
        return dig(self._client.status, "config", "latest_firmware", device_type)

    @property
    def installed_version(self) -> str | None:
        return version_str(dig(self.mixer, "hardware", "versions", "firmware"))

    @property
    def latest_version(self) -> str | None:
        # Unknown latest (update check off/offline) -> report "up to date".
        return version_str(dig(self._latest, "version")) or self.installed_version

    @property
    def release_summary(self) -> str | None:
        log = dig(self._latest, "change_log")
        if not log:
            return "Install firmware updates from the GoXLR Utility on your PC."
        return log if len(log) <= 255 else log[:252] + "..."
