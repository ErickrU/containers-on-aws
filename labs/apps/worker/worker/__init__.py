"""shopfront background workers.

Two entrypoints share this package and one container image:

- ``python -m worker.fulfillment``: consumes ``order.created`` messages from SQS and marks orders
  FULFILLED in PostgreSQL (idempotent, at-least-once).
- ``python -m worker.analytics``: consumes the same events from Kafka and maintains the
  ``daily_stats`` table.

Everything is configured through environment variables; see ``labs/CONTRACT.md`` §2.
"""

__version__ = "0.1.0"
