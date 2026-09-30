"""``python -m worker.fulfillment`` - SQS consumer that fulfils orders.

Per message (labs/CONTRACT.md §5):

1. start span ``order.fulfill`` whose parent comes from the ``traceparent`` message attribute;
2. parse the ``order.created`` body;
3. ``UPDATE orders SET status='FULFILLED', updated_at=now() WHERE id=%s AND status='CREATED'``;
   zero rows affected means "already processed" (a redelivery) and is not an error;
4. delete the message on success. On any exception the message is **not** deleted, so it becomes
   visible again after the visibility timeout and reaches the dead-letter queue after
   ``maxReceiveCount`` attempts.

``FAIL_EVERY_N`` is a chaos knob: every Nth received message raises before touching the database,
which is the quickest way to watch redelivery and the DLQ in action.
"""

from __future__ import annotations

import logging
import sys
import time

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode

from worker import metrics
from worker.config import ConfigError, FulfillmentConfig, load_fulfillment_config, redact_url
from worker.db import Database, DatabaseUnavailable
from worker.events import parse_event
from worker.health import HealthServer
from worker.lifecycle import EXIT_CONFIG_ERROR, EXIT_RUNTIME_ERROR, Lifecycle
from worker.logging import configure_logging
from worker.telemetry import context_from_sqs_attributes, setup_tracing, shutdown_tracing

log = logging.getLogger(__name__)
tracer = trace.get_tracer("shopfront.fulfillment")

SQL_FULFILL = "UPDATE orders SET status = 'FULFILLED', updated_at = now() WHERE id = %s AND status = 'CREATED'"

OUTCOME_FULFILLED = "fulfilled"
OUTCOME_ALREADY_PROCESSED = "already_processed"


class ChaosFailure(RuntimeError):
    """Raised by the FAIL_EVERY_N knob to exercise redelivery and the dead-letter queue."""


class FulfillmentHandler:
    """Business logic for one message. Pure enough to unit test with a fake database."""

    def __init__(self, db, fail_every_n: int = 0) -> None:
        self._db = db
        self._fail_every_n = fail_every_n
        self._received = 0

    def handle(self, body: str | bytes | None) -> str:
        self._received += 1
        if self._fail_every_n and self._received % self._fail_every_n == 0:
            raise ChaosFailure(f"FAIL_EVERY_N={self._fail_every_n}: failing message #{self._received} on purpose")

        event = parse_event(body)
        with self._db.connection() as conn:
            rows = conn.execute(SQL_FULFILL, (event.order_id,)).rowcount
        if rows == 0:
            log.info("order already processed, skipping", extra={"order_id": event.order_id})
            return OUTCOME_ALREADY_PROCESSED
        metrics.ORDERS_FULFILLED.inc()
        log.info(
            "order fulfilled",
            extra={"order_id": event.order_id, "product_id": event.product_id, "quantity": event.quantity},
        )
        return OUTCOME_FULFILLED


class FulfillmentWorker:
    """The polling loop: receive a batch, process each message, delete the ones that succeeded."""

    def __init__(self, cfg: FulfillmentConfig, sqs, handler: FulfillmentHandler, stop) -> None:
        self._cfg = cfg
        self._sqs = sqs
        self._handler = handler
        self._stop = stop

    def run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                messages = self._receive()
                backoff = 1.0
            except (BotoCoreError, ClientError) as exc:
                log.error("sqs receive failed, retrying", extra={"error": str(exc), "retry_in_seconds": backoff})
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 30.0)
                continue
            for message in messages:
                self._process(message)

    def _receive(self) -> list[dict]:
        with tracer.start_as_current_span("sqs.receive", kind=SpanKind.CLIENT):
            response = self._sqs.receive_message(
                QueueUrl=self._cfg.sqs_queue_url,
                MaxNumberOfMessages=self._cfg.sqs_max_messages,
                WaitTimeSeconds=self._cfg.sqs_wait_time_seconds,
                MessageAttributeNames=["All"],
                MessageSystemAttributeNames=["ApproximateReceiveCount"],
            )
        messages = response.get("Messages", [])
        if messages:
            metrics.SQS_MESSAGES_RECEIVED.inc(len(messages))
        return messages

    def _process(self, message: dict) -> None:
        message_id = message.get("MessageId", "")
        receive_count = message.get("Attributes", {}).get("ApproximateReceiveCount")
        parent = context_from_sqs_attributes(message.get("MessageAttributes"))
        attributes = {
            "messaging.system": "aws_sqs",
            "messaging.operation": "process",
            "messaging.destination.name": self._cfg.sqs_queue_url.rsplit("/", 1)[-1],
            "messaging.message.id": message_id,
        }
        if receive_count is not None:
            attributes["messaging.aws_sqs.receive_count"] = int(receive_count)

        with tracer.start_as_current_span("order.fulfill", context=parent, kind=SpanKind.CONSUMER, attributes=attributes) as span:
            started = time.perf_counter()
            try:
                outcome = self._handler.handle(message.get("Body"))
            except Exception as exc:  # noqa: BLE001 - every failure means "leave it on the queue"
                metrics.ORDERS_FAILED.inc()
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                log.exception(
                    "order processing failed; message stays on the queue for redelivery",
                    extra={"message_id": message_id, "receive_count": receive_count, "error": str(exc)},
                )
                return
            finally:
                metrics.PROCESSING_DURATION.labels(handler="order.fulfill").observe(time.perf_counter() - started)
            span.set_attribute("shopfront.outcome", outcome)
            try:
                self._sqs.delete_message(QueueUrl=self._cfg.sqs_queue_url, ReceiptHandle=message["ReceiptHandle"])
            except (BotoCoreError, ClientError) as exc:
                # The order is already FULFILLED; the redelivery will hit the idempotent UPDATE.
                log.error("sqs delete failed; expect one redelivery", extra={"message_id": message_id, "error": str(exc)})


def main() -> int:
    try:
        cfg = load_fulfillment_config()
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    configure_logging(cfg.log_level, cfg.service_name)
    log.info(
        "starting fulfillment worker",
        extra={
            "database_url": redact_url(cfg.database_url),
            "sqs_queue_url": cfg.sqs_queue_url,
            "aws_region": cfg.aws_region,
            "sqs_wait_time_seconds": cfg.sqs_wait_time_seconds,
            "sqs_max_messages": cfg.sqs_max_messages,
            "fail_every_n": cfg.fail_every_n,
            "shutdown_timeout_seconds": cfg.shutdown_timeout_seconds,
        },
    )
    if cfg.sqs_wait_time_seconds > cfg.shutdown_timeout_seconds:
        log.warning(
            "SQS_WAIT_TIME_SECONDS exceeds SHUTDOWN_TIMEOUT_SECONDS: a long poll in progress at SIGTERM "
            "will be cut short by the shutdown deadline"
        )
    if cfg.fail_every_n:
        log.warning("chaos knob active: every Nth message will fail", extra={"fail_every_n": cfg.fail_every_n})

    provider = setup_tracing(cfg.service_name, cfg.otel_endpoint, instrument_botocore=True, instrument_psycopg=True)
    lifecycle = Lifecycle(cfg.shutdown_timeout_seconds)
    lifecycle.install_signal_handlers()

    db = Database(cfg.database_url, name="fulfillment")
    try:
        db.open(timeout_seconds=30.0)
    except DatabaseUnavailable as exc:
        log.error("giving up on the database", extra={"error": str(exc)})
        shutdown_tracing(provider, 2.0)
        return EXIT_RUNTIME_ERROR

    health = HealthServer(cfg.port, ready_check=lambda: {"database": db.check()})
    health.start()

    # Region is passed explicitly (AWS_REGION is the contract's variable); the endpoint override for
    # ElasticMQ comes from AWS_ENDPOINT_URL_SQS, which botocore reads on its own.
    sqs = boto3.client("sqs", region_name=cfg.aws_region)
    worker = FulfillmentWorker(cfg, sqs, FulfillmentHandler(db, cfg.fail_every_n), lifecycle.stop)
    log.info("fulfillment worker ready")

    exit_code, remaining = lifecycle.supervise(worker.run, name="fulfillment-loop")

    health.stop()
    shutdown_tracing(provider, remaining)
    db.close()
    log.info("fulfillment worker stopped", extra={"exit_code": exit_code})
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
