# shopfront/orders

The orders API: Node.js 22, TypeScript, Fastify 5, PostgreSQL through `pg`, SQS through the AWS SDK
v3, Kafka through kafkajs, Prometheus metrics, OpenTelemetry traces. It follows
[`labs/CONTRACT.md`](../../CONTRACT.md); port 8080.

| Endpoint | Behaviour |
| --- | --- |
| `POST /orders` `{"productId": 1, "quantity": 2}` | validates (400), asks catalog (404 unknown product, 409 `quantity > stock`, 502 catalog unavailable), inserts the order with status `CREATED`, sends the SQS message, produces the Kafka event, answers `201 {id, productId, quantity, priceCents, status, createdAt}` |
| `GET /orders/{id}` | the order or `404 {"error":"not found"}` |
| `GET /orders?status=CREATED` | last 50 orders, optional status filter |
| `GET /healthz` | liveness, always `200 {"status":"ok"}` while the process runs |
| `GET /readyz` | readiness: database ping; `503 {"status":"not-ready","checks":{"database":"error: ..."}}` |
| `GET /metrics` | Prometheus text: `http_requests_total`, `http_request_duration_seconds`, `orders_created_total`, `orders_failed_total`, process metrics |

## Configuration

| Variable | Required | Default | Notes |
| --- | --- | --- | --- |
| `DATABASE_URL` | yes | | `postgres://app:app@postgres:5432/shopfront` |
| `CATALOG_URL` | yes | | `http://catalog:8081`; 2 s timeout, one retry on 5xx or timeout |
| `SQS_QUEUE_URL` | yes | | `http://elasticmq:9324/000000000000/orders-created` |
| `AWS_REGION` | yes | | `us-east-1` |
| `AWS_ENDPOINT_URL_SQS` | no | | local only: `http://elasticmq:9324` |
| `PORT` | no | `8080` | |
| `KAFKA_BROKERS` | no | | comma-separated; unset means the Kafka event is skipped |
| `KAFKA_TOPIC` | no | `orders.created` | |
| `KAFKA_SASL_IAM` | no | `false` | `true` is rejected at start (not implemented in this service yet) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | no | | `http://otel-collector:4318`; unset means tracing off, the app still runs |
| `OTEL_SERVICE_NAME` | no | `orders` | also the `service` field of every log line |
| `OTEL_RESOURCE_ATTRIBUTES` | no | | for example `deployment.environment=dev` |
| `LOG_LEVEL` | no | `info` | `debug`, `info`, `warn`, `error` |
| `SHUTDOWN_TIMEOUT_SECONDS` | no | `20` | keep below ECS `stopTimeout` and Kubernetes `terminationGracePeriodSeconds` (30) |

A missing required variable prints `configuration error: ...` on stderr and exits with code 2.

## Layout

```text
src/index.ts           imports telemetry first, then loads the app through a dynamic import
src/telemetry.ts       NodeSDK + auto-instrumentations, only when OTEL_EXPORTER_OTLP_ENDPOINT is set
src/main.ts            bootstrap: config -> logger -> deps -> database with backoff (30 s) -> listen
src/config.ts          environment parsing; ConfigError -> exit code 2
src/logger.ts          pino JSON with service, trace_id and span_id from the active span
src/db.ts              pg Pool, parameterized SQL matching labs/local/schema.sql, start-up retry
src/catalog-client.ts  fetch with AbortSignal.timeout(2000) and one retry
src/publishers.ts      SQS SendMessage (traceparent message attribute), Kafka producer (traceparent header)
src/routes.ts          POST /orders, GET /orders/:id, GET /orders?status=
src/health.ts          /healthz, /readyz, /metrics
src/metrics.ts         prom-client registry and counters
src/app.ts             buildApp(deps): Fastify instance with hooks and error handling, fakes in tests
src/shutdown.ts        SIGTERM/SIGINT: app.close -> publishers.close -> db.end -> flush traces -> exit 0
test/app.test.ts       node:test through tsx, fakes for database, catalog, SQS and Kafka, no network
```

## Develop

```bash
npm install        # Node 22 or newer
npm run build      # tsc -> dist/
npm test           # node --test with tsx
npm run typecheck  # sources and tests
```

## Build and run locally

```bash
docker build -t shopfront/orders:dev .
docker run --rm -p 8080:8080 --read-only --tmpfs /tmp --cap-drop ALL \
  -e DATABASE_URL=postgres://app:app@host.docker.internal:5432/shopfront \
  -e CATALOG_URL=http://host.docker.internal:8081 \
  -e SQS_QUEUE_URL=http://host.docker.internal:9324/000000000000/orders-created \
  -e AWS_ENDPOINT_URL_SQS=http://host.docker.internal:9324 \
  -e AWS_REGION=us-east-1 -e AWS_ACCESS_KEY_ID=x -e AWS_SECRET_ACCESS_KEY=x \
  shopfront/orders:dev
```

Multi-arch, as CI does it (`latest` is never pushed, see the contract §8):

```bash
docker buildx build --platform linux/amd64,linux/arm64 \
  --build-arg VERSION=sha-$(git rev-parse --short HEAD) --build-arg REVISION=$(git rev-parse HEAD) \
  -t <registry>/shopfront/orders:sha-$(git rev-parse --short HEAD) --push .
```

The whole system, including this image built from source, runs with `make up` from the repository
root; see [`labs/README.md`](../../README.md).

## Behaviour worth knowing

- Order of operations in `POST /orders`: insert first, then SQS, then Kafka. If SQS fails the
  response is `500` with the order id: the row exists with status `CREATED` and nothing will fulfil
  it until an operator requeues it. A Kafka failure is logged and the response is still `201`;
  analytics is best effort, fulfillment is not.
- At start-up the Kafka producer connects in the background and creates the topic (3 partitions,
  broker-default replication) when it does not exist yet; readiness never waits for Kafka. Without
  permission to create topics the produce path still works through broker auto-creation.
- Trace context is injected explicitly into the SQS message attributes and Kafka headers from the
  active span (`propagation.inject`); the consumers in `apps/worker` extract it, so one trace spans
  `orders -> catalog -> SQS -> fulfillment-worker` and `orders -> Kafka -> analytics-consumer`.
- ESM and auto-instrumentation: `index.ts` imports `telemetry.ts` first and loads the rest of the
  application with a dynamic import. The instrumentations patch modules while they load, so the
  loader hook has to be registered before `fastify`, `pg`, `undici`, `@aws-sdk` and `kafkajs`.
- `SIGTERM` (`docker stop`): the server stops accepting connections, in-flight requests finish, the
  Kafka producer disconnects, the pool closes, spans are flushed, exit code 0; a hard exit 1 after
  `SHUTDOWN_TIMEOUT_SECONDS` guarantees the platform's grace period is never the one that kills it.
- The `route` label of the metrics is the route pattern (`/orders/:id`), never the raw path, so the
  cardinality stays bounded.
