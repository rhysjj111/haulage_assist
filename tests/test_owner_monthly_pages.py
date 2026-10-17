"""Month pages expose completed payroll weeks rather than hiding missing data."""

import re
from datetime import date

from owner_test_support import OwnerTestCase


class OwnerMonthlyPageTests(OwnerTestCase):
    def test_month_rejects_invalid_and_noncanonical_query_dates(self):
        for value in ("2026-1", "2026-00", "2026-13", "2026-10-01", "bad", "0000-01"):
            with self.subTest(value=value):
                self.assertEqual(self.client.get("/owner-analysis/monthly", query_string={"month": value}).status_code, 400)

    def test_completed_five_week_month_contains_all_expected_empty_weeks(self):
        response, context = self.get_page("/owner-analysis/monthly?month=2026-03")
        report = context["report"]
        self.assertEqual(report["expected_week_count"], 5)
        self.assertEqual(report["completed_week_count"], 5)
        self.assertEqual([week["week_start"] for week in report["weeks"]], [
            date(2026, 2, 28), date(2026, 3, 7), date(2026, 3, 14),
            date(2026, 3, 21), date(2026, 3, 28),
        ])
        self.assertIsNone(report["estimated_operating_result"])
        self.assertNotEqual(report["review_status"], "checked")
        self.assertIn("2026-02-28", response.text)

    def test_completed_four_week_month_has_exact_covered_dates(self):
        _, context = self.get_page("/owner-analysis/monthly?month=2026-02")
        report = context["report"]
        self.assertEqual(report["expected_week_count"], 4)
        self.assertEqual(report["covered_start"], date(2026, 1, 31))
        self.assertEqual(report["covered_end"], date(2026, 2, 27))

    def test_future_month_has_no_completed_week_or_false_zero_profit(self):
        response, context = self.get_page("/owner-analysis/monthly?month=2099-02")
        report = context["report"]
        self.assertEqual(report["completed_week_count"], 0)
        self.assertEqual(report["weeks"], [])
        self.assertIsNone(report["estimated_operating_result"])
        self.assertIn("No completed payroll weeks yet", response.text)
        self.assertNotEqual(report["review_status"], "checked")

    def test_month_has_no_independent_signoff_or_mutating_form(self):
        response, _ = self.get_page("/owner-analysis/monthly?month=2026-03")
        self.assertNotRegex(response.text, r'<form\b[^>]*method=["\']post["\']')
        self.assertNotIn("/owner-analysis/review", response.text)

    def test_month_navigation_crosses_year_and_retains_truck_view_filter(self):
        self.add_truck()
        response, context = self.get_page("/owner-analysis/monthly?month=2026-01&view=trucks&truck_id=1")
        self.assertEqual(context["analysis_view"], "trucks")
        self.assertIn("month=2025-12", response.text)
        self.assertIn("month=2026-02", response.text)
        self.assertIn("truck_id=1", response.text)

    def test_month_current_week_links_do_not_add_unfinished_week_to_totals(self):
        _, context = self.get_page("/owner-analysis/monthly?month=2026-10")
        report = context["report"]
        self.assertTrue(all(week["week_end"] < report["as_of"] for week in report["weeks"]))
        if report["active_week"]:
            self.assertNotIn(report["active_week"], [week["week_start"] for week in report["weeks"]])

    def test_month_return_to_week_preserves_selected_week_and_driver(self):
        self.add_truck()
        self.add_driver()
        response, _ = self.get_page("/owner-analysis/monthly?month=2026-03&week_start=2026-03-07&view=drivers&driver_id=1")
        links = re.findall(r'href="([^"]+)"', response.text)
        self.assertTrue(any("week_start=2026-03-07" in link and "view=drivers" in link
                            and "driver_id=1" in link for link in links))
