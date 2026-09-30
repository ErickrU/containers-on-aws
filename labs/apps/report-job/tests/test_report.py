from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest

import report
from report import (
    SQL_BY_PRODUCT,
    SQL_TOTALS,
    ConfigError,
    build_report,
    load_config,
    parse_output,
    parse_report_date,
    previous_utc_day,
    render_csv,
    render_json,
    window_for,
)

# ---- date window ---------------------------------------------------------------------------


def test_previous_utc_day_uses_utc_not_local_time():
    # 30 Sep 00:30 UTC -> previous day is 29 Sep, even though it is still 29 Sep in UTC-5.
    assert previous_utc_day(datetime(2026, 9, 30, 0, 30, tzinfo=timezone.utc)) == date(2026, 9, 29)
    # 29 Sep 21:00 at UTC-5 is 30 Sep 02:00 UTC -> previous UTC day is 29 Sep.
    minus_five = timezone(timedelta(hours=-5))
    assert previous_utc_day(datetime(2026, 9, 29, 21, 0, tzinfo=minus_five)) == date(2026, 9, 29)


def test_parse_report_date_defaults_and_validates():
    now = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
    assert parse_report_date(None, now) == date(2026, 9, 29)
    assert parse_report_date("  ", now) == date(2026, 9, 29)
    assert parse_report_date("2026-09-15", now) == date(2026, 9, 15)
    with pytest.raises(ConfigError, match="REPORT_DATE"):
        parse_report_date("15/09/2026", now)


def test_window_is_half_open_utc_day():
    start, end = window_for(date(2026, 9, 29))
    assert start == datetime(2026, 9, 29, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 9, 30, 0, 0, tzinfo=timezone.utc)
    assert "created_at >= %s AND created_at < %s" in SQL_TOTALS


# ---- output destinations -------------------------------------------------------------------


def test_parse_output_file_and_s3():
    assert parse_output("file:///out") == ("file", "/out", "")
    assert parse_output("file:///var/reports/") == ("file", "/var/reports/", "")
    assert parse_output("s3://shopfront-reports-123456789012/daily/") == ("s3", "shopfront-reports-123456789012", "daily/")
    assert parse_output("s3://shopfront-reports-123456789012/daily") == ("s3", "shopfront-reports-123456789012", "daily/")
    assert parse_output("s3://bucket") == ("s3", "bucket", "")


def test_parse_output_rejects_other_schemes():
    for bad in ("gs://bucket/x", "/out", "file://relative/path", "s3://", "http://example.com"):
        with pytest.raises(ConfigError):
            parse_output(bad)


def test_load_config_requires_variables_and_region_for_s3():
    with pytest.raises(ConfigError, match="DATABASE_URL, REPORT_OUTPUT"):
        load_config({})
    with pytest.raises(ConfigError, match="AWS_REGION"):
        load_config({"DATABASE_URL": "postgres://x", "REPORT_OUTPUT": "s3://bucket/daily/"})
    cfg = load_config({"DATABASE_URL": "postgres://x", "REPORT_OUTPUT": "file:///out", "REPORT_DATE": "2026-09-01"})
    assert cfg.report_date == date(2026, 9, 1)
    assert cfg.aws_region is None
def test_load_config_reads_database_url_from_file(tmp_path):
    secret = tmp_path / "DATABASE_URL"
    secret.write_text("postgres://from-file\n", encoding="utf-8")
    cfg = load_config({"DATABASE_URL_FILE": str(secret), "REPORT_OUTPUT": "file:///out"})
    assert cfg.database_url == "postgres://from-file"
    # The variable wins over the file when both are present.
    cfg = load_config({"DATABASE_URL": "postgres://direct", "DATABASE_URL_FILE": str(secret), "REPORT_OUTPUT": "file:///out"})
    assert cfg.database_url == "postgres://direct"
    with pytest.raises(ConfigError, match="cannot be read"):
        load_config({"DATABASE_URL_FILE": str(tmp_path / "missing"), "REPORT_OUTPUT": "file:///out"})


# ---- report content ------------------------------------------------------------------------


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        return self._rows[0]

    def fetchall(self):
        return list(self._rows)


class FakeConnection:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params):
        self.calls.append((sql, params))
        if sql == SQL_TOTALS:
            return _Result([(3, 3998 + 2 * 4999)])
        if sql == SQL_BY_PRODUCT:
            return _Result([(2, "SKU-2", 'Desk lamp, "warm"', 2, 2, 2 * 4999), (1, "SKU-1", "Keyboard", 1, 2, 3998)])
        raise AssertionError(f"unexpected SQL: {sql}")


def test_build_report_aggregates_totals_and_products():
    conn = FakeConnection()
    generated = datetime(2026, 9, 30, 1, 0, tzinfo=timezone.utc)

    result = build_report(conn, date(2026, 9, 29), generated_at=generated)

    start, end = window_for(date(2026, 9, 29))
    assert conn.calls == [(SQL_TOTALS, (start, end)), (SQL_BY_PRODUCT, (start, end))]
    assert result["date"] == "2026-09-29"
    assert result["window"] == {"from": "2026-09-29T00:00:00Z", "to": "2026-09-30T00:00:00Z"}
    assert result["generated_at"] == "2026-09-30T01:00:00Z"
    assert result["orders_count"] == 3
    assert result["revenue_cents"] == 13996
    assert [p["sku"] for p in result["products"]] == ["SKU-2", "SKU-1"]
    assert result["products"][0] == {
        "product_id": 2,
        "sku": "SKU-2",
        "name": 'Desk lamp, "warm"',
        "orders": 2,
        "units": 2,
        "revenue_cents": 9998,
    }


def test_render_csv_quotes_commas_and_quotes():
    report_data = build_report(FakeConnection(), date(2026, 9, 29))

    csv_text = render_csv(report_data)

    lines = csv_text.split("\n")
    assert lines[0] == "product_id,sku,name,orders,units,revenue_cents"
    assert lines[1] == '2,SKU-2,"Desk lamp, ""warm""",2,2,9998'
    assert lines[2] == "1,SKU-1,Keyboard,1,2,3998"
    assert lines[3] == "" and len(lines) == 4  # trailing newline, LF only
    assert "\r" not in csv_text


def test_render_json_round_trips():
    report_data = build_report(FakeConnection(), date(2026, 9, 29))

    parsed = json.loads(render_json(report_data))

    assert parsed["orders_count"] == 3
    assert parsed["products"][1]["name"] == "Keyboard"


def test_file_output_writes_both_files(tmp_path):
    output = report.FileOutput(str(tmp_path / "reports"))

    location = output.write("daily-2026-09-29.csv", "a,b\n", "text/csv")

    assert location == f"file://{tmp_path / 'reports' / 'daily-2026-09-29.csv'}"
    assert (tmp_path / "reports" / "daily-2026-09-29.csv").read_text() == "a,b\n"
