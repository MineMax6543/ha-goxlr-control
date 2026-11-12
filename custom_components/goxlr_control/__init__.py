"""GoXLR Control: resilient local-push control of the GoXLR Utility."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client import GoXLRClient
from .const import CONF_AUTO_RECONNECT, DOMAIN

PLATFORMS = [Platform.BINARY_SENSOR, Platform.NUMBER, Platform.SELECT, Platform.SWITCH]

type GoXLRConfigEntry = ConfigEntry[GoXLRClient]


async def async_setup_entry(hass: HomeAssistant, entry: GoXLRConfigEntry) -> bool:
    client = GoXLRClient(
        hass,
        async_get_clientsession(hass),
        entry.data[CONF_HOST],
        entry.data[CONF_PORT],
        auto_reconnect=entry.options.get(CONF_AUTO_RECONNECT, True),
    )
    client.entry_id = entry.entry_id
    entry.runtime_data = client
    # Hub device for the Utility itself; always present, even with the PC off.
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        manufacturer="GoXLR on Linux",
        model="GoXLR Utility",
        name="GoXLR Utility",
        configuration_url=f"http://{entry.data[CONF_HOST]}:{entry.data[CONF_PORT]}",
    )
    # Setup never blocks on the PC being online: entities are created as soon as
    # the daemon reports a mixer, and the supervisor handles reconnecting.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_create_background_task(hass, client.async_run(), "goxlr_control_connection")
    entry.async_on_unload(client.async_stop)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GoXLRConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
