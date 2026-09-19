"""Crewmeister API category metadata for CLI dispatch."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from crewmeister_api.absence_manager import (
    ABSENCE_MANAGER_RESOURCES,
    AbsenceManagerApiService,
)
from crewmeister_api.audit import AUDIT_RESOURCES, AuditApiService
from crewmeister_api.client import CrewmeisterApiClient
from crewmeister_api.integration import (
    INTEGRATION_RESOURCES,
    INTEGRATION_TASKS,
    IntegrationApiService,
)
from crewmeister_api.notification import NOTIFICATION_RESOURCES, NotificationApiService
from crewmeister_api.platform import PLATFORM_RESOURCES, PLATFORM_TASKS, PlatformApiService
from crewmeister_api.resources import ResourceApiService, ResourceEndpoint, TaskEndpoint
from crewmeister_api.salary_export import (
    SALARY_EXPORT_RESOURCES,
    SalaryExportApiService,
)
from crewmeister_api.shift_planner import (
    SHIFT_PLANNER_RESOURCES,
    SHIFT_PLANNER_TASKS,
    ShiftPlannerApiService,
)
from crewmeister_api.time_tracking import (
    TIME_TRACKING_RESOURCES,
    TIME_TRACKING_TASKS,
    TimeTrackingApiService,
)

INTEGRATION_SENSITIVE_EXACT_KEYS = frozenset({"calendarurl", "feedurl", "icalfeedurl", "icalurl"})


@dataclass(frozen=True)
class ApiCategorySpec:
    """CLI metadata for a Crewmeister API category."""

    name: str
    display_name: str
    service_type: Callable[[CrewmeisterApiClient], ResourceApiService]
    resources: Mapping[str, ResourceEndpoint]
    tasks: Mapping[str, TaskEndpoint]
    sensitive_exact_keys: frozenset[str] = frozenset()


API_CATEGORIES: Mapping[str, ApiCategorySpec] = {
    "platform": ApiCategorySpec(
        name="platform",
        display_name="Platform",
        service_type=PlatformApiService,
        resources={resource.name: resource for resource in PLATFORM_RESOURCES},
        tasks={task.name: task for task in PLATFORM_TASKS},
    ),
    "integration": ApiCategorySpec(
        name="integration",
        display_name="Integration",
        service_type=IntegrationApiService,
        resources={resource.name: resource for resource in INTEGRATION_RESOURCES},
        tasks={task.name: task for task in INTEGRATION_TASKS},
        sensitive_exact_keys=INTEGRATION_SENSITIVE_EXACT_KEYS,
    ),
    "time-tracking": ApiCategorySpec(
        name="time-tracking",
        display_name="Time Tracking",
        service_type=TimeTrackingApiService,
        resources={resource.name: resource for resource in TIME_TRACKING_RESOURCES},
        tasks={task.name: task for task in TIME_TRACKING_TASKS},
    ),
    "absence-manager": ApiCategorySpec(
        name="absence-manager",
        display_name="Absence Manager",
        service_type=AbsenceManagerApiService,
        resources={resource.name: resource for resource in ABSENCE_MANAGER_RESOURCES},
        tasks={},
    ),
    "shift-planner": ApiCategorySpec(
        name="shift-planner",
        display_name="Shift Planner",
        service_type=ShiftPlannerApiService,
        resources={resource.name: resource for resource in SHIFT_PLANNER_RESOURCES},
        tasks={task.name: task for task in SHIFT_PLANNER_TASKS},
    ),
    "salary-export": ApiCategorySpec(
        name="salary-export",
        display_name="Salary Export",
        service_type=SalaryExportApiService,
        resources={resource.name: resource for resource in SALARY_EXPORT_RESOURCES},
        tasks={},
    ),
    "audit": ApiCategorySpec(
        name="audit",
        display_name="Audit",
        service_type=AuditApiService,
        resources={resource.name: resource for resource in AUDIT_RESOURCES},
        tasks={},
    ),
    "notification": ApiCategorySpec(
        name="notification",
        display_name="Notification",
        service_type=NotificationApiService,
        resources={resource.name: resource for resource in NOTIFICATION_RESOURCES},
        tasks={},
    ),
}

BINARY_DOWNLOAD_RESOURCES = frozenset({("time-tracking", "time-tracking-reports"), ("salary-export", "salary-exports")})
