# shopfront/catalog

The products API: Go 1.23, standard library `net/http`, PostgreSQL through pgx, Valkey cache-aside
through go-redis, Prometheus metrics, OpenTelemetry traces. It follows
[`labs/CONTRACT.md`](../../CONTRACT.md); port 8081.

| Endpoint | Behaviour |
| --- | --- |
| `GET /products` | all products from PostgreSQL, never cached |
| `GET /products/{id}` | Valkey `product:{id}` first (TTL `CACHE_TTL_SECONDS`), else PostgreSQL; header `X-Cache: HIT`, `MISS` or `BYPASS`; `404 {"error":"not found"}`; `400` for a non-numeric id |
| `GET /healthz` | liveness, always `200 {"status":"ok"}` while the process runs |
| `GET /readyz` | readiness: database ping, plus Valkey ping when configured; `503` names the failing check |
| `GET /metrics` | Prometheus text: `http_requests_total`, `http_request_duration_seconds`, `catalog_cache_hits_total`, `catalog_cache_misses_total`, Go and process metrics |

## Configuration

| Variable | Required | Default | Notes |
| --- | --- | --- | --- |
| `DATABASE_URL` | yes | | `postgres://app:app@postgres:5432/shopfront`; missing means exit code 2 |
| `PORT` | no | `8081` | |
| `VALKEY_URL` | no | | `redis://valkey:6379`; unset means no cache and `X-Cache: BYPASS` |
| `CACHE_TTL_SECONDS` | no | `60` | |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | no | | `http://otel-collector:4318`; unset means tracing off, the app still runs |
| `OTEL_SERVICE_NAME` | no | `catalog` | also used as the `service` field of every log line |
| `OTEL_RESOURCE_ATTRIBUTES` | no | | for example `deployment.environment=dev` |
| `LOG_LEVEL` | no | `info` | `debug`, `info`, `warn`, `error` |
| `SHUTDOWN_TIMEOUT_SECONDS` | no | `20` | keep below ECS `stopTimeout` and Kubernetes `terminationGracePeriodSeconds` (30) |

## Layout

```text
main.go                       lifecycle: config -> database with backoff -> HTTP -> SIGTERM drain
internal/config/config.go     environment parsing, redacted URLs for logs, exit code 2 on errors
internal/store/postgres.go    Store interface, pgx pool, start-up retry (30 s), query spans
internal/cache/valkey.go      Cache interface, go-redis client, Disabled no-op when VALKEY_URL is unset
internal/httpapi/server.go    router (method + pattern), otelhttp, metrics and request-log middleware
internal/httpapi/handlers.go  /healthz, /readyz, /products, /products/{id} cache-aside
internal/telemetry/otel.go    tracer provider and OTLP/HTTP exporter, only when the endpoint is set
internal/telemetry/metrics.go Prometheus registry and counters
internal/telemetry/logging.go slog JSON handler with trace_id/span_id from the active span
internal/httpapi/server_test.go  in-memory fakes for Store and Cache, no network
```

## Run the tests

Go is not required on the host; the same image the Dockerfile uses runs them:

```bash
docker run --rm -v "$PWD":/src -w /src -e GOFLAGS=-mod=mod -e GOCACHE=/tmp/gocache \
  golang:1.23-bookworm sh -c 'go vet ./... && go test ./...'
```

## Build and run locally

```bash
docker build -t shopfront/catalog:dev .
docker run --rm -p 8081:8081 --read-only --tmpfs /tmp --cap-drop ALL \
  -e DATABASE_URL=postgres://app:app@host.docker.internal:5432/shopfront \
  -e VALKEY_URL=redis://host.docker.internal:6379 \
  shopfront/catalog:dev
```

Multi-arch, as CI does it (`latest` is never pushed, see the contract §8):

```bash
docker buildx build --platform linux/amd64,linux/arm64 \
  --build-arg VERSION=sha-$(git rev-parse --short HEAD) --build-arg REVISION=$(git rev-parse HEAD) \
  -t <registry>/shopfront/catalog:sha-$(git rev-parse --short HEAD) --push .
```

The whole system, including this image built from source, runs with `make up` from the repository
root; see [`labs/README.md`](../../README.md).

## What to look at

- `curl -i localhost:8081/products/1` twice: `X-Cache: MISS` then `HIT`. Stop Valkey and the header
  turns into `BYPASS` while the response stays `200`; `/readyz` reports `cache` as failing.
- The final image is `gcr.io/distroless/static-debian12:nonroot` plus one static binary: no shell,
  no libc, no package manager. `docker run --rm shopfront/catalog:dev` without `DATABASE_URL` exits
  with code 2 and a one-line message on stderr.
- Every log line is one JSON object with `time`, `level`, `msg`, `service` and, inside a request,
  `trace_id` and `span_id`. Probes and scrapes are logged at `debug` so `info` stays readable.
- The server span is renamed after routing to the pattern (`GET /products/{id}`), which is also the
  `route` label of the metrics: bounded cardinality no matter how many product ids exist.
- `SIGTERM` (`docker stop`): `http.Server.Shutdown` drains in-flight requests, traces are flushed,
  the pool closes, exit code 0.
