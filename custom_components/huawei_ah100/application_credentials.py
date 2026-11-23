"""Application credentials platform for optional Google Health OAuth2."""

from __future__ import annotations

from homeassistant.components.application_credentials import AuthorizationServer
from homeassistant.core import HomeAssistant

from .const import GOOGLE_HEALTH_AUTHORIZE_URL, GOOGLE_HEALTH_TOKEN_URL


async def async_get_authorization_server(hass: HomeAssistant) -> AuthorizationServer:
    """Return Google OAuth2 authorization server."""
    return AuthorizationServer(
        authorize_url=GOOGLE_HEALTH_AUTHORIZE_URL,
        token_url=GOOGLE_HEALTH_TOKEN_URL,
    )
