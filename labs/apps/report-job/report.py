#!/usr/bin/env python3
"""shopfront report-job: a run-to-completion batch job (labs/CONTRACT.md §5).

Reads the FULFILLED orders of one UTC day (``REPORT_DATE=YYYY-MM-DD``, default: the previous UTC
day), writes ``daily-<date>.json`` and ``daily-<date>.csv`` to ``REPORT_OUTPUT`` and prints one
JSON summary line.

REPORT_OUTPUT:
  file:///out                       a directory (bind mount locally, emptyDir/volume on a cluster)
  s3://bucket/prefix/               S3 PutObject; AWS_ENDPOINT_URL_S3 points at LocalStack locally

Exit codes: 0 report written, 1 runtime error (database, storage), 2 configuration error.
"""

from __future__ import annotations

import csv
import io
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping
from urllib.parse import unquote, urlsplit

EXIT_OK = 0
EXIT_RUNTIME_ERROR = 1
EXIT_CONFIG_ERROR = 2

SERVICE = "report-job"

SQL_TOTALS = (
    "SELECT count(*), coalesce(sum(price_cents * quantity), 0) "
    "FROM orders WHERE status = 'FULFILLED' AND created_at >= %s AND created_at < %s"
)
SQL_BY_PRODUCT = (
    "SELECT p.id, p.sku, p.name, count(o.id), coalesce(sum(o.quantity), 0), "
    "coalesce(sum(o.price_cents * o.quantity), 0) "
    "FROM orders o JOIN products p ON p.id = o.product_id "
    "WHERE o.status = 'FULFILLED' AND o.created_at >= %s AND o.created_at < %s "
    "GROUP BY p.id, p.sku, p.name ORDER BY 6 DESC, p.id"
)
CSV_COLUMNS = ("product_id", "sku", "name", "orders", "units", "revenue_cents")


class ConfigError(Exception):
    """Missing or invalid configuration; exit code 2."""


def log(level: str, msg: str, **fields: Any) -> None:
    """One JSON object per line on stdout, same shape as the long-running services."""
    entry = {
        "time": datetime.now(tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "level": level,
        "msg": msg,
        "service": SERVICE,
    }
    entry.update(fields)
    print(json.dumps(entry, default=str), flush=True)


# ---- configuration -------------------------------------------------------------------------


@dataclass(frozen=True)
class Config:
    database_url: str
    output: str
    report_date: date
    aws_region: str | None


def previous_utc_day(now: datetime | None = None) -> date:
    now = now or datetime.now(tz=timezone.utc)
    return (now.astimezone(timezone.utc) - timedelta(days=1)).date()


def parse_report_date(raw: str | None, now: datetime | None = None) -> date:
    raw = (raw or "").strip()
    if not raw:
        return previous_utc_day(now)
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ConfigError(f"REPORT_DATE={raw!r} is not a YYYY-MM-DD date") from exc


def read_database_url(env: Mapping[str, str]) -> str:
    """DATABASE_URL from the environment, or from the file named by DATABASE_URL_FILE.

    Platforms that mount secrets as files (Kubernetes Secret volumes, AWS Batch on EKS, which has no
    ``secrets[]`` equivalent) set DATABASE_URL_FILE=/secrets/DATABASE_URL instead of the variable.
    """
    direct = env.get("DATABASE_URL", "").strip()
    if direct:
        return direct
    path = env.get("DATABASE_URL_FILE", "").strip()
    if not path:
        return ""
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError as exc:
        raise ConfigError(f"DATABASE_URL_FILE={path!r} cannot be read: {exc.strerror}") from exc
def load_config(env: Mapping[str, str] | None = None) -> Config:
    env = os.environ if env is None else env
    database_url = read_database_url(env)
    missing = [name for name in ("REPORT_OUTPUT",) if not env.get(name, "").strip()]
    if not database_url:
        missing.insert(0, "DATABASE_URL")
    if missing:
        raise ConfigError("missing required environment variables: " + ", ".join(missing))
    output = env["REPORT_OUTPUT"].strip()
    parse_output(output)  # validate early: a bad destination is a configuration error, not a runtime one
    region = env.get("AWS_REGION", "").strip() or None
    if output.startswith("s3://") and not region:
        raise ConfigError("AWS_REGION is required when REPORT_OUTPUT is an s3:// URL")
    return Config(
        database_url=database_url,
        output=output,
        report_date=parse_report_date(env.get("REPORT_DATE")),
        aws_region=region,
    )


def parse_output(url: str) -> tuple[str, str, str]:
    """Return ``("file", directory, "")`` or ``("s3", bucket, prefix)``; raise ConfigError otherwise."""
    parts = urlsplit(url)
    if parts.scheme == "file":
        if parts.netloc not in ("", "localhost"):
            raise ConfigError(f"REPORT_OUTPUT={url!r}: file URLs must look like file:///path")
        directory = unquote(parts.path)
        if not directory:
            raise ConfigError(f"REPORT_OUTPUT={url!r}: file URL has no path")
        return "file", directory, ""
    if parts.scheme == "s3":
        if not parts.netloc:
            raise ConfigError(f"REPORT_OUTPUT={url!r}: s3 URL has no bucket")
        prefix = parts.path.lstrip("/")
        if prefix and not prefix.endswith("/"):
            prefix += "/"
        return "s3", parts.netloc, prefix
    raise ConfigError(f"REPORT_OUTPUT={url!r}: expected file:///dir or s3://bucket/prefix/")


# ---- report --------------------------------------------------------------------------------


def window_for(day: date) -> tuple[datetime, datetime]:
    """Half-open UTC interval ``[day 00:00, next day 00:00)``."""
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def build_report(conn, day: date, generated_at: datetime | None = None) -> dict[str, Any]:
    start, end = window_for(day)
    orders_count, revenue_cents = conn.execute(SQL_TOTALS, (start, end)).fetchone()
    products = [
        {
            "product_id": int(product_id),
            "sku": sku,
            "name": name,
            "orders": int(orders),
            "units": int(units),
            "revenue_cents": int(revenue),
        }
        for product_id, sku, name, orders, units, revenue in conn.execute(SQL_BY_PRODUCT, (start, end)).fetchall()
    ]
    generated_at = generated_at or datetime.now(tz=timezone.utc)
    return {
        "date": day.isoformat(),
        "window": {"from": start.isoformat().replace("+00:00", "Z"), "to": end.isoformat().replace("+00:00", "Z")},
        "generated_at": generated_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "status": "FULFILLED",
        "orders_count": int(orders_count),
        "revenue_cents": int(revenue_cents),
        "products": products,
    }


def render_json(report: Mapping[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=False) + "\n"


def render_csv(report: Mapping[str, Any]) -> str:
    """Per-product rows. RFC 4180 quoting via the csv module; ``\\n`` line endings."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for product in report["products"]:
        writer.writerow([product[column] for column in CSV_COLUMNS])
    return buffer.getvalue()


# ---- outputs -------------------------------------------------------------------------------


class FileOutput:
    def __init__(self, directory: str) -> None:
        self._directory = directory

    def write(self, name: str, data: str, _content_type: str) -> str:
        os.makedirs(self._directory, exist_ok=True)
        path = os.path.join(self._directory, name)
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(data)
        return f"file://{path}"


class S3Output:
    def __init__(self, bucket: str, prefix: str, region: str | None, endpoint_override: bool) -> None:
        import boto3
        from botocore.config import Config as BotoConfig

        # LocalStack and other emulators need path-style addressing; real S3 is fine either way.
        config = BotoConfig(s3={"addressing_style": "path"}) if endpoint_override else None
        self._client = boto3.client("s3", region_name=region, config=config)
        self._bucket = bucket
        self._prefix = prefix

    def write(self, name: str, data: str, content_type: str) -> str:
        key = f"{self._prefix}{name}"
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data.encode("utf-8"), ContentType=content_type)
        return f"s3://{self._bucket}/{key}"


def make_output(cfg: Config):
    kind, location, prefix = parse_output(cfg.output)
    if kind == "file":
        return FileOutput(location)
    return S3Output(location, prefix, cfg.aws_region, endpoint_override=bool(os.environ.get("AWS_ENDPOINT_URL_S3")))


# ---- main ----------------------------------------------------------------------------------


def connect_with_retry(database_url: str, timeout_seconds: float = 30.0):
    import psycopg

    deadline = time.monotonic() + timeout_seconds
    delay = 0.5
    attempt = 0
    while True:
        attempt += 1
        try:
            return psycopg.connect(database_url, connect_timeout=5, autocommit=True)
        except psycopg.OperationalError as exc:
            if time.monotonic() >= deadline:
                raise
            log("warn", "database not ready, retrying", attempt=attempt, retry_in_seconds=delay, error=str(exc).strip())
            time.sleep(min(delay, max(0.0, deadline - time.monotonic())))
            delay = min(delay * 2, 5.0)


def main() -> int:
    try:
        cfg = load_config()
    except ConfigError as exc:
        log("error", "configuration error", error=str(exc))
        return EXIT_CONFIG_ERROR

    started = time.monotonic()
    try:
        output = make_output(cfg)
        with connect_with_retry(cfg.database_url) as conn:
            report = build_report(conn, cfg.report_date)
        base = f"daily-{cfg.report_date.isoformat()}"
        written = [
            output.write(f"{base}.json", render_json(report), "application/json"),
            output.write(f"{base}.csv", render_csv(report), "text/csv"),
        ]
    except ConfigError as exc:
        log("error", "configuration error", error=str(exc))
        return EXIT_CONFIG_ERROR
    except Exception as exc:  # noqa: BLE001 - any other failure is a runtime error for the scheduler to retry
        log("error", "report failed", error=f"{type(exc).__name__}: {exc}")
        return EXIT_RUNTIME_ERROR

    log(
        "info",
        "report written",
        date=report["date"],
        orders_count=report["orders_count"],
        revenue_cents=report["revenue_cents"],
        products=len(report["products"]),
        outputs=written,
        duration_seconds=round(time.monotonic() - started, 3),
    )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
