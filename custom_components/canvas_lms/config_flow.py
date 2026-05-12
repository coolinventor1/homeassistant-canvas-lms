"""Config flow for Canvas LMS."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CanvasApiClient, CanvasApiError, CanvasConnectionError
from .const import (
    CONF_ASSIGNMENT_WINDOW_DAYS,
    CONF_BASE_URL,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_INCLUDE_COMPLETED_COURSES,
    CONF_SCAN_INTERVAL_MINUTES,
    DEFAULT_ASSIGNMENT_WINDOW_DAYS,
    DEFAULT_INCLUDE_COMPLETED_COURSES,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
)
from .oauth import CanvasOAuth2Implementation

_LOGGER = logging.getLogger(__name__)


class InvalidCanvasUrl(ValueError):
    """Raised when the supplied Canvas URL is malformed."""


class CanvasLmsConfigFlow(
    config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN
):
    """Handle a config flow for Canvas LMS."""

    DOMAIN = DOMAIN
    VERSION = 2

    def __init__(self) -> None:
        """Initialize the Canvas config flow."""
        super().__init__()
        self._base_url = ""
        self._client_id = ""
        self._client_secret = ""
        self._reauth_entry: config_entries.ConfigEntry | None = None

    @property
    def logger(self) -> logging.Logger:
        """Return the logger for the OAuth flow helper."""
        return _LOGGER

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the options flow handler."""
        return CanvasLmsOptionsFlow(config_entry)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial setup step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                self._configure_oauth(user_input)
            except InvalidCanvasUrl:
                errors[CONF_BASE_URL] = "invalid_url"
            else:
                return await self.async_step_auth()

        return self._async_show_oauth_form("user", user_input, errors)

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        """Handle re-authentication requests."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if self._reauth_entry is None:
            return self.async_abort(reason="unknown")

        self._base_url = self._reauth_entry.data.get(CONF_BASE_URL, "")
        self._client_id = self._reauth_entry.data.get(CONF_CLIENT_ID, "")
        self._client_secret = self._reauth_entry.data.get(CONF_CLIENT_SECRET, "")
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm Canvas re-authentication."""
        if user_input is not None:
            if not all((self._base_url, self._client_id, self._client_secret)):
                return self.async_abort(reason="missing_oauth_configuration")
            self.flow_impl = CanvasOAuth2Implementation(
                self.hass,
                self._base_url,
                self._client_id,
                self._client_secret,
            )
            return await self.async_step_auth()

        return self.async_show_form(
            step_id="reauth_confirm",
            description_placeholders={
                "host": urlsplit(self._base_url).netloc or self._base_url
            },
        )

    async def async_oauth_create_entry(self, data: dict[str, Any]) -> FlowResult:
        """Create or update a config entry after OAuth succeeds."""
        try:
            info = await _async_validate_oauth_login(
                self.hass,
                self._base_url,
                data["token"]["access_token"],
            )
        except CanvasConnectionError:
            return self.async_abort(reason="cannot_connect")
        except CanvasApiError:
            return self.async_abort(reason="oauth_error")

        unique_id = f"{info['host']}:{info['user_id']}"
        entry_data = {
            CONF_BASE_URL: self._base_url,
            CONF_CLIENT_ID: self._client_id,
            CONF_CLIENT_SECRET: self._client_secret,
            **data,
        }

        if self._reauth_entry is not None:
            if self._reauth_entry.unique_id and self._reauth_entry.unique_id != unique_id:
                return self.async_abort(reason="wrong_account")

            self.hass.config_entries.async_update_entry(
                self._reauth_entry,
                data={**self._reauth_entry.data, **entry_data},
                title=info["title"],
                unique_id=unique_id,
            )
            return self.async_abort(reason="reauth_successful")

        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=info["title"], data=entry_data)

    def _async_show_oauth_form(
        self,
        step_id: str,
        user_input: dict[str, Any] | None,
        errors: dict[str, str],
    ) -> FlowResult:
        """Show the OAuth setup form."""
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_BASE_URL,
                        default=(user_input or {}).get(CONF_BASE_URL, "https://"),
                    ): str,
                    vol.Required(
                        CONF_CLIENT_ID,
                        default=(user_input or {}).get(CONF_CLIENT_ID, ""),
                    ): str,
                    vol.Required(CONF_CLIENT_SECRET): str,
                }
            ),
            errors=errors,
            description_placeholders={
                "redirect_uri": _get_redirect_uri_placeholder(self.hass),
            },
        )

    def _configure_oauth(self, user_input: dict[str, Any]) -> None:
        """Store normalized OAuth settings for the flow."""
        self._base_url = _normalize_base_url(user_input[CONF_BASE_URL])
        self._client_id = user_input[CONF_CLIENT_ID].strip()
        self._client_secret = user_input[CONF_CLIENT_SECRET].strip()
        self.flow_impl = CanvasOAuth2Implementation(
            self.hass,
            self._base_url,
            self._client_id,
            self._client_secret,
        )


class CanvasLmsOptionsFlow(config_entries.OptionsFlow):
    """Handle Canvas LMS options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Store the config entry being edited."""
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the options form."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self._config_entry.options
        data = self._config_entry.data

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL_MINUTES,
                        default=options.get(
                            CONF_SCAN_INTERVAL_MINUTES,
                            data.get(
                                CONF_SCAN_INTERVAL_MINUTES,
                                DEFAULT_SCAN_INTERVAL_MINUTES,
                            ),
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=5, max=180)),
                    vol.Required(
                        CONF_ASSIGNMENT_WINDOW_DAYS,
                        default=options.get(
                            CONF_ASSIGNMENT_WINDOW_DAYS,
                            data.get(
                                CONF_ASSIGNMENT_WINDOW_DAYS,
                                DEFAULT_ASSIGNMENT_WINDOW_DAYS,
                            ),
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=90)),
                    vol.Required(
                        CONF_INCLUDE_COMPLETED_COURSES,
                        default=options.get(
                            CONF_INCLUDE_COMPLETED_COURSES,
                            data.get(
                                CONF_INCLUDE_COMPLETED_COURSES,
                                DEFAULT_INCLUDE_COMPLETED_COURSES,
                            ),
                        ),
                    ): bool,
                }
            ),
        )


async def _async_validate_oauth_login(
    hass,
    base_url: str,
    access_token: str,
) -> dict[str, Any]:
    """Validate OAuth login details and extract account metadata."""
    client = CanvasApiClient(
        session=async_get_clientsession(hass),
        base_url=base_url,
        bearer_token=access_token,
    )
    profile = await client.async_validate()
    parsed = urlsplit(base_url)

    return {
        "title": f"{profile.get('short_name') or profile.get('name') or 'Canvas'} @ {parsed.netloc}",
        "host": parsed.netloc.lower(),
        "user_id": profile["id"],
    }


def _normalize_base_url(value: str) -> str:
    """Normalize user-provided Canvas URLs into a stable base URL."""
    candidate = value.strip()
    if "://" not in candidate:
        candidate = f"https://{candidate}"

    parsed = urlsplit(candidate)
    if not parsed.scheme or not parsed.netloc:
        raise InvalidCanvasUrl

    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path.rstrip("/"),
            "",
            "",
        )
    )


def _get_redirect_uri_placeholder(hass) -> str:
    """Return the best available redirect URI hint for the setup form."""
    try:
        return config_entry_oauth2_flow.async_get_redirect_uri(hass)
    except Exception:  # pragma: no cover - depends on runtime request context
        return "https://<your-home-assistant>/auth/external/callback"
