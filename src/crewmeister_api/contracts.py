"""Offline OpenAPI contract snapshots for catalogued Crewmeister operations."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from functools import cache
from importlib.resources import files
from typing import Any

_CONTRACT_VERSION = 1


@cache
def _data() -> dict[str, Any]:
    """Load the immutable, package-local OpenAPI fact snapshot."""

    data = json.loads(files("crewmeister_api").joinpath("contracts.json").read_text(encoding="utf-8"))
    if data.get("contract_version") != _CONTRACT_VERSION:
        raise RuntimeError("Unsupported Crewmeister contract data version.")
    return data


def contract_version() -> int:
    """Return the installed offline contract-data version."""

    return _data()["contract_version"]


def operation_contract(category: str, method: str, path: str) -> dict[str, object] | None:
    """Return the documented contract for one explicit OpenAPI operation."""

    category_data = _category(category)
    operation = category_data["operations"].get(f"{method} {path}")
    if operation is None:
        return None
    contract = copy.deepcopy(operation)
    contract["kind"] = "openapi"
    contract["source"] = copy.deepcopy(category_data["source"])
    contract["components"], unresolved_references = _components(category_data["components"], contract)
    if unresolved_references:
        contract["unresolved_references"] = unresolved_references
    return contract


def job_contract(category: str, *, verified: bool) -> dict[str, object]:
    """Describe the provider's documented job convention for one category."""

    category_data = _category(category)
    contract: dict[str, object] = {
        "kind": "live-verified" if verified else "guideline-derived",
        "source": copy.deepcopy(category_data["source"]),
        "parameters": [{"name": "job_id", "in": "path", "required": True, "schema": {"type": "string"}}],
        "responses": {"200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Job"}}}}},
    }
    contract["components"], unresolved_references = _components(category_data["components"], contract)
    if unresolved_references:
        contract["unresolved_references"] = unresolved_references
    return contract


def download_contract(category: str, metadata_path: str, binary_reference: str) -> dict[str, object]:
    """Describe the two GET requests needed for one registered download."""

    metadata = operation_contract(category, "GET", metadata_path)
    if metadata is None:
        raise RuntimeError(f"Missing metadata contract for {category} {metadata_path}.")
    return {
        "kind": "composed-read",
        "metadata": metadata,
        "binary": {"method": "GET", "reference": binary_reference, "path_rule": "relative /api/v3 path only"},
    }


def webclient_contract(category: str, method: str, path: str) -> dict[str, object] | None:
    """Return the one verified provider-web-client contract outside OpenAPI."""

    if (category, method, path) != (
        "salary-export",
        "PATCH",
        "/api/v3/salaryexport/salary-export-generation-tasks",
    ):
        return None
    return {
        "kind": "web-client-observed",
        "source": {"url": "https://app.crewmeister.com/flutter_widgets/main.dart.js"},
        "request": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "required": ["method", "path", "body"],
                            "properties": {
                                "method": {"enum": ["POST"]},
                                "path": {"enum": ["/"]},
                                "body": {
                                    "type": "object",
                                    "required": ["input"],
                                    "properties": {
                                        "input": {
                                            "type": "object",
                                            "required": [
                                                "crewId",
                                                "salaryExportConfigurationId",
                                                "from",
                                                "to",
                                                "userIdFilter",
                                            ],
                                            "properties": {
                                                "crewId": {"type": "integer"},
                                                "salaryExportConfigurationId": {"type": "integer"},
                                                "from": {"type": "string", "format": "date"},
                                                "to": {"type": "string", "format": "date"},
                                                "userIdFilter": {
                                                    "type": "array",
                                                    "minItems": 1,
                                                    "items": {"type": "integer"},
                                                },
                                            },
                                        }
                                    },
                                },
                            },
                        },
                    }
                }
            },
        },
        "result": {
            "status_field": "statusCode",
            "salary_export_path": "[0].body.resourceAfterWrite.output.salaryExport",
        },
        "limitations": ["No public OpenAPI schema or async/job contract is available for this route."],
    }


def _category(category: str) -> Mapping[str, Any]:
    try:
        return _data()["categories"][category]
    except KeyError as exc:
        raise RuntimeError(f"Missing Crewmeister contract category: {category}.") from exc


def _components(components: Mapping[str, Any], value: object) -> tuple[dict[str, dict[str, object]], list[str]]:
    """Return the component closure needed to resolve local references in value."""

    pending = _references(value)
    selected: dict[str, dict[str, object]] = {}
    unresolved: list[str] = []
    while pending:
        group, name = pending.pop()
        if name in selected.get(group, {}):
            continue
        try:
            component = components[group][name]
        except KeyError as exc:
            if exc.args == (name,):
                unresolved.append(f"#/components/{group}/{name}")
                continue
            raise
        selected.setdefault(group, {})[name] = copy.deepcopy(component)
        pending.update(_references(component))
    return selected, sorted(unresolved)


def _references(value: object) -> set[tuple[str, str]]:
    if isinstance(value, Mapping):
        references: set[tuple[str, str]] = set()
        reference = _reference(value.get("$ref"))
        if reference is not None:
            references.add(reference)
        for item in value.values():
            references.update(_references(item))
        return references
    if isinstance(value, list):
        return set().union(*(_references(item) for item in value)) if value else set()
    return set()


def _reference(value: object) -> tuple[str, str] | None:
    if not isinstance(value, str) or not value.startswith("#/components/"):
        return None
    group, separator, name = value.removeprefix("#/components/").partition("/")
    if not separator or not group or not name:
        return None
    return group, name
