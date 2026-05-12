"""Shared constants for Canvas LMS."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "canvas_lms"
PLATFORMS = [Platform.SENSOR]

CONF_AUTH_MODE = "auth_mode"
CONF_BASE_URL = "base_url"
CONF_API_TOKEN = "api_token"
CONF_BROWSER_COOKIE = "browser_cookie"
CONF_CLIENT_ID = "client_id"
CONF_CLIENT_SECRET = "client_secret"
CONF_ASSIGNMENT_WINDOW_DAYS = "assignment_window_days"
CONF_SCAN_INTERVAL_MINUTES = "scan_interval_minutes"
CONF_INCLUDE_COMPLETED_COURSES = "include_completed_courses"

DEFAULT_ASSIGNMENT_WINDOW_DAYS = 14
DEFAULT_SCAN_INTERVAL_MINUTES = 15
DEFAULT_INCLUDE_COMPLETED_COURSES = False
DEFAULT_REQUEST_TIMEOUT = 30

MAX_ATTRIBUTE_ITEMS = 25

AUTH_MODE_BROWSER_SESSION = "browser_session"
AUTH_MODE_OAUTH = "oauth"

CANVAS_OAUTH_SCOPES = (
    "url:GET|/api/v1/users/self/profile",
    "url:GET|/api/v1/courses",
    "url:GET|/api/v1/calendar_events",
    "url:GET|/api/v1/users/self/missing_submissions",
)
