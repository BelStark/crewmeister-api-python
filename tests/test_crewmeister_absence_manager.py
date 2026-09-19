"""Synthetic transport checks, not server acceptance; see README.md#known-api-limitations.

Task envelopes and unresolved vendor schemas remain open.
"""

import json
import unittest
from urllib import parse

from crewmeister_api import (
    AbsenceManagerApiService,
    CrewmeisterApiClient,
    CrewmeisterApiConfig,
    CrewmeisterConfigError,
)
from crewmeister_api.absence_manager import (
    ABSENCE_MANAGER_READ_ONLY_RESOURCE_NAMES,
    ABSENCE_MANAGER_RESOURCE_NAMES,
)
from crewmeister_api.resources import LIST_RESOURCE_OPERATION
from tests.support import FakeResponse, FakeTransport


class AbsenceManagerApiServiceTests(unittest.TestCase):
    def test_absence_manager_registry_covers_documented_resources(self) -> None:
        self.assertEqual(
            ABSENCE_MANAGER_RESOURCE_NAMES,
            (
                "absences",
                "absence-entitlements",
                "absence-type-settings",
                "absence-visibility-settings",
                "entitlement-adjustments",
                "entitlement-balances",
                "working-days",
            ),
        )

    def test_resource_descriptors_use_documented_paths_and_read_only_operations(self) -> None:
        service = AbsenceManagerApiService(_client(FakeTransport()))

        self.assertEqual(tuple(service.resources), ABSENCE_MANAGER_RESOURCE_NAMES)
        for name, endpoint in service.resources.items():
            self.assertEqual(endpoint.path, f"/api/v3/absencemanager/{name}")
            if name in ABSENCE_MANAGER_READ_ONLY_RESOURCE_NAMES:
                self.assertEqual(endpoint.supported_operations, LIST_RESOURCE_OPERATION)
            else:
                self.assertTrue(endpoint.supports("list"))
                self.assertTrue(endpoint.supports("get"))
                self.assertTrue(endpoint.supports("create"))
                self.assertTrue(endpoint.supports("patch"))
                self.assertTrue(endpoint.supports("replace"))
                self.assertTrue(endpoint.supports("delete"))

    def test_list_read_only_resource_uses_absence_prefix_filter_sort_and_pagination(self) -> None:
        transport = FakeTransport(
            FakeResponse(200, {"content": [{"userId": 7, "balance": 12.5}], "hasNextPage": False}),
        )
        service = AbsenceManagerApiService(_client(transport))

        balances = service.list_resource(
            "entitlement-balances",
            query={"filter": "crewId==24;userId==7;date>=2026-01-01", "sort": ["date"]},
            page_size=25,
            limit=1,
        )

        self.assertEqual(balances, [{"userId": 7, "balance": 12.5}])
        request = transport.calls[0][0]
        parsed = parse.urlparse(request.full_url)
        query = parse.parse_qs(parsed.query)
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(parsed.path, "/api/v3/absencemanager/entitlement-balances")
        self.assertEqual(query["filter"], ["crewId==24;userId==7;date>=2026-01-01"])
        self.assertEqual(query["sort"], ["date"])
        self.assertEqual(query["page"], ["0"])
        self.assertEqual(query["pageSize"], ["25"])

        with self.assertRaises(CrewmeisterConfigError):
            service.create_resource("entitlement-balances", {"balance": 0})

    def test_crud_resource_methods_use_documented_paths_and_payloads(self) -> None:
        transport = FakeTransport(
            FakeResponse(200, {"content": [{"id": "absence-1"}], "hasNextPage": False}),
            FakeResponse(200, {"id": "absence-1"}),
            FakeResponse(200, {"created": True}),
            FakeResponse(200, {"batched": True}),
            FakeResponse(200, {"patched": True}),
            FakeResponse(200, {"replaced": True}),
            FakeResponse(200, None),
        )
        service = AbsenceManagerApiService(_client(transport))

        self.assertEqual(service.list_resource("absences", query={"filter": "crewId==24"}), [{"id": "absence-1"}])
        self.assertEqual(service.get_resource("absences", "absence/1"), {"id": "absence-1"})
        self.assertEqual(
            service.create_resource("absences", {"crewId": 24, "userId": 7, "absenceType": 1}),
            {"created": True},
        )
        self.assertEqual(
            service.batch_patch_resource("absence-type-settings", [{"method": "DELETE", "path": "/1"}]),
            {"batched": True},
        )
        self.assertEqual(
            service.patch_resource("absences", "absence/1", {"state": "APPROVED"}),
            {"patched": True},
        )
        self.assertEqual(
            service.replace_resource("working-days", "working day 1", {"absenceId": "absence-1", "length": 1}),
            {"replaced": True},
        )
        self.assertIsNone(service.delete_resource("absence-visibility-settings", "visibility 1"))

        requests = [call[0] for call in transport.calls]
        self.assertEqual(
            [request.get_method() for request in requests],
            ["GET", "GET", "POST", "PATCH", "PATCH", "PUT", "DELETE"],
        )
        self.assertEqual(parse.urlparse(requests[0].full_url).path, "/api/v3/absencemanager/absences")
        self.assertEqual(parse.urlparse(requests[1].full_url).path, "/api/v3/absencemanager/absences/absence%2F1")
        self.assertEqual(parse.urlparse(requests[2].full_url).path, "/api/v3/absencemanager/absences")
        self.assertEqual(
            parse.urlparse(requests[3].full_url).path,
            "/api/v3/absencemanager/absence-type-settings",
        )
        self.assertEqual(
            parse.urlparse(requests[4].full_url).path,
            "/api/v3/absencemanager/absences/absence%2F1",
        )
        self.assertEqual(
            parse.urlparse(requests[5].full_url).path,
            "/api/v3/absencemanager/working-days/working%20day%201",
        )
        self.assertEqual(
            parse.urlparse(requests[6].full_url).path,
            "/api/v3/absencemanager/absence-visibility-settings/visibility%201",
        )
        self.assertEqual(
            json.loads(requests[2].data.decode("utf-8")),
            {"crewId": 24, "userId": 7, "absenceType": 1},
        )
        self.assertEqual(json.loads(requests[3].data.decode("utf-8")), [{"method": "DELETE", "path": "/1"}])
        self.assertEqual(json.loads(requests[4].data.decode("utf-8")), {"state": "APPROVED"})
        self.assertEqual(json.loads(requests[5].data.decode("utf-8")), {"absenceId": "absence-1", "length": 1})


def _client(transport: FakeTransport) -> CrewmeisterApiClient:
    return CrewmeisterApiClient(
        CrewmeisterApiConfig(base_url="https://api.crewmeister.com", bearer_token="existing-token"),
        transport=transport,
    )


if __name__ == "__main__":
    unittest.main()
