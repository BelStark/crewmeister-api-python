"""Platform API service for Crewmeister V3."""

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

PLATFORM_PREFIX = "/api/v3/platform-app"

PLATFORM_RESOURCE_NAMES = (
    "admins",
    "admin-authentication-tokens",
    "admin-roles",
    "crews",
    "crew-authentication-tokens",
    "crew-sizes",
    "customers",
    "downgrade-actions",
    "feature-flag-settings",
    "members",
    "member-roles",
    "payouts",
    "prices",
    "products",
    "subscriptions",
    "teams",
    "usage-rights",
    "users",
    "user-authentication-tokens",
    "vouchers",
)

PLATFORM_RESOURCES: tuple[ResourceEndpoint, ...] = tuple(
    prefixed_endpoint(PLATFORM_PREFIX, name) for name in PLATFORM_RESOURCE_NAMES
)

PLATFORM_TASKS: tuple[TaskEndpoint, ...] = (
    prefixed_task(PLATFORM_PREFIX, "get-current-user", "get-current-user-tasks"),
    prefixed_task(PLATFORM_PREFIX, "subscription-action", "subscription-action-tasks"),
)
PLATFORM_TASK_NAMES = tuple(task.name for task in PLATFORM_TASKS)


class PlatformApiService(ResourceApiService):
    """Service facade for Crewmeister Platform resources and tasks."""

    def __init__(self, client: CrewmeisterApiClient) -> None:
        super().__init__(client, PLATFORM_RESOURCES, PLATFORM_TASKS)

    def get_current_user_task(
        self,
        payload: JsonValue,
        *,
        query: Mapping[str, QueryValue] | None = None,
        async_write: bool = False,
    ) -> JsonValue:
        """Invoke the Platform current-user task."""

        return self.run_task("get-current-user", payload, query=query, async_write=async_write)

    def subscription_action_task(
        self,
        payload: JsonValue,
        *,
        query: Mapping[str, QueryValue] | None = None,
        async_write: bool = False,
    ) -> JsonValue:
        """Invoke the Platform subscription-action task."""

        return self.run_task("subscription-action", payload, query=query, async_write=async_write)
