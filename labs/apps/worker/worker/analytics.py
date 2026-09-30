"""``python -m worker.analytics`` - Kafka consumer that maintains ``daily_stats``.

Per record (labs/CONTRACT.md §5):

1. start span ``kafka.consume`` whose parent comes from the ``traceparent`` record header;
2. parse the ``order.created`` value;
3. upsert ``daily_stats`` for ``date(createdAt)`` (UTC): ``orders_count += 1``,
   ``revenue_cents += priceCents * quantity``;
4. commit the offset **after** the write (``enable.auto.commit=false``).

Failure handling shows the two kinds of failure a consumer meets. A malformed record can never
succeed, so it is logged and its offset committed (skipping it) - otherwise the partition would be
stuck forever. A transient failure (database down) is retried in place: the consumer seeks back
to the record's offset and polls again after a backoff. Not committing is *not* a retry on its
own, because ``poll`` keeps advancing the in-memory position.

MSK IAM authentication (``KAFKA_SASL_IAM=true``) uses SASL/OAUTHBEARER with a token minted by
``aws-msk-iam-sasl-signer-python``; the import is lazy so local runs never touch it.
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import date, timezone

from confluent_kafka import Consumer, KafkaError, KafkaException, TopicPartition
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode

from worker import metrics
from worker.config import AnalyticsConfig, ConfigError, load_analytics_config, redact_url
from worker.db import Database, DatabaseUnavailable
from worker.events import MalformedMessage, OrderCreated, parse_event
from worker.health import HealthServer
from worker.lifecycle import EXIT_CONFIG_ERROR, EXIT_RUNTIME_ERROR, Lifecycle
from worker.logging import configure_logging
from worker.telemetry import context_from_kafka_headers, setup_tracing, shutdown_tracing

log = logging.getLogger(__name__)
tracer = trace.get_tracer("shopfront.analytics")

SQL_UPSERT_DAILY_STATS = (
    "INSERT INTO daily_stats (day, orders_count, revenue_cents) VALUES (%s, 1, %s) "
    "ON CONFLICT (day) DO UPDATE SET "
    "orders_count = daily_stats.orders_count + 1, "
    "revenue_cents = daily_stats.revenue_cents + EXCLUDED.revenue_cents"
)


def upsert_params(event: OrderCreated) -> tuple[date, int]:
    """Return ``(day, revenue_cents)`` for the upsert: the UTC calendar day of ``createdAt``."""
    return event.created_at.astimezone(timezone.utc).date(), event.revenue_cents


class AnalyticsHandler:
    def __init__(self, db) -> None:
        self._db = db

    def handle(self, value: bytes | str | None) -> tuple[date, int]:
        event = parse_event(value)
        day, revenue_cents = upsert_params(event)
        with self._db.connection() as conn:
            conn.execute(SQL_UPSERT_DAILY_STATS, (day, revenue_cents))
        log.info(
            "daily_stats updated",
            extra={"order_id": event.order_id, "day": day.isoformat(), "revenue_cents": revenue_cents},
        )
        return day, revenue_cents


def make_msk_iam_oauth_callback(region: str):
    """Return the ``oauth_cb`` librdkafka calls whenever it needs a fresh SASL/OAUTHBEARER token."""
    from aws_msk_iam_sasl_signer import MSKAuthTokenProvider  # lazy: only needed on AWS

    def oauth_cb(_oauth_config: str) -> tuple[str, float]:
        token, expiry_ms = MSKAuthTokenProvider.generate_auth_token(region)
        return token, expiry_ms / 1000  # librdkafka wants the expiry in seconds since the epoch

    return oauth_cb


def build_consumer_config(cfg: AnalyticsConfig) -> dict:
    conf: dict = {
        "bootstrap.servers": cfg.kafka_brokers,
        "group.id": cfg.kafka_group_id,
        "client.id": cfg.service_name,
        "enable.auto.commit": False,
        "auto.offset.reset": "earliest",
        # Locally the topic does not exist before the first order. Against apache/kafka 3.9 (KRaft)
        # the consumer's metadata request did not create it even with this flag; the producer's first
        # send does, and this consumer joins within a second of that.
        "allow.auto.create.topics": True,
        "logger": logging.getLogger("librdkafka"),
        "error_cb": _on_client_error,
    }
    if cfg.kafka_sasl_iam:
        conf.update(
            {
                "security.protocol": "SASL_SSL",
                "sasl.mechanism": "OAUTHBEARER",
                "oauth_cb": make_msk_iam_oauth_callback(cfg.aws_region or ""),
            }
        )
    return conf


def _on_client_error(error: KafkaError) -> None:
    level = logging.ERROR if error.fatal() else logging.WARNING
    log.log(level, "kafka client error", extra={"error": error.str(), "code": error.name(), "fatal": error.fatal()})


class AnalyticsWorker:
    def __init__(self, cfg: AnalyticsConfig, consumer: Consumer, handler: AnalyticsHandler, stop) -> None:
        self._cfg = cfg
        self._consumer = consumer
        self._handler = handler
        self._stop = stop
        self._retry_backoff = 1.0

    def run(self) -> None:
        self._consumer.subscribe([self._cfg.kafka_topic], on_assign=self._on_assign, on_revoke=self._on_revoke)
        try:
            while not self._stop.is_set():
                msg = self._consumer.poll(1.0)
                if msg is None:
                    continue
                if msg.error():
                    self._on_message_error(msg.error())
                    continue
                self._process(msg)
        finally:
            # Leaves the group cleanly so the partitions move to another member without waiting
            # for the session timeout.
            self._consumer.close()

    def _on_assign(self, _consumer, partitions: list[TopicPartition]) -> None:
        log.info("partitions assigned", extra={"partitions": [f"{p.topic}[{p.partition}]" for p in partitions]})

    def _on_revoke(self, _consumer, partitions: list[TopicPartition]) -> None:
        log.info("partitions revoked", extra={"partitions": [f"{p.topic}[{p.partition}]" for p in partitions]})

    def _on_message_error(self, error: KafkaError) -> None:
        if error.code() == KafkaError._PARTITION_EOF:
            return
        if error.fatal():
            raise KafkaException(error)
        if error.code() == KafkaError.UNKNOWN_TOPIC_OR_PART:
            # Locally the topic appears when the first order is produced (auto.create.topics.enable);
            # librdkafka keeps refreshing metadata and joins as soon as it exists.
            log.info("topic not available yet, waiting", extra={"topic": self._cfg.kafka_topic, "error": error.str()})
            return
        log.warning("kafka poll returned an error", extra={"error": error.str(), "code": error.name()})

    def _process(self, msg) -> None:
        metrics.KAFKA_MESSAGES_CONSUMED.inc()
        parent = context_from_kafka_headers(msg.headers())
        attributes = {
            "messaging.system": "kafka",
            "messaging.operation": "process",
            "messaging.destination.name": msg.topic(),
            "messaging.destination.partition.id": str(msg.partition()),
            "messaging.kafka.offset": msg.offset(),
            "messaging.consumer.group.name": self._cfg.kafka_group_id,
        }
        key = msg.key()
        if key:
            attributes["messaging.kafka.message.key"] = key.decode("utf-8", errors="replace")

        with tracer.start_as_current_span("kafka.consume", context=parent, kind=SpanKind.CONSUMER, attributes=attributes) as span:
            started = time.perf_counter()
            try:
                day, revenue_cents = self._handler.handle(msg.value())
            except MalformedMessage as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                log.error(
                    "skipping malformed record",
                    extra={"partition": msg.partition(), "offset": msg.offset(), "error": str(exc)},
                )
                self._commit(msg)
                return
            except Exception as exc:  # noqa: BLE001 - transient failure: retry the same record
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                log.exception(
                    "record processing failed; seeking back to retry",
                    extra={"partition": msg.partition(), "offset": msg.offset(), "retry_in_seconds": self._retry_backoff},
                )
                self._seek_back(msg)
                self._stop.wait(self._retry_backoff)
                self._retry_backoff = min(self._retry_backoff * 2, 30.0)
                return
            finally:
                metrics.PROCESSING_DURATION.labels(handler="kafka.consume").observe(time.perf_counter() - started)
            self._retry_backoff = 1.0
            span.set_attribute("shopfront.day", day.isoformat())
            span.set_attribute("shopfront.revenue_cents", revenue_cents)
            self._commit(msg)

    def _seek_back(self, msg) -> None:
        try:
            self._consumer.seek(TopicPartition(msg.topic(), msg.partition(), msg.offset()))
        except KafkaException as exc:
            # Typically "partition no longer assigned" after a rebalance: the new owner re-reads it.
            log.warning("seek failed", extra={"partition": msg.partition(), "offset": msg.offset(), "error": str(exc)})

    def _commit(self, msg) -> None:
        try:
            self._consumer.commit(message=msg, asynchronous=False)
        except KafkaException as exc:
            log.error(
                "offset commit failed; the record may be consumed again after a restart",
                extra={"partition": msg.partition(), "offset": msg.offset(), "error": str(exc)},
            )


def main() -> int:
    try:
        cfg = load_analytics_config()
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    configure_logging(cfg.log_level, cfg.service_name)
    log.info(
        "starting analytics consumer",
        extra={
            "database_url": redact_url(cfg.database_url),
            "kafka_brokers": cfg.kafka_brokers,
            "kafka_topic": cfg.kafka_topic,
            "kafka_group_id": cfg.kafka_group_id,
            "kafka_sasl_iam": cfg.kafka_sasl_iam,
            "shutdown_timeout_seconds": cfg.shutdown_timeout_seconds,
        },
    )

    provider = setup_tracing(cfg.service_name, cfg.otel_endpoint, instrument_psycopg=True)
    lifecycle = Lifecycle(cfg.shutdown_timeout_seconds)
    lifecycle.install_signal_handlers()

    db = Database(cfg.database_url, name="analytics")
    try:
        db.open(timeout_seconds=30.0)
    except DatabaseUnavailable as exc:
        log.error("giving up on the database", extra={"error": str(exc)})
        shutdown_tracing(provider, 2.0)
        return EXIT_RUNTIME_ERROR

    health = HealthServer(cfg.port, ready_check=lambda: {"database": db.check()})
    health.start()

    try:
        consumer = Consumer(build_consumer_config(cfg))
    except (KafkaException, ImportError) as exc:
        log.error("cannot create the Kafka consumer", extra={"error": str(exc)})
        health.stop()
        shutdown_tracing(provider, 2.0)
        db.close()
        return EXIT_RUNTIME_ERROR

    worker = AnalyticsWorker(cfg, consumer, AnalyticsHandler(db), lifecycle.stop)
    log.info("analytics consumer ready")

    exit_code, remaining = lifecycle.supervise(worker.run, name="analytics-loop")

    health.stop()
    shutdown_tracing(provider, remaining)
    db.close()
    log.info("analytics consumer stopped", extra={"exit_code": exit_code})
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
