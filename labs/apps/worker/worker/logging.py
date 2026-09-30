"""JSON logging to stdout, one object per line (labs/CONTRACT.md §6).

Fields: ``time``, ``level``, ``msg``, ``service``, ``trace_id``, ``span_id`` (when a trace is
active), plus any extra fields passed through ``logger.info("...", extra={...})``.
Never log secrets or full message bodies.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from opentelemetry import trace

# Attributes every LogRecord carries; anything else in record.__dict__ is a user-supplied field.
_STANDARD_ATTRS = frozenset(
    {
        "name", "msg", "args", "levelname", "levelno", "pathname", "filename", "module",
        "exc_info", "exc_text", "stack_info", "lineno", "funcName", "created", "msecs",
        "relativeCreated", "thread", "threadName", "processName", "process", "taskName", "message",
    }
)

_LEVEL_NAMES = {"debug": logging.DEBUG, "info": logging.INFO, "warn": logging.WARNING, "error": logging.ERROR}
# Same vocabulary as LOG_LEVEL so every shopfront service (Go, Node, Python) emits identical labels.
_LEVEL_LABELS = {
    logging.DEBUG: "debug",
    logging.INFO: "info",
    logging.WARNING: "warn",
    logging.ERROR: "error",
    logging.CRITICAL: "error",
}


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self._service = service

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, tz=timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": _LEVEL_LABELS.get(record.levelno, record.levelname.lower()),
            "msg": record.getMessage(),
            "service": self._service,
        }
        span_context = trace.get_current_span().get_span_context()
        if span_context.is_valid:
            entry["trace_id"] = format(span_context.trace_id, "032x")
            entry["span_id"] = format(span_context.span_id, "016x")
        entry["logger"] = record.name
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                entry[key] = value
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str, ensure_ascii=False)


def configure_logging(level: str, service: str) -> None:
    """Route every logger (ours and the libraries') through the JSON formatter on stdout."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service))
    root.addHandler(handler)
    numeric = _LEVEL_NAMES.get(level, logging.INFO)
    root.setLevel(numeric)
    # These libraries are extremely chatty at DEBUG; keep them at INFO or above.
    for name in ("botocore", "boto3", "urllib3", "s3transfer"):
        logging.getLogger(name).setLevel(max(numeric, logging.INFO))
