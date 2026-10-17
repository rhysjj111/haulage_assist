#!/usr/bin/env python3
"""Independently reconcile Owner Analysis against a LOCAL restored test copy.

This command only reads databases. It never downloads a backup, runs migrations,
invents employment history or configures an overhead allowance. Pass explicit
local URLs; application/environment database defaults are deliberately ignored.
Names, registrations, receipt details and connection URLs are never reported.

Example (after restoring/migrating a separate local copy):
  python tools/reconcile_owner_analysis.py \
    --database-url 'postgresql://agent@/owner_historical?host=/tmp/private-socket' \
    --analysis-database-url 'postgresql://agent@/owner_test_copy?host=/tmp/private-socket' \
    --week 2024-11-02 --week 2024-09-28 --month 2024-11 \
    --as-of 2024-12-22 --output /tmp/owner-comparison.json

The JSON contains financial totals in integer pence and litres in hundredths,
so keep it private. Source totals come from independent SQL, not report helpers.
The optional analysis URL must have the new migrations already applied. The
report's estimated result/review state can remain unavailable or need review:
arithmetic reconciliation does not establish that entry coverage is complete.
"""

from __future__ import annotations

import argparse
import calendar
from contextlib import contextmanager
from datetime import date, timedelta
import json
import os
from pathlib import Path
import sys
import types

import psycopg2
from sqlalchemy.engine import make_url


def local_database_url(value: str) -> str:
    """Reject remote/service DSNs and keep the command on explicit test copies."""
    try:
        url = make_url(value)
    except Exception as exc:
        raise ValueError("An explicit local PostgreSQL test-copy URL is required") from exc
    if url.drivername not in {"postgres", "postgresql", "postgresql+psycopg2"}:
        raise ValueError("Only PostgreSQL test copies are supported")
    if not url.database or not any(word in url.database.lower() for word in ("test", "historical", "reconciliation", "rehearsal")):
        raise ValueError("The database name must identify a test, historical, reconciliation or rehearsal copy")
    allowed_query = {"host", "port", "connect_timeout", "sslmode"}
    if set(url.query) - allowed_query or any(isinstance(v, tuple) for v in url.query.values()):
        raise ValueError("Unsupported connection options; service/hostaddr/options/multiple hosts are forbidden")
    hosts = (url.host, url.query.get("host"))
    if not any(hosts):
        raise ValueError("An explicit local host or Unix socket directory is required")
    for host in hosts:
        if host is None:
            continue
        if not (host in {"localhost", "127.0.0.1", "::1"} or host.startswith("/")):
            raise ValueError("Only local loopback addresses or absolute Unix socket directories are allowed")
        if "," in host:
            raise ValueError("Multiple hosts are forbidden")
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


@contextmanager
def read_only_database(value: str):
    _clear_libpq_overrides()
    connection = psycopg2.connect(local_database_url(value), connect_timeout=5)
    connection.set_session(readonly=True)
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


def _clear_libpq_overrides():
    # A PGHOSTADDR/PGSERVICE/PGOPTIONS inherited from a developer shell must not
    # redirect an explicit localhost URL or defeat the read-only session.
    for name in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS"):
        os.environ.pop(name, None)


def parse_week(value: str) -> date:
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value or parsed.weekday() != 5:
        raise ValueError("A payroll week must be a Saturday in YYYY-MM-DD format")
    # Fail before querying when a complete Saturday-Friday range cannot exist.
    parsed + timedelta(days=6)
    return parsed


def month_weeks(value: str, as_of: date) -> tuple[list[date], list[date]]:
    """Derive weeks directly from calendar Tuesdays, independently of app code."""
    year, month = map(int, value.split("-"))
    if f"{date(year, month, 1).year:04d}-{month:02d}" != value:
        raise ValueError("A month must use YYYY-MM format")
    expected = [date(year, month, day) - timedelta(days=3)
                for day in range(1, calendar.monthrange(year, month)[1] + 1)
                if date(year, month, day).weekday() == 1]
    completed = [start for start in expected if start + timedelta(days=6) < as_of]
    return expected, completed


def _date_filter(column: str, weeks: list[date]) -> tuple[str, list[date]]:
    if not weeks:
        return "FALSE", []
    return "(" + " OR ".join(f"({column} >= %s AND {column} <= %s)" for _ in weeks) + ")", [
        value for start in weeks for value in (start, start + timedelta(days=6))
    ]


def source_totals(connection, weeks: list[date]) -> dict:
    """Read separate source aggregates: never multiply Day amounts by job joins."""
    day_filter, day_params = _date_filter("d.date", weeks)
    fuel_filter, fuel_params = _date_filter("f.date", weeks)
    payroll_filter, payroll_params = _date_filter("p.date", weeks)
    drivers: dict[int, dict] = {}

    def driver(driver_id):
        return drivers.setdefault(driver_id, dict(driver_id=driver_id, earnings=0, employer_cost=0,
            working_days=0, holiday_days=0, absent_days=0, payroll_entries=0))

    with connection.cursor() as cursor:
        cursor.execute(f"SELECT d.driver_id, COALESCE(SUM(d.additional_earned), 0), "
                       f"COUNT(*) FILTER (WHERE d.status='working'), COUNT(*) FILTER (WHERE d.status='holiday'), "
                       f"COUNT(*) FILTER (WHERE d.status='absent') FROM day d WHERE {day_filter} GROUP BY d.driver_id", day_params)
        for driver_id, additional, working, holiday, absent in cursor:
            row = driver(driver_id)
            row.update(earnings=int(additional), working_days=working, holiday_days=holiday, absent_days=absent)
        cursor.execute(f"SELECT d.driver_id, COALESCE(SUM(j.earned), 0) FROM job j JOIN day d ON d.id=j.day_id "
                       f"WHERE {day_filter} GROUP BY d.driver_id", day_params)
        for driver_id, earnings in cursor:
            driver(driver_id)["earnings"] += int(earnings)
        cursor.execute(f"SELECT p.driver_id, COALESCE(SUM(p.total_cost_to_employer), 0), COUNT(*) "
                       f"FROM payslip p WHERE {payroll_filter} GROUP BY p.driver_id", payroll_params)
        for driver_id, cost, count in cursor:
            driver(driver_id).update(employer_cost=int(cost), payroll_entries=count)
        cursor.execute(f"SELECT f.truck_id, COALESCE(SUM(f.fuel_cost), 0), COALESCE(SUM(f.fuel_volume), 0), COUNT(*) "
                       f"FROM fuel f WHERE {fuel_filter} GROUP BY f.truck_id", fuel_params)
        trucks = [dict(truck_id=truck_id, fuel_spending=int(cost), fuel_volume=int(volume), fuel_entries=count)
                  for truck_id, cost, volume, count in cursor]
    return dict(earnings=sum(r["earnings"] for r in drivers.values()),
                employer_cost=sum(r["employer_cost"] for r in drivers.values()),
                fuel_spending=sum(r["fuel_spending"] for r in trucks),
                fuel_volume=sum(r["fuel_volume"] for r in trucks),
                drivers=sorted(drivers.values(), key=lambda r: r["driver_id"]),
                trucks=sorted(trucks, key=lambda r: r["truck_id"]))


def source_metadata(connection) -> dict:
    with connection.cursor() as cursor:
        cursor.execute("SELECT version_num FROM alembic_version")
        revisions = [row[0] for row in cursor]
        tables = {}
        for table in ("day", "fuel", "payslip"):
            cursor.execute(f"SELECT COUNT(*), MIN(date), MAX(date) FROM {table}")
            count, first, last = cursor.fetchone()
            tables[table] = dict(count=count, first_date=first, last_date=last)
    return dict(revisions=revisions, tables=tables)


@contextmanager
def analysis_application(value: str):
    """Import against the explicit local copy; disable optional env.py loading."""
    local = local_database_url(value)
    _clear_libpq_overrides()
    if "haulage_app" in sys.modules:
        raise RuntimeError("Run reconciliation in a fresh process so no existing app/database is reused")
    # The legacy app optionally imports env.py. Do not allow it to replace the
    # explicit test-copy database with credentials/developer defaults.
    sys.modules["env"] = types.ModuleType("env")
    os.environ["DEVELOPMENT"] = "True"
    os.environ["DB_URL"] = local
    os.environ["SECRET_KEY"] = "local-read-only-reconciliation"
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from haulage_app import app, db
    from sqlalchemy import event

    with app.app_context():
        if local_database_url(db.engine.url.render_as_string(hide_password=False)) != local:
            raise RuntimeError("Application database differs from the explicit local test copy")

        def enforce_readonly(dbapi_connection, connection_record):
            dbapi_connection.set_session(readonly=True)

        event.listen(db.engine, "connect", enforce_readonly)
        try:
            yield app
        finally:
            db.session.rollback()
            db.session.remove()
            db.engine.dispose()


def report_totals(report: dict) -> dict:
    """Use only the public report values, never report helpers for expectations."""
    keys = ("earnings", "employer_cost", "fuel_spending", "fuel_volume")
    return {key: report[key] for key in keys}


def compare_breakdowns(source: dict, report: dict) -> dict[str, bool]:
    """Compare by stable numeric IDs, including zero rows added by expectations."""
    comparisons = {}
    for kind, fields in (("driver", ("earnings", "employer_cost", "working_days", "holiday_days", "absent_days")),
                         ("truck", ("fuel_spending", "fuel_volume"))):
        expected = {row[f"{kind}_id"]: row for row in source[kind + "s"]}
        actual = report[kind + "s"]
        for identifier in expected.keys() | actual.keys():
            for field in fields:
                comparisons[f"{kind}:{identifier}:{field}"] = expected.get(identifier, {}).get(field, 0) == actual.get(identifier, {}).get(field, 0)
    return comparisons


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database-url", required=True, help="Explicit restored LOCAL source-copy URL")
    parser.add_argument("--analysis-database-url", help="Explicit LOCAL migrated copy for application comparison")
    parser.add_argument("--week", action="append", default=[], help="Saturday YYYY-MM-DD; may be repeated")
    parser.add_argument("--month", action="append", default=[], help="Payroll month YYYY-MM; may be repeated")
    parser.add_argument("--as-of", required=True, help="YYYY-MM-DD; only finished weeks enter monthly totals")
    parser.add_argument("--snapshot-description", default="Local restored copy; freshness must be established separately")
    parser.add_argument("--output", required=True, type=Path, help="Private JSON output containing financial totals")
    args = parser.parse_args(argv)
    try:
        local_database_url(args.database_url)
        if args.analysis_database_url:
            local_database_url(args.analysis_database_url)
        as_of = date.fromisoformat(args.as_of)
        if as_of.isoformat() != args.as_of:
            raise ValueError("The as-of date must use YYYY-MM-DD format")
        periods = [dict(kind="week", selected=value, expected=[parse_week(value)], completed=[parse_week(value)])
                   for value in args.week]
        if any(period["expected"][0] + timedelta(days=6) >= as_of for period in periods):
            raise ValueError("Only finished payroll weeks can be reconciled")
        for value in args.month:
            expected, completed = month_weeks(value, as_of)
            periods.append(dict(kind="month", selected=value, expected=expected, completed=completed))
        if not periods:
            raise ValueError("Select at least one --week or --month")
    except (ValueError, OverflowError):
        parser.error("Invalid input: use explicit local test-copy URLs, Saturday weeks and valid ISO dates/months")
    result = dict(snapshot_description=args.snapshot_description, as_of=as_of,
                  arithmetic_only=True, overheads_configured_by_this_tool=False, periods=[])
    with read_only_database(args.database_url) as connection:
        result["source"] = source_metadata(connection)
        for period in periods:
            period["source_totals"] = source_totals(connection, period["completed"])
            result["periods"].append(period)
    if args.analysis_database_url:
        with analysis_application(args.analysis_database_url):
            from haulage_app.owner_analysis.reviews import get_reviewed_week
            from haulage_app.owner_analysis.monthly import get_monthly_report
            for period in result["periods"]:
                if period["kind"] == "week":
                    report = get_reviewed_week(period["expected"][0], as_of=as_of)
                else:
                    year, month = map(int, period["selected"].split("-"))
                    report = get_monthly_report(year, month, as_of=as_of)
                actual = report_totals(report)
                period["analysis_totals"] = actual
                period["matches"] = {key: actual[key] == period["source_totals"][key] for key in actual}
                period["matches"].update(compare_breakdowns(period["source_totals"], report))
                period["analysis_state"] = {key: report.get(key) for key in
                    ("review_status", "estimated_operating_result", "overheads", "period_state")}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Restrict the report from its first write, including when the target exists.
    descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as output:
        os.fchmod(output.fileno(), 0o600)
        json.dump(result, output, default=str, indent=2)
        output.write("\n")
    comparisons = [matched for period in result["periods"] for matched in period.get("matches", {}).values()]
    if comparisons:
        print(f"Reconciled {len(periods)} period(s); {sum(comparisons)}/{len(comparisons)} source-total comparisons matched.")
    else:
        print(f"Collected independent source totals for {len(periods)} period(s); application comparison was not requested.")
    print("Financial totals saved privately; no live database was accessed and no database writes were made.")
    return 1 if comparisons and not all(comparisons) else 0


if __name__ == "__main__":
    raise SystemExit(main())
