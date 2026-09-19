"""Safe JSON output helpers shared by Crewmeister command integrations."""

from __future__ import annotations

import json
from collections.abc import Mapping

from crewmeister_api.categories import INTEGRATION_SENSITIVE_EXACT_KEYS
from crewmeister_api.client import (
    CrewmeisterApiError,
    CrewmeisterAuthenticationError,
    CrewmeisterConfigError,
    CrewmeisterTransportError,
    JsonValue,
    _safe_error_identifier,
)

SENSITIVE_KEY_PARTS = ("password", "secret", "token")
SHARED_SENSITIVE_EXACT_KEYS = frozenset({"binarycontentreference", "body", "encryptedpassword", "pincode"})
TOKEN_EXPIRY_KEYS = frozenset({"accessTokenExpiresAt", "refreshTokenExpiresAt"})
AUDIT_SNAPSHOT_KEYS = frozenset({"resourceBefore", "resourceAfter"})


def redact_sensitive(payload: JsonValue, *, sensitive_exact_keys: frozenset[str] = frozenset()) -> JsonValue:
    """Return a recursively redacted copy of a JSON-like value."""

    if isinstance(payload, Mapping):
        redacted: dict[str, JsonValue] = {}
        for key, value in payload.items():
            key_text = str(key)
            if (
                key_text == "body"
                and "body" not in sensitive_exact_keys
                and type(payload.get("statusCode")) is int
                and isinstance(value, Mapping)
                and value.get("@type") == "com.crewmeister/SyncWriteResponse"
            ):
                redacted[key] = redact_sensitive(value, sensitive_exact_keys=sensitive_exact_keys)
            elif _is_sensitive_key(key_text, sensitive_exact_keys=sensitive_exact_keys):
                redacted[key] = "[REDACTED]"
            elif key_text in AUDIT_SNAPSHOT_KEYS:
                redacted[key] = _redact_snapshot(value, sensitive_exact_keys=sensitive_exact_keys)
            else:
                redacted[key] = redact_sensitive(value, sensitive_exact_keys=sensitive_exact_keys)
        return redacted
    if isinstance(payload, list):
        return [redact_sensitive(item, sensitive_exact_keys=sensitive_exact_keys) for item in payload]
    return payload


def structured_error(exc: Exception) -> dict[str, str | int]:
    """Return a non-sensitive error record for command and MCP output."""

    if isinstance(exc, CrewmeisterApiError):
        error: dict[str, str | int] = {"type": "api", "message": "Crewmeister API error.", "status": exc.status_code}
        if code := _safe_error_identifier(exc.code):
            error["code"] = code
        if request_id := _safe_error_identifier(exc.request_id):
            error["request_id"] = request_id
        return error
    if isinstance(exc, CrewmeisterAuthenticationError):
        return {"type": "authentication", "message": "Crewmeister authentication configuration error."}
    if isinstance(exc, CrewmeisterConfigError):
        return {"type": "configuration", "message": "Crewmeister configuration error."}
    if isinstance(exc, CrewmeisterTransportError):
        error = {"type": "transport", "message": "Crewmeister transport error."}
        if exc.status_code is not None:
            error["status"] = exc.status_code
        return error
    if isinstance(exc, OSError):
        return {"type": "io", "message": "I/O error."}
    return {"type": "input", "message": "Input error."}


def _redact_snapshot(value: JsonValue, *, sensitive_exact_keys: frozenset[str]) -> JsonValue:
    try:
        snapshot = json.loads(value) if isinstance(value, str) else value
        if snapshot is not None and not isinstance(snapshot, (dict, list)):
            return "[REDACTED]"
        redacted = redact_sensitive(
            snapshot, sensitive_exact_keys=sensitive_exact_keys | INTEGRATION_SENSITIVE_EXACT_KEYS
        )
        return json.dumps(redacted, ensure_ascii=False) if isinstance(value, str) else redacted
    except ValueError, RecursionError:
        return "[REDACTED]"


def _is_sensitive_key(key: str, *, sensitive_exact_keys: frozenset[str]) -> bool:
    if key in TOKEN_EXPIRY_KEYS:
        return False
    normalized = key.replace("_", "").replace("-", "").lower()
    return (
        normalized in SHARED_SENSITIVE_EXACT_KEYS
        or normalized in sensitive_exact_keys
        or any(part in normalized for part in SENSITIVE_KEY_PARTS)
    )
