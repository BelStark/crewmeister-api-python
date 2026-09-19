"""Notification API service for Crewmeister V3."""

from __future__ import annotations

from crewmeister_api.client import CrewmeisterApiClient
from crewmeister_api.resources import (
    ResourceApiService,
    ResourceEndpoint,
    prefixed_endpoint,
)

NOTIFICATION_PREFIX = "/api/v3/notifications"


NOTIFICATION_RESOURCES: tuple[ResourceEndpoint, ...] = (
    prefixed_endpoint(NOTIFICATION_PREFIX, "news"),
    prefixed_endpoint(NOTIFICATION_PREFIX, "user-news-settings"),
    prefixed_endpoint(NOTIFICATION_PREFIX, "user-push-tokens"),
    prefixed_endpoint(NOTIFICATION_PREFIX, "user-reminder-settings"),
)
NOTIFICATION_RESOURCE_NAMES = tuple(resource.name for resource in NOTIFICATION_RESOURCES)


class NotificationApiService(ResourceApiService):
    """Service facade for Crewmeister Notification resources."""

    def __init__(self, client: CrewmeisterApiClient) -> None:
        super().__init__(client, NOTIFICATION_RESOURCES)
