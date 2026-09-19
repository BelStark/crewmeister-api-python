"""Synthetic transport checks, not server acceptance; see README.md#known-api-limitations.

Task envelopes and unresolved vendor schemas remain open.
"""

import json
import unittest
from urllib import parse

from crewmeister_api import (
    CrewmeisterApiClient,
    CrewmeisterApiConfig,
    SalaryExportApiService,
)
from crewmeister_api.salary_export import SALARY_EXPORT_RESOURCE_NAMES
from tests.support import FakeResponse, FakeTransport


class SalaryExportApiServiceTests(unittest.TestCase):
    def test_salary_export_registry_covers_documented_and_webclient_resources(self) -> None:
        self.assertEqual(
            SALARY_EXPORT_RESOURCE_NAMES,
            (
                "salary-exports",
                "salary-export-configurations",
                "wage-type-allocation-absence-days",
                "wage-type-allocation-duration-hours",
                "salary-export-generation-tasks",
            ),
        )

    def test_resource_descriptors_limit_operations_to_the_known_contract(self) -> None:
        service = SalaryExportApiService(_client(FakeTransport()))

        self.assertEqual(tuple(service.resources), SALARY_EXPORT_RESOURCE_NAMES)
        for name, endpoint in service.resources.items():
            self.assertEqual(endpoint.path, f"/api/v3/salaryexport/{name}")
            if name == "salary-export-generation-tasks":
                self.assertEqual(endpoint.supported_operations, frozenset({"batch"}))
                continue
            self.assertTrue(endpoint.supports("list"))
            self.assertTrue(endpoint.supports("get"))
            self.assertTrue(endpoint.supports("create"))
            self.assertTrue(endpoint.supports("patch"))
            self.assertTrue(endpoint.supports("replace"))
            self.assertTrue(endpoint.supports("delete"))

    def test_list_resource_uses_salary_prefix_filter_sort_and_pagination(self) -> None:
        transport = FakeTransport(
            FakeResponse(
                200,
                {
                    "content": [{"id": "salary-export-1", "exportType": "DATEV_LOHN_UND_GEHALT"}],
                    "hasNextPage": False,
                },
            ),
        )
        service = SalaryExportApiService(_client(transport))

        exports = service.list_resource(
            "salary-exports",
            query={
                "filter": "crewId==24;exportType==DATEV_LOHN_UND_GEHALT;firstDate>=2026-01-01",
                "sort": ["firstDate"],
            },
            page_size=25,
            limit=1,
        )

        self.assertEqual(exports, [{"id": "salary-export-1", "exportType": "DATEV_LOHN_UND_GEHALT"}])
        request = transport.calls[0][0]
        parsed = parse.urlparse(request.full_url)
        query = parse.parse_qs(parsed.query)
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(parsed.path, "/api/v3/salaryexport/salary-exports")
        self.assertEqual(query["filter"], ["crewId==24;exportType==DATEV_LOHN_UND_GEHALT;firstDate>=2026-01-01"])
        self.assertEqual(query["sort"], ["firstDate"])
        self.assertEqual(query["page"], ["0"])
        self.assertEqual(query["pageSize"], ["25"])

    def test_crud_resource_methods_use_documented_paths_and_payloads(self) -> None:
        transport = FakeTransport(
            FakeResponse(200, {"content": [{"id": "salary-export-1"}], "hasNextPage": False}),
            FakeResponse(200, {"id": "configuration-1"}),
            FakeResponse(200, {"created": True}),
            FakeResponse(200, {"batched": True}),
            FakeResponse(200, {"patched": True}),
            FakeResponse(200, {"replaced": True}),
            FakeResponse(200, None),
            FakeResponse(200, {"id": "absence-allocation-1"}),
        )
        service = SalaryExportApiService(_client(transport))

        self.assertEqual(
            service.list_resource("salary-exports", query={"filter": "crewId==24"}),
            [{"id": "salary-export-1"}],
        )
        self.assertEqual(
            service.get_resource("salary-export-configurations", "configuration/1"),
            {"id": "configuration-1"},
        )
        self.assertEqual(
            service.create_resource(
                "wage-type-allocation-duration-hours",
                {
                    "crewId": 24,
                    "salaryExportConfigurationId": 1,
                    "durationDefinitionType": "OVERTIME",
                    "employeeType": "COMMERCIAL",
                    "wageType": "WT-1000",
                    "transferIdentifier": "DATEV-1000",
                },
            ),
            {"created": True},
        )
        self.assertEqual(
            service.batch_patch_resource("wage-type-allocation-absence-days", [{"method": "DELETE", "path": "/1"}]),
            {"batched": True},
        )
        self.assertEqual(
            service.patch_resource(
                "salary-export-configurations", "configuration/1", {"exportType": "DATEV_LOHN_UND_GEHALT"}
            ),
            {"patched": True},
        )
        self.assertEqual(
            service.replace_resource(
                "salary-exports",
                "salary export 1",
                {"crewId": 24, "exportType": "DATEV_LOHN_UND_GEHALT", "firstDate": "2026-01-01"},
            ),
            {"replaced": True},
        )
        self.assertIsNone(service.delete_resource("wage-type-allocation-duration-hours", "duration allocation 1"))
        self.assertEqual(
            service.get_resource("wage-type-allocation-absence-days", "absence/allocation/1"),
            {"id": "absence-allocation-1"},
        )

        requests = [call[0] for call in transport.calls]
        self.assertEqual(
            [request.get_method() for request in requests],
            ["GET", "GET", "POST", "PATCH", "PATCH", "PUT", "DELETE", "GET"],
        )
        self.assertEqual(parse.urlparse(requests[0].full_url).path, "/api/v3/salaryexport/salary-exports")
        self.assertEqual(
            parse.urlparse(requests[1].full_url).path,
            "/api/v3/salaryexport/salary-export-configurations/configuration%2F1",
        )
        self.assertEqual(
            parse.urlparse(requests[2].full_url).path,
            "/api/v3/salaryexport/wage-type-allocation-duration-hours",
        )
        self.assertEqual(
            parse.urlparse(requests[3].full_url).path,
            "/api/v3/salaryexport/wage-type-allocation-absence-days",
        )
        self.assertEqual(
            parse.urlparse(requests[4].full_url).path,
            "/api/v3/salaryexport/salary-export-configurations/configuration%2F1",
        )
        self.assertEqual(
            parse.urlparse(requests[5].full_url).path,
            "/api/v3/salaryexport/salary-exports/salary%20export%201",
        )
        self.assertEqual(
            parse.urlparse(requests[6].full_url).path,
            "/api/v3/salaryexport/wage-type-allocation-duration-hours/duration%20allocation%201",
        )
        self.assertEqual(
            parse.urlparse(requests[7].full_url).path,
            "/api/v3/salaryexport/wage-type-allocation-absence-days/absence%2Fallocation%2F1",
        )
        self.assertEqual(
            json.loads(requests[2].data.decode("utf-8")),
            {
                "crewId": 24,
                "salaryExportConfigurationId": 1,
                "durationDefinitionType": "OVERTIME",
                "employeeType": "COMMERCIAL",
                "wageType": "WT-1000",
                "transferIdentifier": "DATEV-1000",
            },
        )
        self.assertEqual(json.loads(requests[3].data.decode("utf-8")), [{"method": "DELETE", "path": "/1"}])
        self.assertEqual(json.loads(requests[4].data.decode("utf-8")), {"exportType": "DATEV_LOHN_UND_GEHALT"})
        self.assertEqual(
            json.loads(requests[5].data.decode("utf-8")),
            {"crewId": 24, "exportType": "DATEV_LOHN_UND_GEHALT", "firstDate": "2026-01-01"},
        )


def _client(transport: FakeTransport) -> CrewmeisterApiClient:
    return CrewmeisterApiClient(
        CrewmeisterApiConfig(base_url="https://api.crewmeister.com", bearer_token="existing-token"),
        transport=transport,
    )


if __name__ == "__main__":
    unittest.main()
