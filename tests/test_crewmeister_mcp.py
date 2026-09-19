"""Offline MCP routing checks using the existing synthetic Crewmeister transport."""

import asyncio
import importlib.util
import io
import json
import unittest
from contextlib import redirect_stderr
from http.client import IncompleteRead
from importlib.metadata import version
from unittest.mock import patch
from urllib import parse

from crewmeister_api import CrewmeisterApiClient, CrewmeisterApiConfig
from crewmeister_api.mcp_server import McpRouter, create_server, main
from tests.support import FakeResponse, FakeTransport


class CrewmeisterMcpTests(unittest.TestCase):
    def test_mcp_rejects_an_unexpected_package_version_before_configuration(self) -> None:
        stderr = io.StringIO()

        with redirect_stderr(stderr), self.assertRaisesRegex(SystemExit, "2"):
            main(["--expected-version", "0.0.0"])

        self.assertIn(f"requires crewmeister-api 0.0.0, found {version('crewmeister-api')}", stderr.getvalue())

    def test_router_uses_login_for_a_registered_write_and_rejects_unknown_routes(self) -> None:
        transport = FakeTransport(
            FakeResponse(200, {"token": "synthetic"}),
            FakeResponse(201, {"password": "hidden"}),
            FakeResponse(202, {"feedUrl": "https://secret.invalid/feed"}),
            FakeResponse(200, {"id": "job-1", "status": "WAITING"}),
            FakeResponse(200, {"id": "job-2", "status": "SUCCESS"}),
            FakeResponse(400, {"code": "REJECTED", "requestId": "request-1"}),
        )
        router = McpRouter(
            CrewmeisterApiClient(
                CrewmeisterApiConfig(username="user@example.com", password="secret"),
                transport=transport,
            )
        )

        unconfirmed = router.create("platform", "crews", {"name": "Synthetic"})
        self.assertEqual(transport.calls, [])
        result = router.create("platform", "crews", {"name": "Synthetic"}, confirm=True)
        task_result = router.task("integration", "i-cal-subscription", {"crewId": 1}, confirm=True, async_write=True)
        job_result = router.job("time-tracking", "task", "time-tracking-report", "job-1")
        resource_job_result = router.job("platform", "resource", "crews", "job-2")
        provider_rejected = router.delete("platform", "crews", "1", confirm=True)
        rejected = router.get("missing", "crews", "1")

        self.assertEqual(
            unconfirmed,
            {"outcome": "not_sent", "error": {"type": "confirmation", "message": "Write confirmation required."}},
        )
        self.assertEqual(result, {"outcome": "completed", "status": 201, "payload": {"password": "[REDACTED]"}})
        self.assertEqual(task_result, {"outcome": "accepted", "status": 202, "payload": {"feedUrl": "[REDACTED]"}})
        self.assertEqual(
            job_result, {"outcome": "pending", "status": 200, "payload": {"id": "job-1", "status": "WAITING"}}
        )
        self.assertEqual(
            resource_job_result,
            {"outcome": "completed", "status": 200, "payload": {"id": "job-2", "status": "SUCCESS"}},
        )
        self.assertEqual(
            provider_rejected,
            {
                "outcome": "rejected",
                "error": {
                    "type": "api",
                    "message": "Crewmeister API error.",
                    "status": 400,
                    "code": "REJECTED",
                    "request_id": "request-1",
                },
            },
        )
        self.assertEqual(rejected, {"error": {"type": "configuration", "message": "Crewmeister configuration error."}})
        self.assertEqual(len(transport.calls), 6)
        request, _ = transport.calls[1]
        self.assertEqual(
            (request.method, parse.urlparse(request.full_url).path),
            ("POST", "/api/v3/platform-app/crews"),
        )
        self.assertEqual(json.loads(request.data.decode("utf-8")), {"name": "Synthetic"})
        task_request = transport.calls[2][0]
        self.assertEqual(
            parse.urlparse(task_request.full_url).path,
            "/api/v3/integration/i-cal-subscription-tasks",
        )
        self.assertEqual(task_request.get_header("X-write-async"), "true")
        self.assertEqual(
            parse.urlparse(transport.calls[3][0].full_url).path,
            "/api/v3/timetracking/time-tracking-report-task-jobs/job-1",
        )
        self.assertEqual(parse.urlparse(transport.calls[4][0].full_url).path, "/api/v3/platform-app/crews-jobs/job-2")
        delete_request, _ = transport.calls[-1]
        self.assertEqual(
            (delete_request.method, parse.urlparse(delete_request.full_url).path),
            ("DELETE", "/api/v3/platform-app/crews/1"),
        )

    def test_router_returns_a_structured_error_for_unknown_catalog_entries(self) -> None:
        router = McpRouter(CrewmeisterApiClient(CrewmeisterApiConfig(bearer_token="synthetic")))

        self.assertEqual(
            router.describe("missing"),
            {"error": {"type": "configuration", "message": "Crewmeister configuration error."}},
        )

    def test_router_marks_failed_authentication_as_not_sent_and_a_write_status_as_unknown(self) -> None:
        auth_transport = FakeTransport(
            FakeResponse(200, {"token": ""}),
            FakeResponse(401, {"code": "UNAUTHORIZED"}),
        )
        auth_router = McpRouter(
            CrewmeisterApiClient(
                CrewmeisterApiConfig(username="user@example.com", password="secret"),
                transport=auth_transport,
            )
        )
        response = FakeResponse(202, None)
        router = McpRouter(
            CrewmeisterApiClient(
                CrewmeisterApiConfig(bearer_token="synthetic"),
                transport=FakeTransport(response),
            )
        )

        auth_result = auth_router.create("platform", "crews", {"name": "Synthetic"}, confirm=True)
        with patch.object(response, "read", side_effect=IncompleteRead(b"partial")):
            result = router.create("platform", "crews", {"name": "Synthetic"}, confirm=True)

        self.assertEqual(
            auth_result,
            {
                "outcome": "not_sent",
                "error": {"type": "transport", "message": "Crewmeister transport error."},
            },
        )
        self.assertEqual(len(auth_transport.calls), 1)
        self.assertEqual(
            result,
            {
                "outcome": "unknown",
                "error": {"type": "transport", "message": "Crewmeister transport error.", "status": 202},
            },
        )

    def test_router_rejects_invalid_payloads_and_marks_server_failures_as_unknown(self) -> None:
        transport = FakeTransport(FakeResponse(500, {"code": "SERVER_ERROR"}))
        router = McpRouter(CrewmeisterApiClient(CrewmeisterApiConfig(bearer_token="synthetic"), transport=transport))
        invalid = {"value": float("nan")}

        self.assertEqual(
            router.create("platform", "crews", invalid, confirm=True),
            {
                "outcome": "not_sent",
                "error": {"type": "configuration", "message": "Crewmeister configuration error."},
            },
        )
        self.assertEqual(
            router.task("integration", "i-cal-subscription", invalid, confirm=True),
            {
                "outcome": "not_sent",
                "error": {"type": "configuration", "message": "Crewmeister configuration error."},
            },
        )
        self.assertEqual(transport.calls, [])
        self.assertEqual(
            router.create("platform", "crews", {"name": "Synthetic"}, confirm=True),
            {
                "outcome": "unknown",
                "error": {
                    "type": "api",
                    "message": "Crewmeister API error.",
                    "status": 500,
                    "code": "SERVER_ERROR",
                },
            },
        )

    @unittest.skipUnless(importlib.util.find_spec("mcp"), "MCP extra is not installed")
    def test_mcp_tools_cover_every_catalogued_operation_family(self) -> None:
        server = create_server(McpRouter(CrewmeisterApiClient(CrewmeisterApiConfig(bearer_token="synthetic"))))
        tools = asyncio.run(server.list_tools())
        tool_names = {tool.name for tool in tools}

        self.assertEqual(
            tool_names,
            {
                "crewmeister_describe",
                "crewmeister_list",
                "crewmeister_get",
                "crewmeister_create",
                "crewmeister_batch",
                "crewmeister_patch",
                "crewmeister_replace",
                "crewmeister_delete",
                "crewmeister_task",
                "crewmeister_job",
            },
        )
        self.assertTrue(all(tool.description for tool in tools))
        catalog = asyncio.run(server.call_tool("crewmeister_describe", {})).structured_content
        self.assertEqual(catalog["operation_count"], 469)
        for category in catalog["categories"]:
            operations = asyncio.run(
                server.call_tool("crewmeister_describe", {"category": category["name"]})
            ).structured_content["operations"]
            self.assertTrue(
                all(
                    operation["mcp_family"] is None or operation["mcp_family"] in tool_names for operation in operations
                )
            )


if __name__ == "__main__":
    unittest.main()
