#!/usr/bin/env python3
"""Create a disposable Codespaces review database, without live credentials.

Run from the repository root using the supplied dev container. The development
container supplies DEVELOPMENT=True, HAULAGE_REVIEW=True and the dedicated
review-db connection. Existing databases are preserved; this command has no
reset, migration-stamping or production mode.
"""

from datetime import date, datetime, timedelta
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]


def validate_review_url(value):
    """Accept only the named, password-isolated PostgreSQL review service."""
    if not isinstance(value, str):
        raise RuntimeError("DB_URL must point to the dedicated review-db service.")
    try:
        parsed = urlsplit(value)
        accepted = (
            parsed.scheme in {"postgresql", "postgresql+psycopg2"}
            and parsed.username == "review"
            and parsed.password == "review"
            and parsed.hostname == "review-db"
            and parsed.port in (None, 5432)
            and parsed.path == "/haulage_review"
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError as error:
        raise RuntimeError("DB_URL must point to the dedicated review-db service.") from error
    if not accepted:
        raise RuntimeError("Refusing database setup: only review:review@review-db:5432/haulage_review is allowed.")
    return value


def validate_review_environment(environ=None, repository=ROOT, cwd=None):
    """Validate isolation before importing the app, which can load env.py."""
    environ = os.environ if environ is None else environ
    if environ.get("DEVELOPMENT") != "True" or environ.get("HAULAGE_REVIEW") != "True":
        raise RuntimeError("Review setup requires DEVELOPMENT=True and HAULAGE_REVIEW=True.")
    if any(key.startswith("PG") for key in environ):
        raise RuntimeError("Remove PG* connection overrides before running review setup.")
    locations = {Path(repository).resolve(), Path.cwd().resolve() if cwd is None else Path(cwd).resolve()}
    if any((location / "env.py").exists() for location in locations):
        raise RuntimeError("Remove env.py from this review checkout; use the supplied review-only environment.")
    return validate_review_url(environ.get("DB_URL"))


def _week_start(value):
    return value - timedelta(days=(value.weekday() - 5) % 7)


def review_dates(today):
    """Choose review periods from London's current calendar date."""
    if type(today) is not date:
        raise ValueError("today must be a calendar date")
    previous_month = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    current_week = _week_start(today)
    return dict(
        first_week=_week_start(previous_month),
        clean_week=current_week - timedelta(days=14),
        issue_week=current_week - timedelta(days=7),
        current_week=current_week,
        previous_month=previous_month,
    )


def seed_review_data(connection, tables, *, today):
    """Insert synthetic records; the caller owns the surrounding transaction.

    Core inserts deliberately use integer pence/hundredths and omit PostgreSQL's
    generated payslip column. No validator or live-data import is involved.
    """
    periods = review_dates(today)

    def add(table_name, **values):
        table = tables[table_name]
        return connection.execute(table.insert().returning(table.c.id), values).scalar_one()

    truck_ids, driver_ids = [], []
    for index, name in enumerate(("Avery", "Bailey", "Casey", "Drew")):
        truck_id = add("truck", registration=f"DE26 AA{chr(65 + index)}", make="Demo", model="Haulage")
        truck_ids.append(truck_id)
        driver_id = add(
            "driver", first_name=name, last_name="Example", basic_wage=65000,
            daily_bonus_threshold=35000, daily_bonus_percentage=0.25,
            weekly_bonus_threshold=250000, weekly_bonus_percentage=0.2,
            overnight_value=2500, truck_id=truck_id,
        )
        driver_ids.append(driver_id)
        add("driver_employment_history", driver_id=driver_id,
            start_date=periods["first_week"], end_date=None, employment_status="ACTIVE")

    # A change in the latest finished week makes mixed monthly overhead bases
    # visible. Earlier weeks keep their original £350 per truck allowance.
    add("owner_overhead_setting", effective_week_start=periods["first_week"],
        truck_count=4, allowance_per_truck=35000)
    add("owner_overhead_setting", effective_week_start=periods["issue_week"],
        truck_count=4, allowance_per_truck=40000)

    cursor = periods["first_week"]
    mileage = [10000000 + index * 500000 for index in range(4)]
    while cursor <= periods["current_week"]:
        for offset in range(7):
            on_date = cursor + timedelta(days=offset)
            if on_date > today:
                break
            for index, driver_id in enumerate(driver_ids):
                if cursor == periods["issue_week"] and index == 0 and offset == 3:
                    # A missing Tuesday for Avery: leave genuinely unknown.
                    continue
                status = "working" if on_date.weekday() < 5 else "absent"
                if cursor == periods["first_week"] + timedelta(days=7):
                    if index == 1 and offset in (2, 3):
                        status = "holiday"
                    elif index == 2 and offset == 4:
                        status = "absent"
                # A recorded one-day truck exchange illustrates that driver
                # earnings and truck assignment are separate concepts.
                assigned_index = (1 - index) if offset == 2 and index < 2 else index
                truck_id = truck_ids[assigned_index] if status == "working" else None
                fuel_flag = status == "working" and offset == 4
                start = mileage[assigned_index] if truck_id else 0
                stop = start + 30000 if truck_id else 0
                if truck_id:
                    mileage[assigned_index] = stop
                additional = 2500 if status == "working" and index == 0 and offset == 2 else 0
                day_id = add(
                    "day", date=on_date, driver_id=driver_id, truck_id=truck_id,
                    status=status, overnight=False, fuel=fuel_flag,
                    start_mileage=start, end_mileage=stop,
                    additional_earned=additional, additional_wages=0,
                )
                if status != "working":
                    continue
                earned = 25000 + index * 1000
                if cursor == periods["issue_week"] and index == 3 and offset == 2:
                    # A deliberate legacy amount outside today's form range.
                    earned = 250000
                add("job", day_id=day_id, earned=earned, collection="Demo Depot",
                    delivery="Demo Port", notes="Synthetic review example", split=False)
                add("job", day_id=day_id, earned=20000 + index * 1000,
                    collection="Demo Port", delivery="Demo Yard", notes="", split=False)
                if fuel_flag and not (cursor == periods["issue_week"] and index == 2):
                    add("fuel", date=on_date, truck_id=truck_id, day_id=day_id,
                        fuel_card_name="Demo Fleet", fuel_volume=25000 + index * 1000,
                        fuel_cost=35000 + index * 1500)

        if cursor + timedelta(days=6) < today:
            for index, driver_id in enumerate(driver_ids):
                if cursor == periods["issue_week"] and index == 1:
                    continue
                add("payslip", date=cursor + timedelta(days=6), day_id=None,
                    driver_id=driver_id, total_wage=65000 + index * 2500,
                    total_cost_to_employer=74000 + index * 2800)
                if cursor == periods["first_week"] and index == 2:
                    # Saturday and Friday have different generated legacy week
                    # values but are the same owner-report payroll week. The
                    # first seeded week avoids collisions with an earlier slip.
                    add("payslip", date=cursor, day_id=None, driver_id=driver_id,
                        total_wage=70000, total_cost_to_employer=79600)
        cursor += timedelta(days=7)

    return dict(seeded=True, **periods, driver_ids=driver_ids, truck_ids=truck_ids)


def setup_review_database(connection, metadata, *, today):
    """Bootstrap a blank schema atomically, or preserve a complete schema."""
    from sqlalchemy import inspect

    inspector = inspect(connection)
    existing = set(inspector.get_table_names())
    expected = {table.name for table in metadata.tables.values()}
    if existing:
        missing = sorted(expected - existing)
        if missing:
            raise RuntimeError("Existing review schema is incomplete; refusing to modify it. Missing: " + ", ".join(missing))
        for table in metadata.tables.values():
            columns = {column["name"] for column in inspector.get_columns(table.name)}
            if set(table.columns.keys()) - columns:
                raise RuntimeError(f"Existing review table {table.name} has an incompatible schema; no changes made.")
        return dict(seeded=False)
    metadata.create_all(bind=connection)
    return seed_review_data(connection, metadata.tables, today=today)


def main():
    # Do not move application imports above this check: the app imports env.py
    # and selects its database at import time.
    try:
        validate_review_environment()
        sys.path.insert(0, str(ROOT))
        from haulage_app import app, db

        validate_review_url(app.config.get("SQLALCHEMY_DATABASE_URI"))
        with app.app_context():
            validate_review_environment()
            validate_review_url(db.engine.url.render_as_string(hide_password=False))
            # PostgreSQL transactional DDL means failure rolls back the new
            # schema as well as the records; a retry never mistakes it for an
            # intentionally populated review database.
            with db.engine.begin() as connection:
                result = setup_review_database(
                    connection, db.metadata,
                    today=datetime.now(ZoneInfo("Europe/London")).date(),
                )
        if not result["seeded"]:
            print("Review database already exists. All records and edits were preserved.")
            print("Start the preview: python3 run.py")
            return 0
        print("Created an isolated review database containing synthetic sample data.")
        print(f"Complete example week: {result['clean_week']} to {result['clean_week'] + timedelta(days=6)}")
        print(f"  /owner-analysis?week_start={result['clean_week']}")
        print(f"Checks to practise: {result['issue_week']} to {result['issue_week'] + timedelta(days=6)}")
        print(f"  /owner-analysis/checks?week_start={result['issue_week']}")
        print(f"Duplicate payslip example: /owner-analysis/checks?week_start={result['first_week']}")
        print(f"Previous month: /owner-analysis/monthly?month={result['previous_month']:%Y-%m}")
        print(f"Current partial week: /owner-analysis?week_start={result['current_week']}")
        print("Start the preview: python3 run.py")
        return 0
    except Exception as error:
        # Connection exceptions can embed URLs or SQL values. Do not dump them
        # (or local credentials) into automatic dev-container setup logs.
        print(f"Review setup stopped ({type(error).__name__}).", file=sys.stderr)
        if isinstance(error, RuntimeError):
            print(str(error), file=sys.stderr)
        else:
            print("Check that the review-db service is healthy and run python tools/setup_review.py again.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
