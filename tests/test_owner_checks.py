"""Readiness checks separate unknown source data from explained exceptions."""

from datetime import date, timedelta

from owner_test_support import OwnerDatabaseTestCase, db
from haulage_app.models import Day
from haulage_app.owner_analysis.calculations import calculate_weekly_report


class OwnerCheckTests(OwnerDatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.start = date(2026, 1, 3)
        self.as_of = self.start + timedelta(days=14)
        self.add_truck()

    def report(self):
        return calculate_weekly_report(self.start, as_of=self.as_of)

    def issues(self, code):
        return [issue for issue in self.report()["issues"] if issue["code"] == code]

    def test_expected_days_use_employment_dates_and_do_not_assume_weekends(self):
        self.add_driver(employment_start=self.start + timedelta(days=3),
                        employment_end=self.start + timedelta(days=4))
        issues = self.issues("missing_day")
        self.assertEqual({issue["date"] for issue in issues},
                         {self.start + timedelta(days=3), self.start + timedelta(days=4)})
        self.assertTrue(all(issue["driver_id"] == 1 for issue in issues))

    def test_unemployed_driver_does_not_create_expected_day_warnings(self):
        self.add_driver(employment_start=None)
        self.add_driver(2, employment_start=date(2025, 1, 1), employment_end=date(2025, 12, 31))
        self.assertEqual(self.issues("missing_day"), [])

    def test_holiday_and_absent_are_recorded_days_not_missing_work(self):
        monday = self.start + timedelta(days=2)
        self.add_driver(employment_start=monday, employment_end=monday + timedelta(days=1))
        self.add_day(driver_id=1, on_date=monday, status="holiday", truck_id=None)
        self.add_day(driver_id=1, on_date=monday + timedelta(days=1), status="absent", truck_id=None)
        self.assertEqual(self.issues("missing_day"), [])
        self.assertEqual(self.issues("working_day_without_earnings"), [])

    def test_working_day_without_revenue_is_unknown(self):
        self.add_driver(employment_start=None)
        on_date = self.start + timedelta(days=2)
        self.add_day(driver_id=1, on_date=on_date)
        issues = self.issues("working_day_without_earnings")
        self.assertEqual(len(issues), 1)
        self.assertEqual((issues[0]["driver_id"], issues[0]["date"]), (1, on_date))

    def test_matching_receipt_counts_do_not_hide_a_missing_flagged_date(self):
        self.add_driver(employment_start=None)
        monday, tuesday = self.start + timedelta(days=2), self.start + timedelta(days=3)
        self.add_day(driver_id=1, on_date=monday, fuel=True)
        self.add_day(driver_id=1, on_date=tuesday, fuel=True)
        self.add_fuel(truck_id=1, on_date=monday)
        self.add_fuel(truck_id=1, on_date=monday)
        issues = self.issues("missing_fuel_receipt")
        self.assertEqual({issue["date"] for issue in issues}, {tuesday})
        self.assertTrue(all(issue["blocking"] for issue in issues))

    def test_first_day_zero_and_reversed_same_day_mileage_are_checked(self):
        self.add_driver(employment_start=None)
        self.add_day(driver_id=1, on_date=self.start + timedelta(days=2),
                     start_mileage=0, end_mileage=100000)
        self.add_day(driver_id=1, on_date=self.start + timedelta(days=3),
                     start_mileage=110000, end_mileage=100000)
        issues = self.issues("missing_mileage") + self.issues("mileage_end_before_start")
        self.assertEqual(len(issues), 2)
        self.assertEqual({issue["date"] for issue in issues},
                         {self.start + timedelta(days=2), self.start + timedelta(days=3)})

    def test_issue_keys_are_stable_when_the_underlying_values_change(self):
        self.add_driver(employment_start=None)
        day_id = self.add_day(driver_id=1, on_date=self.start + timedelta(days=2),
                              start_mileage=0, end_mileage=100000)
        before = {issue["key"] for issue in self.issues("missing_mileage")}
        db.session.execute(Day.__table__.update().where(Day.id == day_id).values(end_mileage=120000))
        after = {issue["key"] for issue in self.issues("missing_mileage")}
        self.assertTrue(before)
        self.assertEqual(after, before)

    def test_source_record_ids_alone_are_not_treated_as_a_completion_state(self):
        self.add_driver(employment_start=None)
        self.add_day(driver_id=1, on_date=self.start + timedelta(days=2), fuel=True)
        report = self.report()
        self.assertTrue(report["source_records"])
        self.assertIsNone(report["estimated_operating_result"])
        self.assertTrue(any(issue["blocking"] for issue in report["issues"]))

    def test_one_payslip_does_not_establish_payroll_for_every_driver(self):
        self.add_driver(employment_start=None)
        self.add_driver(2, employment_start=None)
        for driver_id in (1, 2):
            self.add_day(driver_id=driver_id, on_date=self.start + timedelta(days=2), status="holiday")
        self.add_payslip(driver_id=1, on_date=self.start + timedelta(days=6))
        self.assertEqual([issue["driver_id"] for issue in self.issues("missing_payslip")], [2])

    def test_duplicate_payslips_are_checked_instead_of_silently_counted_as_complete(self):
        self.add_driver(employment_start=None)
        for offset in (5, 6):
            self.add_payslip(driver_id=1, on_date=self.start + timedelta(days=offset))
        issues = self.issues("multiple_payslips")
        self.assertEqual(len(issues), 1)
        self.assertTrue(issues[0]["blocking"])

    def test_employer_cost_below_wage_is_not_a_ready_cost(self):
        self.add_driver(employment_start=None)
        self.add_payslip(driver_id=1, on_date=self.start + timedelta(days=6),
                         total_wage=60000, total_cost_to_employer=50000)
        issues = self.issues("employer_cost_below_wage")
        self.assertEqual(len(issues), 1)
        self.assertTrue(issues[0]["blocking"])

