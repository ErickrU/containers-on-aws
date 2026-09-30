from __future__ import annotations

import json

import pytest

from tests.conftest import EVENT, ORDER_ID, FakeDatabase
from worker.events import MalformedMessage, parse_event
from worker.fulfillment import (
    OUTCOME_ALREADY_PROCESSED,
    OUTCOME_FULFILLED,
    SQL_FULFILL,
    ChaosFailure,
    FulfillmentHandler,
)


def test_fulfilled_path_runs_the_idempotent_update(fake_db, event_body):
    handler = FulfillmentHandler(fake_db)

    assert handler.handle(event_body) == OUTCOME_FULFILLED
    assert fake_db.conn.calls == [(SQL_FULFILL, (ORDER_ID,))]
    assert "status = 'CREATED'" in SQL_FULFILL  # the WHERE clause is what makes redelivery safe


def test_already_processed_when_no_row_changes(event_body):
    db = FakeDatabase(rowcount=0)
    handler = FulfillmentHandler(db)

    assert handler.handle(event_body) == OUTCOME_ALREADY_PROCESSED
    assert len(db.conn.calls) == 1  # the UPDATE ran, matched nothing, and that is not an error


def test_malformed_body_raises_and_never_touches_the_database(fake_db):
    handler = FulfillmentHandler(fake_db)

    with pytest.raises(MalformedMessage):
        handler.handle("{not json")
    with pytest.raises(MalformedMessage):
        handler.handle(None)
    with pytest.raises(MalformedMessage):
        handler.handle(json.dumps({**EVENT, "orderId": "not-a-uuid"}))
    with pytest.raises(MalformedMessage):
        handler.handle(json.dumps({k: v for k, v in EVENT.items() if k != "orderId"}))
    with pytest.raises(MalformedMessage):
        handler.handle(json.dumps({**EVENT, "type": "order.cancelled"}))
    with pytest.raises(MalformedMessage):
        handler.handle(json.dumps({**EVENT, "quantity": 0}))
    assert fake_db.conn.calls == []


def test_bytes_body_is_accepted(fake_db, event_body):
    assert FulfillmentHandler(fake_db).handle(event_body.encode("utf-8")) == OUTCOME_FULFILLED


def test_fail_every_n_raises_before_the_database_is_touched(fake_db, event_body):
    handler = FulfillmentHandler(fake_db, fail_every_n=2)

    assert handler.handle(event_body) == OUTCOME_FULFILLED
    with pytest.raises(ChaosFailure):
        handler.handle(event_body)
    assert handler.handle(event_body) == OUTCOME_FULFILLED
    assert len(fake_db.conn.calls) == 2


def test_parse_event_normalises_fields():
    event = parse_event(json.dumps({**EVENT, "createdAt": "2026-09-29T20:00:00.123Z"}))

    assert event.order_id == ORDER_ID
    assert event.product_id == 1
    assert event.quantity == 2
    assert event.price_cents == 1999
    assert event.revenue_cents == 3998
    assert event.created_at.tzinfo is not None
    assert event.created_at.isoformat() == "2026-09-29T20:00:00.123000+00:00"
