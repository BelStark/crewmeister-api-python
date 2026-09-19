"""Small REST client foundation for the Crewmeister V3 API."""

from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from email.message import Message
from http.client import HTTPException
from importlib.metadata import version
from typing import BinaryIO, Protocol, cast
from urllib import error as urlerror
from urllib import parse
from urllib import request as urlrequest

DEFAULT_BASE_URL = "https://api.crewmeister-stage.com"
AUTH_PATH = "/api/v3/auth/user/"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_PAGE_SIZE = 100

type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]
QueryValue = str | int | float | bool | None | Sequence[str | int | float | bool | None]


class HttpResponse(Protocol):
    @property
    def status(self) -> int | None: ...

    @property
    def headers(self) -> Mapping[str, str] | Message: ...

    def read(self, amount: int = -1) -> bytes: ...

    def close(self) -> None: ...


type Transport = Callable[[urlrequest.Request, float], HttpResponse]


class CrewmeisterError(Exception):
    """Base class for SDK configuration, transport, and API failures."""


class CrewmeisterConfigError(CrewmeisterError, ValueError):
    """Raised when Crewmeister API configuration is invalid."""


class CrewmeisterAuthenticationError(CrewmeisterConfigError):
    """Raised when an authenticated request cannot obtain credentials."""


class CrewmeisterTransportError(CrewmeisterError, RuntimeError):
    """Raised when the HTTP transport or response decoding fails."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(message)


class CrewmeisterApiError(CrewmeisterError, RuntimeError):
    """Raised for non-success Crewmeister API responses."""

    def __init__(self, status_code: int, payload: JsonValue, headers: Mapping[str, str] | None = None) -> None:
        self.status_code = status_code
        self.payload = payload
        self.headers = dict(headers or {})
        self.code = _safe_error_identifier(_payload_value(payload, "code", "Code"))
        self.request_id = _safe_error_identifier(_payload_value(payload, "requestId", "Request ID", "RequestId"))
        details = [f"HTTP {status_code}"]
        if self.code:
            details.append(f"code={self.code}")
        if self.request_id:
            details.append(f"request_id={self.request_id}")
        super().__init__("Crewmeister API request failed: " + " ".join(details))


@dataclass(frozen=True)
class CrewmeisterApiResponse:
    """A successful JSON payload with its HTTP status for adapter integrations."""

    status_code: int
    payload: JsonValue


@dataclass(frozen=True)
class CrewmeisterApiConfig:
    """Runtime configuration for Crewmeister API calls."""

    base_url: str = DEFAULT_BASE_URL
    username: str | None = None
    password: str | None = field(default=None, repr=False)
    bearer_token: str | None = field(default=None, repr=False)
    caller_context: Mapping[str, JsonValue] | None = None
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    page_size: int = DEFAULT_PAGE_SIZE

    def __post_init__(self) -> None:
        if not isinstance(self.base_url, str):
            raise CrewmeisterConfigError("CREWMEISTER_API_BASE_URL must be an absolute HTTPS URL.")
        base_url = self.base_url.rstrip("/")
        try:
            parsed = parse.urlsplit(base_url)
            _ = parsed.port
        except ValueError as exc:
            raise CrewmeisterConfigError("CREWMEISTER_API_BASE_URL must be an absolute HTTPS URL.") from exc
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or "?" in base_url
            or "#" in base_url
        ):
            raise CrewmeisterConfigError(
                "CREWMEISTER_API_BASE_URL must be an absolute HTTPS URL without credentials, query, or fragment."
            )
        if (
            not isinstance(self.timeout_seconds, int | float)
            or isinstance(self.timeout_seconds, bool)
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise CrewmeisterConfigError("CREWMEISTER_API_TIMEOUT_SECONDS must be greater than zero.")
        if not isinstance(self.page_size, int) or isinstance(self.page_size, bool) or self.page_size <= 0:
            raise CrewmeisterConfigError("CREWMEISTER_API_PAGE_SIZE must be greater than zero.")
        if self.caller_context is not None and not isinstance(self.caller_context, Mapping):
            raise CrewmeisterConfigError("CREWMEISTER_API_CALLER_CONTEXT must decode to a JSON object.")

        object.__setattr__(self, "base_url", base_url)
        if self.caller_context is not None:
            caller_context = dict(self.caller_context)
            try:
                json.dumps(caller_context, separators=(",", ":"), sort_keys=True, allow_nan=False)
            except (TypeError, ValueError, RecursionError) as exc:
                raise CrewmeisterConfigError("CREWMEISTER_API_CALLER_CONTEXT must be a finite JSON object.") from exc
            object.__setattr__(self, "caller_context", caller_context)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> CrewmeisterApiConfig:
        """Build configuration from environment variables."""

        source = os.environ if env is None else env
        base_url = _clean_env_value(source.get("CREWMEISTER_API_BASE_URL")) or DEFAULT_BASE_URL
        username = _clean_env_value(source.get("CREWMEISTER_API_USERNAME"))
        password = _clean_env_value(source.get("CREWMEISTER_API_PASSWORD"))
        bearer_token = _clean_env_value(source.get("CREWMEISTER_API_BEARER_TOKEN"))
        caller_context = _parse_caller_context(_clean_env_value(source.get("CREWMEISTER_API_CALLER_CONTEXT")))
        timeout_seconds = _parse_positive_float(
            _clean_env_value(source.get("CREWMEISTER_API_TIMEOUT_SECONDS")),
            "CREWMEISTER_API_TIMEOUT_SECONDS",
            DEFAULT_TIMEOUT_SECONDS,
        )
        page_size = _parse_positive_int(
            _clean_env_value(source.get("CREWMEISTER_API_PAGE_SIZE")),
            "CREWMEISTER_API_PAGE_SIZE",
            DEFAULT_PAGE_SIZE,
        )
        return cls(
            base_url=base_url,
            username=username,
            password=password,
            bearer_token=bearer_token,
            caller_context=caller_context,
            timeout_seconds=timeout_seconds,
            page_size=page_size,
        )

    def has_login_credentials(self) -> bool:
        """Return whether username/password login can be attempted."""

        return bool(self.username and self.password)

    def has_authentication(self) -> bool:
        """Return whether authenticated requests can be made."""

        return bool(self.bearer_token or self.has_login_credentials())


class CrewmeisterApiClient:
    """Generic JSON REST client for Crewmeister V3 endpoints."""

    def __init__(self, config: CrewmeisterApiConfig, transport: Transport | None = None) -> None:
        self.config = config
        self._transport = transport or _default_transport
        self._bearer_token = config.bearer_token

    def authenticate(self) -> str:
        """Return a bearer token, logging in with username/password when needed."""

        if self._bearer_token:
            return self._bearer_token
        if not self.config.has_login_credentials():
            raise CrewmeisterAuthenticationError(
                "Set CREWMEISTER_API_BEARER_TOKEN or both CREWMEISTER_API_USERNAME and CREWMEISTER_API_PASSWORD."
            )

        response = self.request(
            "POST",
            AUTH_PATH,
            json_body={"username": self.config.username, "password": self.config.password},
            authenticated=False,
        )
        token = response.get("token") if isinstance(response, dict) else None
        if not isinstance(token, str) or not (token := token.strip()):
            raise CrewmeisterTransportError("Crewmeister auth response did not contain a token.")
        self._bearer_token = token
        return token

    def get(self, path: str, query: Mapping[str, QueryValue] | None = None) -> JsonValue:
        """Send an authenticated GET request."""

        return self.request("GET", path, query=query)

    def download_binary(self, reference: str, output: BinaryIO) -> None:
        """Stream a non-empty binary payload from a provider-relative API reference."""

        parsed = parse.urlsplit(reference)
        path = parse.unquote(parsed.path)
        if (
            parsed.scheme
            or parsed.netloc
            or parsed.fragment
            or not parsed.path.startswith("/api/v3/")
            or not path.startswith("/api/v3/")
            or "\\" in path
            or any(part in {".", ".."} for part in path.split("/"))
        ):
            raise CrewmeisterConfigError("Crewmeister binary references must be relative API paths.")
        request = urlrequest.Request(
            f"{self.config.base_url}{parse.urlunsplit(('', '', parsed.path, parsed.query, ''))}",
            headers=self._request_headers(accept="*/*"),
            method="GET",
        )
        self._send_binary(request, output)

    def post(self, path: str, json_body: JsonValue = None) -> JsonValue:
        """Send an authenticated POST request."""

        return self.request("POST", path, json_body=json_body)

    def patch(self, path: str, json_body: JsonValue = None) -> JsonValue:
        """Send an authenticated PATCH request."""

        return self.request("PATCH", path, json_body=json_body)

    def put(self, path: str, json_body: JsonValue = None) -> JsonValue:
        """Send an authenticated PUT request."""

        return self.request("PUT", path, json_body=json_body)

    def delete(self, path: str) -> JsonValue:
        """Send an authenticated DELETE request."""

        return self.request("DELETE", path)

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, QueryValue] | None = None,
        json_body: JsonValue = None,
        headers: Mapping[str, str] | None = None,
        authenticated: bool = True,
    ) -> JsonValue:
        """Send a JSON request to the Crewmeister API."""

        return self.request_with_response(
            method, path, query=query, json_body=json_body, headers=headers, authenticated=authenticated
        ).payload

    def request_with_response(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, QueryValue] | None = None,
        json_body: JsonValue = None,
        headers: Mapping[str, str] | None = None,
        authenticated: bool = True,
    ) -> CrewmeisterApiResponse:
        """Send a JSON request and retain its successful HTTP status."""

        url = self.build_url(path, query)

        body = None
        if json_body is not None:
            try:
                body = json.dumps(json_body, separators=(",", ":"), allow_nan=False).encode("utf-8")
            except (TypeError, ValueError, RecursionError) as exc:
                raise CrewmeisterConfigError(
                    "Crewmeister JSON request bodies must contain finite JSON values."
                ) from exc
        request_headers = self._request_headers(headers, authenticated=authenticated)
        if body is not None:
            request_headers["Content-Type"] = "application/json"

        request = urlrequest.Request(
            url,
            data=body,
            headers=request_headers,
            method=method.upper(),
        )
        return self._send(request)

    def iter_paginated(
        self,
        path: str,
        *,
        query: Mapping[str, QueryValue] | None = None,
        page_size: int | None = None,
    ) -> Iterator[JsonValue]:
        """Yield all resources from a Crewmeister paginated list endpoint."""

        if page_size is not None and page_size <= 0:
            raise CrewmeisterConfigError("page_size must be greater than zero.")

        page = 0
        effective_page_size = page_size or self.config.page_size
        base_query: dict[str, QueryValue] = dict(query or {})
        if {"page", "pageSize"} & base_query.keys():
            raise CrewmeisterConfigError("page and pageSize are reserved; use page_size for pagination.")
        while True:
            page_query: dict[str, QueryValue] = {
                **base_query,
                "page": page,
                "pageSize": effective_page_size,
            }
            payload = self.get(path, query=page_query)
            if not isinstance(payload, Mapping):
                raise CrewmeisterTransportError("Crewmeister page response was not a JSON object.")
            content = payload.get("content")
            if not isinstance(content, list):
                raise CrewmeisterTransportError("Crewmeister page response did not contain a content list.")
            has_next_page = payload.get("hasNextPage")
            total_pages = payload.get("totalPages")
            if "hasNextPage" in payload and not isinstance(has_next_page, bool):
                raise CrewmeisterTransportError("Crewmeister page hasNextPage must be a boolean.")
            if "totalPages" in payload:
                if (
                    not isinstance(total_pages, int)
                    or isinstance(total_pages, bool)
                    or total_pages < 0
                    or (total_pages <= page and not (page == 0 and total_pages == 0 and not content))
                ):
                    raise CrewmeisterTransportError("Crewmeister page totalPages is invalid.")
                expected_next = page + 1 < total_pages
                if isinstance(has_next_page, bool) and has_next_page != expected_next:
                    raise CrewmeisterTransportError("Crewmeister page continuation metadata is contradictory.")
                has_next_page = expected_next
            if not isinstance(has_next_page, bool):
                raise CrewmeisterTransportError("Crewmeister page is missing continuation metadata.")
            yield from content
            del payload, content

            if not has_next_page:
                break
            page += 1

    def build_url(self, path: str, query: Mapping[str, QueryValue] | None = None) -> str:
        """Build an API URL from a relative path and optional query mapping."""

        if path.startswith(("http://", "https://")):
            raise CrewmeisterConfigError("Crewmeister API paths must be relative.")
        api_path = "/" + path.lstrip("/")
        url = f"{self.config.base_url}{api_path}"
        query_string = _encode_query(query)
        if query_string:
            return f"{url}?{query_string}"
        return url

    def _send(self, request: urlrequest.Request) -> CrewmeisterApiResponse:
        response = self._open(request)
        succeeded = False
        status_code: int | None = None
        try:
            status_code = _response_status(response)
            headers = dict(response.headers)
            try:
                payload = _decode_response(response.read(), allow_text=status_code >= 300)
            except (OSError, HTTPException, UnicodeError, CrewmeisterTransportError) as exc:
                if status_code >= 300:
                    raise CrewmeisterApiError(status_code, None, headers) from exc
                raise CrewmeisterTransportError(
                    "Crewmeister API response could not be read or decoded.", status_code=status_code
                ) from exc
            if status_code >= 300:
                raise CrewmeisterApiError(status_code, payload, headers)
            succeeded = True
            return CrewmeisterApiResponse(status_code, payload)
        finally:
            try:
                response.close()
            except (OSError, HTTPException) as exc:
                if succeeded:
                    raise CrewmeisterTransportError(
                        "Crewmeister API response could not be closed.", status_code=status_code
                    ) from exc

    def _request_headers(
        self,
        headers: Mapping[str, str] | None = None,
        *,
        authenticated: bool = True,
        accept: str = "application/json",
    ) -> dict[str, str]:
        request_headers = {"Accept": accept, "User-Agent": f"crewmeister-api/{version("crewmeister-api")}"}
        if headers:
            request_headers.update(headers)
        if authenticated:
            request_headers["Authorization"] = f"Bearer {self.authenticate()}"
            if self.config.caller_context:
                request_headers["X-Caller-Context"] = json.dumps(
                    self.config.caller_context, separators=(",", ":"), sort_keys=True, allow_nan=False
                )
        return request_headers

    def _open(self, request: urlrequest.Request) -> HttpResponse:
        try:
            return self._transport(request, self.config.timeout_seconds)
        except urlerror.HTTPError as exc:
            return exc
        except (OSError, HTTPException) as exc:
            raise CrewmeisterTransportError("Crewmeister API transport failed.") from exc

    def _send_binary(self, request: urlrequest.Request, output: BinaryIO) -> None:
        response = self._open(request)
        succeeded = False
        status_code: int | None = None
        try:
            status_code = _response_status(response)
            headers = dict(response.headers)
            if status_code >= 300:
                try:
                    error_payload = _decode_response(response.read(), allow_text=True)
                except OSError, HTTPException, UnicodeError, CrewmeisterTransportError:
                    error_payload = None
                raise CrewmeisterApiError(status_code, error_payload, headers)
            if _is_unexpected_binary_type(_media_type(headers)):
                raise CrewmeisterTransportError(
                    "Crewmeister binary response had an unexpected content type.", status_code=status_code
                )
            size = 0
            try:
                while chunk := response.read(64 * 1024):
                    written = output.write(chunk)
                    if written != len(chunk):
                        raise CrewmeisterTransportError(
                            "Crewmeister binary response could not be written.", status_code=status_code
                        )
                    size += written
            except (OSError, HTTPException) as exc:
                raise CrewmeisterTransportError(
                    "Crewmeister binary response could not be read.", status_code=status_code
                ) from exc
            if not size:
                raise CrewmeisterTransportError("Crewmeister binary response was empty.", status_code=status_code)
            if (expected_size := _content_length(headers)) is not None and size != expected_size:
                raise CrewmeisterTransportError("Crewmeister binary response was incomplete.", status_code=status_code)
            succeeded = True
            return None
        finally:
            try:
                response.close()
            except (OSError, HTTPException) as exc:
                if succeeded:
                    raise CrewmeisterTransportError(
                        "Crewmeister API response could not be closed.", status_code=status_code
                    ) from exc


class _RejectRedirects(urlrequest.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl) -> None:
        return None


def _default_transport(request: urlrequest.Request, timeout: float) -> HttpResponse:
    return cast(HttpResponse, urlrequest.build_opener(_RejectRedirects()).open(request, timeout=timeout))


def _clean_env_value(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned or (cleaned.startswith("<") and cleaned.endswith(">")):
        return None
    return cleaned


def _parse_caller_context(value: str | None) -> JsonObject | None:
    if value is None or value == "{}":
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise CrewmeisterConfigError("CREWMEISTER_API_CALLER_CONTEXT must be valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise CrewmeisterConfigError("CREWMEISTER_API_CALLER_CONTEXT must decode to a JSON object.")
    return parsed


def _parse_positive_float(value: str | None, variable_name: str, default: float) -> float:
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError as exc:
        raise CrewmeisterConfigError(f"{variable_name} must be a number.") from exc
    if parsed <= 0:
        raise CrewmeisterConfigError(f"{variable_name} must be greater than zero.")
    return parsed


def _parse_positive_int(value: str | None, variable_name: str, default: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise CrewmeisterConfigError(f"{variable_name} must be an integer.") from exc
    if parsed <= 0:
        raise CrewmeisterConfigError(f"{variable_name} must be greater than zero.")
    return parsed


def _encode_query(query: Mapping[str, QueryValue] | None) -> str:
    if not query:
        return ""
    items: list[tuple[str, str | int | float | bool]] = []
    for key, value in query.items():
        if value is None:
            continue
        if isinstance(value, str) or not isinstance(value, Sequence):
            items.append((key, value))
            continue
        for nested_value in value:
            if nested_value is not None:
                items.append((key, nested_value))
    return parse.urlencode(items, doseq=True)


def _decode_response(body: bytes, *, allow_text: bool = False) -> JsonValue:
    if not body:
        return None
    text = body.decode("utf-8")
    try:
        return cast(JsonValue, json.loads(text))
    except (ValueError, RecursionError) as exc:
        if allow_text:
            return {"message": text}
        raise CrewmeisterTransportError("Crewmeister API response was not valid JSON.") from exc


def _response_status(response: HttpResponse) -> int:
    return _parse_status(response.status)


def _media_type(headers: Mapping[str, str]) -> str | None:
    for name, value in headers.items():
        if name.lower() == "content-type":
            return value.partition(";")[0].strip().lower()
    return None


def _is_unexpected_binary_type(media_type: str | None) -> bool:
    return media_type in {"text/html", "application/xhtml+xml"} or bool(
        media_type and (media_type == "application/json" or media_type.endswith("+json"))
    )


def _content_length(headers: Mapping[str, str]) -> int | None:
    for name, value in headers.items():
        if name.lower() == "content-length":
            if not value.isdecimal():
                raise CrewmeisterTransportError("Crewmeister binary response had an invalid content length.")
            return int(value)
    return None


def _parse_status(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 200 <= value <= 599:
        raise CrewmeisterTransportError("Crewmeister API response had an invalid HTTP status code.")
    return value


def _payload_value(payload: JsonValue, *keys: str) -> JsonValue | None:
    if not isinstance(payload, Mapping):
        return None
    for key in keys:
        if key in payload:
            return payload[key]
    return None


def _safe_error_identifier(value: JsonValue | None) -> str | None:
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", value) else None
