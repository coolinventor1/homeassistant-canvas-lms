"""Canvas LMS API client."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
import re
from typing import Any

import aiohttp
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.util import dt as dt_util

from .const import DEFAULT_REQUEST_TIMEOUT

_LINK_RE = re.compile(r'<([^>]+)>;\s*rel="([^"]+)"')


class CanvasApiError(Exception):
    """Base API error."""


class CanvasAuthError(CanvasApiError):
    """Raised when Canvas rejects the provided credentials."""


class CanvasConnectionError(CanvasApiError):
    """Raised when Canvas cannot be reached."""


class CanvasApiClient:
    """Small async client for the Canvas LMS REST API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        bearer_token: str | None = None,
        oauth_session: config_entry_oauth2_flow.OAuth2Session | None = None,
    ) -> None:
        """Store client dependencies."""
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._oauth_session = oauth_session
        self._headers = {"Accept": "application/json"}
        if bearer_token:
            self._headers["Authorization"] = f"Bearer {bearer_token}"
        self._timeout = aiohttp.ClientTimeout(total=DEFAULT_REQUEST_TIMEOUT)

    async def async_validate(self) -> dict[str, Any]:
        """Validate credentials and return the current user profile."""
        return await self._async_get_json("/api/v1/users/self/profile")

    async def async_get_courses(self, include_completed: bool) -> list[dict[str, Any]]:
        """Fetch courses for the current user."""
        params: dict[str, Any] = {
            "include[]": [
                "total_scores",
                "current_grading_period_scores",
                "teachers",
                "needs_grading_count",
            ],
            "per_page": 100,
            "state[]": ["available"],
        }
        if include_completed:
            params["state[]"].append("completed")
        return await self._async_paginated_get("/api/v1/courses", params=params)

    async def async_get_upcoming_assignments(
        self, window_days: int
    ) -> list[dict[str, Any]]:
        """Fetch upcoming assignment calendar items across courses."""
        start_of_day = dt_util.start_of_local_day()
        params = {
            "type": "assignment",
            "start_date": start_of_day.isoformat(),
            "end_date": (start_of_day + timedelta(days=window_days + 1)).isoformat(),
            "per_page": 100,
        }
        return await self._async_paginated_get("/api/v1/calendar_events", params=params)

    async def async_get_missing_assignments(self) -> list[dict[str, Any]]:
        """Fetch currently missing submissions."""
        params = {
            "include[]": ["course"],
            "per_page": 100,
        }
        return await self._async_paginated_get(
            "/api/v1/users/self/missing_submissions",
            params=params,
        )

    async def _async_get_json(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Fetch a single JSON document."""
        payload, _ = await self._async_request_json(self._build_url(path), params=params)
        if not isinstance(payload, dict):
            raise CanvasApiError("Expected a JSON object from Canvas.")
        return payload

    async def _async_paginated_get(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Follow Canvas pagination until every page is fetched."""
        next_url = self._build_url(path)
        next_params = params
        items: list[dict[str, Any]] = []

        while next_url:
            payload, headers = await self._async_request_json(next_url, params=next_params)
            if not isinstance(payload, list):
                raise CanvasApiError("Expected a paginated JSON array from Canvas.")
            items.extend(item for item in payload if isinstance(item, dict))
            next_url = self._parse_next_link(headers.get("Link"))
            next_params = None

        return items

    async def _async_request_json(
        self,
        url: str,
        params: Mapping[str, Any] | None = None,
    ) -> tuple[Any, Mapping[str, str]]:
        """Perform a GET request and decode the JSON response."""
        response: aiohttp.ClientResponse | None = None
        try:
            if self._oauth_session is not None:
                response = await self._oauth_session.async_request(
                    "GET",
                    url,
                    params=params,
                    timeout=self._timeout,
                    headers=self._headers,
                )
            else:
                response = await self._session.get(
                    url,
                    headers=self._headers,
                    params=params,
                    timeout=self._timeout,
                )

            if response.status in (401, 403):
                raise CanvasAuthError("Canvas rejected the supplied credentials.")
            if response.status >= 400:
                detail = await response.text()
                raise CanvasApiError(
                    f"Canvas returned HTTP {response.status}: {detail[:200]}"
                )
            return await response.json(content_type=None), response.headers
        except aiohttp.ClientError as err:
            raise CanvasConnectionError("Could not reach the Canvas API.") from err
        except TimeoutError as err:
            raise CanvasConnectionError("Canvas API request timed out.") from err
        finally:
            if response is not None:
                response.release()

    def _build_url(self, path: str) -> str:
        """Build an absolute request URL from an API path."""
        return f"{self._base_url}{path}"

    @staticmethod
    def _parse_next_link(link_header: str | None) -> str | None:
        """Extract the `next` pagination URL from a Link header."""
        if not link_header:
            return None

        for match in _LINK_RE.finditer(link_header):
            if match.group(2) == "next":
                return match.group(1)

        return None
