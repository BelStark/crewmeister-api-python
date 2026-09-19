"""Reusable helpers for Crewmeister resource-style API categories."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from itertools import islice
from typing import BinaryIO, Literal
from urllib import parse

from crewmeister_api.client import (
    CrewmeisterApiClient,
    CrewmeisterConfigError,
    CrewmeisterTransportError,
    JsonValue,
    QueryValue,
)

ResourceOperation = Literal["list", "get", "create", "batch", "patch", "replace", "delete"]
ALL_RESOURCE_OPERATIONS: frozenset[ResourceOperation] = frozenset(
    {"list", "get", "create", "batch", "patch", "replace", "delete"}
)
LIST_RESOURCE_OPERATION: frozenset[ResourceOperation] = frozenset({"list"})


@dataclass(frozen=True)
class ResourceEndpoint:
    """Description of a Crewmeister collection and item endpoint."""

    name: str
    path: str
    supported_operations: frozenset[ResourceOperation] = ALL_RESOURCE_OPERATIONS

    def item_path(self, item_id: str) -> str:
        """Return the endpoint path for a single resource item."""

        return f"{self.path}/{_path_segment(item_id, name='resource ID')}"

    def supports(self, operation: ResourceOperation) -> bool:
        """Return whether the endpoint supports a resource operation."""

        return operation in self.supported_operations


@dataclass(frozen=True)
class TaskEndpoint:
    """Description of a task endpoint and its live-verified job collection, if known."""

    name: str
    path: str
    job_collection_path: str | None = None


class ResourceApiService:
    """Small service facade for common Crewmeister resource and task endpoints."""

    def __init__(
        self,
        client: CrewmeisterApiClient,
        resources: Iterable[ResourceEndpoint],
        tasks: Iterable[TaskEndpoint] = (),
    ) -> None:
        self.client = client
        self.resources = {resource.name: resource for resource in resources}
        self.tasks = {task.name: task for task in tasks}

    def list_resource(
        self,
        resource_name: str,
        *,
        query: Mapping[str, QueryValue] | None = None,
        page_size: int | None = None,
        limit: int | None = None,
    ) -> list[JsonValue]:
        """Materialize a resource iterator as a convenience."""

        return list(self.iter_resource(resource_name, query=query, page_size=page_size, limit=limit))

    def get_resource_page(
        self,
        resource_name: str,
        *,
        page: int,
        query: Mapping[str, QueryValue] | None = None,
        page_size: int | None = None,
    ) -> JsonValue:
        """Read exactly one collection page, preserving the raw response metadata."""

        if page < 0:
            raise CrewmeisterConfigError("page must be greater than or equal to zero.")
        if page_size is not None and page_size <= 0:
            raise CrewmeisterConfigError("page_size must be greater than zero.")
        page_query: dict[str, QueryValue] = dict(query or {})
        if {"page", "pageSize"} & page_query.keys():
            raise CrewmeisterConfigError("page and pageSize are reserved; use page and page_size arguments.")
        endpoint = self._resource(resource_name)
        self._require(endpoint, resource_name, "list")
        page_query.update(page=page, pageSize=page_size if page_size is not None else self.client.config.page_size)
        return self.client.get(endpoint.path, query=page_query)

    def iter_resource(
        self,
        resource_name: str,
        *,
        query: Mapping[str, QueryValue] | None = None,
        page_size: int | None = None,
        limit: int | None = None,
    ) -> Iterator[JsonValue]:
        """Read a paginated resource collection."""

        if limit is not None and limit < 0:
            raise CrewmeisterConfigError("limit must be greater than or equal to zero.")
        endpoint = self._resource(resource_name)
        self._require(endpoint, resource_name, "list")
        items = self.client.iter_paginated(endpoint.path, query=query, page_size=page_size)
        if limit is not None:
            items = islice(items, limit)
        return items

    def get_resource(
        self,
        resource_name: str,
        item_id: str,
        *,
        query: Mapping[str, QueryValue] | None = None,
    ) -> JsonValue:
        """Read a single resource item."""

        endpoint = self._resource(resource_name)
        self._require(endpoint, resource_name, "get")
        return self.client.get(endpoint.item_path(item_id), query=query)

    def download_resource(
        self, resource_name: str, item_id: str, output: BinaryIO, *, query: Mapping[str, QueryValue] | None = None
    ) -> None:
        """Download the binary referenced by one resource's metadata."""

        payload = self.get_resource(resource_name, item_id, query=query)
        reference = payload.get("binaryContentReference") if isinstance(payload, Mapping) else None
        if not isinstance(reference, str) or not reference:
            raise CrewmeisterTransportError("Crewmeister resource did not include a binary reference.")
        self.client.download_binary(reference, output)

    def create_resource(
        self,
        resource_name: str,
        payload: JsonValue,
        *,
        query: Mapping[str, QueryValue] | None = None,
        async_write: bool = False,
    ) -> JsonValue:
        """Create a resource item through a collection endpoint."""

        endpoint = self._resource(resource_name)
        self._require(endpoint, resource_name, "create")
        return self._write("POST", endpoint.path, payload, query=query, async_write=async_write)

    def batch_patch_resource(
        self,
        resource_name: str,
        payload: JsonValue,
        *,
        query: Mapping[str, QueryValue] | None = None,
        async_write: bool = False,
    ) -> JsonValue:
        """Run a collection-level batch patch/write request."""

        endpoint = self._resource(resource_name)
        self._require(endpoint, resource_name, "batch")
        return self._write("PATCH", endpoint.path, payload, query=query, async_write=async_write)

    def patch_resource(
        self,
        resource_name: str,
        item_id: str,
        payload: JsonValue,
        *,
        query: Mapping[str, QueryValue] | None = None,
        async_write: bool = False,
    ) -> JsonValue:
        """Patch selected fields of a resource item."""

        endpoint = self._resource(resource_name)
        self._require(endpoint, resource_name, "patch")
        return self._write("PATCH", endpoint.item_path(item_id), payload, query=query, async_write=async_write)

    def replace_resource(
        self,
        resource_name: str,
        item_id: str,
        payload: JsonValue,
        *,
        query: Mapping[str, QueryValue] | None = None,
        async_write: bool = False,
    ) -> JsonValue:
        """Replace a resource item."""

        endpoint = self._resource(resource_name)
        self._require(endpoint, resource_name, "replace")
        return self._write("PUT", endpoint.item_path(item_id), payload, query=query, async_write=async_write)

    def delete_resource(
        self,
        resource_name: str,
        item_id: str,
        *,
        query: Mapping[str, QueryValue] | None = None,
        async_write: bool = False,
    ) -> JsonValue:
        """Delete a resource item."""

        endpoint = self._resource(resource_name)
        self._require(endpoint, resource_name, "delete")
        return self._write("DELETE", endpoint.item_path(item_id), query=query, async_write=async_write)

    def run_task(
        self,
        task_name: str,
        payload: JsonValue,
        *,
        query: Mapping[str, QueryValue] | None = None,
        async_write: bool = False,
    ) -> JsonValue:
        """Invoke a Crewmeister task endpoint."""

        task = self._task(task_name)
        return self._write("POST", task.path, payload, query=query, async_write=async_write)

    def get_resource_job(self, resource_name: str, job_id: str) -> JsonValue:
        """Read a job for a registered resource endpoint."""

        return self.client.get(job_path(self._resource(resource_name).path, job_id))

    def get_task_job(self, task_name: str, job_id: str) -> JsonValue:
        """Read a job for a registered task endpoint."""

        task = self._task(task_name)
        return self.client.get(job_path(task.path, job_id, collection_path=task.job_collection_path))

    def _write(
        self,
        method: str,
        path: str,
        payload: JsonValue = None,
        *,
        query: Mapping[str, QueryValue] | None,
        async_write: bool,
    ) -> JsonValue:
        return self.client.request(
            method,
            path,
            query=query,
            json_body=payload,
            headers={"X-Write-Async": "true"} if async_write else None,
        )

    def _resource(self, resource_name: str) -> ResourceEndpoint:
        try:
            return self.resources[resource_name]
        except KeyError as exc:
            raise CrewmeisterConfigError(f"Unknown Crewmeister resource: {resource_name}") from exc

    def _task(self, task_name: str) -> TaskEndpoint:
        try:
            return self.tasks[task_name]
        except KeyError as exc:
            raise CrewmeisterConfigError(f"Unknown Crewmeister task: {task_name}") from exc

    @staticmethod
    def _require(endpoint: ResourceEndpoint, resource_name: str, operation: ResourceOperation) -> None:
        if not endpoint.supports(operation):
            raise CrewmeisterConfigError(f"Resource {resource_name} does not support {operation}.")


def prefixed_endpoint(prefix: str, name: str) -> ResourceEndpoint:
    """Build a standard Crewmeister resource endpoint from a category prefix and path name."""

    return ResourceEndpoint(name=name, path=f"{prefix.rstrip('/')}/{name}")


def prefixed_read_only_endpoint(prefix: str, name: str) -> ResourceEndpoint:
    """Build a list-only Crewmeister resource endpoint from a category prefix and path name."""

    return ResourceEndpoint(
        name=name,
        path=f"{prefix.rstrip('/')}/{name}",
        supported_operations=LIST_RESOURCE_OPERATION,
    )


def prefixed_task(prefix: str, name: str, path_name: str) -> TaskEndpoint:
    """Build a standard Crewmeister task endpoint from a category prefix and path name."""

    return TaskEndpoint(name=name, path=f"{prefix.rstrip('/')}/{path_name}")


def job_path(path: str, job_id: str, *, collection_path: str | None = None) -> str:
    """Use a verified job collection where known, otherwise the guideline convention."""

    collection = collection_path or f"{path}-jobs"
    return f"{collection}/{_path_segment(job_id, name='job ID')}"


def _path_segment(value: str, *, name: str) -> str:
    if not isinstance(value, str) or value in {"", ".", ".."}:
        raise CrewmeisterConfigError(f"Crewmeister {name} must be a non-empty, non-dot string.")
    return parse.quote(value, safe="")
