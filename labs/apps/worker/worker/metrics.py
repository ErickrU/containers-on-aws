"""Prometheus metrics (labs/CONTRACT.md §6).

The default registry is used on purpose: ``prometheus_client`` registers the process collector
(``process_cpu_seconds_total``, ``process_resident_memory_bytes``, open file descriptors) and the
Python GC collector there at import time, so ``/metrics`` carries the process metrics for free.
"""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, Counter, Histogram, generate_latest

SQS_MESSAGES_RECEIVED = Counter(
    "sqs_messages_received_total", "Messages returned by SQS ReceiveMessage to the fulfillment worker"
)
ORDERS_FULFILLED = Counter("orders_fulfilled_total", "Orders moved from CREATED to FULFILLED")
ORDERS_FAILED = Counter(
    "orders_failed_total", "Order messages whose processing raised; the message returned to the queue"
)
KAFKA_MESSAGES_CONSUMED = Counter(
    "kafka_messages_consumed_total", "Records consumed from Kafka by the analytics consumer"
)
PROCESSING_DURATION = Histogram(
    "processing_duration_seconds",
    "Wall-clock time spent handling one message, including the database write",
    ["handler"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
HTTP_REQUESTS = Counter(
    "http_requests_total", "Requests served by the health/metrics HTTP endpoint", ["method", "route", "status"]
)


def render() -> tuple[bytes, str]:
    """Return the Prometheus text exposition and its content type."""
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
