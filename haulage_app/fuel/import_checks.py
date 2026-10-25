"""Read-only checks for selected fuel import rows, without retaining a draft."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
import re

from flask import url_for
from sqlalchemy import tuple_

from haulage_app import db
from haulage_app.fuel.import_profiles import get_supplier
from haulage_app.models import Fuel, Truck
from haulage_app.owner_analysis.policy import (
    FUEL_PRICE_MAX_PENCE_PER_LITRE,
    FUEL_PRICE_MIN_PENCE_PER_LITRE,
    normalize_fuel_provider,
)


MAX_CHECK_BYTES = 2 * 1024 * 1024
MAX_CHECK_ROWS = 10_000
MAX_SOURCE_ROW = 10_050
MAX_TRUCK_ID = 2_147_483_647
MAX_EXISTING_ENTRIES = 20_000
LOOKUP_PAIR_CHUNK = 250
FUEL_CARD_NAME = "The Fuel Store"
_PROVIDER = normalize_fuel_provider(FUEL_CARD_NAME)
_AMOUNT = re.compile(r"-?[0-9]{1,12}(?:\.[0-9]{1,2})?\Z")
_ROW_KEYS = frozenset({"source_row", "truck_id", "date", "quantity", "cost"})
_ERRORS = {
    "invalid_check": (400, "Choose valid fuel entries with a purchase date, truck, litres and cost."),
    "checks_too_large": (422, "Too many recorded fuel entries match this selection. Select fewer entries and check again."),
}


class ImportCheckInputError(ValueError):
    """Fixed client-facing errors; never include submitted or stored values."""

    def __init__(self, code="invalid_check"):
        self.code = code
        self.status, message = _ERRORS[code]
        super().__init__(message)


@dataclass(frozen=True)
class _SelectedFuelRow:
    source_row: int
    truck_id: int
    date: date
    quantity: int
    cost: int

    @property
    def pair(self):
        return self.truck_id, self.date

    @property
    def signature(self):
        return self.signature_for(_PROVIDER)

    def signature_for(self, provider):
        return self.truck_id, self.date, provider, self.quantity, self.cost


def _hundredths(value):
    """Parse source pounds/litres exactly; floats and exponent notation fail."""
    if not isinstance(value, str) or len(value) > 32 or not _AMOUNT.fullmatch(value):
        raise ImportCheckInputError()
    negative = value.startswith("-")
    whole, _, fraction = value.lstrip("-").partition(".")
    amount = int(whole) * 100 + int(fraction.ljust(2, "0"))
    return -amount if negative else amount


def _display_hundredths(value):
    # Stored fuel columns are integer hundredths. Never re-run the model's
    # float-to-database validators or round an existing value through a float.
    sign = "-" if value < 0 else ""
    whole, fraction = divmod(abs(value), 100)
    return f"{sign}{whole}.{fraction:02d}"


def _validated_rows(payload):
    if (not isinstance(payload, dict) or set(payload) != {"rows"}
            or not isinstance(payload["rows"], list)
            or len(payload["rows"]) > MAX_CHECK_ROWS):
        raise ImportCheckInputError()
    rows, source_rows = [], set()
    for row in payload["rows"]:
        if (not isinstance(row, dict) or set(row) != _ROW_KEYS
                or type(row["source_row"]) is not int
                or not 0 < row["source_row"] <= MAX_SOURCE_ROW
                or row["source_row"] in source_rows
                or type(row["truck_id"]) is not int
                or not 0 < row["truck_id"] <= MAX_TRUCK_ID
                or not isinstance(row["date"], str) or len(row["date"]) != 10):
            raise ImportCheckInputError()
        try:
            on_date = date.fromisoformat(row["date"])
            if on_date.isoformat() != row["date"]:
                raise ValueError("Non-canonical date")
        except (ValueError, OverflowError):
            raise ImportCheckInputError() from None
        rows.append(_SelectedFuelRow(
            source_row=row["source_row"], truck_id=row["truck_id"], date=on_date,
            quantity=_hundredths(row["quantity"]), cost=_hundredths(row["cost"]),
        ))
        source_rows.add(row["source_row"])
    return rows


def _database_context(rows, provider=_PROVIDER):
    """Bound lookups by exact truck/date pairs and total returned records."""
    truck_ids = sorted({row.truck_id for row in rows})
    available = set()
    entries_by_pair = {}
    signatures = set()
    with db.session.no_autoflush:
        # Chunk even the truck lookup so SQLite and PostgreSQL use modest
        # parameter lists when a large export includes many different trucks.
        for start in range(0, len(truck_ids), LOOKUP_PAIR_CHUNK):
            available.update(truck.id for truck in db.session.query(Truck.id).filter(
                Truck.id.in_(truck_ids[start:start + LOOKUP_PAIR_CHUNK]),
            ).all())
        pairs = sorted({row.pair for row in rows if row.truck_id in available})
        entries_by_pair = {pair: [] for pair in pairs}
        count = 0
        for start in range(0, len(pairs), LOOKUP_PAIR_CHUNK):
            # Column results reflect stored values, even if an unrelated ORM
            # object has an unflushed edit. Do not load or guess a Day relation.
            entries = db.session.query(
                Fuel.id, Fuel.truck_id, Fuel.date, Fuel.fuel_card_name,
                Fuel.fuel_volume, Fuel.fuel_cost,
            ).filter(
                tuple_(Fuel.truck_id, Fuel.date).in_(pairs[start:start + LOOKUP_PAIR_CHUNK]),
            ).order_by(Fuel.truck_id, Fuel.date, Fuel.id).limit(
                MAX_EXISTING_ENTRIES - count + 1,
            ).all()
            count += len(entries)
            if count > MAX_EXISTING_ENTRIES:
                # A complete result or a fixed failure: never truncate a group
                # and accidentally report that a potential duplicate is absent.
                raise ImportCheckInputError("checks_too_large")
            for entry in entries:
                entries_by_pair[(entry.truck_id, entry.date)].append({
                    "id": entry.id,
                    "fuel_card_name": entry.fuel_card_name,
                    "same_supplier": normalize_fuel_provider(entry.fuel_card_name) == provider,
                    "quantity": _display_hundredths(entry.fuel_volume),
                    "cost": _display_hundredths(entry.fuel_cost),
                    "review_url": url_for("fuel.add_fuel", item_id=entry.id, tab="edit"),
                })
                if entry.fuel_volume > 0 and entry.fuel_cost > 0:
                    signatures.add((entry.truck_id, entry.date,
                                    normalize_fuel_provider(entry.fuel_card_name),
                                    entry.fuel_volume, entry.fuel_cost))
    return available, entries_by_pair, signatures


def check_fuel_for_preview(payload, supplier_id=None):
    """Check the current selection without changing, saving or excluding it.

    Matching purchase details are candidates, not proof of a duplicate: the
    legacy Fuel model has no invoice transaction ID or purchase time. Different
    fills on the same truck/date are context rather than duplicate warnings.
    """
    supplier = get_supplier(supplier_id)
    provider = normalize_fuel_provider(supplier.label)
    rows = _validated_rows(payload)
    available, existing_by_pair, stored_signatures = _database_context(rows, provider)
    by_signature = defaultdict(list)
    for row in rows:
        if row.truck_id in available and row.quantity > 0 and row.cost > 0:
            by_signature[row.signature_for(provider)].append(row.source_row)
    duplicate_groups = sorted(
        ({"source_rows": sorted(source_rows)} for source_rows in by_signature.values()
         if len(source_rows) > 1),
        key=lambda group: group["source_rows"][0],
    )
    duplicated_rows = {source_row for group in duplicate_groups for source_row in group["source_rows"]}

    checked = []
    for row in rows:
        issues = []
        if row.truck_id not in available:
            issues.append("truck_unavailable")
        valid_amounts = 100 < row.quantity < 100_000 and 100 < row.cost < 150_000
        if not valid_amounts:
            issues.append("fuel_amount_out_of_range")
        elif not (FUEL_PRICE_MIN_PENCE_PER_LITRE * row.quantity
                  <= row.cost * 100
                  <= FUEL_PRICE_MAX_PENCE_PER_LITRE * row.quantity):
            issues.append("fuel_price_unusual")
        if row.source_row in duplicated_rows:
            issues.append("possible_duplicate_upload")
        if row.truck_id in available and row.signature_for(provider) in stored_signatures:
            issues.append("possible_duplicate_fuel")
        checked.append({
            "source_row": row.source_row, "truck_id": row.truck_id,
            "date": row.date.isoformat(),
            "quantity": _display_hundredths(row.quantity),
            "cost": _display_hundredths(row.cost),
            "issues": issues,
        })
    return {
        "fuel_card_name": supplier.label,
        "rows": checked,
        # Membership appears once per group, avoiding quadratic output for an
        # export containing many rows with the same purchase details.
        "duplicate_groups": duplicate_groups,
        "existing_fuel": [
            {"truck_id": truck_id, "date": on_date.isoformat(), "entries": entries}
            for (truck_id, on_date), entries in existing_by_pair.items()
        ],
    }
