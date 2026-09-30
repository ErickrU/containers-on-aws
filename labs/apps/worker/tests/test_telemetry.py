from __future__ import annotations

from opentelemetry import trace

from worker.telemetry import context_from_kafka_headers, context_from_sqs_attributes, current_trace_ids

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
SPAN_ID = "00f067aa0ba902b7"
TRACEPARENT = f"00-{TRACE_ID}-{SPAN_ID}-01"


def _span_context(ctx):
    return trace.get_current_span(ctx).get_span_context()


def test_sqs_message_attributes_carry_the_parent():
    attributes = {
        "traceparent": {"DataType": "String", "StringValue": TRACEPARENT},
        "tracestate": {"DataType": "String", "StringValue": "vendor=opaque"},
        "ignored": {"DataType": "Number", "StringValue": "42"},
    }

    sc = _span_context(context_from_sqs_attributes(attributes))

    assert sc.is_valid and sc.is_remote
    assert format(sc.trace_id, "032x") == TRACE_ID
    assert format(sc.span_id, "016x") == SPAN_ID
    assert sc.trace_flags.sampled
    assert sc.trace_state.get("vendor") == "opaque"


def test_sqs_attribute_names_are_case_insensitive():
    sc = _span_context(context_from_sqs_attributes({"TraceParent": {"DataType": "String", "StringValue": TRACEPARENT}}))

    assert format(sc.trace_id, "032x") == TRACE_ID


def test_sqs_without_attributes_yields_no_parent():
    assert not _span_context(context_from_sqs_attributes(None)).is_valid
    assert not _span_context(context_from_sqs_attributes({})).is_valid
    assert not _span_context(context_from_sqs_attributes({"traceparent": {"DataType": "Binary"}})).is_valid


def test_kafka_headers_carry_the_parent():
    headers = [("content-type", b"application/json"), ("traceparent", TRACEPARENT.encode("utf-8"))]

    sc = _span_context(context_from_kafka_headers(headers))

    assert sc.is_valid and sc.is_remote
    assert format(sc.trace_id, "032x") == TRACE_ID
    assert format(sc.span_id, "016x") == SPAN_ID


def test_kafka_headers_accept_str_values_and_ignore_none():
    assert not _span_context(context_from_kafka_headers(None)).is_valid
    assert not _span_context(context_from_kafka_headers([("traceparent", None)])).is_valid
    assert _span_context(context_from_kafka_headers([("Traceparent", TRACEPARENT)])).is_valid


def test_malformed_traceparent_is_ignored():
    sc = _span_context(context_from_kafka_headers([("traceparent", b"not-a-traceparent")]))

    assert not sc.is_valid


def test_current_trace_ids_without_active_span():
    assert current_trace_ids() == (None, None)
