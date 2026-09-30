# shopfront/report-job

A Python 3.12 batch job that runs to completion: it aggregates one UTC day of FULFILLED orders from
PostgreSQL, writes `daily-<date>.json` and `daily-<date>.csv`, prints one JSON summary line and
exits. The same image runs as a Compose one-shot (`make report`), an ECS scheduled task, an AWS
Batch job ([`labs/batch/`](../../batch/)) or a Kubernetes CronJob ([`labs/eks/`](../../eks/)).
Contract: [`labs/CONTRACT.md`](../../CONTRACT.md) §5.

## Configuration

| Variable | Required | Meaning |
| --- | --- | --- |
| `DATABASE_URL` | yes | `postgres://app:app@postgres:5432/shopfront` |
| `REPORT_OUTPUT` | yes | `file:///out` (directory) or `s3://bucket/prefix/` |
| `REPORT_DATE` | no | `YYYY-MM-DD`; default is the previous UTC day |
| `AWS_REGION` | for `s3://` | Region for the S3 client |
| `AWS_ENDPOINT_URL_S3` | no | LocalStack or another emulator; switches to path-style addressing |

Exit codes: `0` written, `1` runtime error (database or storage), `2` configuration error.

## Output

`daily-2026-09-29.json`:

```json
{
  "date": "2026-09-29",
  "window": {"from": "2026-09-29T00:00:00Z", "to": "2026-09-30T00:00:00Z"},
  "generated_at": "2026-09-30T01:00:00Z",
  "status": "FULFILLED",
  "orders_count": 3,
  "revenue_cents": 13996,
  "products": [{"product_id": 2, "sku": "SKU-2", "name": "Desk lamp", "orders": 2, "units": 2, "revenue_cents": 9998}]
}
```

`daily-2026-09-29.csv` has one row per product: `product_id,sku,name,orders,units,revenue_cents`.

## Run

```bash
# tests (no network); the pins need Python 3.12, so use the base image when you have none locally
docker run --rm -v "$PWD":/src -w /src python:3.12-slim-bookworm \
  sh -c 'pip install -q -r requirements.txt pytest && python -m pytest -q -p no:cacheprovider'

# build and run against the local stack (from the repository root: make report)
docker build -t shopfront/report-job:dev .
docker run --rm --read-only --tmpfs /tmp -v "$PWD/out":/out \
  -e DATABASE_URL=postgres://app:app@host.docker.internal:5432/shopfront \
  -e REPORT_OUTPUT=file:///out -e REPORT_DATE=2026-09-29 shopfront/report-job:dev
```
