from __future__ import annotations

import pytest

from worker.config import ConfigError, load_analytics_config, load_fulfillment_config, redact_url

FULFILLMENT_ENV = {
    "DATABASE_URL": "postgres://app:app@postgres:5432/shopfront",
    "SQS_QUEUE_URL": "http://elasticmq:9324/000000000000/orders-created",
    "AWS_REGION": "us-east-1",
}


def test_fulfillment_defaults():
    cfg = load_fulfillment_config(FULFILLMENT_ENV)

    assert cfg.port == 8082
    assert cfg.service_name == "fulfillment-worker"
    assert cfg.sqs_wait_time_seconds == 20
    assert cfg.sqs_max_messages == 10
    assert cfg.fail_every_n == 0
    assert cfg.shutdown_timeout_seconds == 20
    assert cfg.log_level == "info"
    assert cfg.otel_endpoint is None


def test_fulfillment_reports_every_missing_variable_at_once():
    with pytest.raises(ConfigError) as exc:
        load_fulfillment_config({"UNRELATED": "ignored"})

    message = str(exc.value)
    assert "DATABASE_URL" in message and "SQS_QUEUE_URL" in message and "AWS_REGION" in message


def test_fulfillment_validates_ranges():
    with pytest.raises(ConfigError, match="SQS_MAX_MESSAGES"):
        load_fulfillment_config({**FULFILLMENT_ENV, "SQS_MAX_MESSAGES": "11"})
    with pytest.raises(ConfigError, match="SQS_WAIT_TIME_SECONDS"):
        load_fulfillment_config({**FULFILLMENT_ENV, "SQS_WAIT_TIME_SECONDS": "abc"})
    with pytest.raises(ConfigError, match="LOG_LEVEL"):
        load_fulfillment_config({**FULFILLMENT_ENV, "LOG_LEVEL": "verbose"})


def test_analytics_defaults_and_overrides():
    cfg = load_analytics_config({"DATABASE_URL": "postgres://x", "KAFKA_BROKERS": "kafka:9092", "PORT": "9000"})

    assert cfg.port == 9000
    assert cfg.service_name == "analytics-consumer"
    assert cfg.kafka_topic == "orders.created"
    assert cfg.kafka_group_id == "analytics"
    assert cfg.kafka_sasl_iam is False
    assert cfg.aws_region is None


def test_analytics_requires_region_only_with_iam_auth():
    load_analytics_config({"DATABASE_URL": "postgres://x", "KAFKA_BROKERS": "b:9092"})
    with pytest.raises(ConfigError, match="AWS_REGION"):
        load_analytics_config({"DATABASE_URL": "postgres://x", "KAFKA_BROKERS": "b:9098", "KAFKA_SASL_IAM": "true"})
    with pytest.raises(ConfigError, match="KAFKA_BROKERS"):
        load_analytics_config({"DATABASE_URL": "postgres://x"})


def test_otel_service_name_overrides_the_default():
    cfg = load_fulfillment_config({**FULFILLMENT_ENV, "OTEL_SERVICE_NAME": "fulfillment-blue"})

    assert cfg.service_name == "fulfillment-blue"


def test_redact_url_hides_the_password_only():
    assert redact_url("postgres://app:s3cret@postgres:5432/shopfront?sslmode=require") == (
        "postgres://app:***@postgres:5432/shopfront?sslmode=require"
    )
    assert redact_url("postgres://postgres:5432/shopfront") == "postgres://postgres:5432/shopfront"
