"""Validate and atomically save an explicitly reviewed fuel import batch."""

from flask import url_for
from sqlalchemy import insert, select, tuple_

from haulage_app import db
from haulage_app.fuel.import_checks import (
    LOOKUP_PAIR_CHUNK, ImportCheckInputError, _display_hundredths,
    _validated_rows, check_fuel_for_preview,
)
from haulage_app.fuel.import_profiles import get_supplier
from haulage_app.models import Day, Fuel, Truck
from haulage_app.verification.models import MissingEntryAnomaly, TableName


MAX_SAVE_BYTES = 524_288
MAX_SAVE_ROWS = 500
SOURCE_ISSUES = frozenset({
    "missing_transaction_registration", "registration_mismatch", "unsupported_product",
    "non_positive_quantity", "non_positive_cost", "cost_price_mismatch",
})
_BASE_KEYS = frozenset({"source_row", "truck_id", "date", "quantity", "cost"})
_ROW_KEYS = _BASE_KEYS | {"product", "source_issues", "review_confirmed"}


class ImportSaveError(ValueError):
    """Fixed safe errors, optionally identifying fields needing review."""

    def __init__(self, code="invalid_save", message=None, *, status=400, row_errors=()):
        self.code = code
        self.status = status
        self.row_errors = list(row_errors)
        super().__init__(message or "Choose valid reviewed fuel entries to save.")


def _row_error(row, field, code, message, **extra):
    return {"source_row": row.source_row, "field": field, "code": code,
            "message": message, **extra}


def _review_error(errors):
    duplicate = any(error["code"] in {"possible_duplicate_upload", "possible_duplicate_fuel"}
                    for error in errors)
    return ImportSaveError(
        "review_required", "Check the highlighted entries. Nothing was saved.",
        status=409 if duplicate else 422, row_errors=errors,
    )


def _validated_batch(payload, supplier):
    if (not isinstance(payload, dict) or set(payload) != {"rows"}
            or not isinstance(payload["rows"], list)
            or not 1 <= len(payload["rows"]) <= MAX_SAVE_ROWS):
        raise ImportSaveError()
    proposed = payload["rows"]
    for row in proposed:
        if (not isinstance(row, dict) or set(row) != _ROW_KEYS
                or not isinstance(row["product"], str)
                or not 0 < len(row["product"]) <= 200 or not row["product"].strip()
                or type(row["review_confirmed"]) is not bool
                or not isinstance(row["source_issues"], list)
                or len(row["source_issues"]) > len(SOURCE_ISSUES)
                or not all(isinstance(issue, str) and issue in SOURCE_ISSUES
                           for issue in row["source_issues"])
                or len(row["source_issues"]) != len(set(row["source_issues"]))):
            raise ImportSaveError()
    base = {"rows": [{key: row[key] for key in _BASE_KEYS} for row in proposed]}
    try:
        rows = _validated_rows(base)
    except ImportCheckInputError:
        raise ImportSaveError() from None
    metadata = {row["source_row"]: row for row in proposed}
    errors = []
    for row in rows:
        source = metadata[row.source_row]
        product = " ".join(source["product"].split()).upper()
        if product not in supplier.diesel_products or "unsupported_product" in source["source_issues"]:
            errors.append(_row_error(row, "product", "unsupported_product",
                "This product cannot be imported as diesel. Exclude this row."))
        if not 100 < row.quantity < 100_000:
            errors.append(_row_error(row, "quantity", "fuel_amount_out_of_range",
                "Enter more than 1 and less than 1,000 litres."))
        if not 100 < row.cost < 150_000:
            errors.append(_row_error(row, "cost", "fuel_amount_out_of_range",
                "Enter more than £1 and less than £1,500."))
    if errors:
        raise _review_error(errors)
    return rows, metadata, base


def _database_review(rows, metadata, base, supplier):
    truck_ids = sorted({row.truck_id for row in rows})
    # Serialize importer batches for these trucks before the final duplicate
    # lookup. Legacy manual forms do not provide a global uniqueness guarantee.
    db.session.execute(select(Truck.id).where(Truck.id.in_(truck_ids))
        .order_by(Truck.id).with_for_update()).all()
    try:
        checked = check_fuel_for_preview(base, supplier.id)
    except ImportCheckInputError as error:
        raise ImportSaveError(error.code, str(error), status=error.status) from None

    # Index stored matches once, rather than scanning a receipt list separately
    # for every selected row. Context is already bounded by the review helper.
    first_matches = {}
    for group in checked["existing_fuel"]:
        for entry in group["entries"]:
            if entry["same_supplier"]:
                signature = (group["truck_id"], group["date"], entry["quantity"], entry["cost"])
                first_matches.setdefault(signature, entry["review_url"])
    results = {row["source_row"]: row for row in checked["rows"]}
    errors = []
    for row in rows:
        issues = results[row.source_row]["issues"]
        if "truck_unavailable" in issues:
            errors.append(_row_error(row, "truck_id", "truck_unavailable",
                "This truck is no longer available. Refresh truck choices."))
        if "fuel_amount_out_of_range" in issues:
            errors.append(_row_error(row, "quantity", "fuel_amount_out_of_range",
                "Check litres and cost against the fuel form's permitted amounts."))
        if "possible_duplicate_upload" in issues:
            errors.append(_row_error(row, "duplicate", "possible_duplicate_upload",
                "Possible duplicate in the selection. Exclude or correct the repeated row."))
        if "possible_duplicate_fuel" in issues:
            signature = (row.truck_id, row.date.isoformat(),
                         _display_hundredths(row.quantity), _display_hundredths(row.cost))
            errors.append(_row_error(row, "duplicate", "possible_duplicate_fuel",
                "Matching fuel is already recorded. Review it and exclude this row.",
                action_url=first_matches[signature]))
        source = metadata[row.source_row]
        if not source["review_confirmed"]:
            if source["source_issues"]:
                errors.append(_row_error(row, "review", "review_required",
                    "Check the source warnings and confirm this entry."))
            elif "fuel_price_unusual" in issues:
                errors.append(_row_error(row, "review", "review_required",
                    "Check the unusual price and confirm this entry."))
    if errors:
        raise _review_error(errors)


def _day_links(pairs):
    links = {pair: None for pair in pairs}
    seen = set()
    for start in range(0, len(pairs), LOOKUP_PAIR_CHUNK):
        days = db.session.execute(select(Day.id, Day.truck_id, Day.date).where(
            tuple_(Day.truck_id, Day.date).in_(pairs[start:start + LOOKUP_PAIR_CHUNK]),
        ).order_by(Day.truck_id, Day.date, Day.id).with_for_update()).all()
        for day in days:
            pair = day.truck_id, day.date
            links[pair] = None if pair in seen else day.id
            seen.add(pair)
    return links


def _rectify_missing_fuel(pairs):
    # ORM deletion removes the joined base anomaly and its feedback in the same
    # transaction. The legacy rectification helper commits each entry itself.
    for start in range(0, len(pairs), LOOKUP_PAIR_CHUNK):
        anomalies = MissingEntryAnomaly.query.filter(
            MissingEntryAnomaly.table_name == TableName.FUEL,
            tuple_(MissingEntryAnomaly.truck_id, MissingEntryAnomaly.date).in_(
                pairs[start:start + LOOKUP_PAIR_CHUNK]),
        ).all()
        for anomaly in anomalies:
            db.session.delete(anomaly)


def save_reviewed_fuel(payload, supplier_id=None):
    """Save a reviewed batch once, or roll back every mutation on failure.

    Exact duplicate candidates cannot be overridden by a confirmation flag.
    This protects importer retries without changing the legacy Fuel schema.
    Purchase amounts remain exact integer hundredths through the Core insert.
    """
    supplier = get_supplier(supplier_id)
    rows, metadata, base = _validated_batch(payload, supplier)
    if db.session.new or db.session.dirty or db.session.deleted:
        # Preserve unrelated pending ORM work: do not commit or roll it back.
        raise ImportSaveError("save_unavailable", "The batch could not be saved. Please try again.", status=409)
    try:
        with db.session.no_autoflush:
            _database_review(rows, metadata, base, supplier)
            pairs = sorted({row.pair for row in rows})
            day_links = _day_links(pairs)
            saved = []
            for row in rows:
                entry_id = db.session.execute(insert(Fuel.__table__).values(
                    date=row.date, truck_id=row.truck_id, day_id=day_links[row.pair],
                    fuel_card_name=supplier.label, fuel_volume=row.quantity, fuel_cost=row.cost,
                ).returning(Fuel.id)).scalar_one()
                saved.append({"source_row": row.source_row, "truck_id": row.truck_id,
                    "date": row.date.isoformat(), "id": entry_id,
                    "review_url": url_for("fuel.add_fuel", item_id=entry_id, tab="edit")})
            _rectify_missing_fuel(pairs)
            result = {"saved_count": len(saved), "fuel_entries": saved,
                      "history_url": url_for("fuel.add_fuel", item_id=0, tab="history")}
        db.session.commit()
        return result
    except Exception:
        db.session.rollback()
        raise
