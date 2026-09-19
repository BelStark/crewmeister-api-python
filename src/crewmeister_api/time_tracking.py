"""Time Tracking API service for Crewmeister V3."""

from __future__ import annotations

from collections.abc import Mapping

from crewmeister_api.client import CrewmeisterApiClient, JsonValue, QueryValue
from crewmeister_api.resources import (
    LIST_RESOURCE_OPERATION,
    ResourceApiService,
    ResourceEndpoint,
    TaskEndpoint,
    prefixed_endpoint,
    prefixed_read_only_endpoint,
    prefixed_task,
)

TIME_TRACKING_PREFIX = "/api/v3/timetracking"


TIME_TRACKING_RESOURCES: tuple[ResourceEndpoint, ...] = (
    prefixed_endpoint(TIME_TRACKING_PREFIX, "bookings"),
    prefixed_read_only_endpoint(TIME_TRACKING_PREFIX, "day-kind-calendar-days"),
    prefixed_read_only_endpoint(TIME_TRACKING_PREFIX, "durations"),
    prefixed_read_only_endpoint(TIME_TRACKING_PREFIX, "duration-balances"),
    prefixed_read_only_endpoint(TIME_TRACKING_PREFIX, "duration-definitions"),
    prefixed_endpoint(TIME_TRACKING_PREFIX, "public-holiday-calendar-settings"),
    prefixed_endpoint(TIME_TRACKING_PREFIX, "public-holiday-templates"),
    prefixed_endpoint(TIME_TRACKING_PREFIX, "stamps"),
    prefixed_endpoint(TIME_TRACKING_PREFIX, "terminal-settings"),
    prefixed_read_only_endpoint(TIME_TRACKING_PREFIX, "time-accounts"),
    prefixed_endpoint(TIME_TRACKING_PREFIX, "time-account-settings"),
    prefixed_endpoint(TIME_TRACKING_PREFIX, "time-categories"),
    prefixed_endpoint(TIME_TRACKING_PREFIX, "time-location-settings"),
    prefixed_endpoint(TIME_TRACKING_PREFIX, "time-tracking-reports"),
    prefixed_endpoint(TIME_TRACKING_PREFIX, "working-time-models"),
)
TIME_TRACKING_RESOURCE_NAMES = tuple(resource.name for resource in TIME_TRACKING_RESOURCES)
TIME_TRACKING_READ_ONLY_RESOURCE_NAMES = frozenset(
    resource.name for resource in TIME_TRACKING_RESOURCES if resource.supported_operations == LIST_RESOURCE_OPERATION
)

TIME_TRACKING_TASKS: tuple[TaskEndpoint, ...] = (
    prefixed_task(TIME_TRACKING_PREFIX, "set-break-in-stamp-chain", "set-break-in-stamp-chain-tasks"),
    TaskEndpoint(
        name="time-tracking-report",
        path=f"{TIME_TRACKING_PREFIX}/time-tracking-report-tasks",
        job_collection_path=f"{TIME_TRACKING_PREFIX}/time-tracking-report-task-jobs",
    ),
)
TIME_TRACKING_TASK_NAMES = tuple(task.name for task in TIME_TRACKING_TASKS)


class TimeTrackingApiService(ResourceApiService):
    """Service facade for Crewmeister Time Tracking resources and tasks."""

    def __init__(self, client: CrewmeisterApiClient) -> None:
        super().__init__(client, TIME_TRACKING_RESOURCES, TIME_TRACKING_TASKS)

    def set_break_in_stamp_chain_task(
        self,
        payload: JsonValue,
        *,
        query: Mapping[str, QueryValue] | None = None,
        async_write: bool = False,
    ) -> JsonValue:
        """Invoke the Time Tracking stamp-chain break task."""

        return self.run_task("set-break-in-stamp-chain", payload, query=query, async_write=async_write)

    def time_tracking_report_task(
        self,
        payload: JsonValue,
        *,
        query: Mapping[str, QueryValue] | None = None,
        async_write: bool = False,
    ) -> JsonValue:
        """Invoke the Time Tracking report generation task."""

        return self.run_task("time-tracking-report", payload, query=query, async_write=async_write)
