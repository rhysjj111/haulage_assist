"""Payroll dates and isolated owner overhead settings/snapshot contracts."""

from datetime import date, timedelta
from unittest.mock import patch

from owner_test_support import OwnerDatabaseTestCase, db
from haulage_app.owner_analysis.dates import (
    payroll_month_for_week, payroll_week_start, payroll_weeks_for_month,
    shift_month, validate_week_start, week_end,
)
from haulage_app.owner_analysis.overheads import (
    ensure_weekly_overhead, get_weekly_overhead, overhead_settings_fingerprint,
    set_overhead_settings,
)
from haulage_app.owner_analysis.models import OwnerWeeklyOverhead


class OwnerOverheadTests(OwnerDatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.start = date(2026, 1, 3)

    def test_payroll_week_is_saturday_through_friday(self):
        for offset in range(7):
            self.assertEqual(payroll_week_start(self.start + timedelta(days=offset)), self.start)
        self.assertEqual(week_end(self.start), date(2026, 1, 9))
        self.assertEqual(payroll_week_start(date(2026, 1, 2)), date(2025, 12, 27))

    def test_only_saturdays_are_accepted_as_week_starts(self):
        self.assertEqual(validate_week_start(self.start), self.start)
        for value in (date(2026, 1, 4), None, "2026-01-03"):
            with self.subTest(value=value), self.assertRaises((TypeError, ValueError)):
                validate_week_start(value)

    def test_month_belongs_to_tuesday_not_start_or_end_date(self):
        self.assertEqual(payroll_month_for_week(date(2026, 1, 31)), date(2026, 2, 1))
        self.assertEqual(payroll_month_for_week(date(2025, 12, 27)), date(2025, 12, 1))
        self.assertEqual(payroll_month_for_week(date(2025, 12, 27)) + timedelta(days=31),
                         date(2026, 1, 1))

    def test_calendar_includes_four_and_five_week_months_and_year_boundary(self):
        self.assertEqual(payroll_weeks_for_month(2026, 2), [
            date(2026, 1, 31), date(2026, 2, 7), date(2026, 2, 14), date(2026, 2, 21),
        ])
        self.assertEqual(len(payroll_weeks_for_month(2026, 3)), 5)
        self.assertEqual(payroll_weeks_for_month(2025, 12)[-1], date(2025, 12, 27))
        self.assertEqual(shift_month(date(2026, 1, 1), -1), date(2025, 12, 1))
        self.assertEqual(shift_month(date(2025, 12, 1), 1), date(2026, 1, 1))

    def test_unset_overheads_are_unknown_and_read_does_not_create_rows(self):
        self.assertIsNone(get_weekly_overhead(self.start))
        self.assertIsNone(ensure_weekly_overhead(self.start))
        self.assertEqual(list(db.session.new), [])

    def test_explicit_snapshot_keeps_unused_trucks_in_allowance(self):
        set_overhead_settings(self.start, 4, 50000)
        row = ensure_weekly_overhead(self.start)
        self.assertEqual(row.truck_count, 4)
        self.assertEqual(row.allowance_per_truck, 50000)
        self.assertEqual(get_weekly_overhead(self.start).total, 200000)

    def test_zero_is_a_valid_setting_and_differs_from_unset(self):
        set_overhead_settings(self.start, 0, 0)
        row = ensure_weekly_overhead(self.start)
        self.assertIsNotNone(row)
        self.assertEqual(row.total, 0)

    def test_read_resolves_policy_without_freezing_or_creating_a_snapshot(self):
        set_overhead_settings(self.start, 4, 50000)
        row = get_weekly_overhead(self.start + timedelta(days=7))
        self.assertEqual(row.total, 200000)
        self.assertEqual(OwnerWeeklyOverhead.query.count(), 0)

    def test_settings_fingerprint_detects_a_changed_future_policy(self):
        set_overhead_settings(self.start, 4, 50000)
        before = overhead_settings_fingerprint()
        set_overhead_settings(self.start + timedelta(days=28), 5, 60000)
        after = overhead_settings_fingerprint()
        self.assertNotEqual(after, before)
        self.assertEqual(overhead_settings_fingerprint(), after)

    def test_settings_resolve_latest_effective_week_without_historical_backfill(self):
        set_overhead_settings(self.start, 4, 50000)
        set_overhead_settings(self.start + timedelta(days=14), 5, 60000)
        self.assertIsNone(ensure_weekly_overhead(self.start - timedelta(days=7)))
        self.assertEqual(ensure_weekly_overhead(self.start + timedelta(days=7)).total, 200000)
        self.assertEqual(ensure_weekly_overhead(self.start + timedelta(days=14)).total, 300000)

    def test_precreated_later_snapshots_refresh_but_later_scheduled_setting_wins(self):
        set_overhead_settings(self.start, 4, 50000)
        for offset in (0, 7, 14, 21):
            ensure_weekly_overhead(self.start + timedelta(days=offset))
        set_overhead_settings(self.start + timedelta(days=21), 5, 70000)
        set_overhead_settings(self.start + timedelta(days=7), 4, 60000)
        self.assertEqual(get_weekly_overhead(self.start).total, 200000)
        self.assertEqual(get_weekly_overhead(self.start + timedelta(days=7)).total, 240000)
        self.assertEqual(get_weekly_overhead(self.start + timedelta(days=14)).total, 240000)
        self.assertEqual(get_weekly_overhead(self.start + timedelta(days=21)).total, 350000)

    def test_settings_reject_values_outside_postgresql_integer_range(self):
        for count, allowance in [(-1, 50000), (4, -1), (2147483648, 1), (1, 2147483648)]:
            with self.subTest(count=count, allowance=allowance), self.assertRaises(ValueError):
                set_overhead_settings(self.start, count, allowance)
        set_overhead_settings(self.start, 2147483647, 0)
        self.assertEqual(ensure_weekly_overhead(self.start).total, 0)

    def test_setting_and_snapshot_services_never_commit_the_callers_transaction(self):
        with patch.object(db.session, "commit", side_effect=AssertionError("unexpected commit")):
            set_overhead_settings(self.start, 4, 50000)
            ensure_weekly_overhead(self.start)
            get_weekly_overhead(self.start)

