"""Report labels use the included weeks, preserving unknown and explicit zero."""

from copy import deepcopy
from datetime import date, timedelta
import unittest

from owner_test_support import OwnerDatabaseTestCase
from haulage_app.owner_analysis.monthly import get_monthly_report
from haulage_app.owner_analysis.overhead_presentation import build_overhead_basis
from haulage_app.owner_analysis.overheads import set_overhead_settings


class OwnerOverheadPresentationTests(unittest.TestCase):
    def week(self, start, count=4, allowance=50000, *, source=1):
        return {
            "week_start": start,
            "week_end": start + timedelta(days=6),
            "overhead_settings": {
                "truck_count": count,
                "allowance_per_truck": allowance,
                "source_setting_id": source,
            } if count is not None else None,
        }

    def test_explicit_zero_is_a_known_basis(self):
        basis = build_overhead_basis([self.week(date(2026, 1, 3), 0, 0)])
        self.assertEqual(basis["state"], "uniform")
        self.assertEqual((basis["truck_count"], basis["allowance_per_truck"]), (0, 0))

    def test_missing_settings_are_unknown_instead_of_zero(self):
        basis = build_overhead_basis([self.week(date(2026, 1, 3), None)])
        self.assertEqual(basis["state"], "missing")
        self.assertIsNone(basis["truck_count"])
        self.assertIsNone(basis["allowance_per_truck"])

    def test_same_basis_from_distinct_settings_has_one_clear_label(self):
        basis = build_overhead_basis([
            self.week(date(2026, 1, 3), source=1),
            self.week(date(2026, 1, 10), source=2),
        ])
        self.assertEqual(basis["state"], "uniform")
        self.assertEqual(basis["week_count"], 2)

    def test_count_or_allowance_change_keeps_each_weeks_dates_and_values(self):
        weeks = [self.week(date(2026, 1, 3)), self.week(date(2026, 1, 10), 5),
                 self.week(date(2026, 1, 17), 5, 60000)]
        before = deepcopy(weeks)
        basis = build_overhead_basis(weeks)
        self.assertEqual(basis["state"], "mixed")
        self.assertEqual([week["truck_count"] for week in basis["weeks"]], [4, 5, 5])
        self.assertEqual([week["allowance_per_truck"] for week in basis["weeks"]], [50000, 50000, 60000])
        self.assertEqual(basis["weeks"][1]["week_end"], date(2026, 1, 16))
        self.assertEqual(weeks, before)

    def test_partial_configuration_does_not_claim_one_basis_for_all_weeks(self):
        basis = build_overhead_basis([
            self.week(date(2026, 1, 3), None), self.week(date(2026, 1, 10)),
        ])
        self.assertEqual(basis["state"], "mixed")
        self.assertIsNone(basis["truck_count"])
        self.assertIsNone(basis["weeks"][0]["truck_count"])
        self.assertEqual(basis["weeks"][1]["truck_count"], 4)

    def test_no_completed_weeks_does_not_claim_any_settings(self):
        basis = build_overhead_basis([])
        self.assertEqual(basis["state"], "empty")
        self.assertEqual(basis["week_count"], 0)
        self.assertIsNone(basis["truck_count"])
        self.assertEqual(basis["weeks"], [])


class OwnerOverheadPresentationPeriodTests(OwnerDatabaseTestCase):
    def test_monthly_basis_uses_only_completed_weeks_not_current_or_future_changes(self):
        set_overhead_settings(date(2026, 1, 3), 4, 50000)
        set_overhead_settings(date(2026, 1, 17), 5, 60000)
        set_overhead_settings(date(2026, 1, 24), 6, 70000)
        report = get_monthly_report(2026, 1, as_of=date(2026, 1, 20))
        basis = build_overhead_basis(report["weeks"])
        self.assertEqual(basis["state"], "uniform")
        self.assertEqual(basis["week_count"], 2)
        self.assertEqual((basis["truck_count"], basis["allowance_per_truck"]), (4, 50000))
        self.assertEqual(basis["weeks"][-1]["week_end"], date(2026, 1, 16))
