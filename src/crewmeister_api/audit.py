"""Audit API service for Crewmeister V3."""

from __future__ import annotations

from crewmeister_api.client import CrewmeisterApiClient
from crewmeister_api.resources import (
    ResourceApiService,
    ResourceEndpoint,
    prefixed_endpoint,
)

AUDIT_PREFIX = "/api/v3/audit-app"


AUDIT_RESOURCES: tuple[ResourceEndpoint, ...] = (
    prefixed_endpoint(AUDIT_PREFIX, "changelogs"),
    prefixed_endpoint(AUDIT_PREFIX, "changelog-settings"),
)
AUDIT_RESOURCE_NAMES = tuple(resource.name for resource in AUDIT_RESOURCES)


class AuditApiService(ResourceApiService):
    """Service facade for Crewmeister Audit resources."""

    def __init__(self, client: CrewmeisterApiClient) -> None:
        super().__init__(client, AUDIT_RESOURCES)
