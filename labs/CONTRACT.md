# shopfront — service contract

`shopfront` is the one system every lab, playbook and hub document refers to. It is deliberately
small (five processes, one database, one cache, one queue, one topic, one object store) but it
touches every integration the repository teaches: HTTP between services, a relational database, a
cache, at-least-once queue processing, a Kafka stream, a batch job, and OpenTelemetry end to end.

This file is the contract. Code, task definitions, manifests and docs must agree with it.

## 1. Topology

```mermaid
flowchart LR
  client((client)) -->|HTTP :8080| orders
  orders -->|HTTP :8081 GET /products/:id| catalog
  orders -->|INSERT| pg[(PostgreSQL)]
  orders -->|SendMessage| sqs[[SQS orders-created]]
  orders -->|produce| kafka[[Kafka orders.created]]
  catalog -->|SELECT| pg
  catalog -->|GET/SET product:id| valkey[(Valkey)]
  fulfillment[fulfillment-worker] -->|ReceiveMessage| sqs
  fulfillment -->|UPDATE status| pg
  analytics[analytics-consumer] -->|consume| kafka
  analytics -->|UPSERT daily_stats| pg
  report[report-job] -->|SELECT| pg
  report -->|PutObject| s3[(S3 or local file)]
  orders & catalog & fulfillment & analytics & report -.->|OTLP| otel[OTel collector]
```

| Service | Language / runtime | Kind | Port | Image |
| --- | --- | --- | --- | --- |
| `catalog` | Go 1.23, distroless static | HTTP API | 8081 | `shopfront/catalog` |
| `orders` | Node.js 22 LTS, TypeScript, Fastify | HTTP API | 8080 | `shopfront/orders` |
| `fulfillment-worker` | Python 3.12 (`worker` package, `python -m worker.fulfillment`) | SQS consumer + tiny HTTP for health/metrics | 8082 | `shopfront/worker` |
| `analytics-consumer` | Python 3.12 (`python -m worker.analytics`) | Kafka consumer + tiny HTTP for health/metrics | 8083 | `shopfront/worker` |
| `report-job` | Python 3.12 | run-to-completion job | none | `shopfront/report-job` |

## 2. Environment variables (twelve-factor)

All services read configuration from the environment only. Unknown variables are ignored; missing
required variables make the process exit non-zero at start with a clear message.

| Variable | Services | Required | Example | Notes |
| --- | --- | --- | --- | --- |
| `PORT` | orders, catalog, workers | no | `8080` | defaults per table above |
| `DATABASE_URL` | all | yes | `postgres://app:app@postgres:5432/shopfront` | `sslmode=require` outside local |
| `DATABASE_URL_FILE` | report | no | `/secrets/DATABASE_URL` | alternative to `DATABASE_URL` for platforms that mount secrets as files (Batch on EKS) |
| `VALKEY_URL` | catalog | no | `redis://valkey:6379` | when unset, catalog runs without cache |
| `CATALOG_URL` | orders | yes | `http://catalog:8081` | |
| `SQS_QUEUE_URL` | orders, fulfillment | yes | `http://elasticmq:9324/000000000000/orders-created` | |
| `AWS_REGION` | orders, fulfillment, report | yes | `us-east-1` | |
| `AWS_ENDPOINT_URL_SQS` | orders, fulfillment | no | `http://elasticmq:9324` | local only; standard SDK variable |
| `AWS_ENDPOINT_URL_S3` | report | no | `http://localstack:4566` | local only, when S3 output is used |
| `KAFKA_BROKERS` | orders, analytics | no (orders) / yes (analytics) | `kafka:9092` | comma-separated; orders skips Kafka when unset |
| `KAFKA_TOPIC` | orders, analytics | no | `orders.created` | default `orders.created` |
| `KAFKA_GROUP_ID` | analytics | no | `analytics` | |
| `KAFKA_SASL_IAM` | orders, analytics | no | `true` | MSK IAM auth; off locally |
| `REPORT_OUTPUT` | report | yes | `file:///out` or `s3://shopfront-reports-123456789012/daily/` | |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | all | no | `http://otel-collector:4318` | when unset, tracing is disabled, app still runs |
| `OTEL_SERVICE_NAME` | all | no | `orders` | defaults to the service name |
| `OTEL_RESOURCE_ATTRIBUTES` | all | no | `deployment.environment=dev` | |
| `LOG_LEVEL` | all | no | `info` | `debug`/`info`/`warn`/`error` |
| `SHUTDOWN_TIMEOUT_SECONDS` | all long-running | no | `20` | must be below ECS `stopTimeout` / K8s `terminationGracePeriodSeconds` |
| `CACHE_TTL_SECONDS` | catalog | no | `60` | |
| `SQS_WAIT_TIME_SECONDS` | fulfillment | no | `20` | long polling |
| `SQS_MAX_MESSAGES` | fulfillment | no | `10` | |
| `FAIL_EVERY_N` | fulfillment | no | `0` | chaos knob: raise on every Nth message to exercise the DLQ |

Secrets (database password, Kafka credentials) arrive through the same variables; on AWS they are
injected from Secrets Manager / SSM by ECS `secrets[]` or by the Secrets Store CSI driver /
External Secrets, never baked into images or plain task definitions.

## 3. HTTP endpoints

Common to every HTTP process:

| Path | Purpose | Success | Failure |
| --- | --- | --- | --- |
| `GET /healthz` | liveness: the process is alive and its event loop responds | `200 {"status":"ok"}` | process should be restarted |
| `GET /readyz` | readiness: dependencies reachable (DB ping; catalog also pings Valkey when configured) | `200 {"status":"ready","checks":{...}}` | `503` with the failing check named; remove from load balancing, do not restart |
| `GET /metrics` | Prometheus text format | `200` | |

Business endpoints:

`catalog` (port 8081)

| Method + path | Behaviour |
| --- | --- |
| `GET /products` | list products (`id, sku, name, price_cents, stock`), from Postgres, no cache |
| `GET /products/{id}` | cache-aside: Valkey `product:{id}` (TTL `CACHE_TTL_SECONDS`), else Postgres; `404` when missing; response header `X-Cache: HIT|MISS|BYPASS` |

`orders` (port 8080)

| Method + path | Behaviour |
| --- | --- |
| `POST /orders` body `{"productId": 1, "quantity": 2}` | validates body; `GET {CATALOG_URL}/products/{id}` (timeout 2 s, one retry on 5xx/timeout); `404` if product missing; `409` if `quantity > stock`; inserts order with status `CREATED`; sends SQS message; produces Kafka event when configured (failure to produce is logged, not fatal); returns `201 {"id": "<uuid>", "status": "CREATED", ...}` |
| `GET /orders/{id}` | returns the order or `404` |
| `GET /orders?status=CREATED` | last 50 orders, optional status filter |

## 4. Data

PostgreSQL 16, database `shopfront`, user `app`. Schema in `labs/local/schema.sql`, seed in
`labs/local/seed.sql` (12 products).

```sql
CREATE TABLE IF NOT EXISTS products (
  id           BIGSERIAL PRIMARY KEY,
  sku          TEXT NOT NULL UNIQUE,
  name         TEXT NOT NULL,
  price_cents  INTEGER NOT NULL CHECK (price_cents >= 0),
  stock        INTEGER NOT NULL CHECK (stock >= 0)
);

CREATE TABLE IF NOT EXISTS orders (
  id           UUID PRIMARY KEY,
  product_id   BIGINT NOT NULL REFERENCES products(id),
  quantity     INTEGER NOT NULL CHECK (quantity > 0),
  price_cents  INTEGER NOT NULL,
  status       TEXT NOT NULL CHECK (status IN ('CREATED','FULFILLED','FAILED')),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS orders_status_created_idx ON orders (status, created_at DESC);

CREATE TABLE IF NOT EXISTS daily_stats (
  day            DATE PRIMARY KEY,
  orders_count   BIGINT NOT NULL DEFAULT 0,
  revenue_cents  BIGINT NOT NULL DEFAULT 0
);
```

Valkey keys: `product:{id}` → JSON of the product, TTL `CACHE_TTL_SECONDS`.

## 5. Messages and events

SQS queue `orders-created` with dead-letter queue `orders-created-dlq` (`maxReceiveCount: 3`),
visibility timeout 30 s, long polling 20 s. Message body:

```json
{"type":"order.created","version":1,"orderId":"<uuid>","productId":1,"quantity":2,"priceCents":1999,"createdAt":"2026-09-29T20:00:00Z"}
```

Message attributes: `traceparent` (String, W3C trace context) so the consumer continues the trace.

Kafka topic `orders.created` (3 partitions locally), key = `orderId`, value = the same JSON as the
SQS body, header `traceparent`.

`fulfillment-worker` processing is idempotent: `UPDATE orders SET status='FULFILLED',
updated_at=now() WHERE id=$1 AND status='CREATED'`; zero rows affected means "already processed",
still delete the message. Processing failures are raised so the message returns to the queue and
eventually the DLQ.

`analytics-consumer` upserts `daily_stats` for `date(createdAt)` (`orders_count += 1`,
`revenue_cents += priceCents * quantity`) and commits offsets after the write.

`report-job` reads `orders` for the previous UTC day (or `REPORT_DATE=YYYY-MM-DD`), writes
`daily-<date>.json` and `daily-<date>.csv` to `REPORT_OUTPUT`, prints a one-line summary, exits 0.
Exit code 2 on configuration error, 1 on runtime error.

## 6. Telemetry

- Traces: OpenTelemetry SDK per language, OTLP over HTTP (`:4318`) to the collector named by
  `OTEL_EXPORTER_OTLP_ENDPOINT`. Propagation: W3C `traceparent` over HTTP headers, SQS message
  attributes and Kafka headers. Span names: `POST /orders`, `GET /products/{id}`, `sqs.receive`,
  `order.fulfill`, `kafka.consume`.
- Metrics: Prometheus text on `/metrics` with at least `http_requests_total{method,route,status}`,
  `http_request_duration_seconds` histogram, `orders_created_total`, `orders_fulfilled_total`,
  `orders_failed_total`, `catalog_cache_hits_total`, `catalog_cache_misses_total`,
  `sqs_messages_received_total`, `kafka_messages_consumed_total`, plus process metrics.
- Logs: one JSON object per line on stdout: `time`, `level`, `msg`, `service`, `trace_id`,
  `span_id`, plus fields. Never log secrets or full request bodies.

## 7. Lifecycle

- Start: validate config → connect DB (retry with backoff up to 30 s) → start HTTP → mark ready.
- SIGTERM: stop accepting new work (HTTP server close / stop polling), finish in-flight requests
  or the current message batch, flush telemetry, close pools, exit 0 — all within
  `SHUTDOWN_TIMEOUT_SECONDS` (default 20). Platform settings: ECS `stopTimeout: 30`, Kubernetes
  `terminationGracePeriodSeconds: 30`, ALB deregistration delay 20 s, `preStop` sleep 5 s on EKS.
- Exit codes: `0` clean, `1` runtime error, `2` configuration error.

## 8. Images

- Multi-stage; final stage non-root `10001:10001`; `WORKDIR /app`; read-only root filesystem
  compatible (`/tmp` may be a writable `emptyDir`/ephemeral mount).
- Base images pinned by tag (and digest comment): `golang:1.23-bookworm` →
  `gcr.io/distroless/static-debian12:nonroot`; `node:22-bookworm-slim`; `python:3.12-slim-bookworm`.
- Labels: `org.opencontainers.image.source`, `org.opencontainers.image.version`,
  `org.opencontainers.image.revision`.
- Multi-arch build: `docker buildx build --platform linux/amd64,linux/arm64`.
- Tag policy: CI pushes `sha-<gitsha>` and deploys by digest; `latest` is never deployed.

## 9. Local compose service names

`postgres`, `valkey`, `kafka`, `elasticmq`, `otel-collector`, `jaeger`, `catalog`, `orders`,
`fulfillment-worker`, `analytics-consumer`, `db-migrate` (one-shot), `report-job` (profile
`jobs`). Host ports: orders 8080, catalog 8081, fulfillment 8082, analytics 8083, Jaeger UI 16686,
Postgres 5432, Valkey 6379, Kafka 9092, ElasticMQ 9324.

## 10. Smoke test (`labs/local/smoke.sh`)

1. Wait until `orders` and `catalog` return `200` on `/readyz`.
2. `GET /products/1` twice → second response has `X-Cache: HIT`.
3. `POST /orders` → `201`; capture `id`.
4. Poll `GET /orders/{id}` until `status == FULFILLED` (max 30 s).
5. `GET /metrics` on orders contains `orders_created_total`.
6. Query Postgres `daily_stats` has a row for today (Kafka path) — skipped when Kafka is off.
7. Print the Jaeger URL for the trace.
