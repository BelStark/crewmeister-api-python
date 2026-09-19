"""Salary Export API service for Crewmeister V3."""

from __future__ import annotations

from crewmeister_api.client import CrewmeisterApiClient
from crewmeister_api.resources import (
    ResourceApiService,
    ResourceEndpoint,
    prefixed_endpoint,
)

SALARY_EXPORT_PREFIX = "/api/v3/salaryexport"


SALARY_EXPORT_RESOURCES: tuple[ResourceEndpoint, ...] = (
    prefixed_endpoint(SALARY_EXPORT_PREFIX, "salary-exports"),
    prefixed_endpoint(SALARY_EXPORT_PREFIX, "salary-export-configurations"),
    prefixed_endpoint(SALARY_EXPORT_PREFIX, "wage-type-allocation-absence-days"),
    prefixed_endpoint(SALARY_EXPORT_PREFIX, "wage-type-allocation-duration-hours"),
    ResourceEndpoint(
        name="salary-export-generation-tasks",
        path=f"{SALARY_EXPORT_PREFIX}/salary-export-generation-tasks",
        supported_operations=frozenset({"batch"}),
    ),
)
SALARY_EXPORT_RESOURCE_NAMES = tuple(resource.name for resource in SALARY_EXPORT_RESOURCES)


class SalaryExportApiService(ResourceApiService):
    """Service facade for Crewmeister Salary Export resources."""

    def __init__(self, client: CrewmeisterApiClient) -> None:
        super().__init__(client, SALARY_EXPORT_RESOURCES)
