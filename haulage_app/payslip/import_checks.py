"""Read-only lookups for the payroll PDF review, without retaining a draft."""

from datetime import date
from decimal import Decimal

from flask import url_for

from haulage_app import db
from haulage_app.driver.choices import get_entry_drivers
from haulage_app.models import Payslip
from haulage_app.owner_analysis.dates import validate_week_start, week_end


MAX_CHECK_BYTES = 32_768
MAX_CHECK_DRIVER_IDS = 500


class ImportCheckInputError(ValueError):
    """Fixed client-facing input errors, never supplied payroll contents."""

    def __init__(self, *, inactive_driver=False):
        self.code = "driver_unavailable" if inactive_driver else "invalid_check"
        self.status = 422 if inactive_driver else 400
        message = ("A selected driver is no longer available. Read the PDF again to refresh driver choices."
                   if inactive_driver else "Choose a valid payroll week and driver selections.")
        super().__init__(message)


def _validated_selection(payload):
    if not isinstance(payload, dict) or set(payload) != {"week_start", "driver_ids"}:
        raise ImportCheckInputError()
    raw_start = payload["week_start"]
    ids = payload["driver_ids"]
    if (not isinstance(raw_start, str) or len(raw_start) != 10
            or not isinstance(ids, list) or len(ids) > MAX_CHECK_DRIVER_IDS
            or any(type(driver_id) is not int or driver_id <= 0 for driver_id in ids)):
        raise ImportCheckInputError()
    try:
        start = date.fromisoformat(raw_start)
        if start.isoformat() != raw_start:
            raise ValueError("Non-canonical date")
        validate_week_start(start)
        end = week_end(start)
    except (ValueError, OverflowError):
        raise ImportCheckInputError() from None
    return start, end, sorted(set(ids))


def existing_payslips_for_preview(payload):
    """Return existing records for a bounded set of current active drivers.

    Use the actual date range rather than the historical generated week number;
    this also distinguishes different years and returns legacy duplicate rows.
    Neither an uploaded report nor edited amounts are needed for this lookup.
    """
    start, end, driver_ids = _validated_selection(payload)
    grouped = {driver_id: [] for driver_id in driver_ids}
    with db.session.no_autoflush:
        if driver_ids:
            active_ids = {driver.id for driver in get_entry_drivers()}
            if not set(driver_ids).issubset(active_ids):
                raise ImportCheckInputError(inactive_driver=True)
            # Column results reflect stored values without reusing a dirty ORM
            # Payslip object, flushing pending edits, or loading relationships.
            entries = db.session.query(
                Payslip.id, Payslip.date, Payslip.driver_id,
                Payslip.total_wage, Payslip.total_cost_to_employer,
            ).filter(
                Payslip.driver_id.in_(driver_ids),
                Payslip.date >= start,
                Payslip.date <= end,
            ).order_by(Payslip.driver_id, Payslip.date, Payslip.id).all()
            for entry in entries:
                grouped[entry.driver_id].append({
                    "id": entry.id,
                    "date": entry.date.isoformat(),
                    "total_wage": format(Decimal(entry.total_wage) / 100, ".2f"),
                    "total_cost_to_employer": format(Decimal(entry.total_cost_to_employer) / 100, ".2f"),
                    "review_url": url_for("payslip.add_payslip", item_id=entry.id, tab="edit"),
                })
    return {
        "week_start": start.isoformat(),
        "week_end": end.isoformat(),
        "existing_payslips": [
            {"driver_id": driver_id, "payslips": entries}
            for driver_id, entries in grouped.items()
        ],
    }
