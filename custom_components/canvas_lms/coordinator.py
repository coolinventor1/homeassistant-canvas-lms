"""Coordinator for Canvas LMS data refreshes."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    OAuth2TokenRequestError,
    OAuth2TokenRequestReauthError,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import CanvasApiClient, CanvasApiError, CanvasAuthError
from .const import (
    CONF_ASSIGNMENT_WINDOW_DAYS,
    CONF_INCLUDE_COMPLETED_COURSES,
    CONF_SCAN_INTERVAL_MINUTES,
    DEFAULT_ASSIGNMENT_WINDOW_DAYS,
    DEFAULT_INCLUDE_COMPLETED_COURSES,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
)


@dataclass(slots=True)
class CanvasSnapshot:
    """Normalized Canvas data for entity consumption."""

    profile: dict[str, Any]
    courses: list[dict[str, Any]]
    upcoming_assignments: list[dict[str, Any]]
    due_today_assignments: list[dict[str, Any]]
    missing_assignments: list[dict[str, Any]]
    next_assignment: dict[str, Any] | None
    due_today_count: int
    due_window_count: int
    missing_count: int
    grading_count: int
    assignment_window_days: int


class CanvasDataUpdateCoordinator(DataUpdateCoordinator[CanvasSnapshot]):
    """Poll Canvas and keep a normalized snapshot in memory."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: CanvasApiClient,
    ) -> None:
        """Initialize the coordinator."""
        self._entry = entry
        self._client = client
        interval_minutes = entry.options.get(
            CONF_SCAN_INTERVAL_MINUTES,
            entry.data.get(CONF_SCAN_INTERVAL_MINUTES, DEFAULT_SCAN_INTERVAL_MINUTES),
        )

        super().__init__(
            hass,
            logger=logging.getLogger(__name__),
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(minutes=interval_minutes),
        )

    async def _async_update_data(self) -> CanvasSnapshot:
        """Fetch, normalize, and aggregate the latest Canvas data."""
        include_completed = self._entry.options.get(
            CONF_INCLUDE_COMPLETED_COURSES,
            self._entry.data.get(
                CONF_INCLUDE_COMPLETED_COURSES,
                DEFAULT_INCLUDE_COMPLETED_COURSES,
            ),
        )
        assignment_window_days = self._entry.options.get(
            CONF_ASSIGNMENT_WINDOW_DAYS,
            self._entry.data.get(
                CONF_ASSIGNMENT_WINDOW_DAYS,
                DEFAULT_ASSIGNMENT_WINDOW_DAYS,
            ),
        )

        try:
            profile = self.data.profile if self.data is not None else await self._client.async_validate()
            raw_courses, raw_missing = await asyncio.gather(
                self._client.async_get_courses(include_completed=include_completed),
                self._client.async_get_missing_assignments(),
            )
            course_context_codes = [f"course_{course['id']}" for course in raw_courses]
            raw_assignments = await self._client.async_get_upcoming_assignments(
                window_days=assignment_window_days,
                context_codes=course_context_codes,
            )
        except (CanvasAuthError, OAuth2TokenRequestReauthError) as err:
            raise ConfigEntryAuthFailed(
                "Canvas authentication failed. Re-authentication is required."
            ) from err
        except OAuth2TokenRequestError as err:
            raise UpdateFailed("Canvas OAuth token refresh failed.") from err
        except CanvasApiError as err:
            raise UpdateFailed(str(err)) from err

        now = dt_util.now()
        local_today = dt_util.as_local(now).date()

        courses = [_normalize_course(course) for course in raw_courses]
        course_lookup = {course["id"]: course for course in courses}
        assignment_details, analytics_by_course = await asyncio.gather(
            _async_fetch_assignment_details(
                self._client,
                raw_assignments,
            ),
            _async_fetch_course_assignment_analytics(
                self._client,
                str(profile["id"]),
                raw_courses,
            ),
        )

        all_assignments = sorted(
            (
                normalized
                for item in raw_assignments
                if (
                    normalized := _normalize_calendar_assignment(
                        item,
                        course_lookup,
                        assignment_details,
                    )
                )
                is not None
            ),
            key=lambda item: item["due_at"],
        )

        course_metrics: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "due_today_count": 0,
                "due_window_count": 0,
                "next_due_at": None,
                "next_due_title": None,
            }
        )
        future_assignments: list[dict[str, Any]] = []
        due_today_assignments: list[dict[str, Any]] = []
        due_today_count = 0

        for assignment in all_assignments:
            due_at: datetime = assignment["due_at"]
            course_id = assignment["course_id"]
            local_due_date = dt_util.as_local(due_at).date()
            is_pending = assignment["needs_attention"]

            if local_due_date == local_today and is_pending:
                due_today_count += 1
                due_today_assignments.append(assignment)
                course_metrics[course_id]["due_today_count"] += 1

            if due_at >= now and is_pending:
                future_assignments.append(assignment)
                course_metrics[course_id]["due_window_count"] += 1
                current_next_due = course_metrics[course_id]["next_due_at"]
                if current_next_due is None or due_at < current_next_due:
                    course_metrics[course_id]["next_due_at"] = due_at
                    course_metrics[course_id]["next_due_title"] = assignment["title"]

        for course in courses:
            last_graded = _extract_last_graded_assignment(
                analytics_by_course.get(course["id"], [])
            )
            metrics = course_metrics[course["id"]]
            course["due_today_count"] = metrics["due_today_count"]
            course["due_window_count"] = metrics["due_window_count"]
            course["next_due_at"] = metrics["next_due_at"]
            course["next_due_title"] = metrics["next_due_title"]
            course["last_graded_assignment_title"] = (
                last_graded["title"] if last_graded is not None else None
            )
            course["last_graded_score"] = (
                last_graded["score"] if last_graded is not None else None
            )
            course["last_graded_points_possible"] = (
                last_graded["points_possible"] if last_graded is not None else None
            )
            course["last_graded_score_display"] = (
                last_graded["score_display"] if last_graded is not None else None
            )
            course["last_graded_due_at"] = (
                last_graded["due_at"] if last_graded is not None else None
            )
            course["last_graded_posted_at"] = (
                last_graded["posted_at"] if last_graded is not None else None
            )

        courses.sort(
            key=lambda course: (
                course["next_due_at"] is None,
                course["next_due_at"] or dt_util.utcnow(),
                course["name"].lower(),
            )
        )

        missing_assignments = sorted(
            (
                normalized
                for item in raw_missing
                if (normalized := _normalize_missing_assignment(item, course_lookup)) is not None
            ),
            key=lambda item: item["due_at"] or dt_util.utcnow(),
        )

        return CanvasSnapshot(
            profile=profile,
            courses=courses,
            upcoming_assignments=future_assignments,
            due_today_assignments=due_today_assignments,
            missing_assignments=missing_assignments,
            next_assignment=future_assignments[0] if future_assignments else None,
            due_today_count=due_today_count,
            due_window_count=len(future_assignments),
            missing_count=len(missing_assignments),
            grading_count=sum(course["needs_grading_count"] for course in courses),
            assignment_window_days=assignment_window_days,
        )


def _normalize_course(course: dict[str, Any]) -> dict[str, Any]:
    """Convert a raw Canvas course into a compact summary."""
    enrollment = _pick_primary_enrollment(course.get("enrollments", []))
    teachers = [
        teacher.get("display_name") or teacher.get("name")
        for teacher in course.get("teachers", [])
        if teacher.get("display_name") or teacher.get("name")
    ]

    return {
        "id": str(course["id"]),
        "name": course.get("name") or f"Course {course['id']}",
        "course_code": course.get("course_code"),
        "workflow_state": course.get("workflow_state"),
        "concluded": bool(course.get("concluded")),
        "html_url": course.get("html_url"),
        "teachers": teachers,
        "score": _extract_score(enrollment),
        "grade": _extract_grade(enrollment),
        "needs_grading_count": int(course.get("needs_grading_count") or 0),
        "last_graded_assignment_title": None,
        "last_graded_score": None,
        "last_graded_points_possible": None,
        "last_graded_score_display": None,
        "last_graded_due_at": None,
        "last_graded_posted_at": None,
    }


def _pick_primary_enrollment(enrollments: list[dict[str, Any]]) -> dict[str, Any]:
    """Pick the enrollment most likely to contain grade data for the current user."""
    for enrollment in enrollments:
        enrollment_type = str(enrollment.get("type") or "").lower()
        if "student" in enrollment_type:
            return enrollment
    return enrollments[0] if enrollments else {}


def _extract_score(enrollment: dict[str, Any]) -> float | None:
    """Extract a numeric score from an enrollment if Canvas exposed one."""
    current_grading_period = enrollment.get("current_grading_period_scores") or {}
    for candidate in (
        enrollment.get("computed_current_score"),
        current_grading_period.get("current_score"),
        enrollment.get("computed_final_score"),
        current_grading_period.get("final_score"),
    ):
        if candidate is not None:
            try:
                return float(candidate)
            except (TypeError, ValueError):
                return None
    return None


def _extract_grade(enrollment: dict[str, Any]) -> str | None:
    """Extract a grade label from an enrollment if available."""
    current_grading_period = enrollment.get("current_grading_period_scores") or {}
    for candidate in (
        enrollment.get("computed_current_grade"),
        current_grading_period.get("current_grade"),
        enrollment.get("computed_final_grade"),
        current_grading_period.get("final_grade"),
    ):
        if candidate:
            return str(candidate)
    return None


def _normalize_calendar_assignment(
    event: dict[str, Any],
    course_lookup: dict[str, dict[str, Any]],
    assignment_details: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any] | None:
    """Normalize an assignment event returned by the Canvas calendar API."""
    due_at = _parse_canvas_datetime(event.get("start_at"))
    if due_at is None:
        return None

    assignment = event.get("assignment") or {}
    course_id = _extract_course_id(event)
    course = course_lookup.get(course_id, {})
    assignment_id = str(assignment.get("id") or event.get("id"))
    detail = assignment_details.get((course_id, assignment_id), {})
    submission = detail.get("submission") or {}

    return {
        "id": assignment_id,
        "title": event.get("title") or assignment.get("name") or "Untitled assignment",
        "course_id": course_id,
        "course_name": course.get("name") or event.get("context_name"),
        "due_at": due_at,
        "html_url": event.get("html_url"),
        "points_possible": assignment.get("points_possible"),
        "submission_types": assignment.get("submission_types") or [],
        "submission_state": submission.get("workflow_state"),
        "submitted_at": _parse_canvas_datetime(submission.get("submitted_at")),
        "needs_attention": _submission_needs_attention(submission),
    }


def _normalize_missing_assignment(
    assignment: dict[str, Any],
    course_lookup: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Normalize a missing submission payload returned by Canvas."""
    course = assignment.get("course") or {}
    course_id = str(assignment.get("course_id") or course.get("id") or "")
    if not course_id:
        return None

    course_summary = course_lookup.get(course_id, {})

    return {
        "id": str(assignment["id"]),
        "title": assignment.get("name") or assignment.get("title") or "Untitled assignment",
        "course_id": course_id,
        "course_name": course.get("name") or course_summary.get("name"),
        "due_at": _parse_canvas_datetime(assignment.get("due_at")),
        "html_url": assignment.get("html_url"),
        "points_possible": assignment.get("points_possible"),
    }


def _extract_course_id(event: dict[str, Any]) -> str:
    """Extract a Canvas course id from a calendar event."""
    if course_id := event.get("course_id"):
        return str(course_id)

    context_code = event.get("context_code") or ""
    if context_code.startswith("course_"):
        return context_code.removeprefix("course_")

    assignment = event.get("assignment") or {}
    if assignment_course_id := assignment.get("course_id"):
        return str(assignment_course_id)

    return "unknown"


def _parse_canvas_datetime(value: str | None) -> datetime | None:
    """Parse a Canvas ISO datetime into a timezone-aware datetime."""
    if not value:
        return None

    parsed = dt_util.parse_datetime(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt_util.UTC)
    return parsed


def _submission_needs_attention(submission: dict[str, Any]) -> bool:
    """Return whether an assignment still appears unsubmitted for the current user."""
    if not submission:
        return True

    if submission.get("excused"):
        return False

    if submission.get("missing"):
        return True

    workflow_state = str(submission.get("workflow_state") or "").lower()
    if workflow_state in {"submitted", "graded", "pending_review"}:
        return False

    submitted_at = submission.get("submitted_at")
    if submitted_at:
        return False

    return True


async def _async_fetch_assignment_details(
    client: CanvasApiClient,
    raw_assignments: list[dict[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    """Fetch submission-aware assignment details for the current due-window items."""
    grouped_ids: dict[str, set[str]] = defaultdict(set)
    for event in raw_assignments:
        assignment = event.get("assignment") or {}
        course_id = _extract_course_id(event)
        assignment_id = str(assignment.get("id") or event.get("id") or "")
        if not course_id or course_id == "unknown" or not assignment_id:
            continue
        grouped_ids[course_id].add(assignment_id)

    if not grouped_ids:
        return {}

    detail_map: dict[tuple[str, str], dict[str, Any]] = {}
    responses = await asyncio.gather(
        *(
            client.async_get_assignment_details(course_id, sorted(assignment_ids))
            for course_id, assignment_ids in grouped_ids.items()
        )
    )

    for course_id, details in zip(grouped_ids, responses, strict=False):
        for detail in details:
            detail_map[(course_id, str(detail["id"]))] = detail

    return detail_map


async def _async_fetch_course_assignment_analytics(
    client: CanvasApiClient,
    user_id: str,
    raw_courses: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Fetch per-course assignment analytics for the current user."""
    course_ids = [str(course["id"]) for course in raw_courses]
    if not course_ids:
        return {}

    responses = await asyncio.gather(
        *(client.async_get_course_assignment_analytics(course_id, user_id) for course_id in course_ids)
    )

    return {
        course_id: analytics
        for course_id, analytics in zip(course_ids, responses, strict=False)
    }


def _extract_last_graded_assignment(
    analytics_rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Pick the most recent graded assignment from the analytics feed."""
    candidates: list[dict[str, Any]] = []
    for row in analytics_rows:
        submission = row.get("submission") or {}
        score = submission.get("score")
        if score is None:
            continue

        due_at = _parse_canvas_datetime(row.get("due_at"))
        posted_at = _parse_canvas_datetime(submission.get("posted_at"))
        submitted_at = _parse_canvas_datetime(submission.get("submitted_at"))
        ranking_date = posted_at or submitted_at or due_at
        if ranking_date is None:
            continue

        score_value = _safe_float(score)
        points_possible = _safe_float(row.get("points_possible"))
        candidates.append(
            {
                "title": row.get("title") or "Untitled assignment",
                "score": score_value,
                "points_possible": points_possible,
                "score_display": _format_score_display(score_value, points_possible),
                "due_at": due_at,
                "posted_at": posted_at,
                "ranking_date": ranking_date,
            }
        )

    if not candidates:
        return None

    candidates.sort(
        key=lambda item: (
            item["ranking_date"],
            item["due_at"] or item["ranking_date"],
        ),
        reverse=True,
    )
    return candidates[0]


def _safe_float(value: Any) -> float | None:
    """Convert a value to float when possible."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_score_display(score: float | None, points_possible: float | None) -> str | None:
    """Format a score as `earned / possible` for display."""
    if score is None:
        return None
    if points_possible is None:
        return _format_number(score)
    return f"{_format_number(score)} / {_format_number(points_possible)}"


def _format_number(value: float) -> str:
    """Format whole-number-like floats cleanly for UI presentation."""
    if value.is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")
