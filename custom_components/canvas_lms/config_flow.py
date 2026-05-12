"""Config flow for Canvas LMS."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit, urlunsplit

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CanvasApiClient, CanvasAuthError, CanvasConnectionError
from .const import (
    CONF_API_TOKEN,
    CONF_ASSIGNMENT_WINDOW_DAYS,
    CONF_BASE_URL,
    CONF_INCLUDE_COMPLETED_COURSES,
    CONF_SCAN_INTERVAL_MINUTES,
    DEFAULT_ASSIGNMENT_WINDOW_DAYS,
    DEFAULT_INCLUDE_COMPLETED_COURSES,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
)


class InvalidCanvasUrl(ValueError):
    """Raised when the supplied Canvas URL is malformed."""


class CanvasLmsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Canvas LMS."""

    VERSION = 1

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
                normalized_data = {
                    **user_input,
                    CONF_BASE_URL: _normalize_base_url(user_input[CONF_BASE_URL]),
                }
                info = await _async_validate_input(self.hass, normalized_data)
            except InvalidCanvasUrl:
                errors[CONF_BASE_URL] = "invalid_url"
            except CanvasAuthError:
                errors["base"] = "invalid_auth"
            except CanvasConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # pragma: no cover - defensive guard
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(f"{info['host']}:{info['user_id']}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=info["title"], data=normalized_data)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_BASE_URL,
                        default=(user_input or {}).get(CONF_BASE_URL, "https://"),
                    ): str,
                    vol.Required(CONF_API_TOKEN): str,
                }
            ),
            errors=errors,
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


async def _async_validate_input(
    hass,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Validate the user input and extract account metadata."""
    client = CanvasApiClient(
        session=async_get_clientsession(hass),
        base_url=data[CONF_BASE_URL],
        api_token=data[CONF_API_TOKEN],
    )
    profile = await client.async_validate()
    parsed = urlsplit(data[CONF_BASE_URL])

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

