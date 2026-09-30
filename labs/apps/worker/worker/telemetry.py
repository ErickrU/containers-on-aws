"""OpenTelemetry setup and W3C trace-context extraction for SQS and Kafka.

Tracing is enabled only when ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set (labs/CONTRACT.md §6). Without
it the process still runs: ``trace.get_tracer`` returns a no-op tracer, spans are not recorded and
log lines carry no ``trace_id``.

Context propagation is W3C ``traceparent``/``tracestate``. Producers put them into SQS message
attributes (``DataType: String``) and Kafka record headers; the helpers below turn either into an
OpenTelemetry :class:`~opentelemetry.context.Context` that the consumer span uses as its parent.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable, Mapping

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.propagate import set_global_textmap
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

log = logging.getLogger(__name__)

_PROPAGATOR = TraceContextTextMapPropagator()


def setup_tracing(
    service_name: str,
    endpoint: str | None,
    *,
    instrument_botocore: bool = False,
    instrument_psycopg: bool = False,
):
    """Configure the SDK when an OTLP endpoint is set; return the provider (or ``None``)."""
    if not endpoint:
        log.info("tracing disabled: OTEL_EXPORTER_OTLP_ENDPOINT is not set")
        return None

    # Imported lazily so the SDK is only wired when tracing is on.
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    # Resource.create() also reads OTEL_RESOURCE_ATTRIBUTES from the environment.
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    # OTLPSpanExporter reads OTEL_EXPORTER_OTLP_ENDPOINT itself and appends /v1/traces.
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    set_global_textmap(_PROPAGATOR)

    if instrument_botocore:
        from opentelemetry.instrumentation.botocore import BotocoreInstrumentor

        BotocoreInstrumentor().instrument()
    if instrument_psycopg:
        from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor

        PsycopgInstrumentor().instrument()

    log.info("tracing enabled", extra={"otlp_endpoint": endpoint, "service_name": service_name})
    return provider


def shutdown_tracing(provider, timeout_seconds: float) -> None:
    """Flush queued spans and stop the exporter, bounded by ``timeout_seconds``."""
    if provider is None:
        return
    timeout_millis = max(100, int(timeout_seconds * 1000))
    try:
        provider.force_flush(timeout_millis=timeout_millis)
        provider.shutdown()
    except Exception:  # noqa: BLE001 - telemetry must never turn a clean shutdown into a crash
        log.warning("tracing shutdown did not complete cleanly", exc_info=True)


def context_from_sqs_attributes(attributes: Mapping[str, Mapping[str, Any]] | None) -> Context:
    """Extract W3C trace context from an SQS ``MessageAttributes`` map.

    ``attributes`` is the boto3 shape: ``{"traceparent": {"DataType": "String",
    "StringValue": "00-<trace-id>-<span-id>-01"}}``. Attribute names are case-insensitive here
    because different SDKs disagree on casing.
    """
    carrier: dict[str, str] = {}
    for name, attribute in (attributes or {}).items():
        if not isinstance(attribute, Mapping):
            continue
        data_type = str(attribute.get("DataType", ""))
        value = attribute.get("StringValue")
        if data_type.startswith("String") and isinstance(value, str):
            carrier[name.lower()] = value
    return _PROPAGATOR.extract(carrier)


def context_from_kafka_headers(headers: Iterable[tuple[str, bytes | str | None]] | None) -> Context:
    """Extract W3C trace context from Kafka record headers (``[(key, value_bytes), ...]``)."""
    carrier: dict[str, str] = {}
    for key, value in headers or []:
        if value is None:
            continue
        if isinstance(value, (bytes, bytearray)):
            value = bytes(value).decode("utf-8", errors="replace")
        carrier[str(key).lower()] = str(value)
    return _PROPAGATOR.extract(carrier)


def current_trace_ids() -> tuple[str | None, str | None]:
    """Return ``(trace_id, span_id)`` of the active span as hex strings, or ``(None, None)``."""
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return None, None
    return format(span_context.trace_id, "032x"), format(span_context.span_id, "016x")
