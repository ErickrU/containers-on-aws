"""The ``order.created`` event shared by SQS and Kafka (labs/CONTRACT.md §5).

Body (SQS) and value (Kafka) are the same JSON document::

    {"type":"order.created","version":1,"orderId":"<uuid>","productId":1,"quantity":2,
     "priceCents":1999,"createdAt":"2026-09-29T20:00:00Z"}

Parsing is strict. A message that cannot be parsed raises :class:`MalformedMessage`; the SQS
consumer leaves it on the queue so it reaches the dead-letter queue after ``maxReceiveCount``
attempts, and the Kafka consumer logs and skips it (a poison record must not block the partition).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

EVENT_TYPE = "order.created"
EVENT_VERSION = 1


class MalformedMessage(ValueError):
    """The message body is not a valid ``order.created`` event."""


@dataclass(frozen=True)
class OrderCreated:
    order_id: str
    product_id: int
    quantity: int
    price_cents: int
    created_at: datetime  # timezone-aware

    @property
    def revenue_cents(self) -> int:
        return self.price_cents * self.quantity


def parse_event(raw: str | bytes | bytearray | None) -> OrderCreated:
    if raw is None:
        raise MalformedMessage("empty message body")
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = bytes(raw).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MalformedMessage(f"body is not UTF-8: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MalformedMessage(f"body is not JSON: {exc.msg} at position {exc.pos}") from exc
    if not isinstance(data, dict):
        raise MalformedMessage("body is not a JSON object")
    if data.get("type") != EVENT_TYPE:
        raise MalformedMessage(f"unexpected event type {data.get('type')!r}")
    if data.get("version") != EVENT_VERSION:
        raise MalformedMessage(f"unsupported event version {data.get('version')!r}")

    try:
        order_id = str(uuid.UUID(str(data["orderId"])))
        product_id = int(data["productId"])
        quantity = int(data["quantity"])
        price_cents = int(data["priceCents"])
        created_at = datetime.fromisoformat(str(data["createdAt"]))
    except KeyError as exc:
        raise MalformedMessage(f"missing field {exc.args[0]!r}") from exc
    except (TypeError, ValueError) as exc:
        raise MalformedMessage(f"invalid field value: {exc}") from exc

    if quantity <= 0:
        raise MalformedMessage(f"quantity must be positive, got {quantity}")
    if price_cents < 0:
        raise MalformedMessage(f"priceCents must not be negative, got {price_cents}")
    if created_at.tzinfo is None:  # a naive timestamp is treated as UTC, the contract's timezone
        created_at = created_at.replace(tzinfo=timezone.utc)

    return OrderCreated(
        order_id=order_id,
        product_id=product_id,
        quantity=quantity,
        price_cents=price_cents,
        created_at=created_at,
    )
