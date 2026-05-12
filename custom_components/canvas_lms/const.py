"""Shared constants for Canvas LMS."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "canvas_lms"
PLATFORMS = [Platform.SENSOR]

CONF_BASE_URL = "base_url"
CONF_API_TOKEN = "api_token"
CONF_ASSIGNMENT_WINDOW_DAYS = "assignment_window_days"
CONF_SCAN_INTERVAL_MINUTES = "scan_interval_minutes"
CONF_INCLUDE_COMPLETED_COURSES = "include_completed_courses"

DEFAULT_ASSIGNMENT_WINDOW_DAYS = 14
DEFAULT_SCAN_INTERVAL_MINUTES = 15
DEFAULT_INCLUDE_COMPLETED_COURSES = False
DEFAULT_REQUEST_TIMEOUT = 30

MAX_ATTRIBUTE_ITEMS = 25

