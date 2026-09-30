# shopfront/worker

One Python 3.12 image, two long-running consumers. Both follow [`labs/CONTRACT.md`](../../CONTRACT.md).

| Entrypoint | Reads | Writes | Port |
| --- | --- | --- | --- |
| `python -m worker.fulfillment` | SQS `orders-created` (long polling, `traceparent` message attribute) | `UPDATE orders SET status='FULFILLED' ... WHERE id=$1 AND status='CREATED'` | 8082 |
| `python -m worker.analytics` | Kafka `orders.created` (manual commits, `traceparent` header) | upsert into `daily_stats` | 8083 |

Each process also serves `GET /healthz`, `GET /readyz` (database ping) and `GET /metrics`
(Prometheus text, including process metrics) on `PORT`.

## Layout

```text
worker/config.py       environment parsing; missing required variables -> exit 2
worker/logging.py      JSON lines on stdout with trace_id/span_id from the active span
worker/telemetry.py    OTel SDK when OTEL_EXPORTER_OTLP_ENDPOINT is set; SQS/Kafka context extraction
worker/db.py           psycopg 3 connection pool, start-up retry with backoff (30 s), ping()
worker/metrics.py      sqs_messages_received_total, orders_fulfilled_total, orders_failed_total,
                       kafka_messages_consumed_total, processing_duration_seconds, http_requests_total
worker/health.py       stdlib HTTP server for /healthz, /readyz, /metrics
worker/events.py       strict parser for the order.created event (shared by both consumers)
worker/lifecycle.py    SIGTERM handling, shutdown deadline, exit codes 0/1/2
worker/fulfillment.py  SQS loop: receive -> order.fulfill span -> idempotent UPDATE -> delete
worker/analytics.py    Kafka loop: poll -> kafka.consume span -> daily_stats upsert -> commit
tests/                 pytest, no network
```

## Run the tests

Python 3.12 is required by the pins. Without a local 3.12, use the same base image the Dockerfile
uses:

```bash
docker run --rm -v "$PWD":/src -w /src python:3.12-slim-bookworm \
  sh -c 'pip install -q -r requirements.txt pytest && python -m pytest -q -p no:cacheprovider'
```

## Build and run locally

```bash
docker build -t shopfront/worker:dev .
docker run --rm -p 8082:8082 --read-only --tmpfs /tmp \
  -e DATABASE_URL=postgres://app:app@host.docker.internal:5432/shopfront \
  -e SQS_QUEUE_URL=http://host.docker.internal:9324/000000000000/orders-created \
  -e AWS_ENDPOINT_URL_SQS=http://host.docker.internal:9324 \
  -e AWS_REGION=us-east-1 -e AWS_ACCESS_KEY_ID=x -e AWS_SECRET_ACCESS_KEY=x \
  shopfront/worker:dev
```

The whole system, including this image built from source, runs with `make up` from the repository
root; see [`labs/README.md`](../../README.md).

## Behaviour worth knowing

- Redelivery is normal. The fulfillment UPDATE matches only `status = 'CREATED'`, so a message
  processed twice changes nothing the second time and is still deleted.
- A message that raises (malformed body, database down, `FAIL_EVERY_N` chaos knob) is not
  deleted; SQS makes it visible again after 30 s and moves it to `orders-created-dlq` after the
  third receive.
- The Kafka consumer commits after the database write. A malformed record is skipped (committed)
  so it cannot block the partition; a transient failure seeks back to the same offset and retries
  with backoff.
- `SIGTERM`: stop taking new work, finish the current batch, flush spans, close the pool, exit 0,
  all within `SHUTDOWN_TIMEOUT_SECONDS` (default 20). Keep that value below the platform grace
  period (ECS `stopTimeout` 30, Kubernetes `terminationGracePeriodSeconds` 30).
- `KAFKA_SASL_IAM=true` switches the consumer to SASL_SSL/OAUTHBEARER with tokens from
  `aws-msk-iam-sasl-signer-python` (requires `AWS_REGION`). Off locally.
