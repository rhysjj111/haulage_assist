"""Canonical Saturday–Friday payroll dates, independent of week numbers."""

from calendar import monthrange
from datetime import date, datetime, timedelta


def _validate_date(value):
    if not isinstance(value, date) or isinstance(value, datetime):
        raise ValueError("Please supply a calendar date")
    return value


def payroll_week_start(value):
    """Return the Saturday on or before a calendar date."""
    value = _validate_date(value)
    try:
        return value - timedelta(days=(value.weekday() - 5) % 7)
    except OverflowError as error:
        raise ValueError("This payroll week is outside the supported calendar") from error


def validate_week_start(value):
    value = _validate_date(value)
    if value.weekday() != 5:
        raise ValueError("Payroll weeks must start on a Saturday")
    return value


def week_end(week_start):
    try:
        return validate_week_start(week_start) + timedelta(days=6)
    except OverflowError as error:
        raise ValueError("This payroll week is outside the supported calendar") from error


def _validate_month(year, month):
    if type(year) is not int or type(month) is not int:
        raise ValueError("Please supply a valid calendar year and month")
    try:
        return date(year, month, 1)
    except (ValueError, OverflowError) as error:
        raise ValueError("Please supply a valid calendar year and month") from error


def payroll_month_for_week(week_start):
    """Assign a complete payroll week to the month containing its Tuesday."""
    validate_week_start(week_start)
    try:
        return (week_start + timedelta(days=3)).replace(day=1)
    except OverflowError as error:
        raise ValueError("This payroll week is outside the supported calendar") from error


def payroll_weeks_for_month(year, month):
    """Generate four or five expected weeks, including weeks with no entries."""
    first = _validate_month(year, month)
    first_tuesday = 1 + (1 - first.weekday()) % 7
    try:
        return [date(year, month, day) - timedelta(days=3)
                for day in range(first_tuesday, monthrange(year, month)[1] + 1, 7)]
    except OverflowError as error:
        raise ValueError("This payroll month is outside the supported calendar") from error


def shift_month(month_start, offset):
    _validate_date(month_start)
    if month_start.day != 1 or type(offset) is not int:
        raise ValueError("Please supply a first-of-month date and whole month offset")
    shifted = (month_start.year - 1) * 12 + month_start.month - 1 + offset
    if not 0 <= shifted < 9999 * 12:
        raise ValueError("The requested month is outside the supported calendar")
    return date(shifted // 12 + 1, shifted % 12 + 1, 1)
