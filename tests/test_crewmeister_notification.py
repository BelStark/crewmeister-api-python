"""Synthetic transport checks, not server acceptance; see README.md#known-api-limitations.

Task envelopes and unresolved vendor schemas remain open.
"""

import io
import json
import unittest
from urllib import parse

from crewmeister_api import (
    CrewmeisterApiClient,
    CrewmeisterApiConfig,
    NotificationApiService,
)
from crewmeister_api.cli import run_cli
from crewmeister_api.notification import NOTIFICATION_RESOURCE_NAMES
from tests.support import FakeResponse, FakeTransport


class NotificationApiServiceTests(unittest.TestCase):
    def test_notification_registry_covers_documented_resources(self) -> None:
        self.assertEqual(
            NOTIFICATION_RESOURCE_NAMES,
            (
                "news",
                "user-news-settings",
                "user-push-tokens",
                "user-reminder-settings",
            ),
        )

    def test_resource_descriptors_use_documented_paths_and_crud_operations(self) -> None:
        service = NotificationApiService(_client(FakeTransport()))

        self.assertEqual(tuple(service.resources), NOTIFICATION_RESOURCE_NAMES)
        for name, endpoint in service.resources.items():
            self.assertEqual(endpoint.path, f"/api/v3/notifications/{name}")
            self.assertTrue(endpoint.supports("list"))
            self.assertTrue(endpoint.supports("get"))
            self.assertTrue(endpoint.supports("create"))
            self.assertTrue(endpoint.supports("patch"))
            self.assertTrue(endpoint.supports("replace"))
            self.assertTrue(endpoint.supports("delete"))

    def test_list_resource_uses_notification_prefix_filter_sort_and_pagination(self) -> None:
        transport = FakeTransport(
            FakeResponse(
                200,
                {
                    "content": [{"id": "news-1", "title": "Shift update"}],
                    "hasNextPage": False,
                },
            ),
        )
        service = NotificationApiService(_client(transport))

        news = service.list_resource(
            "news",
            query={"filter": "crewId==24;senderId==7;receiverId==8", "sort": ["-createdAt"]},
            page_size=25,
            limit=1,
        )

        self.assertEqual(news, [{"id": "news-1", "title": "Shift update"}])
        request = transport.calls[0][0]
        parsed = parse.urlparse(request.full_url)
        query = parse.parse_qs(parsed.query)
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(parsed.path, "/api/v3/notifications/news")
        self.assertEqual(query["filter"], ["crewId==24;senderId==7;receiverId==8"])
        self.assertEqual(query["sort"], ["-createdAt"])
        self.assertEqual(query["page"], ["0"])
        self.assertEqual(query["pageSize"], ["25"])

    def test_crud_resource_methods_use_documented_paths_and_payloads(self) -> None:
        transport = FakeTransport(
            FakeResponse(200, {"content": [{"id": "news-1"}], "hasNextPage": False}),
            FakeResponse(200, {"id": "news-setting-1"}),
            FakeResponse(200, {"created": True}),
            FakeResponse(200, {"batched": True}),
            FakeResponse(200, {"patched": True}),
            FakeResponse(200, {"replaced": True}),
            FakeResponse(200, None),
            FakeResponse(200, {"id": "reminder-1"}),
        )
        service = NotificationApiService(_client(transport))

        self.assertEqual(service.list_resource("news", query={"filter": "crewId==24"}), [{"id": "news-1"}])
        self.assertEqual(service.get_resource("user-news-settings", "setting/1"), {"id": "news-setting-1"})
        self.assertEqual(
            service.create_resource(
                "user-reminder-settings",
                {
                    "userId": 7,
                    "reminderType": "SHIFT_PLANNER",
                    "reminderSubtype": "SHIFT_START",
                    "pushEnabled": True,
                    "timeDeltaSeconds": 1800,
                },
            ),
            {"created": True},
        )
        self.assertEqual(
            service.batch_patch_resource("user-push-tokens", [{"method": "DELETE", "path": "/1"}]), {"batched": True}
        )
        self.assertEqual(
            service.patch_resource("user-news-settings", "setting/1", {"mobilePush": False}), {"patched": True}
        )
        self.assertEqual(
            service.replace_resource(
                "news",
                "news item 1",
                {"crewId": 24, "senderId": 7, "receiverId": 8, "title": "Update"},
            ),
            {"replaced": True},
        )
        self.assertIsNone(service.delete_resource("user-push-tokens", "token 1"))
        self.assertEqual(service.get_resource("user-reminder-settings", "reminder/1"), {"id": "reminder-1"})

        requests = [call[0] for call in transport.calls]
        self.assertEqual(
            [request.get_method() for request in requests],
            ["GET", "GET", "POST", "PATCH", "PATCH", "PUT", "DELETE", "GET"],
        )
        self.assertEqual(parse.urlparse(requests[0].full_url).path, "/api/v3/notifications/news")
        self.assertEqual(
            parse.urlparse(requests[1].full_url).path,
            "/api/v3/notifications/user-news-settings/setting%2F1",
        )
        self.assertEqual(parse.urlparse(requests[2].full_url).path, "/api/v3/notifications/user-reminder-settings")
        self.assertEqual(parse.urlparse(requests[3].full_url).path, "/api/v3/notifications/user-push-tokens")
        self.assertEqual(
            parse.urlparse(requests[4].full_url).path,
            "/api/v3/notifications/user-news-settings/setting%2F1",
        )
        self.assertEqual(parse.urlparse(requests[5].full_url).path, "/api/v3/notifications/news/news%20item%201")
        self.assertEqual(parse.urlparse(requests[6].full_url).path, "/api/v3/notifications/user-push-tokens/token%201")
        self.assertEqual(
            parse.urlparse(requests[7].full_url).path,
            "/api/v3/notifications/user-reminder-settings/reminder%2F1",
        )
        self.assertEqual(
            json.loads(requests[2].data.decode("utf-8")),
            {
                "userId": 7,
                "reminderType": "SHIFT_PLANNER",
                "reminderSubtype": "SHIFT_START",
                "pushEnabled": True,
                "timeDeltaSeconds": 1800,
            },
        )
        self.assertEqual(json.loads(requests[3].data.decode("utf-8")), [{"method": "DELETE", "path": "/1"}])
        self.assertEqual(json.loads(requests[4].data.decode("utf-8")), {"mobilePush": False})
        self.assertEqual(
            json.loads(requests[5].data.decode("utf-8")),
            {"crewId": 24, "senderId": 7, "receiverId": 8, "title": "Update"},
        )


class NotificationApiCliTests(unittest.TestCase):
    def test_list_notification_settings_outputs_json_and_passes_filters(self) -> None:
        transport = FakeTransport(
            FakeResponse(
                200,
                {
                    "content": [{"id": "news-setting-1", "targetProduct": "SHIFT_PLANNER"}],
                    "hasNextPage": False,
                },
            ),
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = run_cli(
            [
                "notification",
                "user-news-settings",
                "list",
                "--filter",
                "userId==7;targetProduct==SHIFT_PLANNER;targetFeature==SHIFTS_CHANGES",
                "--sort",
                "targetProduct",
                "--query",
                # Arbitrary query forwarding probe; not a documented server parameter.
                "includeInactive=false",
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
        self.assertEqual(json.loads(stdout.getvalue()), [{"id": "news-setting-1", "targetProduct": "SHIFT_PLANNER"}])
        parsed = parse.urlparse(transport.calls[0][0].full_url)
        query = parse.parse_qs(parsed.query)
        self.assertEqual(parsed.path, "/api/v3/notifications/user-news-settings")
        self.assertEqual(query["filter"], ["userId==7;targetProduct==SHIFT_PLANNER;targetFeature==SHIFTS_CHANGES"])
        self.assertEqual(query["sort"], ["targetProduct"])
        self.assertEqual(query["includeInactive"], ["false"])
        self.assertEqual(query["pageSize"], ["25"])

    def test_list_user_push_tokens_redacts_push_token_values_from_stdout(self) -> None:
        transport = FakeTransport(
            FakeResponse(
                200,
                {
                    "content": [
                        {
                            "id": "token-1",
                            "userId": 7,
                            "pushToken": "PUSH-TOKEN-SECRET",
                            "metadata": {"nestedPushToken": "NESTED-PUSH-TOKEN-SECRET"},
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
                "notification",
                "user-push-tokens",
                "list",
                "--filter",
                "userId==7",
                "--limit",
                "1",
            ],
            stdout=stdout,
            stderr=stderr,
            client_factory=_factory(transport),
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertNotIn("PUSH-TOKEN-SECRET", stdout.getvalue())
        self.assertNotIn("NESTED-PUSH-TOKEN-SECRET", stdout.getvalue())
        self.assertEqual(
            json.loads(stdout.getvalue()),
            [
                {
                    "id": "token-1",
                    "metadata": {"nestedPushToken": "[REDACTED]"},
                    "pushToken": "[REDACTED]",
                    "userId": 7,
                }
            ],
        )

    def test_create_user_reminder_setting_posts_payload(self) -> None:
        transport = FakeTransport(FakeResponse(200, {"id": "reminder-1", "pushEnabled": True}))
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = run_cli(
            [
                "notification",
                "user-reminder-settings",
                "create",
                "--json-file",
                "-",
                "--yes",
            ],
            stdout=stdout,
            stderr=stderr,
            stdin=io.StringIO(
                '{"userId":7,"reminderType":"SHIFT_PLANNER","reminderSubtype":"SHIFT_START",'
                '"pushEnabled":true,"timeDeltaSeconds":1800}'
            ),
            client_factory=_factory(transport),
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(json.loads(stdout.getvalue()), {"id": "reminder-1", "pushEnabled": True})
        request = transport.calls[0][0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(parse.urlparse(request.full_url).path, "/api/v3/notifications/user-reminder-settings")
        self.assertEqual(
            json.loads(request.data.decode("utf-8")),
            {
                "userId": 7,
                "reminderType": "SHIFT_PLANNER",
                "reminderSubtype": "SHIFT_START",
                "pushEnabled": True,
                "timeDeltaSeconds": 1800,
            },
        )

    def test_write_operations_exit_before_reading_payload_or_calling_api_without_confirmation(self) -> None:
        transport = FakeTransport(FakeResponse(200, {"ok": True}))
        stdout = io.StringIO()
        stderr = io.StringIO()
        factory = _CountingFactory(transport)

        exit_code = run_cli(
            ["notification", "news", "create", "--json-file", "-"],
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

    def test_api_errors_do_not_echo_push_token_payload_or_messages(self) -> None:
        transport = FakeTransport(
            FakeResponse(
                400,
                {
                    "code": "PUSH_TOKEN_INVALID",
                    "message": "push token PUSH-TOKEN-SECRET is invalid",
                    "details": {"pushToken": "PUSH-TOKEN-SECRET"},
                    "requestId": "request-notification-1",
                },
            )
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = run_cli(
            [
                "notification",
                "user-push-tokens",
                "patch",
                "token-1",
                "--json-file",
                "-",
                "--yes",
            ],
            stdout=stdout,
            stderr=stderr,
            stdin=io.StringIO('{"pushToken":"PUSH-TOKEN-SECRET"}'),
            client_factory=_factory(transport),
        )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("HTTP 400", stderr.getvalue())
        self.assertIn("code=PUSH_TOKEN_INVALID", stderr.getvalue())
        self.assertIn("request_id=request-notification-1", stderr.getvalue())
        self.assertNotIn("PUSH-TOKEN-SECRET", stderr.getvalue())
        self.assertNotIn("push token", stderr.getvalue())


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
