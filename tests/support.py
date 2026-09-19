"""Synthetic HTTP test doubles shared by the package test suite."""

from __future__ import annotations

import json
from urllib import request as urlrequest


class FakeResponse:
    def __init__(self, status: int, payload: object) -> None:
        self.status = status
        self.headers: dict[str, str] = {}
        self._body = json.dumps(payload).encode("utf-8") if payload is not None else b""
        self.closed = False

    def read(self, amount: int = -1) -> bytes:
        if amount < 0:
            amount = len(self._body)
        body, self._body = self._body[:amount], self._body[amount:]
        return body

    def close(self) -> None:
        self.closed = True


class FakeTransport:
    def __init__(self, *responses: FakeResponse) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[urlrequest.Request, float]] = []

    def __call__(self, request: urlrequest.Request, timeout: float) -> FakeResponse:
        self.calls.append((request, timeout))
        if not self.responses:
            raise AssertionError("No fake response queued.")
        return self.responses.pop(0)
