"""Offline descriptions of the Crewmeister V3 operations exposed by this package."""

from __future__ import annotations

from collections.abc import Mapping
from importlib.metadata import version

from crewmeister_api.categories import API_CATEGORIES, BINARY_DOWNLOAD_RESOURCES
from crewmeister_api.client import AUTH_PATH
from crewmeister_api.resources import ResourceOperation

_RESOURCE_OPERATIONS: tuple[ResourceOperation, ...] = (
    "list",
    "get",
    "create",
    "batch",
    "patch",
    "replace",
    "delete",
)
_METHODS: Mapping[ResourceOperation, str] = {
    "list": "GET",
    "get": "GET",
    "create": "POST",
    "batch": "PATCH",
    "patch": "PATCH",
    "replace": "PUT",
    "delete": "DELETE",
}
_MCP_FAMILIES = {
    "list": "crewmeister_list",
    "get": "crewmeister_get",
    "create": "crewmeister_create",
    "batch": "crewmeister_batch",
    "patch": "crewmeister_patch",
    "replace": "crewmeister_replace",
    "delete": "crewmeister_delete",
    "task": "crewmeister_task",
    "job": "crewmeister_job",
}
_ITEM_OPERATIONS = frozenset({"get", "patch", "replace", "delete"})
_PAYLOAD_OPERATIONS = frozenset({"create", "batch", "patch", "replace"})
_WRITE_OPERATIONS = frozenset({"create", "batch", "patch", "replace", "delete"})
CatalogOperation = dict[str, str | bool | None]


def describe_api(category_name: str | None = None, endpoint_name: str | None = None) -> dict[str, object]:
    """Return an offline catalog index or the operations for one registered endpoint."""

    if category_name is None:
        if endpoint_name is not None:
            raise ValueError("An endpoint can only be described with its category.")
        categories = []
        operation_count = 1
        for name, category in API_CATEGORIES.items():
            category_operations = _category_operations(name)
            operation_count += len(category_operations)
            categories.append(
                {
                    "name": name,
                    "resources": list(category.resources),
                    "tasks": list(category.tasks),
                    "operation_count": len(category_operations),
                }
            )
        return _document(
            authentication=_authentication_operation(), categories=categories, operation_count=operation_count
        )

    if category_name not in API_CATEGORIES:
        raise ValueError(f"Unknown Crewmeister category: {category_name}")
    operations = _category_operations(category_name)
    if endpoint_name is not None:
        operations = [operation for operation in operations if operation["name"] == endpoint_name]
        if not operations:
            raise ValueError(f"Unknown Crewmeister endpoint: {category_name} {endpoint_name}")
    return _document(
        category=category_name, endpoint=endpoint_name, operation_count=len(operations), operations=operations
    )


def _document(**content: object) -> dict[str, object]:
    return {
        "catalog_version": 1,
        "package_version": version("crewmeister-api"),
        "mcp_status": "available with crewmeister-api[mcp] via crewmeister-mcp",
        "mcp_families": dict(_MCP_FAMILIES),
        "mcp_write_confirmation": "confirm=true",
        "limitations": [
            "Technical availability does not confirm provider permission.",
            "Unverified payload schemas and business result contracts remain provider-specific.",
            "Job paths are marked live-verified or guideline-derived; neither is an explicit OpenAPI operation.",
        ],
        "cli": {
            "query_options": {
                "filter": "--filter TEXT",
                "sort": "--sort VALUE (repeatable)",
                "query": "--query KEY=VALUE (repeatable)",
            },
            "payload_option": "--json-file PATH|-",
            "write_confirmation": "--yes",
            "async_write": "--async adds X-Write-Async: true to a confirmed write",
            "job_read": "registered resource: RESOURCE job JOB_ID; registered task: job TASK JOB_ID",
            "i_cal_output": "integration task i-cal-subscription --output-file PATH writes only a new owner-only file",
            "page_options": {
                "page": "--page INTEGER >= 0",
                "page_size": "--page-size INTEGER > 0",
                "limit": "--limit INTEGER >= 0; cannot be combined with --page",
            },
            "list_output": "streamed redacted JSON array; --page returns one redacted provider page",
            "result_output": "redacted JSON; check a zero exit status before accepting a streamed list",
            "implicit_authentication": (
                "username/password login precedes an authenticated operation when no bearer token exists"
            ),
        },
        **content,
    }


def _category_operations(category_name: str) -> list[CatalogOperation]:
    category = API_CATEGORIES[category_name]
    operations: list[CatalogOperation] = []
    for resource in category.resources.values():
        operations.extend(
            _resource_operation(category_name, resource.name, resource.path, operation)
            for operation in _RESOURCE_OPERATIONS
            if resource.supports(operation)
        )
        if (category_name, resource.name) in BINARY_DOWNLOAD_RESOURCES:
            operations.append(_download_operation(category_name, resource.name, resource.path))
        operations.append(_job_operation(category_name, "resource", resource.name, resource.path))
    for task in category.tasks.values():
        operations.append(_task_operation(category_name, task.name, task.path))
        operations.append(
            _job_operation(category_name, "task", task.name, task.path, collection_path=task.job_collection_path)
        )
    return operations


def _authentication_operation() -> CatalogOperation:
    return {
        "kind": "authentication",
        "category": None,
        "name": "user",
        "operation": "authenticate",
        "mcp_family": None,
        "mcp_confirm": False,
        "method": "POST",
        "path": AUTH_PATH,
        "item_id": False,
        "cli_json_payload": False,
        "http_json_body": True,
        "pageable": False,
        "credential_source": "configured bearer token or configured username/password",
        "side_effect": "authentication",
    }


def _resource_operation(category: str, resource: str, path: str, operation: ResourceOperation) -> CatalogOperation:
    item_id = operation in _ITEM_OPERATIONS
    return {
        "kind": "resource",
        "category": category,
        "name": resource,
        "operation": operation,
        "mcp_family": _MCP_FAMILIES[operation],
        "mcp_confirm": operation in _WRITE_OPERATIONS,
        "method": _METHODS[operation],
        "path": f"{path}/{{id}}" if item_id else path,
        "item_id": item_id,
        "cli_json_payload": operation in _PAYLOAD_OPERATIONS,
        "http_json_body": operation in _PAYLOAD_OPERATIONS,
        "pageable": operation == "list",
        "side_effect": "write" if operation in _WRITE_OPERATIONS else "read",
    }


def _task_operation(category: str, task: str, path: str) -> CatalogOperation:
    return {
        "kind": "task",
        "category": category,
        "name": task,
        "operation": "task",
        "mcp_family": _MCP_FAMILIES["task"],
        "mcp_confirm": True,
        "method": "POST",
        "path": path,
        "item_id": False,
        "cli_json_payload": True,
        "http_json_body": True,
        "pageable": False,
        "side_effect": "write",
    }


def _download_operation(category: str, resource: str, path: str) -> CatalogOperation:
    return {
        "kind": "resource",
        "category": category,
        "name": resource,
        "operation": "download",
        "mcp_family": None,
        "mcp_confirm": False,
        "method": None,
        "path": None,
        "metadata_method": "GET",
        "metadata_path": f"{path}/{{id}}",
        "binary_method": "GET",
        "binary_reference": "binaryContentReference",
        "item_id": True,
        "cli_json_payload": False,
        "http_json_body": False,
        "pageable": False,
        "side_effect": "read",
        "sdk_method": "download_resource",
        "output": "binary file",
    }


def _job_operation(
    category: str, kind: str, name: str, path: str, *, collection_path: str | None = None
) -> CatalogOperation:
    return {
        "kind": kind,
        "category": category,
        "name": name,
        "operation": "job",
        "mcp_family": _MCP_FAMILIES["job"],
        "mcp_confirm": False,
        "method": "GET",
        "path": f"{collection_path or f'{path}-jobs'}/{{job_id}}",
        "item_id": False,
        "cli_json_payload": False,
        "http_json_body": False,
        "pageable": False,
        "side_effect": "read",
        "contract": "live-verified" if collection_path else "guideline-derived",
    }
