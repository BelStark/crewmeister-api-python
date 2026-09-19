"""Synthetic transport checks, not server acceptance; see README.md#known-api-limitations.

Task envelopes and unresolved vendor schemas remain open.
"""

import io
import json
import unittest
from urllib import parse

from crewmeister_api import (
    AuditApiService,
    CrewmeisterApiClient,
    CrewmeisterApiConfig,
    CrewmeisterApiError,
)
from crewmeister_api.audit import AUDIT_RESOURCE_NAMES
from crewmeister_api.cli import run_cli
from tests.support import FakeResponse, FakeTransport


class AuditApiServiceTests(unittest.TestCase):
    def test_audit_registry_covers_documented_resources(self) -> None:
        self.assertEqual(
            AUDIT_RESOURCE_NAMES,
            (
                "changelogs",
                "changelog-settings",
            ),
        )

    def test_resource_descriptors_use_documented_paths_and_crud_operations(self) -> None:
        service = AuditApiService(_client(FakeTransport()))

        self.assertEqual(tuple(service.resources), AUDIT_RESOURCE_NAMES)
        for name, endpoint in service.resources.items():
            self.assertEqual(endpoint.path, f"/api/v3/audit-app/{name}")
            self.assertTrue(endpoint.supports("list"))
            self.assertTrue(endpoint.supports("get"))
            self.assertTrue(endpoint.supports("create"))
            self.assertTrue(endpoint.supports("patch"))
            self.assertTrue(endpoint.supports("replace"))
            self.assertTrue(endpoint.supports("delete"))

    def test_list_resource_uses_audit_prefix_filter_sort_and_pagination(self) -> None:
        transport = FakeTransport(
            FakeResponse(
                200,
                {
                    "content": [
                        {
                            "id": "changelog-1",
                            "action": "UPDATE",
                            "resourceAfter": {"email": "employee@example.test"},
                        }
                    ],
                    "hasNextPage": False,
                },
            ),
        )
        service = AuditApiService(_client(transport))

        entries = service.list_resource(
            "changelogs",
            query={
                "filter": "crewId==24;changeTime>=2026-01-01T00:00:00Z;type==Stamp;action==UPDATE",
                "sort": ["-changeTime"],
            },
            page_size=25,
            limit=1,
        )

        self.assertEqual(
            entries,
            [
                {
                    "id": "changelog-1",
                    "action": "UPDATE",
                    "resourceAfter": {"email": "employee@example.test"},
                }
            ],
        )
        request = transport.calls[0][0]
        parsed = parse.urlparse(request.full_url)
        query = parse.parse_qs(parsed.query)
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(parsed.path, "/api/v3/audit-app/changelogs")
        self.assertEqual(
            query["filter"],
            ["crewId==24;changeTime>=2026-01-01T00:00:00Z;type==Stamp;action==UPDATE"],
        )
        self.assertEqual(query["sort"], ["-changeTime"])
        self.assertEqual(query["page"], ["0"])
        self.assertEqual(query["pageSize"], ["25"])

    def test_crud_resource_methods_use_documented_paths_and_payloads(self) -> None:
        transport = FakeTransport(
            FakeResponse(200, {"content": [{"id": "changelog-1"}], "hasNextPage": False}),
            FakeResponse(200, {"id": "setting-1", "retentionDays": 90}),
            FakeResponse(200, {"created": True}),
            FakeResponse(200, {"batched": True}),
            FakeResponse(200, {"patched": True}),
            FakeResponse(200, {"replaced": True}),
            FakeResponse(200, None),
            FakeResponse(200, {"id": "changelog-1"}),
        )
        service = AuditApiService(_client(transport))

        self.assertEqual(
            service.list_resource("changelogs", query={"filter": "crewId==24"}),
            [{"id": "changelog-1"}],
        )
        self.assertEqual(
            service.get_resource("changelog-settings", "setting/1"), {"id": "setting-1", "retentionDays": 90}
        )
        self.assertEqual(
            service.create_resource(
                "changelog-settings",
                {
                    "crewId": 24,
                    "retentionDays": 365,
                },
            ),
            {"created": True},
        )
        self.assertEqual(
            service.batch_patch_resource("changelogs", [{"method": "DELETE", "path": "/1"}]), {"batched": True}
        )
        self.assertEqual(
            service.patch_resource("changelog-settings", "setting/1", {"retentionDays": 180}),
            {"patched": True},
        )
        self.assertEqual(
            service.replace_resource(
                "changelog-settings",
                "setting 1",
                {"crewId": 24, "retentionDays": 365},
            ),
            {"replaced": True},
        )
        self.assertIsNone(service.delete_resource("changelogs", "change log 1"))
        self.assertEqual(service.get_resource("changelogs", "changelog/1"), {"id": "changelog-1"})

        requests = [call[0] for call in transport.calls]
        self.assertEqual(
            [request.get_method() for request in requests],
            ["GET", "GET", "POST", "PATCH", "PATCH", "PUT", "DELETE", "GET"],
        )
        self.assertEqual(parse.urlparse(requests[0].full_url).path, "/api/v3/audit-app/changelogs")
        self.assertEqual(
            parse.urlparse(requests[1].full_url).path,
            "/api/v3/audit-app/changelog-settings/setting%2F1",
        )
        self.assertEqual(parse.urlparse(requests[2].full_url).path, "/api/v3/audit-app/changelog-settings")
        self.assertEqual(parse.urlparse(requests[3].full_url).path, "/api/v3/audit-app/changelogs")
        self.assertEqual(
            parse.urlparse(requests[4].full_url).path,
            "/api/v3/audit-app/changelog-settings/setting%2F1",
        )
        self.assertEqual(
            parse.urlparse(requests[5].full_url).path,
            "/api/v3/audit-app/changelog-settings/setting%201",
        )
        self.assertEqual(parse.urlparse(requests[6].full_url).path, "/api/v3/audit-app/changelogs/change%20log%201")
        self.assertEqual(parse.urlparse(requests[7].full_url).path, "/api/v3/audit-app/changelogs/changelog%2F1")
        self.assertEqual(json.loads(requests[2].data.decode("utf-8")), {"crewId": 24, "retentionDays": 365})
        self.assertEqual(json.loads(requests[3].data.decode("utf-8")), [{"method": "DELETE", "path": "/1"}])
        self.assertEqual(json.loads(requests[4].data.decode("utf-8")), {"retentionDays": 180})
        self.assertEqual(json.loads(requests[5].data.decode("utf-8")), {"crewId": 24, "retentionDays": 365})

    def test_api_error_string_does_not_echo_large_audit_snapshots(self) -> None:
        snapshot_text = "AUDIT-SNAPSHOT-SECRET-" + ("x" * 2048)
        transport = FakeTransport(
            FakeResponse(
                400,
                {
                    "code": "AUDIT_RETENTION_INVALID",
                    "message": f"invalid retention for resourceBefore={snapshot_text}",
                    "details": {
                        "resourceBefore": {"raw": snapshot_text},
                        "resourceAfter": {"raw": snapshot_text},
                    },
                    "requestId": "request-audit-1",
                },
            )
        )
        service = AuditApiService(_client(transport))

        with self.assertRaises(CrewmeisterApiError) as context:
            service.patch_resource("changelog-settings", "setting-1", {"retentionDays": 180})

        self.assertIn("HTTP 400", str(context.exception))
        self.assertIn("code=AUDIT_RETENTION_INVALID", str(context.exception))
        self.assertIn("request_id=request-audit-1", str(context.exception))
        self.assertNotIn(snapshot_text, str(context.exception))
        self.assertNotIn("resourceBefore", str(context.exception))
        self.assertNotIn("resourceAfter", str(context.exception))
        self.assertIn(snapshot_text, json.dumps(context.exception.payload))


class AuditApiCliTests(unittest.TestCase):
    def test_list_changelogs_outputs_json_and_passes_audit_filters(self) -> None:
        transport = FakeTransport(
            FakeResponse(
                200,
                {
                    "content": [
                        {
                            "id": "changelog-1",
                            "action": "UPDATE",
                            "resourceBefore": {"name": "Before"},
                            "resourceAfter": {"name": "After"},
                        }
                    ],
                    "hasNextPage": False,
                },
            ),
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = run_cli(
            [
                "audit",
                "changelogs",
                "list",
                "--filter",
                "crewId==24;changeTime>=2026-01-01T00:00:00Z;type==Stamp;action==UPDATE",
                "--sort",
                "-changeTime",
                "--query",
                # Arbitrary query forwarding probe; not a documented server parameter.
                "authentication.type=USER",
                "--page-size",
                "25",
                "--limit",
                "1",
            ],
            stdout=stdout,
            stderr=stderr,
            client_factory=_factory(transport),
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(
            json.loads(stdout.getvalue()),
            [
                {
                    "action": "UPDATE",
                    "id": "changelog-1",
                    "resourceAfter": {"name": "After"},
                    "resourceBefore": {"name": "Before"},
                }
            ],
        )
        parsed = parse.urlparse(transport.calls[0][0].full_url)
        query = parse.parse_qs(parsed.query)
        self.assertEqual(parsed.path, "/api/v3/audit-app/changelogs")
        self.assertEqual(
            query["filter"],
            ["crewId==24;changeTime>=2026-01-01T00:00:00Z;type==Stamp;action==UPDATE"],
        )
        self.assertEqual(query["sort"], ["-changeTime"])
        self.assertEqual(query["authentication.type"], ["USER"])
        self.assertEqual(query["pageSize"], ["25"])

    def test_patch_changelog_settings_posts_payload(self) -> None:
        transport = FakeTransport(FakeResponse(200, {"id": "setting-1", "retentionDays": 180}))
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = run_cli(
            [
                "audit",
                "changelog-settings",
                "patch",
                "setting-1",
                "--json-file",
                "-",
                "--yes",
            ],
            stdout=stdout,
            stderr=stderr,
            stdin=io.StringIO('{"retentionDays":180}'),
            client_factory=_factory(transport),
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(json.loads(stdout.getvalue()), {"id": "setting-1", "retentionDays": 180})
        request = transport.calls[0][0]
        self.assertEqual(request.get_method(), "PATCH")
        self.assertEqual(parse.urlparse(request.full_url).path, "/api/v3/audit-app/changelog-settings/setting-1")
        self.assertEqual(json.loads(request.data.decode("utf-8")), {"retentionDays": 180})

    def test_api_errors_do_not_echo_large_audit_snapshots_or_messages(self) -> None:
        snapshot_text = "AUDIT-SNAPSHOT-SECRET-" + ("x" * 2048)
        transport = FakeTransport(
            FakeResponse(
                400,
                {
                    "code": "AUDIT_RETENTION_INVALID",
                    "message": f"invalid retention for resourceBefore={snapshot_text}",
                    "details": {
                        "resourceBefore": {"raw": snapshot_text},
                        "resourceAfter": {"raw": snapshot_text},
                    },
                    "requestId": "request-audit-1",
                },
            )
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = run_cli(
            [
                "audit",
                "changelog-settings",
                "patch",
                "setting-1",
                "--json-file",
                "-",
                "--yes",
            ],
            stdout=stdout,
            stderr=stderr,
            stdin=io.StringIO(f'{{"retentionDays":180,"resourceBefore":"{snapshot_text}"}}'),
            client_factory=_factory(transport),
        )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("HTTP 400", stderr.getvalue())
        self.assertIn("code=AUDIT_RETENTION_INVALID", stderr.getvalue())
        self.assertIn("request_id=request-audit-1", stderr.getvalue())
        self.assertNotIn(snapshot_text, stderr.getvalue())
        self.assertNotIn("resourceBefore", stderr.getvalue())
        self.assertNotIn("resourceAfter", stderr.getvalue())

    def test_write_operations_exit_before_reading_payload_or_calling_api_without_confirmation(self) -> None:
        transport = FakeTransport(FakeResponse(200, {"ok": True}))
        stdout = io.StringIO()
        stderr = io.StringIO()
        factory = _CountingFactory(transport)

        exit_code = run_cli(
            ["audit", "changelog-settings", "patch", "setting-1", "--json-file", "-"],
            stdout=stdout,
            stderr=stderr,
            stdin=_ExplodingInput(),
            client_factory=factory,
        )

        self.assertEqual(exit_code, 2)
        self.assertIn("--yes", stderr.getvalue())
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(factory.calls, 0)
        self.assertEqual(transport.calls, [])


def _client(transport: FakeTransport) -> CrewmeisterApiClient:
    return CrewmeisterApiClient(
        CrewmeisterApiConfig(base_url="https://api.crewmeister.com", bearer_token="existing-token"),
        transport=transport,
    )


def _factory(transport: FakeTransport):
    def create_client() -> CrewmeisterApiClient:
        return _client(transport)

    return create_client


class _CountingFactory:
    def __init__(self, transport: FakeTransport) -> None:
        self.transport = transport
        self.calls = 0

    def __call__(self) -> CrewmeisterApiClient:
        self.calls += 1
        return _client(self.transport)


class _ExplodingInput(io.StringIO):
    def read(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("stdin should not be read before write confirmation")


if __name__ == "__main__":
    unittest.main()
