"""Small deterministic rules shared by owner checks and legacy verification."""


def missing_fuel_dates(expected_dates, purchased_dates):
    """Compare dates directly so extra receipts cannot hide an absent date."""
    return sorted(set(expected_dates) - set(purchased_dates))
