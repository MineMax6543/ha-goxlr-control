"""GoXLR Control: resilient local-push control of the GoXLR Utility."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .advanced import apply_groups, enabled_groups
from .client import GoXLRClient
from .const import CONF_AUTO_RECONNECT, DOMAIN

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.EVENT,
    Platform.LIGHT,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TEXT,
    Platform.UPDATE,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type GoXLRConfigEntry = ConfigEntry[GoXLRClient]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    from .services import async_setup_services

    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: GoXLRConfigEntry) -> bool:
    client = GoXLRClient(
        hass,
        async_get_clientsession(hass),
        entry.data[CONF_HOST],
        entry.data[CONF_PORT],
        auto_reconnect=entry.options.get(CONF_AUTO_RECONNECT, True),
    )
    client.entry_id = entry.entry_id
    client.advanced_groups = enabled_groups(entry)
    entry.runtime_data = client
    # Hub device for the Utility itself; always present, even with the PC off.
    hub = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        manufacturer="GoXLR on Linux",
        model="GoXLR Utility",
        name="GoXLR Utility",
        configuration_url=f"http://{entry.data[CONF_HOST]}:{entry.data[CONF_PORT]}",
    )
    client.hub_device_id = hub.id
    # Setup never blocks on the PC being online: entities are created as soon as
    # the daemon reports a mixer, and the supervisor handles reconnecting.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_create_background_task(hass, client.async_run(), "goxlr_control_connection")
    entry.async_on_unload(client.async_stop)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: GoXLRConfigEntry) -> None:
    """Advanced groups changed in Configure: update the registry and reload.

    Other options (auto reconnect, mic monitoring) also live in entry.options
    and change at runtime; those must not trigger a reload.
    """
    old, new = entry.runtime_data.advanced_groups, enabled_groups(entry)
    if old == new:
        return
    apply_groups(hass, entry, old, new)
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: GoXLRConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
