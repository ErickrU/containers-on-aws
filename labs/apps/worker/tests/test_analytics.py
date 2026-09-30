from __future__ import annotations

import json
from datetime import date

import pytest

from tests.conftest import EVENT
from worker.analytics import SQL_UPSERT_DAILY_STATS, AnalyticsHandler, build_consumer_config, upsert_params
from worker.config import AnalyticsConfig
from worker.events import MalformedMessage, parse_event


def test_upsert_params_from_event(event_body):
    day, revenue_cents = upsert_params(parse_event(event_body))

    assert day == date(2026, 9, 29)
    assert revenue_cents == 1999 * 2


def test_upsert_params_use_the_utc_day():
    # 23:30 at UTC-02:00 is 01:30 the next day in UTC; daily_stats is keyed by the UTC day.
    event = parse_event(json.dumps({**EVENT, "createdAt": "2026-09-29T23:30:00-02:00"}))

    assert upsert_params(event)[0] == date(2026, 9, 30)


def test_handler_executes_the_upsert_with_computed_args(fake_db, event_body):
    day, revenue_cents = AnalyticsHandler(fake_db).handle(event_body.encode("utf-8"))

    assert fake_db.conn.calls == [(SQL_UPSERT_DAILY_STATS, (date(2026, 9, 29), 3998))]
    assert (day, revenue_cents) == (date(2026, 9, 29), 3998)
    assert "ON CONFLICT (day) DO UPDATE" in SQL_UPSERT_DAILY_STATS
    assert "EXCLUDED.revenue_cents" in SQL_UPSERT_DAILY_STATS


def test_handler_rejects_malformed_record_without_database_access(fake_db):
    with pytest.raises(MalformedMessage):
        AnalyticsHandler(fake_db).handle(b"\xff\xfe")
    assert fake_db.conn.calls == []


def _config(**overrides) -> AnalyticsConfig:
    values = dict(
        service_name="analytics-consumer",
        database_url="postgres://app:app@localhost:5432/shopfront",
        port=8083,
        log_level="info",
        shutdown_timeout_seconds=20,
        otel_endpoint=None,
        kafka_brokers="kafka:9092",
        kafka_topic="orders.created",
        kafka_group_id="analytics",
        kafka_sasl_iam=False,
        aws_region=None,
    )
    values.update(overrides)
    return AnalyticsConfig(**values)


def test_consumer_config_local_has_manual_commits_and_no_sasl():
    conf = build_consumer_config(_config())

    assert conf["bootstrap.servers"] == "kafka:9092"
    assert conf["group.id"] == "analytics"
    assert conf["enable.auto.commit"] is False
    assert conf["auto.offset.reset"] == "earliest"
    assert "security.protocol" not in conf
    assert "oauth_cb" not in conf


def test_consumer_config_msk_iam_uses_oauthbearer():
    conf = build_consumer_config(_config(kafka_sasl_iam=True, aws_region="us-east-1"))

    assert conf["security.protocol"] == "SASL_SSL"
    assert conf["sasl.mechanism"] == "OAUTHBEARER"
    assert callable(conf["oauth_cb"])
