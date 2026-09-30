from __future__ import annotations

import json
import logging
import sys

from worker.logging import JsonFormatter


def _record(**extra) -> logging.LogRecord:
    record = logging.LogRecord("worker.test", logging.INFO, __file__, 1, "order %s", ("fulfilled",), None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_formatter_emits_the_contract_fields():
    line = JsonFormatter("fulfillment-worker").format(_record(order_id="abc", quantity=2))
    entry = json.loads(line)

    assert entry["level"] == "info"
    assert entry["msg"] == "order fulfilled"
    assert entry["service"] == "fulfillment-worker"
    assert entry["time"].endswith("Z")
    assert entry["order_id"] == "abc" and entry["quantity"] == 2
    assert "trace_id" not in entry  # no active span in this test
    assert "\n" not in line  # one object per line


def test_formatter_includes_exceptions():
    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.LogRecord("worker.test", logging.ERROR, __file__, 1, "failed", (), sys.exc_info())

    entry = json.loads(JsonFormatter("svc").format(record))

    assert entry["level"] == "error"
    assert "ValueError: boom" in entry["exception"]
