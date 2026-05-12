"""Sensor platform for Canvas LMS."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlsplit

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_BASE_URL, DOMAIN, MAX_ATTRIBUTE_ITEMS
from .coordinator import CanvasDataUpdateCoordinator, CanvasSnapshot


@dataclass(frozen=True, kw_only=True)
class CanvasSensorDescription(SensorEntityDescription):
    """Describe a Canvas-backed sensor."""

    value_fn: Callable[[CanvasSnapshot], Any]
    attrs_fn: Callable[[CanvasSnapshot], dict[str, Any]]


def _serialize_assignments(assignments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prepare assignment data for state attributes."""
    serialized: list[dict[str, Any]] = []
    for assignment in assignments[:MAX_ATTRIBUTE_ITEMS]:
        serialized.append(
            {
                "title": assignment["title"],
                "course": assignment.get("course_name"),
                "due_at": assignment["due_at"].isoformat()
                if assignment.get("due_at") is not None
                else None,
                "url": assignment.get("html_url"),
                "points_possible": assignment.get("points_possible"),
            }
        )
    return serialized


def _serialize_courses(courses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prepare course summaries for state attributes."""
    serialized: list[dict[str, Any]] = []
    for course in courses[:MAX_ATTRIBUTE_ITEMS]:
        serialized.append(
            {
                "name": course["name"],
                "course_code": course.get("course_code"),
                "workflow_state": course.get("workflow_state"),
                "concluded": course.get("concluded"),
                "score": course.get("score"),
                "grade": course.get("grade"),
                "needs_grading_count": course.get("needs_grading_count"),
                "due_today_count": course.get("due_today_count"),
                "due_window_count": course.get("due_window_count"),
                "next_due_title": course.get("next_due_title"),
                "next_due_at": course["next_due_at"].isoformat()
                if course.get("next_due_at") is not None
                else None,
                "teachers": course.get("teachers"),
                "url": course.get("html_url"),
            }
        )
    return serialized


SENSOR_DESCRIPTIONS: tuple[CanvasSensorDescription, ...] = (
    CanvasSensorDescription(
        key="next_assignment_due",
        name="Next assignment due",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: data.next_assignment["due_at"] if data.next_assignment else None,
        attrs_fn=lambda data: {
            "assignment": data.next_assignment["title"] if data.next_assignment else None,
            "course": data.next_assignment["course_name"] if data.next_assignment else None,
            "url": data.next_assignment["html_url"] if data.next_assignment else None,
            "points_possible": data.next_assignment["points_possible"]
            if data.next_assignment
            else None,
            "upcoming_assignments": _serialize_assignments(data.upcoming_assignments),
        },
    ),
    CanvasSensorDescription(
        key="upcoming_assignments",
        name="Upcoming assignments",
        value_fn=lambda data: data.due_window_count,
        attrs_fn=lambda data: {
            "window_days": data.assignment_window_days,
            "assignments": _serialize_assignments(data.upcoming_assignments),
        },
    ),
    CanvasSensorDescription(
        key="assignments_due_today",
        name="Assignments due today",
        value_fn=lambda data: data.due_today_count,
        attrs_fn=lambda data: {
            "window_days": data.assignment_window_days,
            "assignments": _serialize_assignments(data.due_today_assignments),
        },
    ),
    CanvasSensorDescription(
        key="missing_assignments",
        name="Missing assignments",
        value_fn=lambda data: data.missing_count,
        attrs_fn=lambda data: {
            "assignments": _serialize_assignments(data.missing_assignments),
        },
    ),
    CanvasSensorDescription(
        key="courses_tracked",
        name="Courses tracked",
        value_fn=lambda data: len(data.courses),
        attrs_fn=lambda data: {
            "courses": _serialize_courses(data.courses),
            "user": data.profile.get("name"),
            "email": data.profile.get("primary_email"),
        },
    ),
    CanvasSensorDescription(
        key="assignments_needing_grading",
        name="Assignments needing grading",
        value_fn=lambda data: data.grading_count,
        attrs_fn=lambda data: {
            "courses": _serialize_courses(
                [course for course in data.courses if course["needs_grading_count"] > 0]
            ),
        },
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Canvas sensors from a config entry."""
    coordinator: CanvasDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(CanvasSensor(coordinator, entry, description) for description in SENSOR_DESCRIPTIONS)


class CanvasSensor(CoordinatorEntity[CanvasDataUpdateCoordinator], SensorEntity):
    """Generic sensor backed by a Canvas snapshot."""

    entity_description: CanvasSensorDescription

    def __init__(
        self,
        coordinator: CanvasDataUpdateCoordinator,
        entry: ConfigEntry,
        description: CanvasSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_name = description.name
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"

        host = urlsplit(entry.data[CONF_BASE_URL]).netloc or entry.data[CONF_BASE_URL]
        profile_name = coordinator.data.profile.get("short_name") or coordinator.data.profile.get("name")

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"Canvas LMS ({profile_name or host})",
            manufacturer="Instructure",
            model=host,
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=entry.data[CONF_BASE_URL],
        )

    @property
    def native_value(self) -> Any:
        """Return the current sensor state."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes for the sensor."""
        return self.entity_description.attrs_fn(self.coordinator.data)
