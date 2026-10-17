"""Driver work patterns and receipt-assigned truck spending remain simple."""

from datetime import date, timedelta
from decimal import Decimal

from owner_test_support import OwnerDatabaseTestCase
from haulage_app.owner_analysis.calculations import calculate_weekly_report
from haulage_app.owner_analysis.monthly import get_monthly_report


class OwnerBreakdownTests(OwnerDatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.start = date(2026, 1, 3)
        self.add_truck()
        self.add_driver(employment_start=None)

    def report(self):
        return calculate_weekly_report(self.start, as_of=date(2026, 2, 7))

    def test_driver_counts_working_holiday_and_absent_separately(self):
        for offset, status in [(2, "working"), (3, "working"), (4, "holiday"), (5, "absent")]:
            self.add_day(driver_id=1, on_date=self.start + timedelta(days=offset), status=status)
        driver = self.report()["drivers"][1]
        self.assertEqual(driver["recorded_days"], 4)
        self.assertEqual(driver["working_days"], 2)
        self.assertEqual(driver["holiday_days"], 1)
        self.assertEqual(driver["absent_days"], 1)

    def test_average_uses_working_days_and_includes_additional_earnings(self):
        day = self.add_day(driver_id=1, on_date=self.start + timedelta(days=2), additional_earned=1)
        self.add_job(day, earned=100000)
        self.add_day(driver_id=1, on_date=self.start + timedelta(days=3))
        self.add_day(driver_id=1, on_date=self.start + timedelta(days=4), status="holiday")
        driver = self.report()["drivers"][1]
        self.assertEqual(driver["earnings"], 100001)
        self.assertEqual(driver["average_earnings_per_working_day"], Decimal("50000.5"))

    def test_no_working_days_has_no_average_rather_than_division_by_zero(self):
        self.add_day(driver_id=1, on_date=self.start + timedelta(days=2), status="holiday")
        driver = self.report()["drivers"][1]
        self.assertEqual(driver["working_days"], 0)
        self.assertIsNone(driver["average_earnings_per_working_day"])

    def test_working_day_with_zero_earnings_counts_in_denominator(self):
        self.add_day(driver_id=1, on_date=self.start + timedelta(days=2))
        driver = self.report()["drivers"][1]
        self.assertEqual(driver["average_earnings_per_working_day"], Decimal(0))

    def test_driver_payroll_is_employer_cost_and_reports_source_ids(self):
        self.add_day(driver_id=1, on_date=self.start + timedelta(days=2))
        payslip = self.add_payslip(driver_id=1, on_date=self.start + timedelta(days=6),
                                   total_wage=50000, total_cost_to_employer=65000)
        driver = self.report()["drivers"][1]
        self.assertEqual(driver["employer_cost"], 65000)
        self.assertEqual(driver["payslip_ids"], [payslip])

    def test_fuel_is_assigned_to_receipt_truck_even_when_linked_day_differs(self):
        self.add_truck(2)
        day = self.add_day(driver_id=1, on_date=self.start + timedelta(days=2), truck_id=1)
        self.add_fuel(truck_id=2, on_date=self.start + timedelta(days=2), day_id=day,
                      fuel_cost=30000, fuel_volume=20000)
        trucks = self.report()["trucks"]
        self.assertEqual(trucks[2]["fuel_spending"], 30000)
        self.assertEqual(trucks[2]["fuel_volume"], 20000)
        self.assertEqual(trucks[2]["fuel_entry_count"], 1)
        self.assertEqual(trucks.get(1, {}).get("fuel_spending", 0), 0)

    def test_truck_receipts_sum_independent_purchases_without_a_day(self):
        self.add_fuel(truck_id=1, on_date=self.start + timedelta(days=2), fuel_cost=20000, fuel_volume=10000)
        self.add_fuel(truck_id=1, on_date=self.start + timedelta(days=3), fuel_cost=30000, fuel_volume=15000)
        truck = self.report()["trucks"][1]
        self.assertEqual(truck["fuel_spending"], 50000)
        self.assertEqual(truck["fuel_volume"], 25000)
        self.assertEqual(truck["fuel_entry_count"], 2)

    def test_monthly_driver_average_is_weighted_by_total_working_days(self):
        first = self.add_day(driver_id=1, on_date=self.start + timedelta(days=2))
        self.add_job(first, earned=100000)
        for offset in (9, 10, 11):
            day = self.add_day(driver_id=1, on_date=self.start + timedelta(days=offset))
            self.add_job(day, earned=20000)
        driver = get_monthly_report(2026, 1, as_of=date(2026, 2, 7))["drivers"][1]
        self.assertEqual(driver["working_days"], 4)
        self.assertEqual(driver["earnings"], 160000)
        self.assertEqual(driver["average_earnings_per_working_day"], Decimal(40000))

    def test_monthly_truck_spending_and_receipt_counts_equal_weekly_sums(self):
        self.add_fuel(truck_id=1, on_date=self.start + timedelta(days=2), fuel_cost=20000, fuel_volume=10000)
        self.add_fuel(truck_id=1, on_date=self.start + timedelta(days=9), fuel_cost=30000, fuel_volume=15000)
        report = get_monthly_report(2026, 1, as_of=date(2026, 2, 7))
        truck = report["trucks"][1]
        self.assertEqual(truck["fuel_spending"], 50000)
        self.assertEqual(truck["fuel_volume"], 25000)
        self.assertEqual(truck["fuel_entry_count"], 2)

