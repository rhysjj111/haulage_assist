"""Owner analysis uses actual recorded amounts without changing payroll."""

from datetime import date, timedelta
from unittest.mock import patch

from owner_test_support import OwnerDatabaseTestCase, db
from haulage_app.models import Day, Expense, ExpenseOccurrence, Payslip
from haulage_app.owner_analysis.calculations import calculate_weekly_report
from haulage_app.owner_analysis.overheads import ensure_weekly_overhead, set_overhead_settings


class OwnerCalculationTests(OwnerDatabaseTestCase):
    start = date(2026, 1, 3)
    as_of = date(2026, 1, 17)

    def setUp(self):
        super().setUp()
        self.start = date(2026, 1, 3)
        self.add_truck()
        self.add_driver(employment_start=None)

    def add_complete_week(self):
        day_id = self.add_day(driver_id=1, on_date=self.start + timedelta(days=2), truck_id=1,
                              additional_earned=5000, fuel=True)
        self.add_job(day_id, earned=100000)
        self.add_fuel(truck_id=1, on_date=self.start + timedelta(days=2), day_id=day_id,
                      fuel_cost=40000, fuel_volume=25000)
        self.add_payslip(driver_id=1, on_date=self.start + timedelta(days=6),
                         total_wage=50000, total_cost_to_employer=60000)
        set_overhead_settings(self.start, 4, 50000)
        ensure_weekly_overhead(self.start)
        db.session.flush()
        return day_id

    def report(self, **kwargs):
        return calculate_weekly_report(self.start, as_of=kwargs.get("as_of", self.as_of))

    def test_uses_actual_revenue_fuel_employer_cost_and_four_truck_allowance(self):
        self.add_complete_week()
        report = self.report()
        self.assertEqual(report["earnings"], 105000)
        self.assertEqual(report["fuel_spending"], 40000)
        self.assertEqual(report["fuel_volume"], 25000)
        self.assertEqual(report["employer_cost"], 60000)
        self.assertEqual(report["overheads"], 200000)
        self.assertEqual(report["estimated_operating_result"], -195000)

    def test_missing_overheads_stays_unknown(self):
        self.add_day(driver_id=1, on_date=self.start + timedelta(days=2), truck_id=1)
        self.add_payslip(driver_id=1, on_date=self.start + timedelta(days=6))
        report = self.report()
        self.assertIsNone(report["overheads"])
        self.assertIsNone(report["estimated_operating_result"])
        self.assertTrue(any(issue["blocking"] for issue in report["issues"]))

    def test_missing_payslip_does_not_treat_recorded_subtotal_as_complete_cost(self):
        self.add_complete_week()
        db.session.execute(Payslip.__table__.delete())
        report = self.report()
        self.assertEqual(report["employer_cost"], 0)  # Recorded subtotal, explicitly incomplete below.
        self.assertTrue(any(issue["code"] == "missing_payslip" for issue in report["issues"]))
        self.assertIsNone(report["estimated_operating_result"])

    def test_missing_flagged_fuel_receipt_suppresses_result(self):
        self.add_complete_week()
        from haulage_app.models import Fuel
        db.session.execute(Fuel.__table__.delete())
        report = self.report()
        self.assertIsNone(report["estimated_operating_result"])
        self.assertTrue(any(issue["blocking"] and issue.get("date") == self.start + timedelta(days=2)
                            for issue in report["issues"]))

    def test_expense_records_are_not_added_on_top_of_owner_allowance(self):
        self.add_complete_week()
        before = self.report()
        db.session.execute(Expense.__table__.insert(), [dict(id=1, name="Truck allowance")])
        db.session.execute(ExpenseOccurrence.__table__.insert(), [dict(
            id=1, expense_id=1, start_date=self.start, end_date=None, cost=50000)])
        after = self.report()
        for key in ("earnings", "employer_cost", "overheads", "estimated_operating_result"):
            self.assertEqual(after[key], before[key])

    def test_current_week_stays_in_progress_through_friday(self):
        self.add_complete_week()
        for day in (self.start, self.start + timedelta(days=6)):
            with self.subTest(as_of=day):
                report = self.report(as_of=day)
                self.assertEqual(report["period_state"], "in_progress")
                self.assertIsNone(report["estimated_operating_result"])
        self.assertEqual(self.report(as_of=self.start + timedelta(days=7))["period_state"], "finished")

    def test_future_week_has_no_final_result(self):
        self.add_complete_week()
        report = self.report(as_of=self.start - timedelta(days=1))
        self.assertEqual(report["period_state"], "future")
        self.assertIsNone(report["estimated_operating_result"])

    def test_zero_recorded_amounts_and_negative_result_are_not_missing(self):
        self.add_day(driver_id=1, on_date=self.start + timedelta(days=2), truck_id=1, status="holiday")
        self.add_payslip(driver_id=1, on_date=self.start + timedelta(days=6),
                         total_wage=50000, total_cost_to_employer=60000)
        set_overhead_settings(self.start, 0, 0)
        ensure_weekly_overhead(self.start)
        report = self.report()
        self.assertEqual(report["earnings"], 0)
        self.assertEqual(report["fuel_spending"], 0)
        self.assertEqual(report["overheads"], 0)
        self.assertEqual(report["estimated_operating_result"], -60000)

    def test_analysis_does_not_mutate_payroll_values_or_commit(self):
        day_id = self.add_complete_week()
        day = db.session.get(Day, day_id)
        before = day.calculate_daily_bonus(day.driver)
        with patch.object(db.session, "commit", side_effect=AssertionError("unexpected commit")):
            self.report()
        self.assertEqual(day.calculate_daily_bonus(day.driver), before)
        self.assertEqual(list(db.session.new), [])
        self.assertEqual(list(db.session.dirty), [])

