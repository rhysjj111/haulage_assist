"""Bounded, read-only weekly context for investigating an individual check.

The report's scalar review basis is the source for the selected week's records.
Only names and registrations are looked up here. Nearby payslips are a separate,
explicitly requested query and never contribute to the selected week's figures.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select

from haulage_app import db
from haulage_app.models import Driver, Payslip, Truck
from .dates import validate_week_start, week_end


_STATUS_LABELS = {"working": "Working", "holiday": "Holiday", "absent": "Absent"}


def _date(value):
    if isinstance(value, str):
        value = date.fromisoformat(value)
    if type(value) is not date:
        raise ValueError("Please supply a calendar date")
    return value


def _unique_rows(rows):
    """A joined or repeated scalar source must not multiply recorded amounts."""
    return {row["id"]: row for row in rows}.values()


def _source_scope(basis, target_type, target_id):
    """Resolve the person/truck for exact record checks without lazy loading."""
    if target_type == "job":
        job = next((row for row in basis.get("jobs", []) if row["id"] == target_id), None)
        return next((row for row in basis.get("days", [])
                     if job and row["id"] == job["day_id"]), {})
    key = {"day": "days", "fuel": "fuel_entries", "payslip": "payslips"}.get(target_type)
    if key is None:
        return {}
    return next((row for row in basis.get(key, []) if row["id"] == target_id), {})


def build_week_context(week, basis, *, driver_id=None, truck_id=None, on_date=None,
                       target_type=None, target_id=None, as_of=None, include_nearby=False):
    """Return seven dated rows plus actual payslips for a Saturday–Friday week.

    Blank weekends are not scheduled; missing weekdays remain unknown. Future
    dates are not yet due. Recorded weekend work and statuses are kept as entered.
    Driver earnings use each recorded job and each day's additional amount once.
    A truck scope shows recorded day assignments but deliberately has no driver
    earnings: drivers can change trucks during a day. Dates, rather than the
    optional linked Day or a guessed pay period, determine payslip membership.
    """
    with db.session.no_autoflush:
        return _build_week_context(
            week, basis, driver_id=driver_id, truck_id=truck_id, on_date=on_date,
            target_type=target_type, target_id=target_id, as_of=as_of,
            include_nearby=include_nearby,
        )


def _build_week_context(week, basis, *, driver_id, truck_id, on_date,
                        target_type, target_id, as_of, include_nearby):
    validate_week_start(week)
    end = week_end(week)
    as_of = _date(as_of) if as_of is not None else datetime.now(ZoneInfo("Europe/London")).date()
    cutoff = min(end, as_of)
    on_date = _date(on_date) if on_date is not None else None
    if on_date is not None and not week <= on_date <= end:
        raise ValueError("The selected date must belong to this payroll week")
    subject = _source_scope(basis, target_type, target_id)
    if driver_id is None and truck_id is None:
        if target_type in {"day", "job", "payslip"}:
            driver_id = subject.get("driver_id")
        elif target_type == "fuel":
            truck_id = subject.get("truck_id")
    if on_date is None and subject.get("date") is not None:
        on_date = _date(subject["date"])
    scope = "driver" if driver_id is not None else "truck" if truck_id is not None else "week"
    truck_scope = scope == "truck"

    def in_period(row):
        return week <= _date(row["date"]) <= cutoff

    days = [dict(row, date=_date(row["date"]))
            for row in _unique_rows(basis.get("days", [])) if in_period(row)]
    payslips = [dict(row, date=_date(row["date"]))
                for row in _unique_rows(basis.get("payslips", [])) if in_period(row)]
    fuel = [dict(row, date=_date(row["date"]))
            for row in _unique_rows(basis.get("fuel_entries", [])) if in_period(row)]
    driver_ids = {row["driver_id"] for row in days + payslips}
    truck_ids = {row["truck_id"] for row in days + fuel if row.get("truck_id") is not None}
    if driver_id is not None:
        driver_ids.add(driver_id)
    if truck_id is not None:
        truck_ids.add(truck_id)

    with db.session.no_autoflush:
        refresh = not (db.session.new or db.session.dirty or db.session.deleted)

        def fresh(statement):
            return statement.execution_options(populate_existing=True) if refresh else statement

        drivers = (db.session.execute(fresh(select(Driver).where(Driver.id.in_(driver_ids)))).scalars().all()
                   if driver_ids else [])
        trucks = (db.session.execute(fresh(select(Truck).where(Truck.id.in_(truck_ids)))).scalars().all()
                  if truck_ids else [])
        names = {row.id: row.full_name for row in drivers}
        registrations = {row.id: row.registration for row in trucks}
        nearby = []
        nearby_loaded = bool(include_nearby and driver_id is not None)
        if nearby_loaded:
            # Clip at the supported calendar boundaries. Only the adjacent two
            # payroll weeks can be consulted; no all-history picker is involved.
            before = date.fromordinal(max(date.min.toordinal(), week.toordinal() - 7))
            after = date.fromordinal(min(date.max.toordinal(), end.toordinal() + 7))
            statement = select(Payslip).where(
                Payslip.driver_id == driver_id,
                Payslip.date >= before, Payslip.date <= after,
                or_(Payslip.date < week, Payslip.date > end),
            ).order_by(Payslip.date.desc(), Payslip.id.desc()).limit(51)
            nearby = db.session.execute(fresh(statement)).scalars().all()
        # Convert all ORM rows while still inside no_autoflush. No relationships
        # are read here, and the result contains scalar values only.
        nearby_rows = [{"id": row.id, "date": row.date, "driver_id": row.driver_id,
                        "day_id": row.day_id, "total_wage": row.total_wage,
                        "total_cost_to_employer": row.total_cost_to_employer}
                       for row in nearby[:50]]

    def driver_name(identifier):
        return names.get(identifier, f"Driver {identifier}")

    def truck_name(identifier):
        return registrations.get(identifier, f"Truck {identifier}") if identifier is not None else None

    jobs_by_day = defaultdict(list)
    for row in _unique_rows(basis.get("jobs", [])):
        jobs_by_day[row["day_id"]].append(dict(row))
    rows_by_date = defaultdict(list)
    driver_dates = defaultdict(list)
    for row in sorted(days, key=lambda item: (item["date"], item["driver_id"], item["id"])):
        if scope == "driver" and row["driver_id"] != driver_id:
            continue
        if truck_scope and row.get("truck_id") != truck_id:
            continue
        jobs = sorted(jobs_by_day[row["id"]], key=lambda item: item["id"])
        job_earnings = sum(job["earned"] for job in jobs)
        if truck_scope:
            jobs = [dict(job, earned=None) for job in jobs]
        entry = dict(row, driver_name=driver_name(row["driver_id"]),
                     truck_registration=truck_name(row.get("truck_id")),
                     status_label=_STATUS_LABELS.get(row["status"], row["status"] or "Unknown"),
                     jobs=jobs, job_earnings=None if truck_scope else job_earnings,
                     earnings=None if truck_scope else job_earnings + row["additional_earned"],
                     highlighted=(target_type == "day" and row["id"] == target_id)
                     or (target_type == "job" and any(job["id"] == target_id for job in jobs)))
        if truck_scope:
            entry["additional_earned"] = None
        rows_by_date[row["date"]].append(entry)
        driver_dates[(row["driver_id"], row["date"])].append(entry)

    counts = {"working_days": 0, "holiday_days": 0, "absent_days": 0}
    duplicate_groups = 0
    for entries in driver_dates.values():
        duplicate_groups += len(entries) > 1
        statuses = {entry["status"] for entry in entries}
        # Conflicting historical duplicates cannot establish a day's status.
        if len(statuses) == 1:
            key = {"working": "working_days", "holiday": "holiday_days", "absent": "absent_days"}.get(statuses.pop())
            if key is not None:
                counts[key] += 1

    dated_rows = []
    for offset in range(7):
        current = week + timedelta(days=offset)
        entries = rows_by_date[current]
        is_future = current > as_of
        is_non_working_day = current.weekday() >= 5
        labels = list(dict.fromkeys(entry["status_label"] for entry in entries))
        label = ("Not yet due" if is_future else ", ".join(labels) if entries else
                 "Not scheduled" if is_non_working_day else "No entry")
        duplicate_entries = len({entry["driver_id"] for entry in entries}) < len(entries)
        dated_rows.append({
            "date": current, "highlighted": current == on_date,
            "is_future": is_future, "is_non_working_day": is_non_working_day, "entries": entries,
            "label": label, "status_label": label, "duplicate_entries": duplicate_entries,
            "earnings": sum(entry["earnings"] for entry in entries) if entries and not truck_scope else None,
            "job_earnings": sum(entry["job_earnings"] for entry in entries) if entries and not truck_scope else None,
            "additional_earned": sum(entry["additional_earned"] for entry in entries) if entries and not truck_scope else None,
        })

    def payslip_row(row, *, outside=False):
        selected_record = not outside and target_type == "payslip" and row["id"] == target_id
        return dict(row, driver_name=driver_name(row["driver_id"]),
                    highlighted=selected_record or row["driver_id"] == driver_id,
                    selected_record=selected_record, outside_selected_week=outside,
                    future_dated=row["date"] > as_of)

    payslip_rows = [payslip_row(row) for row in sorted(
        payslips, key=lambda row: (driver_name(row["driver_id"]).casefold(), row["date"], row["id"]))]
    visible_fuel = []
    for row in sorted(fuel, key=lambda row: (row["date"], row["id"])):
        if scope == "driver" or truck_scope and row["truck_id"] != truck_id:
            continue
        visible_fuel.append(dict(row, truck_registration=truck_name(row["truck_id"]),
                                 highlighted=target_type == "fuel" and row["id"] == target_id))
    recorded_entries = [entry for row in dated_rows for entry in row["entries"]]
    summary = dict(counts, recorded_days=len(driver_dates), duplicate_day_groups=duplicate_groups,
                   missing_days=sum(not row["entries"] and not row["is_future"]
                                    and not row["is_non_working_day"] for row in dated_rows),
                   earnings=sum(entry["earnings"] for entry in recorded_entries) if not truck_scope else None,
                   fuel_spending=sum(row["fuel_cost"] for row in visible_fuel),
                   fuel_volume=sum(row["fuel_volume"] for row in visible_fuel),
                   fuel_entry_count=len(visible_fuel))
    return {
        "week_start": week, "week_end": end, "as_of": as_of,
        "recorded_through": cutoff if cutoff >= week else None,
        "scope": scope, "driver_id": driver_id,
        "driver_name": driver_name(driver_id) if driver_id is not None else None,
        "truck_id": truck_id, "truck_registration": truck_name(truck_id),
        "on_date": on_date, "target_type": target_type, "target_id": target_id,
        "days": dated_rows, "summary": summary,
        "payslips": payslip_rows, "fuel_entries": visible_fuel,
        "driver_payslip_missing": driver_id is not None and not any(
            row["driver_id"] == driver_id for row in payslip_rows),
        "nearby_loaded": nearby_loaded,
        "nearby_payslips": [payslip_row(row, outside=True) for row in nearby_rows],
        "nearby_truncated": len(nearby) > 50,
    }
