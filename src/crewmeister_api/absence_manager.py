"""Absence Manager API service for Crewmeister V3."""

from __future__ import annotations

from crewmeister_api.client import CrewmeisterApiClient
from crewmeister_api.resources import (
    LIST_RESOURCE_OPERATION,
    ResourceApiService,
    ResourceEndpoint,
    prefixed_endpoint,
    prefixed_read_only_endpoint,
)

ABSENCE_MANAGER_PREFIX = "/api/v3/absencemanager"


ABSENCE_MANAGER_RESOURCES: tuple[ResourceEndpoint, ...] = (
    prefixed_endpoint(ABSENCE_MANAGER_PREFIX, "absences"),
    prefixed_read_only_endpoint(ABSENCE_MANAGER_PREFIX, "absence-entitlements"),
    prefixed_endpoint(ABSENCE_MANAGER_PREFIX, "absence-type-settings"),
    prefixed_endpoint(ABSENCE_MANAGER_PREFIX, "absence-visibility-settings"),
    prefixed_endpoint(ABSENCE_MANAGER_PREFIX, "entitlement-adjustments"),
    prefixed_read_only_endpoint(ABSENCE_MANAGER_PREFIX, "entitlement-balances"),
    prefixed_endpoint(ABSENCE_MANAGER_PREFIX, "working-days"),
)
ABSENCE_MANAGER_RESOURCE_NAMES = tuple(resource.name for resource in ABSENCE_MANAGER_RESOURCES)
ABSENCE_MANAGER_READ_ONLY_RESOURCE_NAMES = frozenset(
    resource.name for resource in ABSENCE_MANAGER_RESOURCES if resource.supported_operations == LIST_RESOURCE_OPERATION
)


class AbsenceManagerApiService(ResourceApiService):
    """Service facade for Crewmeister Absence Manager resources."""

    def __init__(self, client: CrewmeisterApiClient) -> None:
        super().__init__(client, ABSENCE_MANAGER_RESOURCES)
