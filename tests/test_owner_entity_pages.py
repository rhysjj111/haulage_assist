"""Read-only, period-bound summaries replace individual analysis filters."""

from datetime import date, timedelta
from html import unescape
from html.parser import HTMLParser
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import event, func, select, text

from owner_test_support import OwnerTestCase, captured_templates, db
from haulage_app.models import Job


class _Elements(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.elements = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


class OwnerEntityPageTests(OwnerTestCase):
    def setUp(self):
        super().setUp()
        clock = patch("haulage_app.owner_analysis.routes.today_london", return_value=date(2026, 10, 18))
        clock.start()
        self.addCleanup(clock.stop)
        self.add_truck(registration="AL26 ONE")
        self.add_truck(2, registration="BO26 TWO")
        self.add_truck(3, registration="ID26 IDL")
        self.add_driver(first_name="Alice", employment_start=date(2026, 10, 5),
                        employment_end=date(2026, 10, 9), truck_id=1)
        self.add_driver(2, first_name="Bob", employment_start=date(2026, 10, 5),
                        employment_end=date(2026, 10, 9), truck_id=2)
        self.add_driver(3, first_name="Carol", employment_start=None)
        self.monday = self.add_day(on_date=date(2026, 10, 5), truck_id=2,
                                   start_mileage=100000, end_mileage=131234, additional_earned=1250)
        self.job = self.add_job(self.monday, earned=45000, collection="Alice North depot",
                                delivery="Alice West port", notes="<script>unsafe()</script>")
        self.add_day(on_date=date(2026, 10, 7), truck_id=None, status="holiday")
        self.add_day(on_date=date(2026, 10, 8), truck_id=None, status="absent")
        self.bob_day = self.add_day(driver_id=2, on_date=date(2026, 10, 5), truck_id=1,
                                    start_mileage=200000, end_mileage=222200)
        self.add_job(self.bob_day, earned=93210, collection="Bob private depot", delivery="Bob private port")
        self.alice_slip = self.add_payslip(driver_id=1, total_wage=50011, total_cost_to_employer=55022)
        self.bob_slip = self.add_payslip(driver_id=2, total_wage=81789, total_cost_to_employer=91789)
        # Receipt truck and date, not a linked day's assignment, own the purchase.
        self.fuel = self.add_fuel(truck_id=1, on_date=date(2026, 10, 6), day_id=self.monday,
                                  fuel_card_name="Truck one card", fuel_cost=23456, fuel_volume=12345)
        self.other_fuel = self.add_fuel(truck_id=2, on_date=date(2026, 10, 5), day_id=None,
                                        fuel_card_name="Truck two card", fuel_cost=34567, fuel_volume=23456)
        self.configure_overheads()

    def details(self, kind="driver", identifier=1, query="week_start=2026-10-03", *, fragment=False):
        path = f"/owner-analysis/details/{kind}/{identifier}" + ("?" + query if query else "")
        with captured_templates() as contexts:
            response = self.client.get(path, headers={"X-Requested-With": "XMLHttpRequest"} if fragment else {})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(contexts)
        return response, contexts[-1]

    def assert_destination(self, url, path, **fields):
        target = urlsplit(unescape(url))
        self.assertFalse(target.netloc)
        self.assertEqual(target.path, path)
        self.assertEqual(parse_qs(target.query), {key: [str(value)] for key, value in fields.items()})

    def test_cards_show_every_entity_without_individual_dropdowns(self):
        for view, id_key, expected in (("drivers", "driver_id", {1, 2}),
                                       ("trucks", "truck_id", {1, 2})):
            for path in ("/owner-analysis?week_start=2026-10-03&",
                         "/owner-analysis/monthly?month=2026-10&week_start=2026-10-10&"):
                with self.subTest(view=view, path=path):
                    response, context = self.get_page(path + f"view={view}&{id_key}=1")
                    self.assertEqual({row[id_key] for row in context["breakdown"]["rows"]}, expected)
                    controls = [attrs for tag, attrs in _Elements(response.text).elements
                                if tag == "select" and attrs.get("name") in {"driver_id", "truck_id"}]
                    self.assertFalse(controls)
                    self.assertNotIn("filter_fields", context["breakdown"])
                    self.assertIn('id="owner-entity-dialog"', response.text)
                    self.assertNotIn('data-owner-entity-details data-entity-kind=', response.text,
                                     "The cards must not eagerly render every full summary")

    def test_weekly_cards_link_exact_subject_and_period_without_a_filter(self):
        for view, kind, key in (("drivers", "driver", "driver_id"), ("trucks", "truck", "truck_id")):
            response, context = self.get_page("/owner-analysis?week_start=2026-10-03&view=" + view)
            for row in context["breakdown"]["rows"]:
                self.assert_destination(row["details_url"], f"/owner-analysis/details/{kind}/{row[key]}",
                                        week_start="2026-10-03")
                self.assertIn(unescape(row["details_url"]), unescape(response.text))

    def test_monthly_cards_remember_the_report_week_in_their_details_link(self):
        for view, kind, key in (("drivers", "driver", "driver_id"), ("trucks", "truck", "truck_id")):
            _, context = self.get_page("/owner-analysis/monthly?month=2026-10&week_start=2026-10-17&view=" + view)
            for row in context["breakdown"]["rows"]:
                self.assert_destination(row["details_url"], f"/owner-analysis/details/{kind}/{row[key]}",
                                        month="2026-10", return_week="2026-10-17")

    def test_direct_driver_summary_shows_own_journeys_and_actual_recorded_trucks(self):
        response, context = self.details()
        details = context["details"]
        self.assertEqual((details["kind"], details["subject_id"]), ("driver", 1))
        self.assertEqual(details["summary"]["earnings"], 46250)
        self.assertEqual([row["date"] for row in details["weeks"][0]["days"]],
                         [self.start + timedelta(days=offset) for offset in range(7)])
        self.assertIn("Alice North depot", response.text)
        self.assertIn("Alice West port", response.text)
        self.assertIn("BO26 TWO", response.text)
        self.assertNotIn("Bob private depot", response.text)
        self.assertNotIn("£817.89", response.text)
        self.assertNotIn("£917.89", response.text)
        self.assertNotIn("Truck one card", response.text)
        self.assertNotIn("<script>unsafe()</script>", response.text)
        self.assertIn("&lt;script&gt;unsafe()&lt;/script&gt;", response.text)
        self.assert_destination(context["back_url"], "/owner-analysis", week_start="2026-10-03", view="drivers")

    def test_blank_weekends_are_neutral_but_weekday_remains_unknown(self):
        response, context = self.details()
        days = {row["date"]: row for row in context["details"]["weeks"][0]["days"]}
        self.assertEqual(days[date(2026, 10, 3)]["label"], "Not scheduled")
        self.assertEqual(days[date(2026, 10, 4)]["label"], "Not scheduled")
        self.assertEqual(days[date(2026, 10, 6)]["label"], "No entry")
        self.assertEqual(context["details"]["summary"]["absent_days"], 1)
        self.assertIn("Not scheduled", response.text)
        self.assertIn("No entry", response.text)

    def test_truck_summary_uses_receipt_dates_and_recorded_mileage_without_earnings(self):
        response, context = self.details("truck")
        details = context["details"]
        self.assertEqual(details["summary"]["fuel_spending"], 23456)
        entries = [entry for day in details["weeks"][0]["days"] for entry in day["entries"]]
        self.assertEqual({row["id"] for row in entries}, {self.bob_day})
        self.assertEqual(entries[0]["distance"], 22200)
        self.assertEqual(details["weeks"][0]["fuel_entries"][0]["date"], date(2026, 10, 6))
        self.assertIn("Truck one card", response.text)
        self.assertIn("222.00", response.text)
        self.assertNotIn("Truck two card", response.text)
        self.assertNotIn("Bob private depot", response.text)
        self.assertNotIn("£932.10", response.text)
        self.assertNotIn("£817.89", response.text)
        self.assertNotIn("Employer wage cost", response.text)
        self.assert_destination(context["back_url"], "/owner-analysis", week_start="2026-10-03", view="trucks")

    def test_ajax_is_a_readonly_fragment_of_the_same_subject_and_period(self):
        for kind in ("driver", "truck"):
            full, context = self.details(kind)
            fragment, fragment_context = self.details(kind, fragment=True)
            self.assertEqual(context["details"], fragment_context["details"])
            self.assertIn('data-owner-entity-details', fragment.text)
            self.assertNotIn("<html", fragment.text.lower())
            self.assertNotIn("<nav", fragment.text.lower())
            self.assertNotIn("<form", fragment.text.lower())
            self.assertNotIn("owner_context", fragment.text)
            self.assertNotIn("<script", fragment.text)
            self.assertIn("Back to Owner Analysis", full.text)
            for response in (full, fragment):
                self.assertIn("no-store", response.headers.get("Cache-Control", ""))
                self.assertIn("X-Requested-With", response.headers.get("Vary", ""))
            self.assertEqual(self.client.post(f"/owner-analysis/details/{kind}/1?week_start=2026-10-03").status_code, 405)

    def test_monthly_summary_excludes_unfinished_weeks_and_preserves_return_period(self):
        day = self.add_day(on_date=date(2026, 10, 17))
        self.add_job(day, earned=99999, collection="Unfinished Saturday depot", delivery="Future port")
        response, context = self.details(query="month=2026-10&return_week=2026-10-17")
        self.assertEqual([row["week_start"] for row in context["details"]["weeks"]],
                         [date(2026, 10, 3), date(2026, 10, 10)])
        self.assertEqual(context["details"]["summary"]["earnings"], 46250)
        self.assertEqual(context["details"]["pending_week_count"], 2)
        self.assertNotIn("Unfinished Saturday depot", response.text)
        self.assert_destination(context["back_url"], "/owner-analysis/monthly",
                                month="2026-10", week_start="2026-10-17", view="drivers")

    def test_month_with_no_completed_weeks_displays_empty_summary(self):
        response, context = self.details("truck", query="month=2026-11")
        self.assertEqual(context["details"]["weeks"], [])
        self.assertEqual(context["details"]["summary"]["fuel_spending"], 0)
        self.assertIn("No completed payroll weeks", response.text)

    def test_weekday_selection_normalizes_and_no_query_defaults_to_current_week(self):
        _, context = self.details(query="week_start=2026-10-05")
        self.assertEqual(context["details"]["week_start"], self.start)
        self.assert_destination(context["back_url"], "/owner-analysis", week_start="2026-10-03", view="drivers")
        _, default = self.details(query="")
        self.assertEqual(default["details"]["week_start"], date(2026, 10, 17))

    def test_current_week_excludes_source_entries_after_today(self):
        current_day = self.add_day(on_date=date(2026, 10, 17), truck_id=1)
        self.add_job(current_day, earned=22222, collection="Recorded Saturday depot", delivery="Current port")
        future_day = self.add_day(on_date=date(2026, 10, 19), truck_id=1)
        self.add_job(future_day, earned=88888, collection="Future Monday depot", delivery="Future port")
        self.add_fuel(truck_id=1, on_date=date(2026, 10, 19), fuel_card_name="Future receipt card")
        response, context = self.details(query="week_start=2026-10-17")
        self.assertEqual(context["details"]["summary"]["earnings"], 22222)
        self.assertEqual(context["details"]["summary"]["working_days"], 1)
        self.assertIn("Recorded Saturday depot", response.text)
        self.assertNotIn("Future Monday depot", response.text)
        response, truck = self.details("truck", query="week_start=2026-10-17")
        self.assertEqual(truck["details"]["summary"]["fuel_entry_count"], 0)
        self.assertNotIn("Future receipt card", response.text)

    def test_future_week_is_a_safe_empty_preview(self):
        response, context = self.details(query="week_start=2026-10-24")
        self.assertEqual(context["details"]["summary"]["earnings"], 0)
        self.assertEqual(context["details"]["weeks"][0]["recorded_through"], None)
        self.assertTrue(all(row["is_future"] for row in context["details"]["weeks"][0]["days"]))
        self.assertIn("Not yet due", response.text)

    def test_existing_entity_without_records_has_empty_dates_but_unknown_is_404(self):
        for kind in ("driver", "truck"):
            _, context = self.details(kind, identifier=3)
            self.assertFalse(any(day["entries"] for day in context["details"]["weeks"][0]["days"]))
            self.assertEqual(self.client.get(f"/owner-analysis/details/{kind}/999?week_start=2026-10-03").status_code, 404)

    def test_invalid_paths_and_ambiguous_or_untrusted_query_scope_are_rejected(self):
        for path in ("/owner-analysis/details/other/1", "/owner-analysis/details/driver/0",
                     "/owner-analysis/details/truck/2147483648", "/owner-analysis/details/driver/-1"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)
        invalid = ("week_start=bad", "week_start=2026-1-03", "week_start=20261003",
                   "week_start=2026-02-30", "week_start=0001-01-01", "month=2026-1",
                   "month=2026-13", "month=0000-01", "month=0001-01",
                   "week_start=2026-10-03&month=2026-10", "return_week=2026-10-03",
                   "month=2026-10&return_week=2026-10-05", "month=2026-10&return_week=2026-09-26",
                   "week_start=2026-10-03&week_start=2026-10-10", "month=2026-10&month=2026-10",
                   "month=2026-10&return_week=2026-10-03&return_week=2026-10-10",
                   "week_start=2026-10-03&driver_id=2", "week_start=2026-10-03&truck_id=2",
                   "week_start=2026-10-03&return_url=https://example.com", "week_start=2026-10-03&nearby=1")
        for query in invalid:
            with self.subTest(query=query):
                self.assertEqual(self.client.get("/owner-analysis/details/driver/1?" + query).status_code, 400)

    def test_get_never_flushes_pending_source_changes_or_writes_review_tables(self):
        pending = db.session.get(Job, self.job)
        pending.notes = "Unsaved browser review edit"
        with db.session.no_autoflush:
            before = {table.name: db.session.execute(select(func.count()).select_from(table)).scalar()
                      for table in db.metadata.sorted_tables}
        writes = []

        def capture(connection, cursor, statement, parameters, *unused):
            if statement.lstrip().lower().startswith(("insert", "update", "delete")):
                writes.append(statement)

        event.listen(db.engine, "before_cursor_execute", capture)
        try:
            for kind in ("driver", "truck"):
                for query in ("week_start=2026-10-03", "month=2026-10&return_week=2026-10-17"):
                    for fragment in (False, True):
                        self.details(kind, query=query, fragment=fragment)
        finally:
            event.remove(db.engine, "before_cursor_execute", capture)
        self.assertFalse(writes)
        self.assertIn(pending, db.session.dirty)
        with db.session.no_autoflush:
            self.assertEqual(db.session.execute(text("SELECT notes FROM job WHERE id=:id"),
                                                {"id": self.job}).scalar(), "<script>unsafe()</script>")
            self.assertEqual({table.name: db.session.execute(select(func.count()).select_from(table)).scalar()
                              for table in db.metadata.sorted_tables}, before)
