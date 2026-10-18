"""Read-only payroll-month aggregation; whole weeks are assigned by Tuesday."""

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from haulage_app.owner_analysis.dates import payroll_weeks_for_month, week_end
from haulage_app.owner_analysis.reviews import get_reviewed_week


def get_monthly_report(year, month, *, as_of=None):
    """Include every finished expected week, preserving unknown costs/results."""
    expected = payroll_weeks_for_month(year, month)
    if as_of is None:
        as_of = datetime.now(ZoneInfo("Europe/London")).date()
    if type(as_of) is not date:
        raise ValueError("as_of must be a calendar date")
    month_start = date(year, month, 1)
    expected_start, expected_end = expected[0], week_end(expected[-1])
    completed = [start for start in expected if week_end(start) < as_of]
    pending = [start for start in expected if week_end(start) >= as_of]
    weeks = [get_reviewed_week(start, as_of=as_of) for start in completed]
    active_week = next((start for start in pending if start <= as_of <= week_end(start)), None)
    period_state = "future" if as_of < expected_start else "in_progress" if as_of <= expected_end else "finished"
    outstanding = [dict(issue, week_start=week["week_start"], week_end=week["week_end"])
                   for week in weeks for issue in week["outstanding_issues"]]
    optional = [dict(issue, week_start=week["week_start"], week_end=week["week_end"])
                for week in weeks for issue in week["optional_issues"]]
    history = [dict(entry, week_start=week["week_start"], week_end=week["week_end"])
               for week in weeks for entry in week["verification_history"]]
    all_checked = bool(weeks) and all(week["review_status"] == "checked" for week in weeks)
    if any(week["review_status"] in {"needs_review", "outdated"} for week in weeks):
        review_status = "needs_review"
    elif outstanding:
        review_status = "awaiting_records"
    elif all_checked:
        review_status = "checked"
    else:
        review_status = "not_reviewed"
    absences, drivers, trucks = {}, {}, {}
    for week in weeks:
        for row in week["absence_summary"]:
            item = absences.setdefault(row["driver_id"], {"driver_id": row["driver_id"],
                "driver_name": row["driver_name"], "holiday_dates": set(), "absent_dates": set()})
            item["holiday_dates"].update(row["holiday_dates"])
            item["absent_dates"].update(row["absent_dates"])
        for driver_id, row in week.get("drivers", {}).items():
            item = drivers.setdefault(driver_id, {"driver_id": driver_id, "driver_name": row["driver_name"],
                "recorded_days": 0, "working_days": 0, "holiday_days": 0, "absent_days": 0,
                "earnings": 0, "employer_cost": 0, "payslip_ids": []})
            for field in ("recorded_days", "working_days", "holiday_days", "absent_days", "earnings", "employer_cost"):
                item[field] += row[field]
            item["payslip_ids"].extend(row["payslip_ids"])
        for truck_id, row in week.get("trucks", {}).items():
            item = trucks.setdefault(truck_id, {"truck_id": truck_id, "truck_registration": row["truck_registration"],
                                               "fuel_spending": 0, "fuel_volume": 0, "fuel_entry_count": 0})
            for field in ("fuel_spending", "fuel_volume", "fuel_entry_count"):
                item[field] += row[field]
    absence_summary = [{"driver_id": driver_id, "driver_name": row["driver_name"],
                        "holiday_dates": sorted(row["holiday_dates"]), "absent_dates": sorted(row["absent_dates"]),
                        "holiday_days": len(row["holiday_dates"]), "absent_days": len(row["absent_dates"])}
                       for driver_id, row in sorted(absences.items())]
    for row in drivers.values():
        row["average_earnings_per_working_day"] = Decimal(row["earnings"]) / row["working_days"] if row["working_days"] else None
    overheads, result = None, None
    if weeks:
        if all(week["overheads"] is not None for week in weeks):
            overheads = sum(week["overheads"] for week in weeks)
        if all(week["estimated_operating_result"] is not None for week in weeks):
            result = sum(week["estimated_operating_result"] for week in weeks)
    return {
        "month_start": month_start, "month_name": month_start.strftime("%B"), "year": year, "month": month,
        "as_of": as_of, "expected_week_starts": expected, "expected_week_count": len(expected),
        "completed_week_count": len(weeks), "weeks": weeks, "pending_week_starts": pending, "active_week": active_week,
        "expected_start": expected_start, "expected_end": expected_end,
        "covered_start": completed[0] if completed else None,
        "covered_end": week_end(completed[-1]) if completed else None,
        "period_state": period_state, "review_status": review_status,
        "reviewed_through": week_end(completed[-1]) if all_checked else None,
        "earnings": sum(week["earnings"] for week in weeks),
        "fuel_spending": sum(week["fuel_spending"] for week in weeks),
        "fuel_volume": sum(week.get("fuel_volume", 0) for week in weeks),
        "employer_cost": sum(week["employer_cost"] for week in weeks),
        "overheads": overheads, "estimated_operating_result": result,
        "absence_summary": absence_summary, "outstanding_issues": outstanding, "optional_issues": optional,
        "all_outstanding_issues": outstanding + optional, "verification_history": history,
        "outstanding_count": len(outstanding), "optional_check_count": len(optional),
        "drivers": dict(sorted(drivers.items())), "trucks": dict(sorted(trucks.items())),
    }
