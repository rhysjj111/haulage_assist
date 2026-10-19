"""Read-only owner totals from recorded money, without payroll/fuel estimates.

Money is integer pence; fuel volume remains hundredths of litres. Fuel spending
is purchases dated in the period, not fuel consumed. No VAT conversion applies.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import or_
from sqlalchemy.orm import selectinload

from haulage_app import db
from haulage_app.models import Day, Driver, DriverEmploymentHistory, Fuel, Payslip, Truck
from haulage_app.owner_analysis.checks import build_weekly_checks
from haulage_app.owner_analysis.dates import validate_week_start, week_end
from haulage_app.owner_analysis.overheads import get_weekly_overhead


def _review_basis(week_start, end_date, *, days, jobs, fuel_entries, payslips, employment_periods, overhead):
    """Actual scalar values; cosmetic names and equivalent config IDs excluded."""
    expected_dates = defaultdict(set)
    for period in employment_periods:
        start, stop = max(week_start, period.start_date), min(end_date, period.end_date or end_date)
        for offset in range((stop - start).days + 1):
            expected_dates[period.driver_id].add((start + timedelta(days=offset)).isoformat())
    return {
        "week_start": week_start.isoformat(),
        "days": [{"id": day.id, "date": day.date.isoformat(), "driver_id": day.driver_id,
                  "truck_id": day.truck_id, "status": day.status, "overnight": day.overnight,
                  "fuel": day.fuel, "start_mileage": day.start_mileage, "end_mileage": day.end_mileage,
                  "additional_earned": day.additional_earned, "additional_wages": day.additional_wages}
                 for day in days],
        "jobs": [{"id": job.id, "day_id": job.day_id, "earned": job.earned,
                  "collection": job.collection, "delivery": job.delivery,
                  "split": job.split, "notes": job.notes} for job in sorted(jobs, key=lambda item: item.id)],
        "fuel_entries": [{"id": row.id, "date": row.date.isoformat(), "truck_id": row.truck_id,
                          "day_id": row.day_id, "fuel_cost": row.fuel_cost,
                          "fuel_volume": row.fuel_volume, "fuel_card_name": row.fuel_card_name}
                         for row in fuel_entries],
        "payslips": [{"id": row.id, "date": row.date.isoformat(), "driver_id": row.driver_id,
                      "day_id": row.day_id, "total_wage": row.total_wage,
                      "total_cost_to_employer": row.total_cost_to_employer} for row in payslips],
        "employment_periods": [{"driver_id": driver_id, "expected_dates": sorted(dates)}
                               for driver_id, dates in sorted(expected_dates.items())],
        "overhead": {"truck_count": overhead.truck_count, "allowance_per_truck": overhead.allowance_per_truck,
                     "total": overhead.total} if overhead is not None else None,
    }


def calculate_weekly_report(week_start, *, as_of=None):
    """Return dated recorded totals and checks, never creating or signing a week.

    Employment determines expected entries, never which financial entries count.
    ``as_of`` limits transaction dates and overdue checks; it is not an archived
    database snapshot, so later corrections to those dated records remain seen.
    """
    validate_week_start(week_start)
    end_date = week_end(week_start)
    if as_of is None:
        as_of = datetime.now(ZoneInfo("Europe/London")).date()
    if type(as_of) is not date:
        raise ValueError("as_of must be a calendar date")
    recorded_through = min(end_date, as_of)
    period_state = "future" if as_of < week_start else "in_progress" if as_of <= end_date else "finished"
    with db.session.no_autoflush:
        refresh = not (db.session.new or db.session.dirty or db.session.deleted)

        def source_query(model):
            return model.query.populate_existing() if refresh else model.query

        days = source_query(Day).options(selectinload(Day.jobs)).filter(
            Day.date >= week_start, Day.date <= recorded_through
        ).order_by(Day.date, Day.id).all()
        fuel_entries = source_query(Fuel).filter(
            Fuel.date >= week_start, Fuel.date <= recorded_through
        ).order_by(Fuel.date, Fuel.id).all()
        payslips = source_query(Payslip).filter(
            Payslip.date >= week_start, Payslip.date <= recorded_through
        ).order_by(Payslip.date, Payslip.id).all()
        employment_periods = source_query(DriverEmploymentHistory).filter(
            DriverEmploymentHistory.start_date <= end_date,
            or_(DriverEmploymentHistory.end_date.is_(None), DriverEmploymentHistory.end_date >= week_start),
        ).order_by(DriverEmploymentHistory.driver_id, DriverEmploymentHistory.start_date,
                   DriverEmploymentHistory.id).all()
        overhead = get_weekly_overhead(week_start)
        driver_ids = ({day.driver_id for day in days} | {row.driver_id for row in payslips}
                      | {period.driver_id for period in employment_periods})
        drivers = Driver.query.filter(Driver.id.in_(driver_ids)).order_by(Driver.id).all() if driver_ids else []
        issues = build_weekly_checks(week_start, as_of=as_of, days=days, fuel_entries=fuel_entries,
                                     payslips=payslips, employment_periods=employment_periods, overhead=overhead)
        truck_ids = ({day.truck_id for day in days if day.truck_id is not None}
                     | {row.truck_id for row in fuel_entries}
                     | {issue["truck_id"] for issue in issues if issue.get("truck_id") is not None})
        trucks = Truck.query.filter(Truck.id.in_(truck_ids)).order_by(Truck.id).all() if truck_ids else []

    jobs = [job for day in days for job in day.jobs]
    job_earnings = sum(job.earned for job in jobs)
    additional_earnings = sum(day.additional_earned for day in days)
    earnings = job_earnings + additional_earnings
    fuel_spending = sum(row.fuel_cost for row in fuel_entries)
    fuel_volume = sum(row.fuel_volume for row in fuel_entries)
    employer_cost = sum(row.total_cost_to_employer for row in payslips)
    overheads = overhead.total if overhead is not None else None
    result = None
    if period_state == "finished" and overheads is not None and not any(issue["blocking"] for issue in issues):
        result = earnings - fuel_spending - employer_cost - overheads

    driver_data = {driver.id: {
        "driver_id": driver.id, "driver_name": driver.full_name, "recorded_days": 0,
        "working_days": 0, "holiday_days": 0, "absent_days": 0,
        "earnings": 0, "employer_cost": 0, "payslip_ids": [],
    } for driver in drivers}
    for day in days:
        row = driver_data[day.driver_id]
        row["recorded_days"] += 1
        if day.status == "working":
            row["working_days"] += 1
        elif day.status == "holiday":
            row["holiday_days"] += 1
        elif day.status == "absent":
            row["absent_days"] += 1
        row["earnings"] += sum(job.earned for job in day.jobs) + day.additional_earned
    for payslip in payslips:
        driver_data[payslip.driver_id]["employer_cost"] += payslip.total_cost_to_employer
        driver_data[payslip.driver_id]["payslip_ids"].append(payslip.id)
    for row in driver_data.values():
        row["average_earnings_per_working_day"] = Decimal(row["earnings"]) / row["working_days"] if row["working_days"] else None
    driver_names = {driver.id: driver.full_name for driver in drivers}
    truck_names = {truck.id: truck.registration for truck in trucks}
    truck_data = {truck_id: {"truck_id": truck_id,
                            "truck_registration": truck_names.get(truck_id, f"Truck {truck_id}"),
                            "fuel_spending": 0, "fuel_volume": 0, "fuel_entry_count": 0}
                  for truck_id in sorted(truck_ids)}
    for row in fuel_entries:
        truck_data[row.truck_id]["fuel_spending"] += row.fuel_cost
        truck_data[row.truck_id]["fuel_volume"] += row.fuel_volume
        truck_data[row.truck_id]["fuel_entry_count"] += 1
    absence_summary = []
    for driver_id in sorted(driver_data):
        holiday = sorted(day.date for day in days if day.driver_id == driver_id and day.status == "holiday")
        absent = sorted(day.date for day in days if day.driver_id == driver_id and day.status == "absent")
        if holiday or absent:
            absence_summary.append({"driver_id": driver_id, "driver_name": driver_names[driver_id],
                                    "holiday_days": len(holiday), "absent_days": len(absent),
                                    "holiday_dates": holiday, "absent_dates": absent})

    def day_label(day):
        return f"{driver_names.get(day.driver_id, 'Driver')} — {day.date:%d %b %Y}"

    day_by_id = {day.id: day for day in days}
    record_labels = {
        "day": {day.id: day_label(day) for day in days},
        "job": {job.id: f"{day_label(day_by_id[job.day_id])}: {job.collection} → {job.delivery}" for job in jobs},
        "fuel": {row.id: f"{truck_names.get(row.truck_id, 'Truck')} — {row.date:%d %b %Y}" for row in fuel_entries},
        "payslip": {row.id: f"{driver_names.get(row.driver_id, 'Driver')} — {row.date:%d %b %Y}" for row in payslips},
    }
    for issue in issues:
        if issue.get("driver_id") in driver_names:
            issue["driver_name"] = driver_names[issue["driver_id"]]
        if issue.get("truck_id") in truck_names:
            issue["truck_registration"] = truck_names[issue["truck_id"]]
        if issue.get("record_id") is not None:
            if issue["code"] == "job_amount_out_of_range":
                record_type = "job"
            elif issue["code"] in {"fuel_amount_out_of_range", "fuel_price_unusual", "possible_duplicate_fuel"}:
                record_type = "fuel"
            elif issue["code"] in {"payslip_amount_out_of_range", "employer_cost_below_wage", "payroll_gap_unusual"}:
                record_type = "payslip"
            else:
                record_type = "day"
            issue["record_type"] = record_type
            issue["record_label"] = record_labels[record_type][issue["record_id"]]
        else:
            label = issue.get("driver_name") or issue.get("truck_registration")
            if label and issue.get("date") is not None:
                label += f" — {issue['date']:%d %b %Y}"
            issue["record_label"] = label or "Weekly overhead settings"
    return {
        "week_start": week_start, "week_end": end_date, "as_of": as_of,
        "recorded_through": recorded_through if recorded_through >= week_start else None,
        "period_state": period_state, "earnings": earnings, "job_earnings": job_earnings,
        "additional_earnings": additional_earnings, "fuel_spending": fuel_spending, "fuel_volume": fuel_volume,
        "employer_cost": employer_cost, "overheads": overheads,
        "overhead_settings": {"truck_count": overhead.truck_count, "allowance_per_truck": overhead.allowance_per_truck,
                              "source_setting_id": overhead.source_setting_id} if overhead is not None else None,
        "estimated_operating_result": result, "issues": issues,
        "check_state": "needs_review" if issues else "not_reviewed", "drivers": driver_data, "trucks": truck_data,
        "driver_names": driver_names, "truck_names": truck_names, "record_labels": record_labels,
        "absence_summary": absence_summary,
        "review_basis": _review_basis(week_start, end_date, days=days, jobs=jobs, fuel_entries=fuel_entries,
                                      payslips=payslips, employment_periods=employment_periods, overhead=overhead),
        "record_counts": {"days": len(days), "jobs": len(jobs), "fuel_entries": len(fuel_entries), "payslips": len(payslips)},
        "source_records": {"day_ids": [day.id for day in days], "job_ids": sorted(job.id for job in jobs),
                           "fuel_ids": [row.id for row in fuel_entries], "payslip_ids": [row.id for row in payslips],
                           "overhead_source_setting_id": overhead.source_setting_id if overhead is not None else None},
    }
