"""Canvas LMS custom integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CanvasApiClient
from .const import (
    CONF_API_TOKEN,
    CONF_BASE_URL,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import CanvasDataUpdateCoordinator
from .oauth import CanvasOAuth2Implementation


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Canvas LMS from a config entry."""
    websession = async_get_clientsession(hass)

    if CONF_API_TOKEN in entry.data:
        client = CanvasApiClient(
            session=websession,
            base_url=entry.data[CONF_BASE_URL],
            bearer_token=entry.data[CONF_API_TOKEN],
        )
    else:
        implementation = CanvasOAuth2Implementation(
            hass,
            entry.data[CONF_BASE_URL],
            entry.data[CONF_CLIENT_ID],
            entry.data[CONF_CLIENT_SECRET],
        )
        oauth_session = config_entry_oauth2_flow.OAuth2Session(
            hass,
            entry,
            implementation,
        )
        client = CanvasApiClient(
            session=websession,
            base_url=entry.data[CONF_BASE_URL],
            oauth_session=oauth_session,
        )

    coordinator = CanvasDataUpdateCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry after an options update."""
    await hass.config_entries.async_reload(entry.entry_id)
