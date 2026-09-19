"""Local STDIO MCP adapter for the registered Crewmeister API operations."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections.abc import Mapping, Sequence
from importlib.metadata import version
from threading import RLock
from typing import cast
from urllib.parse import urlsplit

from crewmeister_api.catalog import describe_api
from crewmeister_api.categories import API_CATEGORIES
from crewmeister_api.client import (
    CrewmeisterApiClient,
    CrewmeisterApiConfig,
    CrewmeisterApiError,
    CrewmeisterConfigError,
    CrewmeisterError,
    CrewmeisterTransportError,
    JsonValue,
    QueryValue,
)
from crewmeister_api.configuration import load_env_file
from crewmeister_api.resources import ResourceOperation, job_path
from crewmeister_api.safe_output import redact_sensitive, structured_error

_METHODS: Mapping[ResourceOperation, str] = {
    "list": "GET",
    "get": "GET",
    "create": "POST",
    "batch": "PATCH",
    "patch": "PATCH",
    "replace": "PUT",
    "delete": "DELETE",
}
_ITEM_OPERATIONS = frozenset({"get", "patch", "replace", "delete"})
_PAYLOAD_OPERATIONS = frozenset({"create", "batch", "patch", "replace"})
_WRITE_OPERATIONS = _PAYLOAD_OPERATIONS | {"delete"}


class McpRouter:
    """Route fixed MCP operation families through one existing SDK client."""

    def __init__(self, client: CrewmeisterApiClient) -> None:
        self.client = client
        self._lock = RLock()

    def describe(self, category: str | None = None, endpoint: str | None = None) -> dict[str, object]:
        """Return the offline SDK operation catalog."""

        try:
            return describe_api(category, endpoint)
        except ValueError:
            return self._invalid()

    def list(
        self,
        category: str,
        resource: str,
        *,
        query: Mapping[str, object] | None = None,
        page: int = 0,
        page_size: int | None = None,
    ) -> dict[str, object]:
        """Fetch one registered collection page."""

        if not isinstance(page, int) or isinstance(page, bool) or page < 0:
            return self._invalid()
        if page_size is not None and (not isinstance(page_size, int) or isinstance(page_size, bool) or page_size <= 0):
            return self._invalid()
        values = self._query(query)
        if values is None or {"page", "pageSize"} & values.keys():
            return self._invalid()
        values.update(page=page, pageSize=page_size or self.client.config.page_size)
        return self._request("list", category, resource, query=values)

    def get(
        self, category: str, resource: str, item_id: str, *, query: Mapping[str, object] | None = None
    ) -> dict[str, object]:
        """Fetch one registered resource item."""

        return self._request("get", category, resource, item_id=item_id, query=self._query(query))

    def create(
        self,
        category: str,
        resource: str,
        payload: object,
        *,
        confirm: bool = False,
        query: Mapping[str, object] | None = None,
        async_write: bool = False,
    ) -> dict[str, object]:
        """Create through one registered collection endpoint."""

        return self._request(
            "create",
            category,
            resource,
            payload=payload,
            confirm=confirm,
            query=self._query(query),
            async_write=async_write,
        )

    def batch(
        self,
        category: str,
        resource: str,
        payload: object,
        *,
        confirm: bool = False,
        query: Mapping[str, object] | None = None,
        async_write: bool = False,
    ) -> dict[str, object]:
        """Send a registered collection-level PATCH request."""

        return self._request(
            "batch",
            category,
            resource,
            payload=payload,
            confirm=confirm,
            query=self._query(query),
            async_write=async_write,
        )

    def patch(
        self,
        category: str,
        resource: str,
        item_id: str,
        payload: object,
        *,
        confirm: bool = False,
        query: Mapping[str, object] | None = None,
        async_write: bool = False,
    ) -> dict[str, object]:
        """Patch a registered resource item."""

        return self._request(
            "patch",
            category,
            resource,
            item_id=item_id,
            payload=payload,
            confirm=confirm,
            query=self._query(query),
            async_write=async_write,
        )

    def replace(
        self,
        category: str,
        resource: str,
        item_id: str,
        payload: object,
        *,
        confirm: bool = False,
        query: Mapping[str, object] | None = None,
        async_write: bool = False,
    ) -> dict[str, object]:
        """Replace a registered resource item."""

        return self._request(
            "replace",
            category,
            resource,
            item_id=item_id,
            payload=payload,
            confirm=confirm,
            query=self._query(query),
            async_write=async_write,
        )

    def delete(
        self,
        category: str,
        resource: str,
        item_id: str,
        *,
        confirm: bool = False,
        query: Mapping[str, object] | None = None,
        async_write: bool = False,
    ) -> dict[str, object]:
        """Delete a registered resource item."""

        return self._request(
            "delete",
            category,
            resource,
            item_id=item_id,
            confirm=confirm,
            query=self._query(query),
            async_write=async_write,
        )

    def task(
        self,
        category: str,
        task: str,
        payload: object,
        *,
        confirm: bool = False,
        query: Mapping[str, object] | None = None,
        async_write: bool = False,
    ) -> dict[str, object]:
        """Run one registered Crewmeister task endpoint."""

        if confirm is not True:
            return self._confirmation()
        if (
            not isinstance(category, str)
            or not isinstance(task, str)
            or not isinstance(async_write, bool)
            or (values := self._query(query)) is None
            or not _json_value(payload)
        ):
            return self._invalid(write=True)
        try:
            category_spec = API_CATEGORIES[category]
            endpoint = category_spec.tasks[task]
            with self._lock:
                if error := self._authentication_error():
                    return self._error(error, write=True)
                response = self.client.request_with_response(
                    "POST",
                    endpoint.path,
                    query=values,
                    json_body=cast(JsonValue, payload),
                    headers={"X-Write-Async": "true"} if async_write else None,
                )
            return self._success(response.status_code, response.payload, category_spec.sensitive_exact_keys)
        except KeyError:
            return self._invalid(write=True)
        except (CrewmeisterError, OSError) as exc:
            return self._error(exc, write=True, sent=True)

    def job(self, category: str, kind: str, endpoint: str, job_id: str) -> dict[str, object]:
        """Read a job for one registered resource or task endpoint."""

        try:
            if not all(isinstance(value, str) and value for value in (category, kind, endpoint, job_id)):
                raise CrewmeisterConfigError("Invalid MCP tool input.")
            category_spec = API_CATEGORIES[category]
            path = (category_spec.resources if kind == "resource" else category_spec.tasks if kind == "task" else {})[
                endpoint
            ].path
            collection = category_spec.tasks[endpoint].job_collection_path if kind == "task" else None
            with self._lock:
                if error := self._authentication_error():
                    return self._error(error, write=False)
                response = self.client.request_with_response("GET", job_path(path, job_id, collection_path=collection))
            return self._success(response.status_code, response.payload, category_spec.sensitive_exact_keys, job=True)
        except KeyError:
            return self._invalid()
        except (CrewmeisterError, OSError) as exc:
            return self._error(exc, write=False, sent=True)

    def _request(
        self,
        operation: ResourceOperation,
        category: str,
        resource: str,
        *,
        item_id: str | None = None,
        payload: object = None,
        confirm: bool = False,
        query: Mapping[str, QueryValue] | None = None,
        async_write: bool = False,
    ) -> dict[str, object]:
        write = operation in _WRITE_OPERATIONS
        if write and confirm is not True:
            return self._confirmation()
        if (
            query is None
            or not isinstance(async_write, bool)
            or (operation in _PAYLOAD_OPERATIONS and not _json_value(payload))
        ):
            return self._invalid(write=write)
        try:
            if not isinstance(category, str) or not isinstance(resource, str):
                raise CrewmeisterConfigError("Invalid MCP tool input.")
            endpoint = API_CATEGORIES[category].resources[resource]
            if not endpoint.supports(operation):
                raise CrewmeisterConfigError("Unsupported Crewmeister operation.")
            if operation in _ITEM_OPERATIONS:
                if not isinstance(item_id, str) or not item_id:
                    raise CrewmeisterConfigError("Invalid MCP tool input.")
                path = endpoint.item_path(item_id)
            else:
                path = endpoint.path
            with self._lock:
                if error := self._authentication_error():
                    return self._error(error, write=write)
                response = self.client.request_with_response(
                    _METHODS[operation],
                    path,
                    query=query,
                    json_body=cast(JsonValue, payload) if operation in _PAYLOAD_OPERATIONS else None,
                    headers={"X-Write-Async": "true"} if async_write else None,
                )
            return self._success(response.status_code, response.payload, API_CATEGORIES[category].sensitive_exact_keys)
        except KeyError:
            return self._invalid(write=write)
        except (CrewmeisterError, OSError) as exc:
            return self._error(exc, write=write, sent=True)

    def _authentication_error(self) -> CrewmeisterError | OSError | None:
        try:
            if not self.client.authenticate():
                return CrewmeisterTransportError("Crewmeister auth response did not contain a token.")
        except (CrewmeisterError, OSError) as exc:
            return exc
        return None

    @staticmethod
    def _query(query: Mapping[str, object] | None) -> dict[str, QueryValue] | None:
        if query is None:
            return {}
        if not isinstance(query, Mapping):
            return None
        values: dict[str, QueryValue] = {}
        for key, value in query.items():
            if not isinstance(key, str) or not key or not _query_value(value):
                return None
            values[key] = cast(QueryValue, value)
        return values

    @staticmethod
    def _invalid(*, write: bool = False) -> dict[str, object]:
        result: dict[str, object] = {"error": structured_error(CrewmeisterConfigError("Invalid MCP tool input."))}
        if write:
            result["outcome"] = "not_sent"
        return result

    @staticmethod
    def _confirmation() -> dict[str, object]:
        return {
            "outcome": "not_sent",
            "error": {"type": "confirmation", "message": "Write confirmation required."},
        }

    @staticmethod
    def _success(
        status: int, payload: JsonValue, sensitive_exact_keys: frozenset[str], *, job: bool = False
    ) -> dict[str, object]:
        return {
            "outcome": _job_outcome(payload) if job else "accepted" if status == 202 else "completed",
            "status": status,
            "payload": redact_sensitive(payload, sensitive_exact_keys=sensitive_exact_keys),
        }

    @staticmethod
    def _error(exc: CrewmeisterError | OSError, *, write: bool, sent: bool = False) -> dict[str, object]:
        result: dict[str, object] = {"error": structured_error(exc)}
        if write:
            result["outcome"] = (
                "not_sent"
                if not sent or isinstance(exc, CrewmeisterConfigError)
                else "rejected" if isinstance(exc, CrewmeisterApiError) and 400 <= exc.status_code < 500 else "unknown"
            )
        return result


def _query_value(value: object) -> bool:
    return (
        value is None
        or isinstance(value, str | int | bool)
        or isinstance(value, float)
        and math.isfinite(value)
        or (
            isinstance(value, list)
            and all(
                item is None or isinstance(item, str | int | bool) or isinstance(item, float) and math.isfinite(item)
                for item in value
            )
        )
    )


def _json_value(value: object) -> bool:
    try:
        json.dumps(value, allow_nan=False)
    except TypeError, ValueError, RecursionError:
        return False
    return True


def _job_status(payload: JsonValue) -> str | None:
    status = payload.get("status") if isinstance(payload, dict) else None
    return status if isinstance(status, str) else None


def _job_outcome(payload: JsonValue) -> str:
    status = _job_status(payload)
    if not status:
        return "unknown"
    return {"ERROR": "rejected", "SUCCESS": "completed", "WAITING": "pending", "PROCESSING": "pending"}.get(
        status, "unknown"
    )


def create_server(router: McpRouter):
    """Create the optional STDIO MCP server without performing API I/O."""

    try:
        from mcp.server import MCPServer
        from mcp.types import ToolAnnotations
    except ImportError:
        raise CrewmeisterConfigError("Install crewmeister-api[mcp] to run the MCP server.") from None
    server = MCPServer("Crewmeister", description="Local Crewmeister API adapter.")
    read = ToolAnnotations(read_only_hint=True, open_world_hint=True)
    write = ToolAnnotations(read_only_hint=False, open_world_hint=True)

    @server.tool(description="Inspect registered operations offline before selecting an endpoint.", annotations=read)
    def crewmeister_describe(category: str | None = None, endpoint: str | None = None) -> dict[str, object]:
        return router.describe(category, endpoint)

    @server.tool(description="Read one registered collection page.", annotations=read)
    def crewmeister_list(
        category: str,
        resource: str,
        query: dict[str, object] | None = None,
        page: int = 0,
        page_size: int | None = None,
    ) -> dict[str, object]:
        return router.list(category, resource, query=query, page=page, page_size=page_size)

    @server.tool(description="Read one registered resource by its resource ID.", annotations=read)
    def crewmeister_get(
        category: str, resource: str, item_id: str, query: dict[str, object] | None = None
    ) -> dict[str, object]:
        return router.get(category, resource, item_id, query=query)

    @server.tool(description="Create a resource with payload and confirm=true.", annotations=write)
    def crewmeister_create(
        category: str,
        resource: str,
        payload: object,
        confirm: bool = False,
        query: dict[str, object] | None = None,
        async_write: bool = False,
    ) -> dict[str, object]:
        return router.create(category, resource, payload, confirm=confirm, query=query, async_write=async_write)

    @server.tool(description="Run a batch write with payload and confirm=true.", annotations=write)
    def crewmeister_batch(
        category: str,
        resource: str,
        payload: object,
        confirm: bool = False,
        query: dict[str, object] | None = None,
        async_write: bool = False,
    ) -> dict[str, object]:
        return router.batch(category, resource, payload, confirm=confirm, query=query, async_write=async_write)

    @server.tool(description="Patch a resource with payload and confirm=true.", annotations=write)
    def crewmeister_patch(
        category: str,
        resource: str,
        item_id: str,
        payload: object,
        confirm: bool = False,
        query: dict[str, object] | None = None,
        async_write: bool = False,
    ) -> dict[str, object]:
        return router.patch(category, resource, item_id, payload, confirm=confirm, query=query, async_write=async_write)

    @server.tool(description="Replace a resource with payload and confirm=true.", annotations=write)
    def crewmeister_replace(
        category: str,
        resource: str,
        item_id: str,
        payload: object,
        confirm: bool = False,
        query: dict[str, object] | None = None,
        async_write: bool = False,
    ) -> dict[str, object]:
        return router.replace(
            category, resource, item_id, payload, confirm=confirm, query=query, async_write=async_write
        )

    @server.tool(
        description="Delete a registered resource only after authorization and confirm=true.",
        annotations=ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=True),
    )
    def crewmeister_delete(
        category: str,
        resource: str,
        item_id: str,
        confirm: bool = False,
        query: dict[str, object] | None = None,
        async_write: bool = False,
    ) -> dict[str, object]:
        return router.delete(category, resource, item_id, confirm=confirm, query=query, async_write=async_write)

    @server.tool(description="Run a POST task with payload and confirm=true.", annotations=write)
    def crewmeister_task(
        category: str,
        task: str,
        payload: object,
        confirm: bool = False,
        query: dict[str, object] | None = None,
        async_write: bool = False,
    ) -> dict[str, object]:
        return router.task(category, task, payload, confirm=confirm, query=query, async_write=async_write)

    @server.tool(description="Read the status or output of a registered job.", annotations=read)
    def crewmeister_job(category: str, kind: str, endpoint: str, job_id: str) -> dict[str, object]:
        return router.job(category, kind, endpoint, job_id)

    return server


def _config_from_env(env_file: str | None) -> CrewmeisterApiConfig:
    values = dict(load_env_file(env_file)) if env_file else dict(os.environ)
    raw_base_url = values.get("CREWMEISTER_API_BASE_URL", "").strip()
    if not raw_base_url or (raw_base_url.startswith("<") and raw_base_url.endswith(">")):
        raise CrewmeisterConfigError("crewmeister-mcp requires CREWMEISTER_API_BASE_URL.")
    config = CrewmeisterApiConfig.from_env(values)
    parsed = urlsplit(config.base_url)
    if parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise CrewmeisterConfigError("CREWMEISTER_API_BASE_URL must be a canonical HTTPS origin for MCP.")
    return config


def main(argv: Sequence[str] | None = None) -> None:
    """Start the local STDIO server after reading one fixed configuration snapshot."""

    parser = argparse.ArgumentParser(prog="crewmeister-mcp", description="Local Crewmeister MCP server")
    parser.add_argument("--env-file", metavar="PATH", help="load one UTF-8 .env file")
    parser.add_argument("--expected-version", metavar="VERSION", help=argparse.SUPPRESS)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if args.expected_version and args.expected_version != version("crewmeister-api"):
        parser.error(f"requires crewmeister-api {args.expected_version}, found {version('crewmeister-api')}")
    create_server(McpRouter(CrewmeisterApiClient(_config_from_env(args.env_file)))).run()
