"""Shift Planner API service for Crewmeister V3."""

from __future__ import annotations

from collections.abc import Mapping

from crewmeister_api.client import CrewmeisterApiClient, JsonValue, QueryValue
from crewmeister_api.resources import (
    ResourceApiService,
    ResourceEndpoint,
    TaskEndpoint,
    prefixed_endpoint,
    prefixed_task,
)

SHIFT_PLANNER_PREFIX = "/api/v3/shiftplanner"

SHIFT_PLANNER_RESOURCES: tuple[ResourceEndpoint, ...] = (
    prefixed_endpoint(SHIFT_PLANNER_PREFIX, "shifts"),
    prefixed_endpoint(SHIFT_PLANNER_PREFIX, "shift-grace-period-settings"),
    prefixed_endpoint(SHIFT_PLANNER_PREFIX, "shift-offer-replies"),
    prefixed_endpoint(SHIFT_PLANNER_PREFIX, "shift-visibility-settings"),
    prefixed_endpoint(SHIFT_PLANNER_PREFIX, "shift-working-time-settings"),
    prefixed_endpoint(SHIFT_PLANNER_PREFIX, "templates"),
    prefixed_endpoint(SHIFT_PLANNER_PREFIX, "template-shifts"),
    prefixed_endpoint(SHIFT_PLANNER_PREFIX, "workplaces"),
)
SHIFT_PLANNER_RESOURCE_NAMES = tuple(resource.name for resource in SHIFT_PLANNER_RESOURCES)

SHIFT_PLANNER_TASKS: tuple[TaskEndpoint, ...] = (
    prefixed_task(SHIFT_PLANNER_PREFIX, "shift-apply-template", "shift-apply-template-tasks"),
    prefixed_task(SHIFT_PLANNER_PREFIX, "shift-copy", "shift-copy-tasks"),
    prefixed_task(SHIFT_PLANNER_PREFIX, "shift-publish", "shift-publish-tasks"),
)
SHIFT_PLANNER_TASK_NAMES = tuple(task.name for task in SHIFT_PLANNER_TASKS)


class ShiftPlannerApiService(ResourceApiService):
    """Service facade for Crewmeister Shift Planner resources and tasks."""

    def __init__(self, client: CrewmeisterApiClient) -> None:
        super().__init__(client, SHIFT_PLANNER_RESOURCES, SHIFT_PLANNER_TASKS)

    def shift_apply_template_task(
        self,
        payload: JsonValue,
        *,
        query: Mapping[str, QueryValue] | None = None,
        async_write: bool = False,
    ) -> JsonValue:
        """Invoke the Shift Planner apply-template task."""

        return self.run_task("shift-apply-template", payload, query=query, async_write=async_write)

    def shift_copy_task(
        self,
        payload: JsonValue,
        *,
        query: Mapping[str, QueryValue] | None = None,
        async_write: bool = False,
    ) -> JsonValue:
        """Invoke the Shift Planner copy task."""

        return self.run_task("shift-copy", payload, query=query, async_write=async_write)

    def shift_publish_task(
        self,
        payload: JsonValue,
        *,
        query: Mapping[str, QueryValue] | None = None,
        async_write: bool = False,
    ) -> JsonValue:
        """Invoke the Shift Planner publish task."""

        return self.run_task("shift-publish", payload, query=query, async_write=async_write)
