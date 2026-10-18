"""Weekly report pages remain read-only, explicit about gaps, and safe to navigate."""

from datetime import date, timedelta
from sqlalchemy import func, select

from owner_test_support import OwnerTestCase, app, db
from haulage_app.models import Day, Job
from haulage_app.owner_analysis.models import OwnerWeekReview


class OwnerWeeklyPageTests(OwnerTestCase):
    def seed_week(self):
        self.add_truck()
        self.add_driver(first_name="Alice", employment_start=date(2026, 10, 5),
                        employment_end=date(2026, 10, 9))
        for offset in range(5):
            day_id = self.add_day(on_date=date(2026, 10, 5) + timedelta(days=offset))
            self.add_job(day_id, earned=50000)
        self.add_fuel(fuel_cost=12000)
        self.add_payslip(total_cost_to_employer=55000)
        self.configure_overheads()

    def test_overview_contains_actual_recorded_totals_and_both_period_choices(self):
        self.seed_week()
        response, context = self.get_page("/owner-analysis?week_start=2026-10-03")
        report = context["report"]
        self.assertEqual(report["earnings"], 250000)
        self.assertEqual(report["fuel_spending"], 12000)
        self.assertEqual(report["employer_cost"], 55000)
        self.assertEqual(report["overheads"], 200000)
        self.assertEqual(report["estimated_operating_result"], -17000)
        self.assertIn("Weekly", response.text)
        self.assertIn("Monthly", response.text)
        self.assertIn("Overview", response.text)
        self.assertIn("Drivers", response.text)
        self.assertIn("Trucks", response.text)

    def test_all_get_views_leave_database_and_overhead_history_unchanged(self):
        self.seed_week()

        def counts():
            return {table.name: db.session.execute(select(func.count()).select_from(table)).scalar()
                    for table in db.metadata.sorted_tables}

        before = counts()
        for suffix in ("", "&view=drivers", "&view=trucks"):
            self.get_page("/owner-analysis?week_start=2026-10-03" + suffix)
            self.get_page("/owner-analysis/monthly?month=2026-10" + suffix)
        self.assertEqual(counts(), before)

    def test_report_get_does_not_autoflush_pending_source_edits(self):
        self.seed_week()
        job = db.session.get(Job, 1)
        for base in ("/owner-analysis?week_start=2026-10-03",
                     "/owner-analysis/monthly?month=2026-10"):
            for view in ("overview", "drivers", "trucks"):
                with self.subTest(base=base, view=view):
                    job.notes = "Pending source edit " + base + view
                    self.get_page(base + "&view=" + view)
                    self.assertIn(job, db.session.dirty)
                    self.assertTrue(db.session.is_modified(job))

    def test_malformed_week_is_rejected(self):
        for value in ("garbage", "2026-1-03", "2026-10-03T00:00:00",
                      "2026-02-30", "0000-01-01"):
            with self.subTest(value=value):
                self.assertEqual(self.client.get("/owner-analysis", query_string={"week_start": value}).status_code, 400)

    def test_date_picker_can_select_a_weekday_and_normalizes_to_saturday(self):
        _, context = self.get_page("/owner-analysis?week_start=2026-10-05")
        self.assertEqual(context["report"]["week_start"], date(2026, 10, 3))

    def test_empty_finished_week_is_not_checked_and_result_is_unknown(self):
        response, context = self.get_page("/owner-analysis?week_start=2026-10-03")
        self.assertNotEqual(context["report"]["review_status"], "checked")
        self.assertIsNone(context["report"]["estimated_operating_result"])
        self.assertIn("overhead", response.text.lower())

    def test_future_week_cannot_appear_reviewed(self):
        _, context = self.get_page("/owner-analysis?week_start=2099-01-03")
        self.assertNotEqual(context["report"]["review_status"], "checked")
        self.assertIsNone(context["report"]["estimated_operating_result"])

    def test_week_to_month_uses_tuesday_assignment_at_calendar_boundary(self):
        response, _ = self.get_page("/owner-analysis?week_start=2026-01-31")
        self.assertIn("month=2026-02", response.text)

    def test_post_actions_require_csrf_when_enabled(self):
        self.seed_week()
        _, context = self.get_page("/owner-analysis/checks?week_start=2026-10-03")
        _, settings_context = self.get_page("/owner-analysis/overheads?week_start=2026-10-03")
        payloads = {
            "overheads": {"selected_week": "2026-10-03", "effective_week_start": "2026-10-03",
                          "truck_count": "9", "allowance_per_truck": "700.00",
                          "fingerprint": settings_context["overhead_form"].fingerprint.data},
            "note": {"week_start": "2026-10-03", "fingerprint": context["report"]["week_fingerprint"],
                     "scope_key": "week_note", "note": "Should not be saved"},
            "review": {"week_start": "2026-10-03", "fingerprint": context["report"]["week_fingerprint"],
                       "review_id": "0", "action": "check"},
        }
        app.config["WTF_CSRF_ENABLED"] = True
        try:
            for action in ("overheads", "verify", "note", "review", "absence"):
                with self.subTest(action=action):
                    response = self.client.post("/owner-analysis/" + action,
                                                data=payloads.get(action, {"week_start": "2026-10-03"}))
                    self.assertEqual(response.status_code, 400 if action == "overheads" else 303)
                    if action != "overheads":
                        response, _ = self.get_page(response.headers["Location"])
                    self.assertIn("CSRF", response.text)
                    _, rejected = self.get_page("/owner-analysis?week_start=2026-10-03")
                    self.assertEqual(rejected["report"]["overhead_settings"]["truck_count"], 4)
                    self.assertFalse(any(item["note"] == "Should not be saved"
                                         for item in rejected["report"]["verification_history"]))
        finally:
            app.config["WTF_CSRF_ENABLED"] = False

    def test_person_names_are_escaped_on_weekly_and_detail_pages(self):
        self.add_truck()
        self.add_driver(first_name="<script>alert(1)</script>")
        self.add_day(status="holiday")
        for suffix in ("", "&view=drivers"):
            response, _ = self.get_page("/owner-analysis?week_start=2026-10-03" + suffix)
            self.assertNotIn("<script>alert(1)</script>", response.text)
            self.assertIn("&lt;script&gt;", response.text)

    def test_week_note_is_saved_and_escaped_without_signing_off_the_week(self):
        self.seed_week()
        _, context = self.get_page("/owner-analysis/checks?week_start=2026-10-03")
        form = context["weeks"][0]["forms"]["note"]
        response = self.client.post("/owner-analysis/note", data={
            "week_start": "2026-10-03", "scope_key": "week_note",
            "fingerprint": form.fingerprint.data, "note": "Fuel checked <script>alert(1)</script>",
        })
        self.assertEqual(response.status_code, 303)
        response, context = self.get_page("/owner-analysis?week_start=2026-10-03")
        self.assertIn("Fuel checked &lt;script&gt;", response.text)
        self.assertNotIn("<script>alert(1)</script>", response.text)
        self.assertNotEqual(context["report"]["review_status"], "checked")

    def test_overhead_form_rejects_stale_history_even_if_selected_week_is_unchanged(self):
        self.seed_week()
        _, context = self.get_page("/owner-analysis/overheads?week_start=2026-10-03")
        fingerprint = context["overhead_form"].fingerprint.data
        self.configure_overheads(date(2026, 10, 24), 5, 60000)
        response = self.client.post("/owner-analysis/overheads", data={
            "selected_week": "2026-10-03", "effective_week_start": "2026-10-03",
            "truck_count": "4", "allowance_per_truck": "510.00", "fingerprint": fingerprint,
        })
        self.assertEqual(response.status_code, 409)
        _, context = self.get_page("/owner-analysis?week_start=2026-10-03")
        self.assertEqual(context["report"]["overhead_settings"]["allowance_per_truck"], 50000)

    def test_missing_day_can_be_explained_as_absent_with_the_issue_fingerprint(self):
        self.add_truck()
        self.add_driver(first_name="Alice", employment_start=date(2026, 10, 5),
                        employment_end=date(2026, 10, 9))
        _, context = self.get_page("/owner-analysis?week_start=2026-10-03")
        issue = next(item for item in context["report"]["outstanding_issues"]
                     if item["code"] == "missing_day" and item["date"] == date(2026, 10, 6))
        response = self.client.post("/owner-analysis/absence", data={
            "week_start": "2026-10-03", "fingerprint": issue["fingerprint"],
            "driver_id": "1", "absent_date": "2026-10-06", "status": "absent",
            "note": "Alice was off <script>unsafe()</script>",
        })
        self.assertEqual(response.status_code, 303)
        recorded = Day.query.filter_by(driver_id=1, date=date(2026, 10, 6)).one()
        self.assertEqual(recorded.status, "absent")
        self.assertIsNone(recorded.truck_id)
        response, context = self.get_page("/owner-analysis?week_start=2026-10-03")
        self.assertEqual(context["report"]["absence_summary"][0]["absent_days"], 1)
        checks_response, _ = self.get_page("/owner-analysis/checks?week_start=2026-10-03")
        self.assertIn("Alice was off &lt;script&gt;", checks_response.text)
        self.assertNotEqual(context["report"]["review_status"], "checked")

    def test_review_requires_an_explicit_current_action_before_creating_signoff(self):
        self.seed_week()
        _, context = self.get_page("/owner-analysis?week_start=2026-10-03")
        self.assertEqual(context["report"]["outstanding_issues"], [])
        payload = {
            "week_start": "2026-10-03", "fingerprint": context["report"]["week_fingerprint"],
            "review_id": "0", "action": "check",
        }
        for invalid in ({"action": ""}, {"action": "unknown"}, {"review_id": ""}, {"review_id": "-1"}):
            with self.subTest(invalid=invalid):
                response = self.client.post("/owner-analysis/review", data=dict(payload, **invalid))
                self.assertEqual(response.status_code, 303)
                self.assertEqual(OwnerWeekReview.query.count(), 0)
        response = self.client.post("/owner-analysis/review", data=payload)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(OwnerWeekReview.query.count(), 1)
        _, context = self.get_page("/owner-analysis?week_start=2026-10-03")
        self.assertEqual(context["report"]["review_status"], "checked")
