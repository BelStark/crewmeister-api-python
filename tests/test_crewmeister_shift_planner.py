"""Synthetic transport checks, not server acceptance; see README.md#known-api-limitations.

Task envelopes and unresolved vendor schemas remain open.
"""

import json
import unittest
from urllib import parse

from crewmeister_api import (
    CrewmeisterApiClient,
    CrewmeisterApiConfig,
    ShiftPlannerApiService,
)
from crewmeister_api.shift_planner import (
    SHIFT_PLANNER_RESOURCE_NAMES,
    SHIFT_PLANNER_TASK_NAMES,
)
from tests.support import FakeResponse, FakeTransport


class ShiftPlannerApiServiceTests(unittest.TestCase):
    def test_shift_planner_registry_covers_documented_resources_and_tasks(self) -> None:
        self.assertEqual(
            SHIFT_PLANNER_RESOURCE_NAMES,
            (
                "shifts",
                "shift-grace-period-settings",
                "shift-offer-replies",
                "shift-visibility-settings",
                "shift-working-time-settings",
                "templates",
                "template-shifts",
                "workplaces",
            ),
        )
        self.assertEqual(SHIFT_PLANNER_TASK_NAMES, ("shift-apply-template", "shift-copy", "shift-publish"))

    def test_resource_descriptors_use_documented_paths_and_crud_operations(self) -> None:
        service = ShiftPlannerApiService(_client(FakeTransport()))

        self.assertEqual(tuple(service.resources), SHIFT_PLANNER_RESOURCE_NAMES)
        for name, endpoint in service.resources.items():
            self.assertEqual(endpoint.path, f"/api/v3/shiftplanner/{name}")
            self.assertTrue(endpoint.supports("list"))
            self.assertTrue(endpoint.supports("get"))
            self.assertTrue(endpoint.supports("create"))
            self.assertTrue(endpoint.supports("patch"))
            self.assertTrue(endpoint.supports("replace"))
            self.assertTrue(endpoint.supports("delete"))

    def test_list_resource_uses_shift_prefix_filter_sort_and_pagination(self) -> None:
        transport = FakeTransport(
            FakeResponse(200, {"content": [{"id": "shift-1", "userId": 7}], "hasNextPage": False}),
        )
        service = ShiftPlannerApiService(_client(transport))

        shifts = service.list_resource(
            "shifts",
            query={"filter": "crewId==24;userId==7;from>=2026-01-01T00:00:00Z", "sort": ["from"]},
            page_size=25,
            limit=1,
        )

        self.assertEqual(shifts, [{"id": "shift-1", "userId": 7}])
        request = transport.calls[0][0]
        parsed = parse.urlparse(request.full_url)
        query = parse.parse_qs(parsed.query)
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(parsed.path, "/api/v3/shiftplanner/shifts")
        self.assertEqual(query["filter"], ["crewId==24;userId==7;from>=2026-01-01T00:00:00Z"])
        self.assertEqual(query["sort"], ["from"])
        self.assertEqual(query["page"], ["0"])
        self.assertEqual(query["pageSize"], ["25"])

    def test_crud_resource_methods_use_documented_paths_and_payloads(self) -> None:
        transport = FakeTransport(
            FakeResponse(200, {"content": [{"id": "shift-1"}], "hasNextPage": False}),
            FakeResponse(200, {"id": "template-1"}),
            FakeResponse(200, {"created": True}),
            FakeResponse(200, {"batched": True}),
            FakeResponse(200, {"patched": True}),
            FakeResponse(200, {"replaced": True}),
            FakeResponse(200, None),
            FakeResponse(200, {"id": "template-shift-1"}),
            FakeResponse(200, {"id": "workplace-1"}),
        )
        service = ShiftPlannerApiService(_client(transport))

        self.assertEqual(service.list_resource("shifts", query={"filter": "crewId==24"}), [{"id": "shift-1"}])
        self.assertEqual(service.get_resource("templates", "template/1"), {"id": "template-1"})
        self.assertEqual(
            service.create_resource(
                "shifts",
                {"crewId": 24, "userId": 7, "from": "2026-01-01T08:00:00Z", "to": "2026-01-01T16:00:00Z"},
            ),
            {"created": True},
        )
        self.assertEqual(
            service.batch_patch_resource("shift-grace-period-settings", [{"method": "DELETE", "path": "/1"}]),
            {"batched": True},
        )
        self.assertEqual(
            service.patch_resource("shift-offer-replies", "reply/1", {"accepted": True}),
            {"patched": True},
        )
        self.assertEqual(
            service.replace_resource("shift-visibility-settings", "visibility 1", {"seeAllShifts": True}),
            {"replaced": True},
        )
        self.assertIsNone(service.delete_resource("shift-working-time-settings", "working-time 1"))
        self.assertEqual(service.get_resource("template-shifts", "template-shift/1"), {"id": "template-shift-1"})
        self.assertEqual(service.get_resource("workplaces", "workplace 1"), {"id": "workplace-1"})

        requests = [call[0] for call in transport.calls]
        self.assertEqual(
            [request.get_method() for request in requests],
            ["GET", "GET", "POST", "PATCH", "PATCH", "PUT", "DELETE", "GET", "GET"],
        )
        self.assertEqual(parse.urlparse(requests[0].full_url).path, "/api/v3/shiftplanner/shifts")
        self.assertEqual(parse.urlparse(requests[1].full_url).path, "/api/v3/shiftplanner/templates/template%2F1")
        self.assertEqual(parse.urlparse(requests[2].full_url).path, "/api/v3/shiftplanner/shifts")
        self.assertEqual(
            parse.urlparse(requests[3].full_url).path,
            "/api/v3/shiftplanner/shift-grace-period-settings",
        )
        self.assertEqual(
            parse.urlparse(requests[4].full_url).path,
            "/api/v3/shiftplanner/shift-offer-replies/reply%2F1",
        )
        self.assertEqual(
            parse.urlparse(requests[5].full_url).path,
            "/api/v3/shiftplanner/shift-visibility-settings/visibility%201",
        )
        self.assertEqual(
            parse.urlparse(requests[6].full_url).path,
            "/api/v3/shiftplanner/shift-working-time-settings/working-time%201",
        )
        self.assertEqual(
            parse.urlparse(requests[7].full_url).path,
            "/api/v3/shiftplanner/template-shifts/template-shift%2F1",
        )
        self.assertEqual(parse.urlparse(requests[8].full_url).path, "/api/v3/shiftplanner/workplaces/workplace%201")
        self.assertEqual(
            json.loads(requests[2].data.decode("utf-8")),
            {"crewId": 24, "userId": 7, "from": "2026-01-01T08:00:00Z", "to": "2026-01-01T16:00:00Z"},
        )
        self.assertEqual(json.loads(requests[3].data.decode("utf-8")), [{"method": "DELETE", "path": "/1"}])
        self.assertEqual(json.loads(requests[4].data.decode("utf-8")), {"accepted": True})
        self.assertEqual(json.loads(requests[5].data.decode("utf-8")), {"seeAllShifts": True})

    def test_task_helpers_use_documented_paths_and_return_raw_payloads(self) -> None:
        transport = FakeTransport(
            FakeResponse(200, {"task": "apply-template", "status": "queued"}),
            FakeResponse(200, {"task": "copy", "status": "queued"}),
            FakeResponse(200, {"task": "publish", "status": "queued"}),
        )
        service = ShiftPlannerApiService(_client(transport))

        self.assertEqual(
            service.shift_apply_template_task(
                {"crewId": 24, "templateId": 1, "date": "2026-01-01", "zoneId": "Europe/Berlin"}
            ),
            {"task": "apply-template", "status": "queued"},
        )
        self.assertEqual(
            service.shift_copy_task(
                {
                    "crewId": 24,
                    "originStartDate": "2026-01-01",
                    "originEndDate": "2026-01-08",
                    "targetStartDate": "2026-02-01",
                    "zoneId": "Europe/Berlin",
                }
            ),
            {"task": "copy", "status": "queued"},
        )
        self.assertEqual(
            service.shift_publish_task({"shiftIdToPublish": 1}),
            {"task": "publish", "status": "queued"},
        )

        requests = [call[0] for call in transport.calls]
        self.assertEqual([request.get_method() for request in requests], ["POST", "POST", "POST"])
        self.assertEqual(
            parse.urlparse(requests[0].full_url).path,
            "/api/v3/shiftplanner/shift-apply-template-tasks",
        )
        self.assertEqual(parse.urlparse(requests[1].full_url).path, "/api/v3/shiftplanner/shift-copy-tasks")
        self.assertEqual(parse.urlparse(requests[2].full_url).path, "/api/v3/shiftplanner/shift-publish-tasks")
        self.assertEqual(
            json.loads(requests[0].data.decode("utf-8")),
            {"crewId": 24, "templateId": 1, "date": "2026-01-01", "zoneId": "Europe/Berlin"},
        )
        self.assertEqual(
            json.loads(requests[1].data.decode("utf-8")),
            {
                "crewId": 24,
                "originStartDate": "2026-01-01",
                "originEndDate": "2026-01-08",
                "targetStartDate": "2026-02-01",
                "zoneId": "Europe/Berlin",
            },
        )
        self.assertEqual(json.loads(requests[2].data.decode("utf-8")), {"shiftIdToPublish": 1})


def _client(transport: FakeTransport) -> CrewmeisterApiClient:
    return CrewmeisterApiClient(
        CrewmeisterApiConfig(base_url="https://api.crewmeister.com", bearer_token="existing-token"),
        transport=transport,
    )


if __name__ == "__main__":
    unittest.main()
