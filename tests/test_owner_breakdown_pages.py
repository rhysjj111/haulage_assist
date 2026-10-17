"""Driver and truck filters retain accounting ownership and overall readiness."""

import re
from datetime import date
from decimal import Decimal

from owner_test_support import OwnerTestCase


class OwnerBreakdownPageTests(OwnerTestCase):
    def seed_entities(self):
        self.add_truck(1, registration="AA26 ONE")
        self.add_truck(2, registration="BB26 TWO")
        self.add_truck(3, registration="CC26 IDL")
        self.add_driver(1, first_name="Alice", truck_id=1,
                        employment_start=date(2026, 10, 5), employment_end=date(2026, 10, 9))
        self.add_driver(2, first_name="Bob", truck_id=2,
                        employment_start=date(2026, 10, 5), employment_end=date(2026, 10, 9))
        self.add_driver(3, first_name="Carol", employment_start=None)
        day_id = self.add_day(driver_id=1, truck_id=2, additional_earned=1000)
        self.add_job(day_id, earned=50000)
        self.add_job(day_id, earned=20000)
        self.add_day(driver_id=2, truck_id=None, status="holiday")
        self.add_fuel(truck_id=1, day_id=day_id, fuel_cost=12000, fuel_volume=10000)
        self.add_fuel(truck_id=2, day_id=None, fuel_cost=24000, fuel_volume=20000)
        self.add_payslip(driver_id=1, total_cost_to_employer=55000)

    def test_invalid_view_and_noncanonical_entity_ids_are_rejected(self):
        for suffix in ("view=unknown", "view=Drivers", "view=drivers&driver_id=0",
                       "view=drivers&driver_id=-1", "view=drivers&driver_id=01",
                       "view=trucks&truck_id=abc", "view=trucks&truck_id=2147483648"):
            with self.subTest(suffix=suffix):
                for path in ("/owner-analysis?week_start=2026-10-03&",
                             "/owner-analysis/monthly?month=2026-10&"):
                    self.assertEqual(self.client.get(path + suffix).status_code, 400)

    def test_unknown_entity_404_but_existing_entity_without_records_is_valid(self):
        self.seed_entities()
        for view, field in (("drivers", "driver_id"), ("trucks", "truck_id")):
            for base in ("/owner-analysis?week_start=2026-10-03&",
                         "/owner-analysis/monthly?month=2026-10&"):
                self.assertEqual(self.client.get(base + f"view={view}&{field}=999").status_code, 404)
                self.get_page(base + f"view={view}&{field}=3")

    def test_driver_breakdown_earnings_belong_to_driver_despite_truck_swap(self):
        self.seed_entities()
        _, context = self.get_page("/owner-analysis?week_start=2026-10-03&view=drivers&driver_id=1")
        rows = context["breakdown"]["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["earnings"], 71000)
        self.assertEqual(rows[0]["working_days"], 1)
        self.assertEqual(rows[0]["average_earnings_per_working_day"], 71000)
        self.assertEqual(context["report"]["earnings"], 71000)

    def test_holiday_has_no_invented_working_day_or_average(self):
        self.seed_entities()
        _, context = self.get_page("/owner-analysis?week_start=2026-10-03&view=drivers&driver_id=2")
        row = context["breakdown"]["rows"][0]
        self.assertEqual(row["working_days"], 0)
        self.assertEqual(row["holiday_days"], 1)
        self.assertIsNone(row["average_earnings_per_working_day"])

    def test_fuel_is_owned_by_receipt_truck_including_unlinked_receipt(self):
        self.seed_entities()
        _, context = self.get_page("/owner-analysis?week_start=2026-10-03&view=trucks")
        rows = {row["truck_id"]: row for row in context["breakdown"]["rows"]}
        self.assertEqual(rows[1]["fuel_spending"], 12000)
        self.assertEqual(rows[1]["fuel_volume"], 10000)
        self.assertEqual(rows[2]["fuel_spending"], 24000)
        self.assertEqual(rows[2]["fuel_entry_count"], 1)
        self.assertEqual(sum(row["fuel_spending"] for row in rows.values()), context["report"]["fuel_spending"])

    def test_missing_payroll_shows_pending_instead_of_zero_wage_cost(self):
        self.seed_entities()
        response, context = self.get_page("/owner-analysis?week_start=2026-10-03&view=drivers&driver_id=2")
        self.assertTrue(context["breakdown"]["rows"][0]["payroll_pending"])
        self.assertIn("Pending", response.text)

    def test_filter_does_not_turn_whole_period_review_into_checked(self):
        self.seed_entities()
        _, overview = self.get_page("/owner-analysis?week_start=2026-10-03")
        response, detail = self.get_page("/owner-analysis?week_start=2026-10-03&view=drivers&driver_id=1")
        self.assertEqual(overview["report"]["review_status"], detail["report"]["review_status"])
        self.assertNotEqual(detail["report"]["review_status"], "checked")
        self.assertIn("whole period", response.text)

    def test_details_only_have_get_forms_and_open_overview_for_corrections(self):
        self.seed_entities()
        for suffix in ("view=drivers&driver_id=1", "view=trucks&truck_id=1"):
            response, context = self.get_page("/owner-analysis?week_start=2026-10-03&" + suffix)
            self.assertNotRegex(response.text, r'<form\b[^>]*method=["\']post["\']')
            self.assertNotIn("owner_context=", response.text)
            for week in context["breakdown"]["weekly_links"]:
                self.assertNotIn("view=drivers", week["url"])
                self.assertNotIn("view=trucks", week["url"])

    def test_driver_filter_and_navigation_preserve_selected_period_and_entity(self):
        self.seed_entities()
        response, context = self.get_page("/owner-analysis?week_start=2026-10-03&view=drivers&driver_id=1")
        breakdown = context["breakdown"]
        self.assertEqual(breakdown["filter_fields"]["view"], "drivers")
        self.assertEqual(breakdown["filter_fields"]["week_start"], "2026-10-03")
        links = re.findall(r'href="([^"]+)"', response.text)
        self.assertTrue(any("week_start=2026-09-26" in link and "driver_id=1" in link for link in links))
        self.assertTrue(any("month=2026-10" in link and "driver_id=1" in link for link in links))

    def test_truck_allowance_is_separate_and_no_truck_profit_is_invented(self):
        self.seed_entities()
        self.configure_overheads()
        response, context = self.get_page("/owner-analysis?week_start=2026-10-03&view=trucks&truck_id=1")
        self.assertEqual(context["breakdown"]["allowance_weeks"][0]["allowance_per_truck"], 50000)
        self.assertIn("Standard overhead allowance", response.text)
        row = context["breakdown"]["rows"][0]
        self.assertNotIn("earnings", row)
        self.assertNotIn("estimated_operating_result", row)

    def test_month_uses_weighted_driver_average_and_shows_recorded_payroll_subtotal(self):
        self.add_truck()
        self.add_driver(first_name="Alice", employment_start=date(2026, 2, 2),
                        employment_end=date(2026, 2, 13))
        for on_date, earned in ((date(2026, 2, 2), 10000),
                                (date(2026, 2, 9), 30000), (date(2026, 2, 10), 30000)):
            self.add_job(self.add_day(on_date=on_date), earned=earned)
        self.add_payslip(on_date=date(2026, 2, 6), total_wage=9000, total_cost_to_employer=10000)
        response, context = self.get_page("/owner-analysis/monthly?month=2026-02&view=drivers&driver_id=1")
        row = context["breakdown"]["rows"][0]
        self.assertEqual(row["working_days"], 3)
        self.assertEqual(row["average_earnings_per_working_day"], Decimal(70000) / 3)
        self.assertEqual(row["employer_cost"], 10000)
        self.assertTrue(row["payroll_pending"])
        self.assertIn("£100.00", response.text)
        self.assertIn("pending", response.text.lower())

    def test_explicit_confirmed_zero_payroll_displays_zero_rather_than_pending(self):
        self.add_truck()
        self.add_driver(first_name="Bob", employment_start=date(2026, 10, 5),
                        employment_end=date(2026, 10, 6))
        self.add_day(status="absent", truck_id=None)
        self.add_day(on_date=date(2026, 10, 6), status="absent", truck_id=None)
        _, context = self.get_page("/owner-analysis?week_start=2026-10-03")
        issue = next(item for item in context["report"]["outstanding_issues"] if item["code"] == "missing_payslip")
        response = self.client.post("/owner-analysis/verify", data={
            "week_start": "2026-10-03", "issue_key": issue["key"],
            "fingerprint": issue["fingerprint"], "decision": "confirmed_zero",
            "note": "Unpaid absence; no employer wage cost confirmed.",
        })
        self.assertEqual(response.status_code, 303)
        response, context = self.get_page("/owner-analysis?week_start=2026-10-03&view=drivers&driver_id=1")
        self.assertFalse(context["breakdown"]["rows"][0]["payroll_pending"])
        self.assertIn("£0.00", response.text)
