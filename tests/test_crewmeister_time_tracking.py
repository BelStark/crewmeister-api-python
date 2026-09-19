"""Synthetic transport checks, not server acceptance; see README.md#known-api-limitations.

Task envelopes and unresolved vendor schemas remain open.
"""

import json
import unittest
from urllib import parse

from crewmeister_api import (
    CrewmeisterApiClient,
    CrewmeisterApiConfig,
    CrewmeisterConfigError,
    TimeTrackingApiService,
)
from crewmeister_api.resources import LIST_RESOURCE_OPERATION
from crewmeister_api.time_tracking import (
    TIME_TRACKING_READ_ONLY_RESOURCE_NAMES,
    TIME_TRACKING_RESOURCE_NAMES,
    TIME_TRACKING_TASK_NAMES,
)
from tests.support import FakeResponse, FakeTransport


class TimeTrackingApiServiceTests(unittest.TestCase):
    def test_time_tracking_registry_covers_documented_resources_and_tasks(self) -> None:
        self.assertEqual(
            TIME_TRACKING_RESOURCE_NAMES,
            (
                "bookings",
                "day-kind-calendar-days",
                "durations",
                "duration-balances",
                "duration-definitions",
                "public-holiday-calendar-settings",
                "public-holiday-templates",
                "stamps",
                "terminal-settings",
                "time-accounts",
                "time-account-settings",
                "time-categories",
                "time-location-settings",
                "time-tracking-reports",
                "working-time-models",
            ),
        )
        self.assertEqual(TIME_TRACKING_TASK_NAMES, ("set-break-in-stamp-chain", "time-tracking-report"))

    def test_resource_descriptors_use_documented_paths_and_read_only_operations(self) -> None:
        service = TimeTrackingApiService(_client(FakeTransport()))

        self.assertEqual(tuple(service.resources), TIME_TRACKING_RESOURCE_NAMES)
        for name, endpoint in service.resources.items():
            self.assertEqual(endpoint.path, f"/api/v3/timetracking/{name}")
            if name in TIME_TRACKING_READ_ONLY_RESOURCE_NAMES:
                self.assertEqual(endpoint.supported_operations, LIST_RESOURCE_OPERATION)
            else:
                self.assertTrue(endpoint.supports("list"))
                self.assertTrue(endpoint.supports("get"))
                self.assertTrue(endpoint.supports("create"))
                self.assertTrue(endpoint.supports("patch"))
                self.assertTrue(endpoint.supports("replace"))
                self.assertTrue(endpoint.supports("delete"))

    def test_list_read_only_resource_uses_time_tracking_prefix_filter_sort_and_pagination(self) -> None:
        transport = FakeTransport(
            FakeResponse(200, {"content": [{"userId": 7, "balance": 480}], "hasNextPage": False}),
        )
        service = TimeTrackingApiService(_client(transport))

        balances = service.list_resource(
            "duration-balances",
            query={"filter": "crewId==24;userId==7;date>=2026-01-01", "sort": ["date"]},
            page_size=31,
            limit=1,
        )

        self.assertEqual(balances, [{"userId": 7, "balance": 480}])
        request = transport.calls[0][0]
        parsed = parse.urlparse(request.full_url)
        query = parse.parse_qs(parsed.query)
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(parsed.path, "/api/v3/timetracking/duration-balances")
        self.assertEqual(query["filter"], ["crewId==24;userId==7;date>=2026-01-01"])
        self.assertEqual(query["sort"], ["date"])
        self.assertEqual(query["page"], ["0"])
        self.assertEqual(query["pageSize"], ["31"])

        with self.assertRaises(CrewmeisterConfigError):
            service.create_resource("duration-balances", {"balance": 0})

    def test_crud_resource_methods_use_documented_paths_and_payloads(self) -> None:
        transport = FakeTransport(
            FakeResponse(200, {"content": [{"id": "booking-1"}], "hasNextPage": False}),
            FakeResponse(200, {"id": "booking-1"}),
            FakeResponse(200, {"created": True}),
            FakeResponse(200, {"batched": True}),
            FakeResponse(200, {"patched": True}),
            FakeResponse(200, {"replaced": True}),
            FakeResponse(200, None),
        )
        service = TimeTrackingApiService(_client(transport))

        self.assertEqual(service.list_resource("bookings", query={"filter": "crewId==24"}), [{"id": "booking-1"}])
        self.assertEqual(service.get_resource("bookings", "booking/1"), {"id": "booking-1"})
        self.assertEqual(service.create_resource("bookings", {"crewId": 24, "duration": "PT8H"}), {"created": True})
        self.assertEqual(
            service.batch_patch_resource("bookings", [{"method": "DELETE", "path": "/1"}]), {"batched": True}
        )
        self.assertEqual(service.patch_resource("bookings", "booking/1", {"duration": "PT7H30M"}), {"patched": True})
        self.assertEqual(
            service.replace_resource("bookings", "booking 1", {"crewId": 24, "duration": "PT8H"}),
            {"replaced": True},
        )
        self.assertIsNone(service.delete_resource("bookings", "booking 1"))

        requests = [call[0] for call in transport.calls]
        self.assertEqual(
            [request.get_method() for request in requests],
            ["GET", "GET", "POST", "PATCH", "PATCH", "PUT", "DELETE"],
        )
        self.assertEqual(parse.urlparse(requests[0].full_url).path, "/api/v3/timetracking/bookings")
        self.assertEqual(parse.urlparse(requests[1].full_url).path, "/api/v3/timetracking/bookings/booking%2F1")
        self.assertEqual(parse.urlparse(requests[2].full_url).path, "/api/v3/timetracking/bookings")
        self.assertEqual(parse.urlparse(requests[3].full_url).path, "/api/v3/timetracking/bookings")
        self.assertEqual(parse.urlparse(requests[4].full_url).path, "/api/v3/timetracking/bookings/booking%2F1")
        self.assertEqual(parse.urlparse(requests[5].full_url).path, "/api/v3/timetracking/bookings/booking%201")
        self.assertEqual(parse.urlparse(requests[6].full_url).path, "/api/v3/timetracking/bookings/booking%201")
        self.assertEqual(json.loads(requests[2].data.decode("utf-8")), {"crewId": 24, "duration": "PT8H"})
        self.assertEqual(json.loads(requests[3].data.decode("utf-8")), [{"method": "DELETE", "path": "/1"}])

    def test_task_helpers_use_documented_paths_and_return_raw_payloads(self) -> None:
        transport = FakeTransport(
            FakeResponse(200, {"stampChainId": 9, "status": "updated"}),
            FakeResponse(200, {"reportId": "report-1", "status": "queued"}),
        )
        service = TimeTrackingApiService(_client(transport))

        self.assertEqual(
            service.set_break_in_stamp_chain_task({"stampIdInStampChain": 9, "duration": "PT30M"}),
            {"stampChainId": 9, "status": "updated"},
        )
        self.assertEqual(
            service.time_tracking_report_task(
                {
                    "crewId": 24,
                    "from": "2026-01-01",
                    "to": "2026-01-31",
                    "userIds": "7,8",
                    "timeCategoryOneIds": "1",
                    "timeCategoryTwoIds": "2",
                    "fileCategory": "SPREADSHEET",
                    "language": "DE",
                }
            ),
            {"reportId": "report-1", "status": "queued"},
        )

        requests = [call[0] for call in transport.calls]
        self.assertEqual([request.get_method() for request in requests], ["POST", "POST"])
        self.assertEqual(
            parse.urlparse(requests[0].full_url).path,
            "/api/v3/timetracking/set-break-in-stamp-chain-tasks",
        )
        self.assertEqual(parse.urlparse(requests[1].full_url).path, "/api/v3/timetracking/time-tracking-report-tasks")
        self.assertEqual(json.loads(requests[0].data.decode("utf-8")), {"stampIdInStampChain": 9, "duration": "PT30M"})
        self.assertEqual(
            json.loads(requests[1].data.decode("utf-8")),
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
        )


def _client(transport: FakeTransport) -> CrewmeisterApiClient:
    return CrewmeisterApiClient(
        CrewmeisterApiConfig(base_url="https://api.crewmeister.com", bearer_token="existing-token"),
        transport=transport,
    )


if __name__ == "__main__":
    unittest.main()
