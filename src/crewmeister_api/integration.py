"""Integration API service for Crewmeister V3."""

from __future__ import annotations

from collections.abc import Mapping

from crewmeister_api.client import CrewmeisterApiClient, JsonValue, QueryValue
from crewmeister_api.resources import (
    LIST_RESOURCE_OPERATION,
    ResourceApiService,
    ResourceEndpoint,
    TaskEndpoint,
    prefixed_endpoint,
    prefixed_task,
)

INTEGRATION_PREFIX = "/api/v3/integration"

INTEGRATION_RESOURCES: tuple[ResourceEndpoint, ...] = (
    prefixed_endpoint(INTEGRATION_PREFIX, "connections"),
    ResourceEndpoint(
        name="oauth-status",
        path=f"{INTEGRATION_PREFIX}/oauth-status",
        supported_operations=LIST_RESOURCE_OPERATION,
    ),
)
INTEGRATION_RESOURCE_NAMES = tuple(resource.name for resource in INTEGRATION_RESOURCES)

INTEGRATION_TASKS: tuple[TaskEndpoint, ...] = (
    prefixed_task(INTEGRATION_PREFIX, "i-cal-subscription", "i-cal-subscription-tasks"),
)
INTEGRATION_TASK_NAMES = tuple(task.name for task in INTEGRATION_TASKS)


class IntegrationApiService(ResourceApiService):
    """Service facade for Crewmeister Integration resources and tasks."""

    def __init__(self, client: CrewmeisterApiClient) -> None:
        super().__init__(client, INTEGRATION_RESOURCES, INTEGRATION_TASKS)

    def i_cal_subscription_task(
        self,
        payload: JsonValue,
        *,
        query: Mapping[str, QueryValue] | None = None,
        async_write: bool = False,
    ) -> JsonValue:
        """Invoke the Integration iCal subscription task."""

        return self.run_task("i-cal-subscription", payload, query=query, async_write=async_write)
