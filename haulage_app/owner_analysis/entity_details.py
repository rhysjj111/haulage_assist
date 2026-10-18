"""Bounded, read-only detail for the owner report's driver and truck summaries.

The selected report period determines every source query. A payroll month uses
the same completed Saturday–Friday weeks as the report, assigned by Tuesday.
Scalar queries deliberately avoid relationship loading and session autoflush.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from haulage_app import db
from haulage_app.models import Day, Driver, Fuel, Job, Payslip, Truck
from .dates import payroll_weeks_for_month, validate_week_start, week_end


_STATUSES = {"working": "Working", "holiday": "Holiday", "absent": "Absent"}
_DAY_COLUMNS = (
    Day.id, Day.date, Day.driver_id, Day.truck_id, Day.status, Day.overnight,
    Day.fuel, Day.start_mileage, Day.end_mileage, Day.additional_earned,
    Day.additional_wages,
)


def _calendar_date(value, name):
    if type(value) is not date:
        raise ValueError(f"{name} must be a calendar date")
    return value


def _period(week_start, month, as_of):
    if (week_start is None) == (month is None):
        raise ValueError("Select exactly one payroll week or month")
    if week_start is not None:
        validate_week_start(week_start)
        end = week_end(week_start)
        return [week_start], [], week_start, end
    _calendar_date(month, "month")
    if month.day != 1:
        raise ValueError("month must be the first day of a calendar month")
    expected = payroll_weeks_for_month(month.year, month.month)
    # Validate the entire expected range, even when it lies in the future.
    end = week_end(expected[-1])
    completed = [start for start in expected if week_end(start) < as_of]
    pending = [start for start in expected if week_end(start) >= as_of]
    return completed, pending, expected[0], end


def _rows(statement):
    return [dict(row) for row in db.session.execute(statement).mappings()]


def _summary(kind, days, payslips):
    entries = [entry for day in days for entry in day["entries"]]
    if kind == "driver":
        statuses = defaultdict(set)
        for entry in entries:
            statuses[entry["date"]].add(entry["status"])
        counts = {"working_days": 0, "holiday_days": 0, "absent_days": 0}
        for values in statuses.values():
            if len(values) == 1:
                key = {"working": "working_days", "holiday": "holiday_days",
                       "absent": "absent_days"}.get(next(iter(values)))
                if key:
                    counts[key] += 1
        return dict(
            counts, recorded_days=len(statuses), job_count=sum(len(row["jobs"]) for row in entries),
            earnings=sum(row["earnings"] for row in entries),
            job_earnings=sum(row["job_earnings"] for row in entries),
            additional_earned=sum(row["additional_earned"] for row in entries),
            total_wage=sum(row["total_wage"] for row in payslips),
            employer_cost=sum(row["total_cost_to_employer"] for row in payslips),
            payslip_count=len(payslips),
        )
    fuel = [row for day in days for row in day["fuel_entries"]]
    working = [entry for entry in entries if entry["status"] == "working"]
    invalid = sum(not row["mileage_valid"] for row in working)
    multiple = sum(sum(row["status"] == "working" for row in day["entries"]) > 1
                   for day in days)
    # Multiple recorded assignments can have overlapping readings; a sum of
    # those deltas is not necessarily the distance travelled by the truck.
    distance = (sum(row["distance"] for row in working)
                if working and not invalid and not multiple else None)
    return {
        "recorded_days": sum(bool(day["entries"]) for day in days),
        "fuel_spending": sum(row["fuel_cost"] for row in fuel),
        "fuel_volume": sum(row["fuel_volume"] for row in fuel),
        "fuel_entry_count": len(fuel), "distance": distance,
        "invalid_mileage_count": invalid, "multiple_assignment_days": multiple,
        "missing_fuel_receipt_count": sum(row["missing_fuel_receipt"] for row in entries),
    }


def build_entity_details(kind, subject_id, *, week_start=None, month=None, as_of=None):
    """Return recorded work or mileage/fuel for one selected report entity.

    Dates must be calendar dates, with a Saturday week or first-of-month month.
    Money, fuel volume and mileage keep their existing stored hundredths.
    Unknown/missing dates never establish absence or truck downtime. Historical
    drivers remain available without relying on today's employment status.
    """
    if kind not in {"driver", "truck"}:
        raise ValueError("Select a driver or truck")
    if type(subject_id) is not int or subject_id <= 0:
        raise ValueError("The selected driver or truck must have a valid identifier")
    as_of = (_calendar_date(as_of, "as_of") if as_of is not None
             else datetime.now(ZoneInfo("Europe/London")).date())
    starts, pending, expected_start, expected_end = _period(week_start, month, as_of)
    with db.session.no_autoflush:
        return _build(kind, subject_id, week_start, month, as_of,
                      starts, pending, expected_start, expected_end)


def _build(kind, subject_id, selected_week, month, as_of, starts, pending,
           expected_start, expected_end):
    if kind == "driver":
        subjects = _rows(select(Driver.id, Driver.first_name, Driver.last_name).where(
            Driver.id == subject_id))
        name = " ".join(part for part in (
            subjects[0]["first_name"], subjects[0]["last_name"]) if part).strip() if subjects else ""
    else:
        subjects = _rows(select(Truck.id, Truck.registration).where(Truck.id == subject_id))
        name = subjects[0]["registration"] if subjects else ""
    if not subjects:
        raise LookupError("The selected driver or truck no longer exists")
    name = name or f"{kind.title()} {subject_id}"
    start = starts[0] if starts else None
    end = week_end(starts[-1]) if starts else None
    cutoff = min(end, as_of) if end else None
    days, jobs, payslips, fuel = [], [], [], []
    driver_names, registrations = {}, {}
    if start is not None and start <= cutoff:
        subject_column = Day.driver_id if kind == "driver" else Day.truck_id
        conditions = (subject_column == subject_id, Day.date >= start, Day.date <= cutoff)
        days = _rows(select(*_DAY_COLUMNS).where(*conditions).order_by(Day.date, Day.id))
        if kind == "driver":
            jobs = _rows(select(Job.id, Job.day_id, Job.collection, Job.delivery,
                                Job.earned, Job.notes, Job.split)
                         .join(Day, Day.id == Job.day_id).where(*conditions)
                         .order_by(Job.day_id, Job.id))
            payslips = _rows(select(Payslip.id, Payslip.date, Payslip.driver_id,
                                    Payslip.total_wage, Payslip.total_cost_to_employer)
                            .where(Payslip.driver_id == subject_id,
                                   Payslip.date >= start, Payslip.date <= cutoff)
                            .order_by(Payslip.date, Payslip.id))
            truck_ids = {row["truck_id"] for row in days if row["truck_id"] is not None}
            if truck_ids:
                registrations = {row["id"]: row["registration"] for row in _rows(
                    select(Truck.id, Truck.registration).where(Truck.id.in_(truck_ids)))}
        else:
            fuel = _rows(select(Fuel.id, Fuel.date, Fuel.day_id, Fuel.fuel_card_name,
                                Fuel.fuel_volume, Fuel.fuel_cost)
                         .where(Fuel.truck_id == subject_id,
                                Fuel.date >= start, Fuel.date <= cutoff)
                         .order_by(Fuel.date, Fuel.id))
            driver_ids = {row["driver_id"] for row in days}
            if driver_ids:
                driver_names = {row["id"]: " ".join(
                    part for part in (row["first_name"], row["last_name"]) if part).strip()
                    for row in _rows(select(Driver.id, Driver.first_name, Driver.last_name)
                                     .where(Driver.id.in_(driver_ids)))}

    jobs_by_day, entries_by_date, fuel_by_date = defaultdict(list), defaultdict(list), defaultdict(list)
    for row in jobs:
        jobs_by_day[row["day_id"]].append(row)
    for row in fuel:
        fuel_by_date[row["date"]].append(row)
    for row in days:
        entry = dict(row, status_label=_STATUSES.get(row["status"], row["status"] or "Unknown"))
        if kind == "driver":
            entry["truck_registration"] = registrations.get(row["truck_id"],
                f'Truck {row["truck_id"]}' if row["truck_id"] is not None else None)
            entry["jobs"] = jobs_by_day[row["id"]]
            entry["job_earnings"] = sum(job["earned"] for job in entry["jobs"])
            entry["earnings"] = entry["job_earnings"] + row["additional_earned"]
        else:
            # A truck assignment is not a safe basis for allocating earnings.
            for field in ("additional_earned", "additional_wages"):
                entry.pop(field)
            entry["driver_name"] = driver_names.get(row["driver_id"]) or f'Driver {row["driver_id"]}'
            start_reading, end_reading = row["start_mileage"], row["end_mileage"]
            valid = (row["status"] == "working" and start_reading is not None
                     and end_reading is not None and start_reading > 0 and end_reading >= start_reading)
            entry["mileage_valid"] = valid
            entry["distance"] = end_reading - start_reading if valid else None
            entry["missing_fuel_receipt"] = bool(row["fuel"] and not fuel_by_date[row["date"]])
        entries_by_date[row["date"]].append(entry)

    weeks = []
    for start in starts:
        stop = week_end(start)
        dated_rows = []
        for offset in range(7):
            current = start + timedelta(days=offset)
            entries = entries_by_date[current]
            receipts = fuel_by_date[current] if kind == "truck" else []
            is_future = current > as_of
            if is_future:
                label = "Not yet due"
            elif entries:
                label = ", ".join(dict.fromkeys(entry["status_label"] for entry in entries))
            elif kind == "truck":
                label = "Fuel recorded" if receipts else "No recorded activity"
            else:
                label = "Not scheduled" if current.weekday() >= 5 else "No entry"
            dated_rows.append({
                "date": current, "label": label, "status_label": label,
                "is_future": is_future, "is_weekend": current.weekday() >= 5,
                "entries": entries, "fuel_entries": receipts,
            })
        week_payslips = [row for row in payslips if start <= row["date"] <= stop]
        weeks.append({
            "week_start": start, "week_end": stop,
            "recorded_through": min(stop, as_of) if start <= as_of else None,
            "days": dated_rows, "payslips": week_payslips,
            "fuel_entries": [row for day in dated_rows for row in day["fuel_entries"]],
            "summary": _summary(kind, dated_rows, week_payslips),
        })
    period_label = (f'{selected_week:%d %b} – {week_end(selected_week):%d %b %Y}'
                    if selected_week else month.strftime("%B %Y"))
    return {
        "kind": kind, "subject_id": subject_id, "name": name, "label": name,
        "period": "weekly" if selected_week else "monthly", "period_label": period_label,
        "week_start": selected_week, "month": month, "as_of": as_of,
        "period_start": starts[0] if starts else None,
        "period_end": week_end(starts[-1]) if starts else None,
        "expected_start": expected_start, "expected_end": expected_end,
        "pending_week_count": len(pending), "weeks": weeks,
        "summary": _summary(kind, [day for week in weeks for day in week["days"]], payslips),
    }
