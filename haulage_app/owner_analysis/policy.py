"""Small, shared owner-review rules; no costs or completion are inferred."""

from datetime import date


OPTIONAL_ISSUES = frozenset({
    "working_day_without_truck", "missing_mileage", "mileage_end_before_start",
})

# Deliberately generous typo bounds, in pence per litre. Recorded purchases are
# not a measure of consumption, and legitimate exceptions remain reviewable.
FUEL_PRICE_MIN_PENCE_PER_LITRE = 50
FUEL_PRICE_MAX_PENCE_PER_LITRE = 300
PAYROLL_GAP_MULTIPLIER = 5
PAYROLL_GAP_MIN_PENCE = 20000


def normalize_fuel_provider(value):
    """Compare provider labels without case or spacing differences."""
    return " ".join((value or "").split()).casefold()


def review_schedule(week_end, as_of):
    """Use the following Friday–Monday for days, payroll and fuel alike.

    Dates at the calendar limit are clamped so a valid final payroll week can
    still be displayed. Passing the deadline never verifies missing records.
    """
    if type(week_end) is not date or type(as_of) is not date:
        raise ValueError("Review dates must be calendar dates")
    if week_end.weekday() != 4:
        raise ValueError("Payroll weeks must end on a Friday")
    last_ordinal = date.max.toordinal()
    window_start = date.fromordinal(min(week_end.toordinal() + 7, last_ordinal))
    due = date.fromordinal(min(week_end.toordinal() + 10, last_ordinal))
    return {
        "review_window_start": window_start,
        "review_due_date": due,
        "review_overdue": as_of > due,
    }
