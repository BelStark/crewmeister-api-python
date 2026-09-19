"""Synthetic transport checks, not server acceptance; see README.md#known-api-limitations.

Task envelopes and unresolved vendor schemas remain open.
"""

import json
import unittest
from urllib import parse

from crewmeister_api import CrewmeisterApiClient, CrewmeisterApiConfig, PlatformApiService
from crewmeister_api.platform import PLATFORM_RESOURCE_NAMES
from tests.support import FakeResponse, FakeTransport


class PlatformApiServiceTests(unittest.TestCase):
    def test_platform_resource_registry_covers_documented_resources(self) -> None:
        self.assertEqual(
            PLATFORM_RESOURCE_NAMES,
            (
                "admins",
                "admin-authentication-tokens",
                "admin-roles",
                "crews",
                "crew-authentication-tokens",
                "crew-sizes",
                "customers",
                "downgrade-actions",
                "feature-flag-settings",
                "members",
                "member-roles",
                "payouts",
                "prices",
                "products",
                "subscriptions",
                "teams",
                "usage-rights",
                "users",
                "user-authentication-tokens",
                "vouchers",
            ),
        )

    def test_list_resource_uses_platform_prefix_pagination_filter_sort_and_limit(self) -> None:
        transport = FakeTransport(
            FakeResponse(200, {"content": [{"id": 1}, {"id": 2}], "hasNextPage": True}),
        )
        service = PlatformApiService(
            CrewmeisterApiClient(
                CrewmeisterApiConfig(base_url="https://api.crewmeister.com", bearer_token="existing-token"),
                transport=transport,
            )
        )

        members = service.list_resource(
            "members",
            query={"filter": "crewId==24", "sort": ["-id", "+name"]},
            page_size=2,
            limit=1,
        )

        self.assertEqual(members, [{"id": 1}])
        self.assertEqual(len(transport.calls), 1)
        request = transport.calls[0][0]
        parsed = parse.urlparse(request.full_url)
        query = parse.parse_qs(parsed.query)
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(parsed.path, "/api/v3/platform-app/members")
        self.assertEqual(query["filter"], ["crewId==24"])
        self.assertEqual(query["sort"], ["-id", "+name"])
        self.assertEqual(query["page"], ["0"])
        self.assertEqual(query["pageSize"], ["2"])

    def test_resource_write_methods_use_documented_platform_paths_and_payloads(self) -> None:
        transport = FakeTransport(
            FakeResponse(200, {"created": True}),
            FakeResponse(200, {"batched": True}),
            FakeResponse(200, {"patched": True}),
            FakeResponse(200, {"replaced": True}),
            FakeResponse(200, None),
        )
        service = PlatformApiService(
            CrewmeisterApiClient(
                CrewmeisterApiConfig(base_url="https://api.crewmeister.com", bearer_token="existing-token"),
                transport=transport,
            )
        )

        self.assertEqual(service.create_resource("teams", {"name": "Ops"}), {"created": True})
        self.assertEqual(service.batch_patch_resource("teams", [{"method": "DELETE", "path": "/1"}]), {"batched": True})
        self.assertEqual(service.patch_resource("teams", "team/1", {"name": "Support"}), {"patched": True})
        self.assertEqual(service.replace_resource("teams", "team 1", {"name": "Sales"}), {"replaced": True})
        self.assertIsNone(service.delete_resource("teams", "team 1"))

        requests = [call[0] for call in transport.calls]
        self.assertEqual([request.get_method() for request in requests], ["POST", "PATCH", "PATCH", "PUT", "DELETE"])
        self.assertEqual(parse.urlparse(requests[0].full_url).path, "/api/v3/platform-app/teams")
        self.assertEqual(parse.urlparse(requests[1].full_url).path, "/api/v3/platform-app/teams")
        self.assertEqual(parse.urlparse(requests[2].full_url).path, "/api/v3/platform-app/teams/team%2F1")
        self.assertEqual(parse.urlparse(requests[3].full_url).path, "/api/v3/platform-app/teams/team%201")
        self.assertEqual(parse.urlparse(requests[4].full_url).path, "/api/v3/platform-app/teams/team%201")
        self.assertEqual(json.loads(requests[0].data.decode("utf-8")), {"name": "Ops"})
        self.assertEqual(json.loads(requests[1].data.decode("utf-8")), [{"method": "DELETE", "path": "/1"}])

    def test_platform_task_helpers_use_explicit_task_paths(self) -> None:
        transport = FakeTransport(
            FakeResponse(200, {"userId": 7}),
            FakeResponse(200, {"job": {"id": "subscription-job"}}),
        )
        service = PlatformApiService(
            CrewmeisterApiClient(
                CrewmeisterApiConfig(base_url="https://api.crewmeister.com", bearer_token="existing-token"),
                transport=transport,
            )
        )

        self.assertEqual(service.get_current_user_task({"client": "prime"}), {"userId": 7})
        self.assertEqual(
            service.subscription_action_task({"subscriptionId": 42, "action": "sync"}),
            {"job": {"id": "subscription-job"}},
        )

        requests = [call[0] for call in transport.calls]
        self.assertEqual([request.get_method() for request in requests], ["POST", "POST"])
        self.assertEqual(parse.urlparse(requests[0].full_url).path, "/api/v3/platform-app/get-current-user-tasks")
        self.assertEqual(parse.urlparse(requests[1].full_url).path, "/api/v3/platform-app/subscription-action-tasks")


if __name__ == "__main__":
    unittest.main()
