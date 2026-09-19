"""Crewmeister API client foundation."""

from crewmeister_api.absence_manager import AbsenceManagerApiService
from crewmeister_api.audit import AuditApiService
from crewmeister_api.catalog import describe_api
from crewmeister_api.client import (
    CrewmeisterApiClient,
    CrewmeisterApiConfig,
    CrewmeisterApiError,
    CrewmeisterApiResponse,
    CrewmeisterAuthenticationError,
    CrewmeisterConfigError,
    CrewmeisterError,
    CrewmeisterTransportError,
    HttpResponse,
    JsonObject,
    JsonValue,
    QueryValue,
    Transport,
)
from crewmeister_api.integration import IntegrationApiService
from crewmeister_api.notification import NotificationApiService
from crewmeister_api.platform import PlatformApiService
from crewmeister_api.salary_export import SalaryExportApiService
from crewmeister_api.shift_planner import ShiftPlannerApiService
from crewmeister_api.time_tracking import TimeTrackingApiService

__all__ = [
    "CrewmeisterApiClient",
    "CrewmeisterApiConfig",
    "CrewmeisterApiError",
    "CrewmeisterApiResponse",
    "CrewmeisterAuthenticationError",
    "CrewmeisterConfigError",
    "CrewmeisterError",
    "AbsenceManagerApiService",
    "AuditApiService",
    "IntegrationApiService",
    "NotificationApiService",
    "PlatformApiService",
    "SalaryExportApiService",
    "ShiftPlannerApiService",
    "TimeTrackingApiService",
    "CrewmeisterTransportError",
    "describe_api",
    "JsonValue",
    "JsonObject",
    "QueryValue",
    "HttpResponse",
    "Transport",
]
