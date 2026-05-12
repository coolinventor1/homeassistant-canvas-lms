"""OAuth helpers for Canvas LMS."""

from __future__ import annotations

from urllib.parse import urlsplit

from homeassistant.helpers import config_entry_oauth2_flow

from .const import CANVAS_OAUTH_SCOPES, DOMAIN


class CanvasOAuth2Implementation(config_entry_oauth2_flow.LocalOAuth2Implementation):
    """Canvas-specific OAuth2 implementation."""

    def __init__(
        self,
        hass,
        base_url: str,
        client_id: str,
        client_secret: str,
    ) -> None:
        """Initialize the Canvas OAuth implementation."""
        self._base_url = base_url.rstrip("/")
        self._host = urlsplit(self._base_url).netloc or self._base_url
        super().__init__(
            hass,
            DOMAIN,
            client_id,
            client_secret,
            f"{self._base_url}/login/oauth2/auth",
            f"{self._base_url}/login/oauth2/token",
        )

    @property
    def name(self) -> str:
        """Return a friendly implementation name."""
        return f"Canvas ({self._host})"

    @property
    def extra_authorize_data(self) -> dict[str, str]:
        """Request only the scopes this integration needs."""
        return {
            "scope": " ".join(CANVAS_OAUTH_SCOPES),
        }
