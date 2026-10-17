"""Monthly analysis aggregates complete payroll weeks, including empty ones."""

from datetime import date, timedelta
from unittest.mock import patch

from owner_test_support import OwnerDatabaseTestCase, db
from haulage_app.models import Job, Payslip
from haulage_app.owner_analysis.dates import payroll_weeks_for_month
from haulage_app.owner_analysis.monthly import get_monthly_report
from haulage_app.owner_analysis.overheads import ensure_weekly_overhead, set_overhead_settings
from haulage_app.owner_analysis.reviews import get_reviewed_week, save_week_review


class OwnerMonthlyTests(OwnerDatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.start = date(2026, 1, 3)
        self.add_truck()
        self.add_driver(employment_start=None)

    def add_complete_week(self, start, *, earnings=100000, fuel=20000, employer=60000):
        day = self.add_day(driver_id=1, on_date=start + timedelta(days=2), fuel=True)
        self.add_job(day, earned=earnings)
        self.add_fuel(truck_id=1, on_date=start + timedelta(days=2), day_id=day,
                      fuel_cost=fuel, fuel_volume=10000)
        self.add_payslip(driver_id=1, on_date=start + timedelta(days=6),
                         total_wage=50000, total_cost_to_employer=employer)
        ensure_weekly_overhead(start)

    def complete_january(self):
        set_overhead_settings(self.start, 4, 50000)
        for start in payroll_weeks_for_month(2026, 1):
            self.add_complete_week(start)
        db.session.flush()

    def report(self, **kwargs):
        return get_monthly_report(2026, 1, as_of=kwargs.get("as_of", date(2026, 2, 7)))

    def mark_week_checked(self, start, *, as_of=date(2026, 2, 7)):
        week = get_reviewed_week(start, as_of=as_of)
        save_week_review(start, week["week_fingerprint"], as_of=as_of)

    def test_finished_month_includes_all_calendar_weeks_including_empty_weeks(self):
        report = self.report()
        self.assertEqual(report["expected_week_count"], 4)
        self.assertEqual(report["completed_week_count"], 4)
        self.assertEqual([week["week_start"] for week in report["weeks"]],
                         payroll_weeks_for_month(2026, 1))
        self.assertIsNone(report["estimated_operating_result"])

    def test_five_week_month_is_generated_without_payslips(self):
        report = get_monthly_report(2026, 3, as_of=date(2026, 4, 11))
        self.assertEqual(report["expected_week_count"], 5)
        self.assertEqual(report["completed_week_count"], 5)
        self.assertEqual(len(report["weeks"]), 5)

    def test_complete_month_totals_equal_the_included_weekly_totals(self):
        self.complete_january()
        report = self.report()
        for key in ("earnings", "fuel_spending", "fuel_volume", "employer_cost", "overheads",
                    "estimated_operating_result"):
            self.assertEqual(report[key], sum(week[key] for week in report["weeks"]))
        self.assertEqual(report["estimated_operating_result"], -720000)
        self.assertEqual(report["covered_start"], date(2026, 1, 3))
        self.assertEqual(report["covered_end"], date(2026, 1, 30))

    def test_incomplete_week_suppresses_monthly_result_but_preserves_recorded_subtotals(self):
        self.complete_january()
        db.session.execute(Payslip.__table__.delete().where(Payslip.date == date(2026, 1, 16)))
        report = self.report()
        self.assertEqual(report["earnings"], 400000)
        self.assertEqual(report["fuel_spending"], 80000)
        self.assertIsNone(report["estimated_operating_result"])
        self.assertTrue(any(week["estimated_operating_result"] is None for week in report["weeks"]))

    def test_current_week_is_excluded_until_the_saturday_after_friday(self):
        self.complete_january()
        friday = self.report(as_of=date(2026, 1, 16))
        self.assertEqual(friday["completed_week_count"], 1)
        self.assertEqual(friday["active_week"], date(2026, 1, 10))
        self.assertEqual(friday["earnings"], 100000)
        saturday = self.report(as_of=date(2026, 1, 17))
        self.assertEqual(saturday["completed_week_count"], 2)
        self.assertEqual(saturday["earnings"], 200000)

    def test_future_month_has_no_completed_weeks_or_result(self):
        report = self.report(as_of=date(2025, 12, 20))
        self.assertEqual(report["period_state"], "future")
        self.assertEqual(report["weeks"], [])
        self.assertEqual(report["completed_week_count"], 0)
        self.assertEqual(report["pending_week_starts"], payroll_weeks_for_month(2026, 1))
        self.assertIsNone(report["estimated_operating_result"])

    def test_mixed_allowances_sum_saved_week_values(self):
        self.complete_january()
        set_overhead_settings(date(2026, 1, 17), 5, 60000)
        report = self.report()
        self.assertEqual([week["overheads"] for week in report["weeks"]],
                         [200000, 200000, 300000, 300000])
        self.assertEqual(report["overheads"], 1000000)

    def test_cross_year_week_appears_in_tuesday_month(self):
        report = get_monthly_report(2025, 12, as_of=date(2026, 1, 10))
        self.assertEqual(report["weeks"][-1]["week_start"], date(2025, 12, 27))
        self.assertEqual(report["covered_end"], date(2026, 1, 2))
        self.assertEqual(self.report()["weeks"][0]["week_start"], date(2026, 1, 3))

    def test_monthly_report_is_read_only(self):
        self.complete_january()
        with patch.object(db.session, "commit", side_effect=AssertionError("unexpected commit")):
            self.report()
        self.assertEqual(list(db.session.new), [])
        self.assertEqual(list(db.session.dirty), [])

    def test_genuine_zero_monthly_result_is_preserved(self):
        set_overhead_settings(self.start, 0, 0)
        for start in payroll_weeks_for_month(2026, 1):
            self.add_complete_week(start, earnings=80000)
        report = self.report()
        self.assertEqual(report["overheads"], 0)
        self.assertEqual(report["estimated_operating_result"], 0)

    def test_checked_month_reopens_when_a_historical_week_changes(self):
        self.complete_january()
        for start in payroll_weeks_for_month(2026, 1):
            self.mark_week_checked(start)
        self.assertEqual(self.report()["review_status"], "checked")
        db.session.execute(Job.__table__.update().where(Job.id == 1).values(earned=110000))
        report = self.report()
        self.assertEqual(report["review_status"], "needs_review")
        self.assertEqual(report["weeks"][0]["review_status"], "outdated")
        self.assertIsNone(report["reviewed_through"])

    def test_one_checked_week_does_not_mark_the_whole_month_checked(self):
        self.complete_january()
        self.mark_week_checked(self.start)
        report = self.report()
        self.assertEqual(report["weeks"][0]["review_status"], "checked")
        self.assertEqual(report["review_status"], "not_reviewed")
        self.assertIsNone(report["reviewed_through"])

    def test_current_month_can_be_reviewed_only_through_its_last_completed_week(self):
        self.complete_january()
        self.mark_week_checked(self.start, as_of=date(2026, 1, 10))
        report = self.report(as_of=date(2026, 1, 10))
        self.assertEqual(report["period_state"], "in_progress")
        self.assertEqual(report["review_status"], "checked")
        self.assertEqual(report["reviewed_through"], date(2026, 1, 9))
        self.assertEqual(report["completed_week_count"], 1)
        self.assertEqual(len(report["pending_week_starts"]), 3)

