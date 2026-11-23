"""The Huawei AH100 / Honor CH100 Scale integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_entry_oauth2_flow

from .const import DOMAIN
from .coordinator import HuaweiAH100Coordinator
from .google_health import GoogleHealthClient

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BUTTON, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Huawei AH100 Scale from a config entry."""
    google_health_client: GoogleHealthClient | None = None

    if "token" in entry.data and "auth_implementation" in entry.data:
        try:
            implementation = (
                await config_entry_oauth2_flow.async_get_config_entry_implementation(
                    hass, entry
                )
            )
            oauth_session = config_entry_oauth2_flow.OAuth2Session(
                hass, entry, implementation
            )
            google_health_client = GoogleHealthClient(oauth_session)
            _LOGGER.info("Google Health sync enabled for %s", entry.title)
        except Exception as err:
            _LOGGER.warning(
                "Could not initialize Google Health OAuth2 session for %s: %s. "
                "Local Bluetooth scale measurements will continue to work normally.",
                entry.title,
                err,
            )

    coordinator = HuaweiAH100Coordinator(
        hass, entry, google_health_client=google_health_client
    )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload integration when options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
