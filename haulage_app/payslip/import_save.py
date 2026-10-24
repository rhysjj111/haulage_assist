"""Validate and atomically save an explicitly reviewed payroll import batch."""

from collections import Counter
from datetime import date
import re

from flask import url_for
from sqlalchemy import insert, select

from haulage_app import db
from haulage_app.driver.choices import get_entry_drivers
from haulage_app.models import Day, Driver, Payslip
from haulage_app.owner_analysis.dates import validate_week_start, week_end
from haulage_app.verification.models import MissingEntryAnomaly, TableName


MAX_SAVE_BYTES = 131_072
MAX_SAVE_ROWS = 500
MAX_ROW_ID = 2_147_483_647
_AMOUNT = re.compile(r"[0-9]+(?:\.[0-9]{1,2})?\Z")
_ROW_KEYS = {"source_index", "driver_id", "total_wage", "total_cost_to_employer"}


class ImportSaveError(ValueError):
    """A fixed safe message, optionally identifying fields needing review."""

    def __init__(self, code="invalid_save", message=None, *, status=400, row_errors=()):
        self.code = code
        self.status = status
        self.row_errors = list(row_errors)
        super().__init__(message or "Choose a valid payroll week and reviewed payslip entries.")


def _row_error(row, field, code, message, **extra):
    return {"source_index": row["source_index"], "driver_id": row["driver_id"],
            "field": field, "code": code, "message": message, **extra}


def _review_error(errors, *, conflict=False):
    return ImportSaveError(
        "review_required", "Check the highlighted entries. Nothing was saved.",
        status=409 if conflict else 422, row_errors=errors,
    )


def _pence(value):
    if not isinstance(value, str) or len(value) > 32 or not _AMOUNT.fullmatch(value):
        return None
    whole, _, fraction = value.partition(".")
    return int(whole) * 100 + int(fraction.ljust(2, "0"))


def _validated_batch(payload):
    if not isinstance(payload, dict) or set(payload) != {"week_start", "rows"}:
        raise ImportSaveError()
    raw_start, rows = payload["week_start"], payload["rows"]
    if (not isinstance(raw_start, str) or len(raw_start) != 10
            or not isinstance(rows, list) or not 1 <= len(rows) <= MAX_SAVE_ROWS):
        raise ImportSaveError()
    try:
        start = date.fromisoformat(raw_start)
        if start.isoformat() != raw_start:
            raise ValueError("Non-canonical date")
        validate_week_start(start)
        end = week_end(start)
    except (ValueError, OverflowError):
        raise ImportSaveError() from None
    for row in rows:
        if (not isinstance(row, dict) or set(row) != _ROW_KEYS
                or any(type(row[key]) is not int or not 0 < row[key] <= MAX_ROW_ID
                       for key in ("source_index", "driver_id"))):
            raise ImportSaveError()
    if len({row["source_index"] for row in rows}) != len(rows):
        raise ImportSaveError()

    counts = Counter(row["driver_id"] for row in rows)
    errors, validated = [], []
    for row in rows:
        if counts[row["driver_id"]] > 1:
            errors.append(_row_error(row, "driver_id", "duplicate_driver",
                                     "Driver selected more than once."))
        amounts = {}
        for field in ("total_wage", "total_cost_to_employer"):
            pence = _pence(row[field])
            if pence is None:
                errors.append(_row_error(row, field, "invalid_amount",
                                         "Use a positive amount with up to 2 decimals."))
            elif not 100 < pence < 300_000:
                errors.append(_row_error(row, field, "amount_out_of_range",
                                         "Enter more than £1 and less than £3,000."))
            else:
                amounts[field] = pence
        if (len(amounts) == 2
                and amounts["total_cost_to_employer"] < amounts["total_wage"]):
            errors.append(_row_error(row, "total_cost_to_employer", "employer_cost_below_wage",
                                     "Employer cost is below total wage."))
        validated.append({"source_index": row["source_index"], "driver_id": row["driver_id"],
                          **amounts})
    if errors:
        raise _review_error(errors)
    return start, end, validated


def _database_review(rows, start, end):
    driver_ids = sorted(row["driver_id"] for row in rows)
    # Import requests lock the same driver rows in the same order before any
    # duplicate lookup. A second importer waits, then sees the first commit.
    # Existing manual entry paths retain their own database constraint checks.
    db.session.execute(select(Driver.id).where(Driver.id.in_(driver_ids))
                       .order_by(Driver.id).with_for_update()).all()
    active_ids = {driver.id for driver in get_entry_drivers()}
    errors = [_row_error(row, "driver_id", "driver_unavailable",
                         "This driver is no longer available. Refresh driver choices.")
              for row in rows if row["driver_id"] not in active_ids]
    existing = db.session.execute(select(Payslip.id, Payslip.driver_id)
        .where(Payslip.driver_id.in_(driver_ids), Payslip.date >= start, Payslip.date <= end)
        .order_by(Payslip.id)).all()
    existing_by_driver = {}
    for entry in existing:
        existing_by_driver.setdefault(entry.driver_id, entry.id)
    days = db.session.execute(select(Day.id, Day.driver_id)
        .where(Day.driver_id.in_(driver_ids), Day.date == end)
        .order_by(Day.driver_id, Day.id).with_for_update()).all()
    days_by_driver = {driver_id: [] for driver_id in driver_ids}
    for day in days:
        days_by_driver[day.driver_id].append(day.id)
    for row in rows:
        driver_id = row["driver_id"]
        if driver_id not in active_ids:
            continue
        if driver_id in existing_by_driver:
            errors.append(_row_error(row, "existing_payslip", "existing_payslip",
                "A payslip is already recorded for this payroll week.",
                action_url=url_for("payslip.add_payslip", item_id=existing_by_driver[driver_id], tab="edit")))
        day_ids = days_by_driver[driver_id]
        if not day_ids:
            errors.append(_row_error(row, "day", "missing_day",
                "Add this driver's day entry for the Friday ending this week.",
                action_url=url_for("day.add_day", item_id=0, tab="entry")))
        elif len(day_ids) > 1:
            errors.append(_row_error(row, "day", "multiple_days",
                "More than one day entry exists for this driver on the week's Friday."))
    if errors:
        raise _review_error(errors, conflict=any(error["field"] == "existing_payslip" for error in errors))
    return {driver_id: day_ids[0] for driver_id, day_ids in days_by_driver.items()}


def save_reviewed_payslips(payload):
    """Save the entire selected batch once, or roll back every mutation.

    Amounts have already been validated and converted to exact integer pence;
    narrowly scoped Core inserts avoid the legacy model's float conversion.
    No PDF, draft, or imported filename is persisted.
    """
    start, end, rows = _validated_batch(payload)
    if db.session.new or db.session.dirty or db.session.deleted:
        # Do not commit or discard unrelated pending changes from this session.
        raise ImportSaveError("save_unavailable", "The batch could not be saved. Please try again.", status=409)
    try:
        with db.session.no_autoflush:
            days_by_driver = _database_review(rows, start, end)
            saved = []
            for row in rows:
                entry_id = db.session.execute(insert(Payslip.__table__).values(
                    date=end, driver_id=row["driver_id"], day_id=days_by_driver[row["driver_id"]],
                    total_wage=row["total_wage"],
                    total_cost_to_employer=row["total_cost_to_employer"],
                ).returning(Payslip.id)).scalar_one()
                saved.append({"source_index": row["source_index"], "driver_id": row["driver_id"],
                              "id": entry_id, "review_url": url_for(
                                  "payslip.add_payslip", item_id=entry_id, tab="edit")})
            # Match ordinary Add Payslip's exact-date rectification while
            # keeping inherited anomaly/feedback deletion in this transaction.
            anomalies = MissingEntryAnomaly.query.filter(
                MissingEntryAnomaly.table_name == TableName.PAYSLIP,
                MissingEntryAnomaly.driver_id.in_(days_by_driver),
                MissingEntryAnomaly.date == end,
            ).all()
            for anomaly in anomalies:
                db.session.delete(anomaly)
            result = {"saved_count": len(saved), "week_start": start.isoformat(),
                      "week_end": end.isoformat(), "entry_date": end.isoformat(), "payslips": saved,
                      "history_url": url_for("payslip.add_payslip", item_id=0, tab="history")}
        db.session.commit()
        return result
    except Exception:
        db.session.rollback()
        raise
