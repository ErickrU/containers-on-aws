"""Shared test doubles. No network, no database: the handlers only need ``db.connection()``."""

from __future__ import annotations

import json
from contextlib import contextmanager

import pytest

ORDER_ID = "6f1c1c3a-8b1e-4e0f-9b4a-2d7c5a1e9f10"

EVENT = {
    "type": "order.created",
    "version": 1,
    "orderId": ORDER_ID,
    "productId": 1,
    "quantity": 2,
    "priceCents": 1999,
    "createdAt": "2026-09-29T20:00:00Z",
}


class FakeCursor:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class FakeConnection:
    """Records every ``execute`` call and answers with a fixed ``rowcount``."""

    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount
        self.calls: list[tuple[str, tuple]] = []

    def execute(self, sql: str, params=None):
        self.calls.append((sql, params))
        return FakeCursor(self.rowcount)


class FakeDatabase:
    def __init__(self, rowcount: int = 1) -> None:
        self.conn = FakeConnection(rowcount)
        self.borrowed = 0

    @contextmanager
    def connection(self, timeout=None):
        self.borrowed += 1
        yield self.conn


@pytest.fixture
def event_body() -> str:
    return json.dumps(EVENT)


@pytest.fixture
def fake_db() -> FakeDatabase:
    return FakeDatabase(rowcount=1)
