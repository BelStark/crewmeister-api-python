import io
import json
import unittest
from http.client import IncompleteRead
from unittest.mock import patch
from urllib import parse
from urllib import request as urlrequest
from urllib.error import HTTPError
from urllib.response import addinfourl

from crewmeister_api import (
    CrewmeisterApiClient,
    CrewmeisterApiConfig,
    CrewmeisterApiError,
    CrewmeisterConfigError,
    CrewmeisterTransportError,
)
from crewmeister_api.resources import ResourceEndpoint, job_path
from tests.support import FakeResponse, FakeTransport


class ShortWriter(io.BytesIO):
    def write(self, data: bytes) -> int:
        super().write(data[:1])
        return 1


class CrewmeisterApiConfigTests(unittest.TestCase):
    def test_from_env_parses_runtime_values_and_hides_secrets(self) -> None:
        config = CrewmeisterApiConfig.from_env(
            {
                "CREWMEISTER_API_BASE_URL": "https://api.crewmeister-stage.com/",
                "CREWMEISTER_API_USERNAME": "user@example.com",
                "CREWMEISTER_API_PASSWORD": "super-secret-password",
                "CREWMEISTER_API_BEARER_TOKEN": "super-secret-token",
                "CREWMEISTER_API_CALLER_CONTEXT": '{"clientAppId":"SINGLE_USER","clientDevice":"DESKTOP"}',
                "CREWMEISTER_API_TIMEOUT_SECONDS": "12.5",
                "CREWMEISTER_API_PAGE_SIZE": "50",
            }
        )

        self.assertEqual(config.base_url, "https://api.crewmeister-stage.com")
        self.assertEqual(config.username, "user@example.com")
        self.assertEqual(config.caller_context, {"clientAppId": "SINGLE_USER", "clientDevice": "DESKTOP"})
        self.assertEqual(config.timeout_seconds, 12.5)
        self.assertEqual(config.page_size, 50)
        self.assertTrue(config.has_authentication())
        self.assertNotIn("super-secret-password", repr(config))
        self.assertNotIn("super-secret-token", repr(config))

    def test_from_env_ignores_template_placeholders(self) -> None:
        config = CrewmeisterApiConfig.from_env(
            {
                "CREWMEISTER_API_USERNAME": "<crewmeister_username>",
                "CREWMEISTER_API_PASSWORD": "<crewmeister_password>",
                "CREWMEISTER_API_BEARER_TOKEN": "<crewmeister_bearer_token>",
            }
        )

        self.assertIsNone(config.username)
        self.assertIsNone(config.password)
        self.assertIsNone(config.bearer_token)
        self.assertEqual(config.base_url, "https://api.crewmeister-stage.com")
        self.assertFalse(config.has_authentication())

    def test_from_env_rejects_invalid_caller_context(self) -> None:
        with self.assertRaisesRegex(CrewmeisterConfigError, "CALLER_CONTEXT"):
            CrewmeisterApiConfig.from_env({"CREWMEISTER_API_CALLER_CONTEXT": "not-json"})

    def test_from_env_rejects_invalid_base_url(self) -> None:
        with self.assertRaisesRegex(CrewmeisterConfigError, "BASE_URL"):
            CrewmeisterApiConfig.from_env({"CREWMEISTER_API_BASE_URL": "api.crewmeister.com"})

    def test_from_env_rejects_insecure_base_url(self) -> None:
        with self.assertRaisesRegex(CrewmeisterConfigError, "HTTPS"):
            CrewmeisterApiConfig.from_env({"CREWMEISTER_API_BASE_URL": "http://api.crewmeister.com"})

    def test_config_rejects_nonfinite_timeouts_and_unsafe_url_components(self) -> None:
        for timeout in (float("nan"), float("inf"), float("-inf")):
            with self.assertRaisesRegex(CrewmeisterConfigError, "TIMEOUT"):
                CrewmeisterApiConfig(timeout_seconds=timeout)
        for base_url in (
            "https://api.crewmeister.com?ignored",
            "https://api.crewmeister.com#fragment",
            "https://user:password@api.crewmeister.com",
            "https://api.crewmeister.com:invalid",
        ):
            with self.assertRaisesRegex(CrewmeisterConfigError, "BASE_URL"):
                CrewmeisterApiConfig(base_url=base_url)
        with self.assertRaisesRegex(CrewmeisterConfigError, "CALLER_CONTEXT"):
            CrewmeisterApiConfig(caller_context={"limit": float("nan")})


class CrewmeisterApiClientTests(unittest.TestCase):
    def test_default_transport_rejects_redirect_without_followup(self) -> None:
        response = addinfourl(io.BytesIO(b"{}"), {"Location": "http://other.invalid/"}, "https://api.invalid/", 302)
        response.msg = "Found"
        client = CrewmeisterApiClient(CrewmeisterApiConfig(bearer_token="synthetic", caller_context={"app": "test"}))
        with (
            patch.object(urlrequest.AbstractHTTPHandler, "do_open", return_value=response) as send,
            self.assertRaises(CrewmeisterApiError) as raised,
        ):
            client.get("/members")
        self.assertEqual(raised.exception.status_code, 302)
        send.assert_called_once()

    def test_authenticated_get_logs_in_and_adds_headers(self) -> None:
        transport = FakeTransport(
            FakeResponse(200, {"token": "jwt-token"}),
            FakeResponse(200, {"content": [{"id": 1}], "hasNextPage": False}),
        )
        config = CrewmeisterApiConfig(
            base_url="https://api.crewmeister-stage.com",
            username="user@example.com",
            password="secret",
            caller_context={"clientAppId": "SINGLE_USER", "clientDevice": "DESKTOP"},
        )
        client = CrewmeisterApiClient(config, transport=transport)

        response = client.get(
            "/api/v3/platform-app/members",
            query={"sort": ["-id", "+name"], "filter": "crewId==24", "ignored": None},
        )

        self.assertEqual(response, {"content": [{"id": 1}], "hasNextPage": False})
        self.assertEqual(len(transport.calls), 2)

        auth_request, auth_timeout = transport.calls[0]
        self.assertEqual(auth_timeout, 30.0)
        self.assertEqual(auth_request.full_url, "https://api.crewmeister-stage.com/api/v3/auth/user/")
        self.assertEqual(
            json.loads(auth_request.data.decode("utf-8")), {"username": "user@example.com", "password": "secret"}
        )
        self.assertIsNone(auth_request.get_header("Authorization"))

        api_request, _ = transport.calls[1]
        parsed = parse.urlparse(api_request.full_url)
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.netloc, "api.crewmeister-stage.com")
        self.assertEqual(parsed.path, "/api/v3/platform-app/members")
        query = parse.parse_qs(parsed.query)
        self.assertEqual(query["sort"], ["-id", "+name"])
        self.assertEqual(query["filter"], ["crewId==24"])
        self.assertNotIn("ignored", query)
        self.assertEqual(api_request.get_header("Authorization"), "Bearer jwt-token")
        self.assertEqual(
            json.loads(api_request.get_header("X-caller-context")),
            {"clientAppId": "SINGLE_USER", "clientDevice": "DESKTOP"},
        )

    def test_bearer_token_skips_login(self) -> None:
        transport = FakeTransport(FakeResponse(200, {"ok": True}))
        client = CrewmeisterApiClient(
            CrewmeisterApiConfig(base_url="https://api.crewmeister.com", bearer_token="existing-token"),
            transport=transport,
        )

        response = client.get("/api/v3/platform-app/users")

        self.assertEqual(response, {"ok": True})
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(transport.calls[0][0].get_header("Authorization"), "Bearer existing-token")

    def test_empty_login_token_stops_before_an_authenticated_request(self) -> None:
        transport = FakeTransport(FakeResponse(200, {"token": " "}))
        client = CrewmeisterApiClient(
            CrewmeisterApiConfig(username="user@example.com", password="secret"), transport=transport
        )

        with self.assertRaises(CrewmeisterTransportError):
            client.get("/api/v3/platform-app/users")

        self.assertEqual(len(transport.calls), 1)

    def test_request_with_response_retains_success_status(self) -> None:
        client = CrewmeisterApiClient(
            CrewmeisterApiConfig(bearer_token="synthetic"), FakeTransport(FakeResponse(202, {"id": "job-1"}))
        )

        response = client.request_with_response("POST", "/tasks", json_body={"name": "report"})

        self.assertEqual((response.status_code, response.payload), (202, {"id": "job-1"}))

    def test_request_rejects_nonfinite_json_before_authentication(self) -> None:
        transport = FakeTransport(FakeResponse(200, {"token": "synthetic"}))
        client = CrewmeisterApiClient(
            CrewmeisterApiConfig(username="user@example.com", password="secret"), transport=transport
        )

        with self.assertRaisesRegex(CrewmeisterConfigError, "finite JSON"):
            client.post("/api/v3/platform-app/crews", {"limit": float("nan")})

        self.assertEqual(transport.calls, [])

    def test_api_error_exposes_status_code_code_and_request_id(self) -> None:
        api_message = "Resource does not exist or you do not have permissions to read."
        body = io.BytesIO(
            json.dumps({"code": "NOT_FOUND", "message": api_message, "requestId": "request-123"}).encode()
        )
        headers = {"Retry-After": "30"}
        response = HTTPError("https://api.invalid/", 404, "Not Found", headers, body)
        transport = unittest.mock.Mock(side_effect=response)
        client = CrewmeisterApiClient(
            CrewmeisterApiConfig(base_url="https://api.crewmeister.com", bearer_token="existing-token"),
            transport=transport,
        )

        with self.assertRaises(CrewmeisterApiError) as context:
            client.get("/api/v3/platform-app/users/999")

        self.assertTrue(body.closed)
        self.assertEqual(context.exception.headers, headers)
        self.assertIsNot(context.exception.headers, headers)
        self.assertEqual(context.exception.status_code, 404)
        self.assertEqual(context.exception.code, "NOT_FOUND")
        self.assertEqual(context.exception.request_id, "request-123")
        self.assertIn("HTTP 404", str(context.exception))
        self.assertIn("code=NOT_FOUND", str(context.exception))
        self.assertIn("request_id=request-123", str(context.exception))
        self.assertNotIn(api_message, str(context.exception))
        self.assertEqual(
            context.exception.payload,
            {
                "code": "NOT_FOUND",
                "message": api_message,
                "requestId": "request-123",
            },
        )

    def test_api_error_never_formats_untrusted_identifiers(self) -> None:
        error = CrewmeisterApiError(
            400,
            {"code": {"password": "synthetic-secret"}, "requestId": "request\nwith-control-character"},
        )

        self.assertIsNone(error.code)
        self.assertIsNone(error.request_id)
        self.assertNotIn("synthetic-secret", str(error))
        self.assertNotIn("\n", str(error))

    def test_incomplete_response_is_closed_and_translated(self) -> None:
        response = FakeResponse(200, None)
        client = CrewmeisterApiClient(CrewmeisterApiConfig(bearer_token="synthetic"), FakeTransport(response))
        with (
            patch.object(response, "read", side_effect=IncompleteRead(b"partial")),
            self.assertRaises(CrewmeisterTransportError) as raised,
        ):
            client.get("/members")
        self.assertTrue(response.closed)
        self.assertEqual(raised.exception.status_code, 200)

    def test_informational_response_is_not_a_successful_api_response(self) -> None:
        response = FakeResponse(101, {"switching": True})
        client = CrewmeisterApiClient(CrewmeisterApiConfig(bearer_token="synthetic"), FakeTransport(response))

        with self.assertRaisesRegex(CrewmeisterTransportError, "status"):
            client.get("/api/v3/platform-app/users")

        self.assertTrue(response.closed)

    def test_decode_error_retains_received_status(self) -> None:
        response = FakeResponse(202, None)
        response._body = b'{"id":' + b"9" * 5000 + b"}"
        client = CrewmeisterApiClient(CrewmeisterApiConfig(bearer_token="synthetic"), FakeTransport(response))

        with self.assertRaises(CrewmeisterTransportError) as raised:
            client.request_with_response("POST", "/tasks")

        self.assertEqual(raised.exception.status_code, 202)

    def test_iter_paginated_yields_content_until_last_page(self) -> None:
        transport = FakeTransport(
            FakeResponse(200, {"content": [{"id": 1}], "hasNextPage": True}),
            FakeResponse(200, {"content": [{"id": 2}], "hasNextPage": False}),
        )
        client = CrewmeisterApiClient(
            CrewmeisterApiConfig(base_url="https://api.crewmeister.com", bearer_token="existing-token", page_size=25),
            transport=transport,
        )

        items = list(client.iter_paginated("/api/v3/platform-app/members", query={"filter": "crewId==24"}))

        self.assertEqual(items, [{"id": 1}, {"id": 2}])
        first_query = parse.parse_qs(parse.urlparse(transport.calls[0][0].full_url).query)
        second_query = parse.parse_qs(parse.urlparse(transport.calls[1][0].full_url).query)
        self.assertEqual(first_query["page"], ["0"])
        self.assertEqual(second_query["page"], ["1"])
        self.assertEqual(first_query["pageSize"], ["25"])
        self.assertEqual(second_query["pageSize"], ["25"])

    def test_iter_paginated_can_fallback_to_total_pages(self) -> None:
        transport = FakeTransport(
            FakeResponse(200, {"content": [{"id": 1}], "totalPages": 2}),
            FakeResponse(200, {"content": [{"id": 2}], "totalPages": 2}),
        )
        client = CrewmeisterApiClient(
            CrewmeisterApiConfig(base_url="https://api.crewmeister.com", bearer_token="existing-token"),
            transport=transport,
        )

        items = list(client.iter_paginated("/api/v3/platform-app/members"))

        self.assertEqual(items, [{"id": 1}, {"id": 2}])

    def test_build_url_rejects_absolute_paths(self) -> None:
        client = CrewmeisterApiClient(
            CrewmeisterApiConfig(base_url="https://api.crewmeister.com", bearer_token="existing-token")
        )

        with self.assertRaisesRegex(CrewmeisterConfigError, "relative"):
            client.build_url("https://example.invalid/api")

    def test_resource_and_job_ids_cannot_be_empty_or_dot_segments(self) -> None:
        endpoint = ResourceEndpoint("members", "/api/v3/platform-app/members")

        for value in ("", ".", ".."):
            with self.assertRaises(CrewmeisterConfigError):
                endpoint.item_path(value)
            with self.assertRaises(CrewmeisterConfigError):
                job_path(endpoint.path, value)

        self.assertEqual(endpoint.item_path("member/1"), "/api/v3/platform-app/members/member%2F1")

    def test_binary_download_fails_on_a_short_write(self) -> None:
        response = FakeResponse(200, None)
        response._body = b"report"
        response.headers["Content-Length"] = "6"
        client = CrewmeisterApiClient(CrewmeisterApiConfig(bearer_token="synthetic"), FakeTransport(response))
        output = ShortWriter()

        with self.assertRaisesRegex(CrewmeisterTransportError, "written"):
            client.download_binary("/api/v3/platform-app/reports/1", output)

        self.assertEqual(output.getvalue(), b"r")
        self.assertTrue(response.closed)


if __name__ == "__main__":
    unittest.main()
