"""Synthetic transport checks, not server acceptance; see README.md#known-api-limitations.

Task envelopes and unresolved vendor schemas remain open.
"""

import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from urllib import parse

from crewmeister_api import CrewmeisterApiClient, CrewmeisterApiConfig
from crewmeister_api.catalog import describe_api
from crewmeister_api.cli import redact_sensitive, run_cli
from tests.support import FakeResponse, FakeTransport


class CrewmeisterCliTests(unittest.TestCase):
    def test_describe_returns_an_isolated_mcp_family_mapping(self) -> None:
        catalog = describe_api()
        catalog["mcp_families"]["list"] = "changed"

        self.assertEqual(describe_api()["mcp_families"]["list"], "crewmeister_list")

    def test_describe_lists_all_registered_operations_without_creating_a_client(self) -> None:
        stdout, stderr = io.StringIO(), io.StringIO()
        factory = _CountingFactory(FakeTransport())

        code = run_cli(["describe", "--json"], stdout=stdout, stderr=stderr, client_factory=factory)

        index_text = stdout.getvalue()
        catalog = json.loads(stdout.getvalue())
        self.assertEqual((code, stderr.getvalue(), factory.calls), (0, "", 0))
        self.assertEqual(catalog["operation_count"], 469)
        self.assertEqual(sum(category["operation_count"] for category in catalog["categories"]), 468)
        self.assertEqual(catalog["authentication"]["cli_json_payload"], False)
        self.assertEqual(catalog["authentication"]["http_json_body"], True)
        self.assertEqual(catalog["cli"]["page_options"]["page"], "--page INTEGER >= 0")
        self.assertIn("Technical availability does not confirm provider permission.", catalog["limitations"])
        self.assertEqual(
            catalog["mcp_families"],
            {
                "list": "crewmeister_list",
                "get": "crewmeister_get",
                "create": "crewmeister_create",
                "batch": "crewmeister_batch",
                "patch": "crewmeister_patch",
                "replace": "crewmeister_replace",
                "delete": "crewmeister_delete",
                "task": "crewmeister_task",
                "job": "crewmeister_job",
            },
        )
        stdout = io.StringIO()
        code = run_cli(
            ["--env-file", "does-not-exist", "describe", "--json"],
            stdout=stdout,
            stderr=stderr,
            client_factory=factory,
        )
        self.assertEqual((code, stdout.getvalue(), stderr.getvalue(), factory.calls), (0, index_text, "", 0))

        operations = [catalog["authentication"]]
        for category in catalog["categories"]:
            stdout = io.StringIO()
            code = run_cli(
                ["describe", category["name"], "--json"],
                stdout=stdout,
                stderr=stderr,
                client_factory=factory,
            )
            self.assertEqual(code, 0)
            operations.extend(json.loads(stdout.getvalue())["operations"])
        routed_operations = [operation for operation in operations if operation["operation"] != "download"]
        actual = {(operation["method"], operation["path"]) for operation in routed_operations}
        non_job = {
            (operation["method"], operation["path"])
            for operation in routed_operations
            if operation["operation"] != "job"
        }
        webclient = {("PATCH", "/api/v3/salaryexport/salary-export-generation-tasks")}
        # Frozen method/path reference from the original OpenAPI audit, not the runtime registry.
        matrix_path = Path(__file__).parent / "fixtures" / "api-operations.csv"
        with matrix_path.open(newline="", encoding="utf-8") as matrix:
            expected = {(row["method"], row["path"]) for row in csv.DictReader(matrix)}
        self.assertEqual(non_job, expected | webclient)
        self.assertEqual((len(operations), len(actual), len(non_job - webclient)), (469, 467, 395))
        report_job = next(op for op in operations if op["name"] == "time-tracking-report" and op["operation"] == "job")
        self.assertEqual(
            (report_job["path"], report_job["contract"]),
            ("/api/v3/timetracking/time-tracking-report-task-jobs/{job_id}", "live-verified"),
        )
        downloads = {operation["name"]: operation for operation in operations if operation["operation"] == "download"}
        self.assertEqual(
            {
                name: (
                    operation["method"],
                    operation["path"],
                    operation["metadata_path"],
                    operation["binary_reference"],
                )
                for name, operation in downloads.items()
            },
            {
                "time-tracking-reports": (
                    None,
                    None,
                    "/api/v3/timetracking/time-tracking-reports/{id}",
                    "binaryContentReference",
                ),
                "salary-exports": (None, None, "/api/v3/salaryexport/salary-exports/{id}", "binaryContentReference"),
            },
        )

        stdout = io.StringIO()
        code = run_cli(
            ["describe", "platform", "teams", "--json"],
            stdout=stdout,
            stderr=stderr,
            client_factory=factory,
        )
        catalog = json.loads(stdout.getvalue())
        self.assertEqual((code, stderr.getvalue(), factory.calls), (0, "", 0))
        self.assertEqual(catalog["operation_count"], 8)
        self.assertEqual(
            next(
                operation
                for operation in catalog["operations"]
                if operation["category"] == "platform"
                and operation["name"] == "teams"
                and operation["operation"] == "delete"
            ),
            {
                "category": "platform",
                "item_id": True,
                "cli_json_payload": False,
                "http_json_body": False,
                "kind": "resource",
                "mcp_confirm": True,
                "method": "DELETE",
                "mcp_family": "crewmeister_delete",
                "name": "teams",
                "operation": "delete",
                "pageable": False,
                "path": "/api/v3/platform-app/teams/{id}",
                "side_effect": "write",
            },
        )
        job = next(operation for operation in catalog["operations"] if operation["operation"] == "job")
        self.assertEqual(
            (job["kind"], job["path"], job["mcp_family"], job["contract"]),
            ("resource", "/api/v3/platform-app/teams-jobs/{job_id}", "crewmeister_job", "guideline-derived"),
        )

    def test_describe_rejects_an_unknown_endpoint_without_creating_a_client(self) -> None:
        stdout, stderr = io.StringIO(), io.StringIO()
        factory = _CountingFactory(FakeTransport())

        code = run_cli(
            ["describe", "platform", "missing", "--json"], stdout=stdout, stderr=stderr, client_factory=factory
        )

        self.assertEqual((code, stdout.getvalue(), factory.calls), (2, "", 0))
        self.assertIn("Unknown Crewmeister endpoint", stderr.getvalue())

    def test_audit_json_snapshot_redacts_secrets_and_preserves_expiries(self) -> None:
        snapshot = {
            "pin_code": "synthetic-pin",
            "nested": [{"accessToken": "synthetic-token", "binaryContentReference": "synthetic-report-reference"}],
            "password": "synthetic-password",
            "feedUrl": "synthetic-feed",
            "accessTokenExpiresAt": "2030-01-01",
            "refreshTokenExpiresAt": "2030-02-01",
        }
        payload = {"resourceBefore": json.dumps(snapshot), "resourceAfter": None, "name": "kept"}
        stdout, stderr = io.StringIO(), io.StringIO()
        code = run_cli(
            ["audit", "changelogs", "get", "1"],
            stdout=stdout,
            stderr=stderr,
            client_factory=_factory(FakeTransport(FakeResponse(200, payload))),
        )
        self.assertEqual((code, stderr.getvalue()), (0, ""))
        self.assertNotIn("synthetic-", stdout.getvalue())
        output = json.loads(stdout.getvalue())
        self.assertEqual(
            json.loads(output["resourceBefore"]),
            {
                **snapshot,
                "pin_code": "[REDACTED]",
                "nested": [{"accessToken": "[REDACTED]", "binaryContentReference": "[REDACTED]"}],
                "password": "[REDACTED]",
                "feedUrl": "[REDACTED]",
            },
        )
        self.assertEqual((output["resourceAfter"], output["name"]), (None, "kept"))
        self.assertEqual(json.loads(payload["resourceBefore"]), snapshot)

    def test_unreadable_audit_snapshot_is_replaced_safely(self) -> None:
        payload = {"resourceBefore": '{"password":"synthetic-secret"', "resourceAfter": "[" * 2000 + "]" * 2000}
        self.assertEqual(redact_sensitive(payload), {"resourceBefore": "[REDACTED]", "resourceAfter": "[REDACTED]"})

    def test_explicit_page_preserves_metadata_and_redacts_content(self) -> None:
        page = {
            "content": [{"id": 7, "pincode": "synthetic-pin"}],
            "number": 2,
            "totalPages": 5,
            "totalElements": 41,
            "hasNextPage": True,
        }
        transport = FakeTransport(FakeResponse(200, page))
        stdout, stderr = io.StringIO(), io.StringIO()
        code = run_cli(
            ["platform", "members", "list", "--page", "2", "--page-size", "10", "--filter", "crewId==24", "--sort=-id"],
            stdout=stdout,
            stderr=stderr,
            client_factory=_factory(transport),
        )
        self.assertEqual((code, stderr.getvalue()), (0, ""))
        self.assertEqual(json.loads(stdout.getvalue()), {**page, "content": [{"id": 7, "pincode": "[REDACTED]"}]})
        self.assertEqual(len(transport.calls), 1)
        request = transport.calls[0][0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(
            parse.parse_qs(parse.urlparse(request.full_url).query),
            {"page": ["2"], "pageSize": ["10"], "filter": ["crewId==24"], "sort": ["-id"]},
        )

    def test_page_limit_conflict_rejects_before_client_creation(self) -> None:
        factory = _CountingFactory(FakeTransport())
        stdout, stderr = io.StringIO(), io.StringIO()
        code = run_cli(
            ["platform", "members", "list", "--page", "0", "--limit", "1"],
            stdout=stdout,
            stderr=stderr,
            client_factory=factory,
        )
        self.assertEqual((code, stdout.getvalue(), factory.calls), (2, "", 0))
        self.assertIn("--page and --limit", stderr.getvalue())

    def test_root_help_needs_no_client(self) -> None:
        stdout, stderr = io.StringIO(), io.StringIO()
        factory = _CountingFactory(FakeTransport())
        code = run_cli(["--help"], stdout=stdout, stderr=stderr, client_factory=factory)
        self.assertEqual(code, 0)
        self.assertIn("platform", stdout.getvalue())
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(factory.calls, 0)

    def test_list_writes_redacted_items_before_requesting_next_page(self) -> None:
        stdout, stderr = io.StringIO(), io.StringIO()
        transport = FakeTransport(
            FakeResponse(200, {"content": [{"token": "secret"}], "hasNextPage": True}),
            FakeResponse(200, {"content": [{"id": 2}], "hasNextPage": False}),
        )

        def send(request, timeout):
            if transport.calls:
                self.assertIn("[REDACTED]", stdout.getvalue())
                self.assertNotIn("secret", stdout.getvalue())
            return transport(request, timeout)

        code = run_cli(["platform", "members", "list"], stdout=stdout, stderr=stderr, client_factory=_factory(send))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue()), [{"token": "[REDACTED]"}, {"id": 2}])

    def test_invalid_next_page_stops_without_emitting_its_items_or_closing_array(self) -> None:
        stdout, stderr = io.StringIO(), io.StringIO()
        transport = FakeTransport(
            FakeResponse(200, {"content": [{"id": 1}], "hasNextPage": True}),
            FakeResponse(200, {"content": [{"id": "invalid-page-item"}]}),
        )
        code = run_cli(
            ["platform", "members", "list"], stdout=stdout, stderr=stderr, client_factory=_factory(transport)
        )
        self.assertEqual(code, 1)
        self.assertIn('"id": 1', stdout.getvalue())
        self.assertNotIn("invalid-page-item", stdout.getvalue())
        self.assertFalse(stdout.getvalue().rstrip().endswith("]"))
        self.assertIn("continuation", stderr.getvalue())

    def test_platform_list_outputs_json_and_passes_pagination_filter_sort_and_query_options(self) -> None:
        transport = FakeTransport(
            FakeResponse(200, {"content": [{"id": 1}], "hasNextPage": False}),
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = run_cli(
            [
                "platform",
                "members",
                "list",
                "--filter",
                "crewId==24",
                "--sort",
                "-id",
                "--sort=+name",
                "--query",
                "disabled=false",
                "--page-size",
                "50",
                "--limit",
                "1",
            ],
            stdout=stdout,
            stderr=stderr,
            client_factory=_factory(transport),
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(json.loads(stdout.getvalue()), [{"id": 1}])
        parsed = parse.urlparse(transport.calls[0][0].full_url)
        query = parse.parse_qs(parsed.query)
        self.assertEqual(parsed.path, "/api/v3/platform-app/members")
        self.assertEqual(query["filter"], ["crewId==24"])
        self.assertEqual(query["sort"], ["-id", "+name"])
        self.assertEqual(query["disabled"], ["false"])
        self.assertEqual(query["pageSize"], ["50"])

    def test_platform_write_requires_confirmation_before_reading_payload_or_calling_api(self) -> None:
        transport = FakeTransport(FakeResponse(200, {"ok": True}))
        stdout = io.StringIO()
        stderr = io.StringIO()
        stdin = _ExplodingInput()
        factory = _CountingFactory(transport)

        exit_code = run_cli(
            [
                "platform",
                "teams",
                "create",
                "--json-file",
                "-",
            ],
            stdout=stdout,
            stderr=stderr,
            stdin=stdin,
            client_factory=factory,
        )

        self.assertEqual(exit_code, 2)
        self.assertIn("--yes", stderr.getvalue())
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(factory.calls, 0)
        self.assertEqual(transport.calls, [])

    def test_platform_create_reads_json_from_stdin_and_redacts_sensitive_response_fields(self) -> None:
        transport = FakeTransport(
            FakeResponse(200, {"id": 1, "body": "server-token-body", "adminId": 5}),
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = run_cli(
            [
                "platform",
                "admin-authentication-tokens",
                "create",
                "--json-file",
                "-",
                "--yes",
            ],
            stdout=stdout,
            stderr=stderr,
            stdin=io.StringIO('{"adminId":5,"body":"client-token-body"}'),
            client_factory=_factory(transport),
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertNotIn("server-token-body", stdout.getvalue())
        self.assertEqual(json.loads(stdout.getvalue()), {"adminId": 5, "body": "[REDACTED]", "id": 1})
        request = transport.calls[0][0]
        self.assertEqual(request.get_method(), "POST")
        self.assertIsNone(request.get_header("X-write-async"))
        self.assertEqual(parse.urlparse(request.full_url).path, "/api/v3/platform-app/admin-authentication-tokens")
        self.assertEqual(json.loads(request.data.decode("utf-8")), {"adminId": 5, "body": "client-token-body"})

    def test_platform_task_command_requires_confirmation_and_posts_payload(self) -> None:
        transport = FakeTransport(FakeResponse(200, {"id": "task-1"}))
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = run_cli(
            [
                "platform",
                "task",
                "subscription-action",
                "--json-file",
                "-",
                "--yes",
                "--async",
            ],
            stdout=stdout,
            stderr=stderr,
            stdin=io.StringIO('{"subscriptionId":42,"action":"sync"}'),
            client_factory=_factory(transport),
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(stdout.getvalue()), {"id": "task-1"})
        request = transport.calls[0][0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("X-write-async"), "true")
        self.assertEqual(parse.urlparse(request.full_url).path, "/api/v3/platform-app/subscription-action-tasks")
        self.assertEqual(json.loads(request.data.decode("utf-8")), {"subscriptionId": 42, "action": "sync"})

    def test_platform_patch_reads_json_from_file_and_uses_item_path(self) -> None:
        transport = FakeTransport(FakeResponse(200, {"id": "team/1", "name": "Support"}))
        stdout = io.StringIO()
        stderr = io.StringIO()

        with tempfile.TemporaryDirectory() as temp_dir:
            payload_path = Path(temp_dir) / "payload.json"
            payload_path.write_text('{"name":"Support"}', encoding="utf-8")
            exit_code = run_cli(
                [
                    "platform",
                    "teams",
                    "patch",
                    "team/1",
                    "--json-file",
                    str(payload_path),
                    "--query",
                    "audit=true",
                    "--yes",
                ],
                stdout=stdout,
                stderr=stderr,
                client_factory=_factory(transport),
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(json.loads(stdout.getvalue()), {"id": "team/1", "name": "Support"})
        request = transport.calls[0][0]
        parsed = parse.urlparse(request.full_url)
        self.assertEqual(request.get_method(), "PATCH")
        self.assertEqual(parsed.path, "/api/v3/platform-app/teams/team%2F1")
        self.assertEqual(parse.parse_qs(parsed.query)["audit"], ["true"])
        self.assertEqual(json.loads(request.data.decode("utf-8")), {"name": "Support"})

    def test_platform_api_errors_do_not_echo_sensitive_api_messages(self) -> None:
        transport = FakeTransport(
            FakeResponse(
                403,
                {
                    "code": "PERMISSION_DENIED",
                    "message": "permission denied for token server-token-body",
                    "requestId": "request-123",
                },
            )
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = run_cli(
            ["platform", "admin-authentication-tokens", "get", "1"],
            stdout=stdout,
            stderr=stderr,
            client_factory=_factory(transport),
        )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("HTTP 403", stderr.getvalue())
        self.assertIn("code=PERMISSION_DENIED", stderr.getvalue())
        self.assertIn("request_id=request-123", stderr.getvalue())
        self.assertNotIn("server-token-body", stderr.getvalue())
        self.assertNotIn("permission denied for token", stderr.getvalue())

    def test_platform_sort_does_not_consume_following_long_option(self) -> None:
        transport = FakeTransport(FakeResponse(200, {"content": [], "hasNextPage": False}))
        stdout = io.StringIO()
        stderr = io.StringIO()
        factory = _CountingFactory(transport)

        exit_code = run_cli(
            ["platform", "members", "list", "--sort", "--limit", "1"],
            stdout=stdout,
            stderr=stderr,
            client_factory=factory,
        )

        self.assertEqual(exit_code, 2)
        self.assertIn("--sort", stderr.getvalue())
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(factory.calls, 0)
        self.assertEqual(transport.calls, [])

    def test_integration_list_outputs_json_and_passes_query_options(self) -> None:
        transport = FakeTransport(
            FakeResponse(200, {"content": [{"serviceName": "calendar"}], "hasNextPage": False}),
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = run_cli(
            [
                "integration",
                "oauth-status",
                "list",
                "--filter",
                "crewId==24",
                "--sort",
                "serviceName",
                "--query",
                "provider=google",
                "--page-size",
                "20",
                "--limit",
                "1",
            ],
            stdout=stdout,
            stderr=stderr,
            client_factory=_factory(transport),
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(json.loads(stdout.getvalue()), [{"serviceName": "calendar"}])
        parsed = parse.urlparse(transport.calls[0][0].full_url)
        query = parse.parse_qs(parsed.query)
        self.assertEqual(parsed.path, "/api/v3/integration/oauth-status")
        self.assertEqual(query["filter"], ["crewId==24"])
        self.assertEqual(query["sort"], ["serviceName"])
        self.assertEqual(query["provider"], ["google"])
        self.assertEqual(query["pageSize"], ["20"])

    def test_integration_connection_create_redacts_token_fields_from_stdout(self) -> None:
        transport = FakeTransport(
            FakeResponse(
                200,
                {
                    "id": "connection-1",
                    "accessToken": "server-access-token",
                    "refreshToken": "server-refresh-token",
                    "metadata": {"nestedToken": "nested-token"},
                },
            ),
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = run_cli(
            [
                "integration",
                "connections",
                "create",
                "--json-file",
                "-",
                "--yes",
            ],
            stdout=stdout,
            stderr=stderr,
            stdin=io.StringIO('{"crewId":24,"accessToken":"client-access-token"}'),
            client_factory=_factory(transport),
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertNotIn("server-access-token", stdout.getvalue())
        self.assertNotIn("server-refresh-token", stdout.getvalue())
        self.assertNotIn("nested-token", stdout.getvalue())
        self.assertEqual(
            json.loads(stdout.getvalue()),
            {
                "accessToken": "[REDACTED]",
                "id": "connection-1",
                "metadata": {"nestedToken": "[REDACTED]"},
                "refreshToken": "[REDACTED]",
            },
        )
        request = transport.calls[0][0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(parse.urlparse(request.full_url).path, "/api/v3/integration/connections")
        self.assertEqual(json.loads(request.data.decode("utf-8")), {"crewId": 24, "accessToken": "client-access-token"})

    def test_integration_task_requires_confirmation_before_reading_payload_or_calling_api(self) -> None:
        transport = FakeTransport(FakeResponse(200, {"iCalUrl": "https://calendar.example.test/feed-secret"}))
        stdout = io.StringIO()
        stderr = io.StringIO()
        stdin = _ExplodingInput()
        factory = _CountingFactory(transport)

        exit_code = run_cli(
            [
                "integration",
                "task",
                "i-cal-subscription",
                "--json-file",
                "-",
            ],
            stdout=stdout,
            stderr=stderr,
            stdin=stdin,
            client_factory=factory,
        )

        self.assertEqual(exit_code, 2)
        self.assertIn("--yes", stderr.getvalue())
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(factory.calls, 0)
        self.assertEqual(transport.calls, [])

    def test_integration_task_posts_payload_and_redacts_ical_url_from_stdout(self) -> None:
        transport = FakeTransport(
            FakeResponse(
                200, {"resourceAfterWrite": {"output": {"feedURL": "https://calendar.example.test/feed-secret"}}}
            )
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = run_cli(
            [
                "integration",
                "task",
                "i-cal-subscription",
                "--json-file",
                "-",
                "--yes",
            ],
            stdout=stdout,
            stderr=stderr,
            stdin=io.StringIO('{"crewId":24,"calendar":"absence"}'),
            client_factory=_factory(transport),
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertNotIn("feed-secret", stdout.getvalue())
        self.assertEqual(json.loads(stdout.getvalue()), {"resourceAfterWrite": {"output": {"feedURL": "[REDACTED]"}}})
        request = transport.calls[0][0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(parse.urlparse(request.full_url).path, "/api/v3/integration/i-cal-subscription-tasks")
        self.assertEqual(json.loads(request.data.decode("utf-8")), {"crewId": 24, "calendar": "absence"})

    def test_ical_task_writes_feed_to_file(self) -> None:
        feed_url = "https://calendar.example.test/feed-secret"
        response = {"resourceAfterWrite": {"output": {"feedURL": feed_url}}}
        transport = FakeTransport(FakeResponse(200, response))

        with tempfile.TemporaryDirectory() as directory:
            task_target = Path(directory) / "task-feed.txt"
            task_stdout, task_stderr = io.StringIO(), io.StringIO()
            task_code = run_cli(
                [
                    "integration",
                    "task",
                    "i-cal-subscription",
                    "--json-file",
                    "-",
                    "--yes",
                    "--output-file",
                    str(task_target),
                ],
                stdout=task_stdout,
                stderr=task_stderr,
                stdin=io.StringIO('{"crewId":24,"userId":7}'),
                client_factory=_factory(transport),
            )

            self.assertEqual((task_code, task_stderr.getvalue(), task_target.read_text()), (0, "", feed_url))
            self.assertEqual(task_target.stat().st_mode & 0o077, 0)
            self.assertNotIn("feed-secret", task_stdout.getvalue())

    def test_ical_output_refuses_an_existing_target_before_transport(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "existing-feed.txt"
            target.write_text("unchanged")
            transport = FakeTransport(FakeResponse(200, {"unexpected": True}))
            stdout, stderr = io.StringIO(), io.StringIO()

            code = run_cli(
                [
                    "integration",
                    "task",
                    "i-cal-subscription",
                    "--json-file",
                    "-",
                    "--yes",
                    "--output-file",
                    str(target),
                ],
                stdout=stdout,
                stderr=stderr,
                stdin=io.StringIO('{"crewId":24,"userId":7}'),
                client_factory=_factory(transport),
            )

            self.assertEqual((code, stdout.getvalue(), target.read_text(), transport.calls), (2, "", "unchanged", []))
            self.assertIn("Output file could not be prepared.", stderr.getvalue())

    def test_report_download_writes_provider_binary_to_a_new_private_file(self) -> None:
        binary = FakeResponse(200, None)
        binary._body = b"synthetic-report"
        transport = FakeTransport(
            FakeResponse(200, {"binaryContentReference": "/api/v3/timetracking/time-tracking-reports/7/stream"}),
            binary,
        )

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "report.xlsx"
            stdout, stderr = io.StringIO(), io.StringIO()
            code = run_cli(
                ["time-tracking", "time-tracking-reports", "download", "7", "--output-file", str(target)],
                stdout=stdout,
                stderr=stderr,
                client_factory=_factory(transport),
            )

            self.assertEqual(
                (code, stdout.getvalue(), stderr.getvalue(), target.read_bytes()), (0, "", "", b"synthetic-report")
            )
            self.assertEqual(target.stat().st_mode & 0o077, 0)
        self.assertEqual(
            [parse.urlparse(call[0].full_url).path for call in transport.calls],
            ["/api/v3/timetracking/time-tracking-reports/7", "/api/v3/timetracking/time-tracking-reports/7/stream"],
        )

    def test_report_download_rejects_an_external_reference_without_leaving_a_file(self) -> None:
        transport = FakeTransport(
            FakeResponse(200, {"binaryContentReference": "%2Fapi%2Fv3%2F@outside.invalid/report"})
        )

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "report.xlsx"
            stdout, stderr = io.StringIO(), io.StringIO()
            code = run_cli(
                ["time-tracking", "time-tracking-reports", "download", "7", "--output-file", str(target)],
                stdout=stdout,
                stderr=stderr,
                client_factory=_factory(transport),
            )

            self.assertEqual((code, stdout.getvalue(), target.exists(), len(transport.calls)), (1, "", False, 1))
            self.assertIn("relative API paths", stderr.getvalue())

    def test_job_error_returns_a_failure_status_without_a_new_write(self) -> None:
        transport = FakeTransport(FakeResponse(200, {"id": "job-1", "status": "ERROR"}))
        stdout, stderr = io.StringIO(), io.StringIO()

        exit_code = run_cli(
            ["--error-format", "json", "integration", "job", "i-cal-subscription", "job-1"],
            stdout=stdout,
            stderr=stderr,
            client_factory=_factory(transport),
        )

        self.assertEqual(exit_code, 1)
        self.assertEqual(json.loads(stdout.getvalue()), {"id": "job-1", "status": "ERROR"})
        self.assertEqual(
            json.loads(stderr.getvalue()), {"error": {"type": "job", "message": "Crewmeister job reported ERROR."}}
        )
        request = transport.calls[0][0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(
            parse.urlparse(request.full_url).path,
            "/api/v3/integration/i-cal-subscription-tasks-jobs/job-1",
        )
        response = {
            "@type": "com.crewmeister/SyncWriteResponse",
            "resourceAfterWrite": {"output": {"timeTrackingReport": {"id": 24}}},
        }
        job = {"id": "job/2", "status": "SUCCESS", "apiError": None, "responses": [response]}
        transport = FakeTransport(FakeResponse(200, job))
        stdout, stderr = io.StringIO(), io.StringIO()
        exit_code = run_cli(
            ["time-tracking", "job", "time-tracking-report", "job/2"],
            stdout=stdout,
            stderr=stderr,
            client_factory=_factory(transport),
        )
        self.assertEqual(
            (exit_code, stderr.getvalue(), json.loads(stdout.getvalue())),
            (0, "", job),
        )
        self.assertEqual(
            parse.urlparse(transport.calls[0][0].full_url).path,
            "/api/v3/timetracking/time-tracking-report-task-jobs/job%2F2",
        )

    def test_integration_unsupported_operation_exits_before_creating_client(self) -> None:
        transport = FakeTransport(FakeResponse(200, {"ok": True}))
        stdout = io.StringIO()
        stderr = io.StringIO()
        factory = _CountingFactory(transport)

        exit_code = run_cli(
            ["integration", "oauth-status", "get", "calendar"],
            stdout=stdout,
            stderr=stderr,
            client_factory=factory,
        )

        self.assertEqual(exit_code, 2)
        self.assertIn("invalid choice: 'get'", stderr.getvalue())
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(factory.calls, 0)
        self.assertEqual(transport.calls, [])

        stderr = io.StringIO()
        exit_code = run_cli(
            ["--error-f", "json", "integration", "oauth-status", "get", "calendar"],
            stdout=stdout,
            stderr=stderr,
            client_factory=factory,
        )
        self.assertEqual(
            (exit_code, json.loads(stderr.getvalue()), factory.calls),
            (2, {"error": {"message": "Syntax error.", "type": "syntax"}}, 0),
        )

    def test_new_resource_categories_list_outputs_json_and_passes_filter_options(self) -> None:
        cases = [
            (
                [
                    "time-tracking",
                    "bookings",
                    "list",
                    "--filter",
                    "crewId==24;userId==7;allocationDate>=2026-01-01",
                    "--sort",
                    "-allocationDate",
                    "--query",
                    "includeDeleted=false",
                    "--page-size",
                    "25",
                    "--limit",
                    "1",
                ],
                FakeResponse(200, {"content": [{"id": "booking-1", "duration": "PT8H"}], "hasNextPage": False}),
                "/api/v3/timetracking/bookings",
                "crewId==24;userId==7;allocationDate>=2026-01-01",
                "-allocationDate",
                "includeDeleted",
                [{"duration": "PT8H", "id": "booking-1"}],
            ),
            (
                [
                    "absence-manager",
                    "absences",
                    "list",
                    "--filter",
                    "crewId==24;userId==7;from>=2026-01-01",
                    "--sort",
                    "-from",
                    "--query",
                    "includeCancelled=false",
                    "--page-size",
                    "25",
                    "--limit",
                    "1",
                ],
                FakeResponse(200, {"content": [{"id": "absence-1", "state": "REQUESTED"}], "hasNextPage": False}),
                "/api/v3/absencemanager/absences",
                "crewId==24;userId==7;from>=2026-01-01",
                "-from",
                "includeCancelled",
                [{"id": "absence-1", "state": "REQUESTED"}],
            ),
            (
                [
                    "shift-planner",
                    "shifts",
                    "list",
                    "--filter",
                    "crewId==24;userId==7;from>=2026-01-01T00:00:00Z",
                    "--sort",
                    "-from",
                    "--query",
                    "includeUnpublished=false",
                    "--page-size",
                    "25",
                    "--limit",
                    "1",
                ],
                FakeResponse(200, {"content": [{"id": "shift-1", "userId": 7}], "hasNextPage": False}),
                "/api/v3/shiftplanner/shifts",
                "crewId==24;userId==7;from>=2026-01-01T00:00:00Z",
                "-from",
                "includeUnpublished",
                [{"id": "shift-1", "userId": 7}],
            ),
            (
                [
                    "salary-export",
                    "salary-exports",
                    "list",
                    "--filter",
                    "crewId==24;exportType==DATEV_LOHN_UND_GEHALT;firstDate>=2026-01-01",
                    "--sort",
                    "-firstDate",
                    "--query",
                    "includeClosed=false",
                    "--page-size",
                    "25",
                    "--limit",
                    "1",
                ],
                FakeResponse(
                    200,
                    {
                        "content": [
                            {
                                "id": "salary-export-1",
                                "consultantNumber": "consultant-placeholder",
                                "customerNumber": "customer-placeholder",
                            }
                        ],
                        "hasNextPage": False,
                    },
                ),
                "/api/v3/salaryexport/salary-exports",
                "crewId==24;exportType==DATEV_LOHN_UND_GEHALT;firstDate>=2026-01-01",
                "-firstDate",
                "includeClosed",
                [
                    {
                        "consultantNumber": "consultant-placeholder",
                        "customerNumber": "customer-placeholder",
                        "id": "salary-export-1",
                    }
                ],
            ),
        ]

        for args, response, expected_path, expected_filter, expected_sort, expected_query_key, expected_output in cases:
            with self.subTest(args=args):
                transport = FakeTransport(response)
                stdout = io.StringIO()
                stderr = io.StringIO()

                exit_code = run_cli(
                    [*args],
                    stdout=stdout,
                    stderr=stderr,
                    client_factory=_factory(transport),
                )

                self.assertEqual(exit_code, 0)
                self.assertEqual(stderr.getvalue(), "")
                self.assertEqual(json.loads(stdout.getvalue()), expected_output)
                parsed = parse.urlparse(transport.calls[0][0].full_url)
                query = parse.parse_qs(parsed.query)
                self.assertEqual(parsed.path, expected_path)
                self.assertEqual(query["filter"], [expected_filter])
                self.assertEqual(query["sort"], [expected_sort])
                self.assertEqual(query[expected_query_key], ["false"])
                self.assertEqual(query["pageSize"], ["25"])

    def test_new_resource_category_writes_use_registered_methods_and_payloads(self) -> None:
        salary_batch = [
            {
                "method": "POST",
                "path": "/",
                "body": {
                    "input": {
                        "crewId": 24,
                        "salaryExportConfigurationId": 1,
                        "from": "2026-08-01",
                        "to": "2026-08-31",
                        "userIdFilter": [7],
                    }
                },
            }
        ]
        salary_result = [
            {
                "statusCode": 201,
                "body": {
                    "@type": "com.crewmeister/SyncWriteResponse",
                    "resourceAfterWrite": {
                        "output": {"salaryExport": {"id": 123, "binaryContentReference": "[REDACTED]"}}
                    },
                },
            }
        ]
        cases = [
            (
                ["salary-export", "salary-export-generation-tasks", "batch", "--json-file", "-", "--yes"],
                json.dumps(salary_batch),
                FakeResponse(
                    200,
                    json.loads(
                        json.dumps(salary_result).replace(
                            "[REDACTED]", "/api/v3/salaryexport/salary-exports/123/stream"
                        )
                    ),
                ),
                "/api/v3/salaryexport/salary-export-generation-tasks",
                "PATCH",
                salary_batch,
                salary_result,
            ),
            (
                ["time-tracking", "stamps", "create", "--json-file", "-", "--yes"],
                '{"crewId":24,"stampType":"START_WORK"}',
                FakeResponse(200, {"id": "stamp-1", "stampType": "START_WORK"}),
                "/api/v3/timetracking/stamps",
                "POST",
                {"crewId": 24, "stampType": "START_WORK"},
                {"id": "stamp-1", "stampType": "START_WORK"},
            ),
            (
                ["time-tracking", "task", "time-tracking-report", "--json-file", "-", "--yes"],
                '{"crewId":24,"from":"2026-01-01","to":"2026-01-31","userIds":"7,8","timeCategoryOneIds":"1","timeCategoryTwoIds":"2","fileCategory":"SPREADSHEET","language":"DE"}',
                FakeResponse(200, {"reportId": "report-1", "status": "queued"}),
                "/api/v3/timetracking/time-tracking-report-tasks",
                "POST",
                {
                    "crewId": 24,
                    "from": "2026-01-01",
                    "to": "2026-01-31",
                    "userIds": "7,8",
                    "timeCategoryOneIds": "1",
                    "timeCategoryTwoIds": "2",
                    "fileCategory": "SPREADSHEET",
                    "language": "DE",
                },
                {"reportId": "report-1", "status": "queued"},
            ),
            (
                ["absence-manager", "absences", "create", "--json-file", "-", "--yes"],
                '{"crewId":24,"userId":7,"absenceType":1}',
                FakeResponse(200, {"id": "absence-1", "state": "REQUESTED"}),
                "/api/v3/absencemanager/absences",
                "POST",
                {"crewId": 24, "userId": 7, "absenceType": 1},
                {"id": "absence-1", "state": "REQUESTED"},
            ),
            (
                ["absence-manager", "working-days", "patch", "working-day/1", "--json-file", "-", "--yes"],
                '{"length":0.5}',
                FakeResponse(200, {"id": "working-day/1", "length": 0.5}),
                "/api/v3/absencemanager/working-days/working-day%2F1",
                "PATCH",
                {"length": 0.5},
                {"id": "working-day/1", "length": 0.5},
            ),
            (
                ["shift-planner", "workplaces", "create", "--json-file", "-", "--yes"],
                '{"crewId":24,"name":"Kitchen"}',
                FakeResponse(200, {"id": "workplace-1", "name": "Kitchen"}),
                "/api/v3/shiftplanner/workplaces",
                "POST",
                {"crewId": 24, "name": "Kitchen"},
                {"id": "workplace-1", "name": "Kitchen"},
            ),
            (
                ["shift-planner", "task", "shift-apply-template", "--json-file", "-", "--yes"],
                '{"crewId":24,"templateId":1,"date":"2026-01-01","zoneId":"Europe/Berlin"}',
                FakeResponse(200, {"task": "apply-template", "status": "queued"}),
                "/api/v3/shiftplanner/shift-apply-template-tasks",
                "POST",
                {"crewId": 24, "templateId": 1, "date": "2026-01-01", "zoneId": "Europe/Berlin"},
                {"task": "apply-template", "status": "queued"},
            ),
            (
                ["shift-planner", "task", "shift-copy", "--json-file", "-", "--yes"],
                '{"crewId":24,"originStartDate":"2026-01-01","originEndDate":"2026-01-08","targetStartDate":"2026-02-01","zoneId":"Europe/Berlin"}',
                FakeResponse(200, {"task": "copy", "status": "queued"}),
                "/api/v3/shiftplanner/shift-copy-tasks",
                "POST",
                {
                    "crewId": 24,
                    "originStartDate": "2026-01-01",
                    "originEndDate": "2026-01-08",
                    "targetStartDate": "2026-02-01",
                    "zoneId": "Europe/Berlin",
                },
                {"task": "copy", "status": "queued"},
            ),
            (
                ["shift-planner", "task", "shift-publish", "--json-file", "-", "--yes"],
                '{"shiftIdToPublish":1}',
                FakeResponse(200, {"task": "publish", "status": "queued"}),
                "/api/v3/shiftplanner/shift-publish-tasks",
                "POST",
                {"shiftIdToPublish": 1},
                {"task": "publish", "status": "queued"},
            ),
            (
                [
                    "salary-export",
                    "wage-type-allocation-duration-hours",
                    "create",
                    "--json-file",
                    "-",
                    "--yes",
                ],
                (
                    '{"crewId":24,"salaryExportConfigurationId":1,'
                    '"durationDefinitionType":"OVERTIME","employeeType":"COMMERCIAL",'
                    '"wageType":"WT-1000","transferIdentifier":"DATEV-1000"}'
                ),
                FakeResponse(200, {"id": "duration-allocation-1", "wageType": "WT-1000"}),
                "/api/v3/salaryexport/wage-type-allocation-duration-hours",
                "POST",
                {
                    "crewId": 24,
                    "salaryExportConfigurationId": 1,
                    "durationDefinitionType": "OVERTIME",
                    "employeeType": "COMMERCIAL",
                    "wageType": "WT-1000",
                    "transferIdentifier": "DATEV-1000",
                },
                {"id": "duration-allocation-1", "wageType": "WT-1000"},
            ),
        ]

        for args, stdin_text, response, expected_path, expected_method, expected_request, expected_output in cases:
            with self.subTest(args=args):
                transport = FakeTransport(response)
                stdout = io.StringIO()
                stderr = io.StringIO()

                exit_code = run_cli(
                    [*args],
                    stdout=stdout,
                    stderr=stderr,
                    stdin=io.StringIO(stdin_text),
                    client_factory=_factory(transport),
                )

                self.assertEqual(exit_code, 0)
                self.assertEqual(stderr.getvalue(), "")
                self.assertEqual(json.loads(stdout.getvalue()), expected_output)
                request = transport.calls[0][0]
                self.assertEqual(request.get_method(), expected_method)
                self.assertEqual(parse.urlparse(request.full_url).path, expected_path)
                self.assertEqual(json.loads(request.data.decode("utf-8")), expected_request)

    def test_salary_export_api_errors_do_not_echo_payroll_sensitive_payload_or_messages(self) -> None:
        transport = FakeTransport(
            FakeResponse(
                400,
                {
                    "code": "PAYROLL_MAPPING_INVALID",
                    "message": (
                        "Wage type WT-SECRET with transfer identifier DATEV-SECRET for consultant "
                        "CONSULTANT-SECRET and customer CUSTOMER-SECRET is invalid."
                    ),
                    "requestId": "request-salary-1",
                },
            )
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = run_cli(
            [
                "salary-export",
                "salary-export-configurations",
                "patch",
                "configuration-1",
                "--json-file",
                "-",
                "--yes",
            ],
            stdout=stdout,
            stderr=stderr,
            stdin=io.StringIO(
                '{"consultantNumber":"CONSULTANT-SECRET","customerNumber":"CUSTOMER-SECRET",'
                '"wageType":"WT-SECRET","transferIdentifier":"DATEV-SECRET"}'
            ),
            client_factory=_factory(transport),
        )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("HTTP 400", stderr.getvalue())
        self.assertIn("code=PAYROLL_MAPPING_INVALID", stderr.getvalue())
        self.assertIn("request_id=request-salary-1", stderr.getvalue())
        self.assertNotIn("CONSULTANT-SECRET", stderr.getvalue())
        self.assertNotIn("CUSTOMER-SECRET", stderr.getvalue())
        self.assertNotIn("WT-SECRET", stderr.getvalue())
        self.assertNotIn("DATEV-SECRET", stderr.getvalue())

    def test_new_resource_category_unsafe_operations_exit_before_reading_payload_or_calling_api(self) -> None:
        cases = [
            (
                ["time-tracking", "stamps", "create", "--json-file", "-"],
                "--yes",
            ),
            (
                ["time-tracking", "duration-balances", "create", "--json-file", "-", "--yes"],
                "invalid choice: 'create'",
            ),
            (
                ["absence-manager", "absences", "create", "--json-file", "-"],
                "--yes",
            ),
            (
                ["absence-manager", "entitlement-balances", "create", "--json-file", "-", "--yes"],
                "invalid choice: 'create'",
            ),
            (
                ["shift-planner", "shifts", "create", "--json-file", "-"],
                "--yes",
            ),
            (
                ["shift-planner", "task", "shift-publish", "--json-file", "-"],
                "--yes",
            ),
            (
                ["salary-export", "salary-export-generation-tasks", "batch", "--json-file", "-"],
                "--yes",
            ),
        ]

        for args, expected_error in cases:
            with self.subTest(args=args):
                transport = FakeTransport(FakeResponse(200, {"ok": True}))
                stdout = io.StringIO()
                stderr = io.StringIO()
                factory = _CountingFactory(transport)

                exit_code = run_cli(
                    [*args],
                    stdout=stdout,
                    stderr=stderr,
                    stdin=_ExplodingInput(),
                    client_factory=factory,
                )

                self.assertEqual(exit_code, 2)
                self.assertIn(expected_error, stderr.getvalue())
                self.assertEqual(stdout.getvalue(), "")
                self.assertEqual(factory.calls, 0)
                self.assertEqual(transport.calls, [])


class _ExplodingInput(io.StringIO):
    def read(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("stdin should not be read before write confirmation")


class _CountingFactory:
    def __init__(self, transport: FakeTransport) -> None:
        self.transport = transport
        self.calls = 0

    def __call__(self) -> CrewmeisterApiClient:
        self.calls += 1
        return _client(self.transport)


def _factory(transport: FakeTransport):
    def create_client() -> CrewmeisterApiClient:
        return _client(transport)

    return create_client


def _client(transport: FakeTransport) -> CrewmeisterApiClient:
    return CrewmeisterApiClient(
        CrewmeisterApiConfig(base_url="https://api.crewmeister.com", bearer_token="existing-token"),
        transport=transport,
    )


if __name__ == "__main__":
    unittest.main()
