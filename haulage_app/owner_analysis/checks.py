"""Read-only checks for one payroll week, independent of dismissed alerts."""

from collections import defaultdict
from datetime import date, timedelta

from haulage_app.owner_analysis.dates import validate_week_start, week_end
from haulage_app.verification.checks.period_rules import missing_fuel_dates


def build_weekly_checks(week_start, *, as_of, days, fuel_entries, payslips, employment_periods, overhead):
    """Check omissions without treating a blank day as absence or guessing costs."""
    validate_week_start(week_start)
    if type(as_of) is not date:
        raise ValueError("as_of must be a calendar date")
    end = week_end(week_start)
    days = [day for day in days if week_start <= day.date <= end]
    fuel_entries = [entry for entry in fuel_entries if week_start <= entry.date <= end]
    payslips = [entry for entry in payslips if week_start <= entry.date <= end]
    issues = []

    def add(code, message, *, blocking=True, **details):
        identity = [code, week_start.isoformat()]
        for name in ("driver_id", "truck_id", "date", "record_id"):
            if details.get(name) is not None:
                identity.append(f"{name}={details[name]}")
        issues.append(dict(code=code, key=":".join(identity), message=message, blocking=blocking, **details))

    employed_dates = defaultdict(set)
    for period in employment_periods:
        start, stop = max(week_start, period.start_date), min(end, period.end_date or end)
        for offset in range((stop - start).days + 1):
            employed_dates[period.driver_id].add(start + timedelta(days=offset))
    present_dates = {(day.driver_id, day.date) for day in days}
    for driver_id, dates in sorted(employed_dates.items()):
        for expected in sorted(dates):
            if expected.weekday() < 5 and expected < as_of and (driver_id, expected) not in present_dates:
                add("missing_day", "Day entry missing; absence has not been recorded.", driver_id=driver_id, date=expected)
    for day in days:
        if day.date >= as_of:
            continue
        if day.status not in {"working", "holiday", "absent"}:
            add("invalid_day_status", "Day status needs checking.", driver_id=day.driver_id, date=day.date, record_id=day.id)
        if day.status == "working":
            if not day.jobs and not day.additional_earned:
                add("working_day_without_earnings", "Working day has no job or additional earnings; please check.",
                    driver_id=day.driver_id, date=day.date, record_id=day.id)
            if day.truck_id is None:
                add("working_day_without_truck", "Working day has no recorded truck.", blocking=False,
                    driver_id=day.driver_id, date=day.date, record_id=day.id)
            if day.start_mileage <= 0 or day.end_mileage <= 0:
                add("missing_mileage", "Working day is missing a mileage reading.", blocking=False,
                    driver_id=day.driver_id, date=day.date, record_id=day.id)
            elif day.end_mileage < day.start_mileage:
                add("mileage_end_before_start", "End mileage is below start mileage; check the readings or truck change.",
                    blocking=False, driver_id=day.driver_id, date=day.date, record_id=day.id)
        elif day.jobs or day.additional_earned:
            add("earnings_on_nonworking_day", "A Holiday/Absent day also has earnings; please check.",
                driver_id=day.driver_id, date=day.date, record_id=day.id)
        for job in day.jobs:
            if not 100 < job.earned < 200000:
                add("job_amount_out_of_range", "Job earnings are outside the entry form's permitted range.",
                    driver_id=day.driver_id, date=day.date, record_id=job.id)

    expected_fuel, purchased_fuel = defaultdict(set), defaultdict(set)
    for day in days:
        if day.fuel and day.date < as_of:
            if day.truck_id is None:
                add("fuel_flag_without_truck", "Fuel is marked as purchased but no truck is recorded.",
                    driver_id=day.driver_id, date=day.date, record_id=day.id)
            else:
                expected_fuel[day.truck_id].add(day.date)
    for entry in fuel_entries:
        purchased_fuel[entry.truck_id].add(entry.date)
        if not 100 < entry.fuel_cost < 150000 or not 100 < entry.fuel_volume < 100000:
            add("fuel_amount_out_of_range", "Fuel cost or volume is outside the entry form's permitted range.",
                truck_id=entry.truck_id, date=entry.date, record_id=entry.id)
    for truck_id, dates in sorted(expected_fuel.items()):
        for missing in missing_fuel_dates(dates, purchased_fuel[truck_id]):
            add("missing_fuel_receipt", "Fuel was marked as purchased but no receipt matches this truck and date.",
                truck_id=truck_id, date=missing)

    by_driver = defaultdict(list)
    for entry in payslips:
        by_driver[entry.driver_id].append(entry)
        if not 100 < entry.total_wage < 300000 or not 100 < entry.total_cost_to_employer < 300000:
            add("payslip_amount_out_of_range", "Payslip amounts are outside the entry form's permitted range.",
                driver_id=entry.driver_id, date=entry.date, record_id=entry.id)
        if entry.total_cost_to_employer < entry.total_wage:
            add("employer_cost_below_wage", "Employer cost is below the recorded wage; please check.",
                driver_id=entry.driver_id, date=entry.date, record_id=entry.id)
    if as_of > end:
        expected_payroll = set(employed_dates) | {day.driver_id for day in days}
        for driver_id in sorted(expected_payroll):
            if not by_driver[driver_id]:
                add("missing_payslip", "Employer wage cost has not been entered for this week.", driver_id=driver_id)
    for driver_id, entries in sorted(by_driver.items()):
        if len(entries) > 1:
            add("multiple_payslips", "More than one payslip is recorded for this driver and week.", driver_id=driver_id)
    if overhead is None:
        add("missing_overhead_settings", "Truck count and weekly overhead allowance have not been configured.")
    return issues
