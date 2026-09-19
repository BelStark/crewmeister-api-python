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
    IntegrationApiService,
)
from crewmeister_api.integration import INTEGRATION_RESOURCE_NAMES, INTEGRATION_TASK_NAMES
from tests.support import FakeResponse, FakeTransport


class IntegrationApiServiceTests(unittest.TestCase):
    def test_integration_registry_covers_documented_resources_and_tasks(self) -> None:
        self.assertEqual(INTEGRATION_RESOURCE_NAMES, ("connections", "oauth-status"))
        self.assertEqual(INTEGRATION_TASK_NAMES, ("i-cal-subscription",))

    def test_connection_resource_methods_use_integration_prefix_and_payloads(self) -> None:
        transport = FakeTransport(
            FakeResponse(200, {"content": [{"id": "connection-1"}], "hasNextPage": False}),
            FakeResponse(200, {"id": "connection-1"}),
            FakeResponse(200, {"created": True}),
            FakeResponse(200, {"batched": True}),
            FakeResponse(200, {"patched": True}),
            FakeResponse(200, {"replaced": True}),
            FakeResponse(200, None),
        )
        service = IntegrationApiService(_client(transport))

        self.assertEqual(service.list_resource("connections", query={"filter": "crewId==24"}), [{"id": "connection-1"}])
        self.assertEqual(service.get_resource("connections", "connection/1"), {"id": "connection-1"})
        self.assertEqual(service.create_resource("connections", {"crewId": 24}), {"created": True})
        self.assertEqual(
            service.batch_patch_resource("connections", [{"method": "DELETE", "path": "/1"}]), {"batched": True}
        )
        self.assertEqual(service.patch_resource("connections", "connection/1", {"metadata": {}}), {"patched": True})
        self.assertEqual(service.replace_resource("connections", "connection 1", {"crewId": 24}), {"replaced": True})
        self.assertIsNone(service.delete_resource("connections", "connection 1"))

        requests = [call[0] for call in transport.calls]
        self.assertEqual(
            [request.get_method() for request in requests],
            ["GET", "GET", "POST", "PATCH", "PATCH", "PUT", "DELETE"],
        )
        self.assertEqual(parse.urlparse(requests[0].full_url).path, "/api/v3/integration/connections")
        self.assertEqual(parse.urlparse(requests[1].full_url).path, "/api/v3/integration/connections/connection%2F1")
        self.assertEqual(parse.urlparse(requests[2].full_url).path, "/api/v3/integration/connections")
        self.assertEqual(parse.urlparse(requests[3].full_url).path, "/api/v3/integration/connections")
        self.assertEqual(parse.urlparse(requests[4].full_url).path, "/api/v3/integration/connections/connection%2F1")
        self.assertEqual(parse.urlparse(requests[5].full_url).path, "/api/v3/integration/connections/connection%201")
        self.assertEqual(parse.urlparse(requests[6].full_url).path, "/api/v3/integration/connections/connection%201")
        self.assertEqual(json.loads(requests[2].data.decode("utf-8")), {"crewId": 24})
        self.assertEqual(json.loads(requests[3].data.decode("utf-8")), [{"method": "DELETE", "path": "/1"}])

    def test_oauth_status_is_list_only(self) -> None:
        transport = FakeTransport(FakeResponse(200, {"content": [{"serviceName": "calendar"}], "hasNextPage": False}))
        service = IntegrationApiService(_client(transport))

        self.assertEqual(
            service.list_resource(
                "oauth-status",
                query={"filter": "crewId==24", "sort": ["serviceName"]},
                page_size=25,
            ),
            [{"serviceName": "calendar"}],
        )
        parsed = parse.urlparse(transport.calls[0][0].full_url)
        query = parse.parse_qs(parsed.query)
        self.assertEqual(parsed.path, "/api/v3/integration/oauth-status")
        self.assertEqual(query["filter"], ["crewId==24"])
        self.assertEqual(query["sort"], ["serviceName"])
        self.assertEqual(query["pageSize"], ["25"])

        with self.assertRaises(CrewmeisterConfigError):
            service.get_resource("oauth-status", "calendar")

    def test_ical_subscription_task_can_request_async_work_and_read_its_job(self) -> None:
        transport = FakeTransport(
            FakeResponse(202, {"job": {"id": "job/1", "status": "WAITING"}}),
            FakeResponse(200, {"id": "job/1", "status": "SUCCESS"}),
        )
        service = IntegrationApiService(_client(transport))

        self.assertEqual(
            service.i_cal_subscription_task({"crewId": 24, "userId": 7}, async_write=True),
            {"job": {"id": "job/1", "status": "WAITING"}},
        )
        self.assertEqual(service.get_task_job("i-cal-subscription", "job/1"), {"id": "job/1", "status": "SUCCESS"})

        request, job_request = (call[0] for call in transport.calls)
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("X-write-async"), "true")
        self.assertEqual(parse.urlparse(request.full_url).path, "/api/v3/integration/i-cal-subscription-tasks")
        self.assertEqual(json.loads(request.data.decode("utf-8")), {"crewId": 24, "userId": 7})
        self.assertEqual(job_request.get_method(), "GET")
        self.assertEqual(
            parse.urlparse(job_request.full_url).path,
            "/api/v3/integration/i-cal-subscription-tasks-jobs/job%2F1",
        )


def _client(transport: FakeTransport) -> CrewmeisterApiClient:
    return CrewmeisterApiClient(
        CrewmeisterApiConfig(base_url="https://api.crewmeister.com", bearer_token="existing-token"),
        transport=transport,
    )


if __name__ == "__main__":
    unittest.main()
