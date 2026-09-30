"""Twelve-factor configuration: everything comes from the environment.

Rules (labs/CONTRACT.md §2):

- unknown variables are ignored;
- a missing required variable or an invalid value raises :class:`ConfigError`, and the
  entrypoints turn that into exit code 2 with a clear message on stderr;
- defaults are the ones listed in the contract table.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlsplit, urlunsplit

LOG_LEVELS = ("debug", "info", "warn", "error")


class ConfigError(Exception):
    """Raised for missing or invalid configuration. Maps to exit code 2."""


class _Env:
    """Small helper that collects every problem so the operator sees them all at once."""

    def __init__(self, env: Mapping[str, str]) -> None:
        self._env = env
        self.missing: list[str] = []
        self.invalid: list[str] = []

    def str(self, name: str, default: str | None = None, *, required: bool = False) -> str | None:
        value = self._env.get(name, "").strip()
        if value:
            return value
        if required:
            self.missing.append(name)
        return default

    def int(self, name: str, default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
        raw = self._env.get(name, "").strip()
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError:
            self.invalid.append(f"{name}={raw!r} is not an integer")
            return default
        if minimum is not None and value < minimum:
            self.invalid.append(f"{name}={value} is below the minimum {minimum}")
        if maximum is not None and value > maximum:
            self.invalid.append(f"{name}={value} is above the maximum {maximum}")
        return value

    def bool(self, name: str, default: bool = False) -> bool:
        raw = self._env.get(name, "").strip().lower()
        if not raw:
            return default
        if raw in ("1", "true", "yes", "on"):
            return True
        if raw in ("0", "false", "no", "off"):
            return False
        self.invalid.append(f"{name}={raw!r} is not a boolean (use true/false)")
        return default

    def log_level(self) -> str:
        level = (self._env.get("LOG_LEVEL", "").strip() or "info").lower()
        if level not in LOG_LEVELS:
            self.invalid.append(f"LOG_LEVEL={level!r} must be one of {', '.join(LOG_LEVELS)}")
            return "info"
        return level

    def raise_if_problems(self) -> None:
        problems = []
        if self.missing:
            problems.append("missing required environment variables: " + ", ".join(self.missing))
        problems.extend(self.invalid)
        if problems:
            raise ConfigError("; ".join(problems))


@dataclass(frozen=True)
class CommonConfig:
    service_name: str
    database_url: str
    port: int
    log_level: str
    shutdown_timeout_seconds: int
    otel_endpoint: str | None


@dataclass(frozen=True)
class FulfillmentConfig(CommonConfig):
    sqs_queue_url: str
    aws_region: str
    sqs_wait_time_seconds: int
    sqs_max_messages: int
    fail_every_n: int


@dataclass(frozen=True)
class AnalyticsConfig(CommonConfig):
    kafka_brokers: str
    kafka_topic: str
    kafka_group_id: str
    kafka_sasl_iam: bool
    aws_region: str | None


def _common(env: _Env, default_service_name: str, default_port: int) -> dict:
    return {
        "service_name": env.str("OTEL_SERVICE_NAME", default_service_name),
        "database_url": env.str("DATABASE_URL", required=True),
        "port": env.int("PORT", default_port, minimum=1, maximum=65535),
        "log_level": env.log_level(),
        "shutdown_timeout_seconds": env.int("SHUTDOWN_TIMEOUT_SECONDS", 20, minimum=1),
        "otel_endpoint": env.str("OTEL_EXPORTER_OTLP_ENDPOINT"),
    }


def load_fulfillment_config(environ: Mapping[str, str] | None = None) -> FulfillmentConfig:
    env = _Env(os.environ if environ is None else environ)
    values = _common(env, "fulfillment-worker", 8082)
    values.update(
        sqs_queue_url=env.str("SQS_QUEUE_URL", required=True),
        aws_region=env.str("AWS_REGION", required=True),
        sqs_wait_time_seconds=env.int("SQS_WAIT_TIME_SECONDS", 20, minimum=0, maximum=20),
        sqs_max_messages=env.int("SQS_MAX_MESSAGES", 10, minimum=1, maximum=10),
        fail_every_n=env.int("FAIL_EVERY_N", 0, minimum=0),
    )
    env.raise_if_problems()
    return FulfillmentConfig(**values)


def load_analytics_config(environ: Mapping[str, str] | None = None) -> AnalyticsConfig:
    env = _Env(os.environ if environ is None else environ)
    values = _common(env, "analytics-consumer", 8083)
    sasl_iam = env.bool("KAFKA_SASL_IAM", False)
    values.update(
        kafka_brokers=env.str("KAFKA_BROKERS", required=True),
        kafka_topic=env.str("KAFKA_TOPIC", "orders.created"),
        kafka_group_id=env.str("KAFKA_GROUP_ID", "analytics"),
        kafka_sasl_iam=sasl_iam,
        # The MSK IAM token is signed for a Region, so the Region becomes required with IAM auth.
        aws_region=env.str("AWS_REGION", required=sasl_iam),
    )
    env.raise_if_problems()
    return AnalyticsConfig(**values)


def redact_url(url: str) -> str:
    """Return ``url`` with any password replaced by ``***`` so it is safe to log."""
    parts = urlsplit(url)
    if parts.password is None:
        return url
    host = parts.hostname or ""
    if parts.port is not None:
        host = f"{host}:{parts.port}"
    user = parts.username or ""
    netloc = f"{user}:***@{host}" if user else f"***@{host}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
