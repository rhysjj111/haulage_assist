"""Weekly investigation context stays bounded and independent of edit forms."""

from copy import deepcopy
from datetime import date, timedelta

from sqlalchemy import event, text

from owner_test_support import OwnerTestCase, db
from haulage_app.models import Driver, Job, Payslip
from haulage_app.owner_analysis.corrections import _week_basis
from haulage_app.owner_analysis.investigation import build_week_context


class OwnerInvestigationDataTests(OwnerTestCase):
    def setUp(self):
        super().setUp()
        self.add_truck()
        self.add_truck(2)
        self.add_driver()
        self.add_driver(2)
        self.as_of = self.start + timedelta(days=8)

    def week_context(self, basis=None, **kwargs):
        kwargs.setdefault("driver_id", 1)
        kwargs.setdefault("as_of", self.as_of)
        return build_week_context(self.start, basis if basis is not None else _week_basis(self.start), **kwargs)

    def test_seven_dates_show_actual_statuses_and_unknown_blanks(self):
        self.add_day(on_date=self.start, status="holiday")
        self.add_day(on_date=self.start + timedelta(days=1), status="absent")
        self.add_day(on_date=self.start + timedelta(days=2), additional_earned=0)
        self.add_day(driver_id=2, on_date=self.start + timedelta(days=3))
        context = self.week_context()
        self.assertEqual([row["date"] for row in context["days"]],
                         [self.start + timedelta(days=i) for i in range(7)])
        self.assertEqual([row["status_label"] for row in context["days"][:4]],
                         ["Holiday", "Absent", "Working", "No entry"])
        self.assertEqual(context["days"][2]["earnings"], 0)
        self.assertIsNone(context["days"][3]["earnings"])
        self.assertEqual(context["summary"]["recorded_days"], 3)
        self.assertEqual(context["summary"]["working_days"], 1)
        self.assertEqual(context["summary"]["holiday_days"], 1)
        self.assertEqual(context["summary"]["absent_days"], 1)
        self.assertEqual(context["summary"]["missing_days"], 4)

    def test_many_jobs_and_additional_are_counted_once_without_mutating_basis(self):
        first_day = self.add_day(on_date=self.start, additional_earned=1)
        first_job = self.add_job(first_day, earned=12345)
        self.add_job(first_day, earned=67890, split=True)
        self.add_day(on_date=self.start + timedelta(days=1), additional_earned=3)
        basis = _week_basis(self.start)
        basis["jobs"].append(deepcopy(next(row for row in basis["jobs"] if row["id"] == first_job)))
        original = deepcopy(basis)
        context = self.week_context(basis, target_type="job", target_id=first_job)
        self.assertEqual(context["days"][0]["job_earnings"], 80235)
        self.assertEqual(context["days"][0]["earnings"], 80236)
        self.assertEqual(context["summary"]["earnings"], 80239)
        self.assertTrue(context["days"][0]["highlighted"])
        self.assertTrue(context["days"][0]["entries"][0]["highlighted"])
        self.assertEqual(len(context["days"][0]["entries"][0]["jobs"]), 2)
        self.assertEqual(basis, original)

    def test_blank_weekends_are_not_scheduled_or_missing_but_weekdays_still_are(self):
        context = self.week_context()
        self.assertEqual([row["label"] for row in context["days"][:2]],
                         ["Not scheduled", "Not scheduled"])
        self.assertTrue(all(row["is_non_working_day"] for row in context["days"][:2]))
        self.assertEqual(context["summary"]["missing_days"], 5)
        self.assertEqual(context["summary"]["absent_days"], 0)
        self.assertEqual(context["days"][2]["label"], "No entry")

    def test_recorded_weekend_work_and_explicit_absence_remain_in_the_week(self):
        saturday = self.add_day(on_date=self.start, additional_earned=100)
        self.add_job(saturday, earned=12345)
        self.add_day(on_date=self.start + timedelta(days=1), status="absent")
        context = self.week_context()
        self.assertEqual(context["days"][0]["label"], "Working")
        self.assertEqual(context["days"][1]["label"], "Absent")
        self.assertEqual(context["summary"]["working_days"], 1)
        self.assertEqual(context["summary"]["absent_days"], 1)
        self.assertEqual(context["summary"]["earnings"], 12445)
        self.assertEqual(context["summary"]["missing_days"], 5)

    def test_future_weekends_are_not_yet_due_and_never_missing(self):
        context = self.week_context(as_of=self.start - timedelta(days=1))
        self.assertEqual(context["days"][0]["label"], "Not yet due")
        self.assertEqual(context["days"][1]["label"], "Not yet due")
        self.assertEqual(context["summary"]["missing_days"], 0)

    def test_future_dated_actual_records_are_excluded_from_context(self):
        past_day = self.add_day(on_date=self.start, additional_earned=101)
        self.add_job(past_day, earned=200)
        future_day = self.add_day(on_date=self.start + timedelta(days=4), additional_earned=500)
        self.add_job(future_day, earned=600)
        self.add_payslip(on_date=self.start + timedelta(days=2), total_wage=110, total_cost_to_employer=120)
        self.add_payslip(driver_id=2, on_date=self.start + timedelta(days=6))
        context = self.week_context(as_of=self.start + timedelta(days=2))
        self.assertEqual(context["summary"]["earnings"], 301)
        self.assertEqual(len(context["payslips"]), 1)
        self.assertEqual(context["days"][4]["label"], "Not yet due")
        self.assertEqual(context["days"][4]["entries"], [])
        self.assertIsNone(context["days"][4]["earnings"])
        self.assertEqual(context["summary"]["missing_days"], 1)

    def test_all_week_payslips_are_shown_by_date_with_selected_highlights(self):
        day = self.add_day(on_date=self.start)
        chosen = self.add_payslip(on_date=self.start + timedelta(days=2), total_wage=0,
                                  total_cost_to_employer=0, day_id=day)
        self.add_payslip(driver_id=2, on_date=self.start + timedelta(days=3), day_id=day)
        self.add_payslip(driver_id=1, on_date=self.start - timedelta(days=1), day_id=day)
        context = self.week_context(target_type="payslip", target_id=chosen)
        self.assertEqual(len(context["payslips"]), 2)
        selected = next(row for row in context["payslips"] if row["id"] == chosen)
        self.assertTrue(selected["highlighted"])
        self.assertTrue(selected["selected_record"])
        self.assertEqual(selected["total_wage"], 0)
        self.assertFalse(context["driver_payslip_missing"])
        self.assertFalse(next(row for row in context["payslips"] if row["driver_id"] == 2)["highlighted"])
        db.session.execute(text("DELETE FROM payslip WHERE driver_id = 1"))
        db.session.commit()
        self.assertTrue(self.week_context()["driver_payslip_missing"])

    def test_truck_scope_only_lists_recorded_assignments_without_attributing_earnings(self):
        selected_day = self.add_day(on_date=self.start, additional_earned=400)
        self.add_job(selected_day, earned=500)
        self.add_day(on_date=self.start + timedelta(days=1), truck_id=2)
        self.add_day(driver_id=2, on_date=self.start + timedelta(days=2))
        self.add_payslip(driver_id=2)
        self.add_fuel(on_date=self.start, truck_id=1, fuel_cost=123, fuel_volume=456)
        self.add_fuel(on_date=self.start, truck_id=2, fuel_cost=999)
        context = self.week_context(driver_id=None, truck_id=1)
        self.assertEqual(context["scope"], "truck")
        self.assertEqual(context["summary"]["recorded_days"], 2)
        self.assertEqual(context["days"][1]["entries"], [])
        self.assertIsNone(context["summary"]["earnings"])
        self.assertIsNone(context["days"][0]["entries"][0]["earnings"])
        self.assertIsNone(context["days"][0]["entries"][0]["jobs"][0]["earned"])
        self.assertEqual(context["summary"]["fuel_spending"], 123)
        self.assertEqual(context["summary"]["fuel_volume"], 456)
        self.assertEqual(len(context["payslips"]), 1)

    def test_nearby_payslips_are_opt_in_bounded_and_separate(self):
        self.add_payslip(on_date=self.start)
        previous = self.add_payslip(on_date=self.start - timedelta(days=1), total_cost_to_employer=111)
        following = self.add_payslip(on_date=self.start + timedelta(days=7), total_cost_to_employer=222)
        self.add_payslip(on_date=self.start - timedelta(days=8))
        self.add_payslip(on_date=self.start + timedelta(days=14))
        self.add_payslip(driver_id=2, on_date=self.start - timedelta(days=1))
        basis = _week_basis(self.start)
        queries = []

        def capture(connection, cursor, statement, parameters, context, executemany):
            queries.append((statement.lower(), parameters))

        event.listen(db.engine, "before_cursor_execute", capture)
        try:
            without = self.week_context(basis)
            self.assertEqual(without["nearby_payslips"], [])
            self.assertFalse(without["nearby_loaded"])
            self.assertFalse(any("from payslip" in sql for sql, _ in queries))
            queries.clear()
            with_nearby = self.week_context(basis, include_nearby=True)
        finally:
            event.remove(db.engine, "before_cursor_execute", capture)
        self.assertEqual({row["id"] for row in with_nearby["nearby_payslips"]}, {previous, following})
        self.assertTrue(with_nearby["nearby_loaded"])
        self.assertTrue(all(row["outside_selected_week"] for row in with_nearby["nearby_payslips"]))
        self.assertEqual(with_nearby["payslips"], without["payslips"])
        self.assertEqual(with_nearby["summary"], without["summary"])
        nearby_sql = [sql for sql, _ in queries if "from payslip" in sql]
        self.assertEqual(len(nearby_sql), 1)
        self.assertIn("limit", nearby_sql[0])

    def test_nearby_display_limit_and_explicit_future_date_flags(self):
        for identifier in range(1, 53):
            self.add_payslip(id=identifier, on_date=self.start - timedelta(days=1))
        self.add_payslip(id=53, on_date=self.start + timedelta(days=7))
        context = self.week_context(include_nearby=True, as_of=self.start + timedelta(days=2))
        self.assertEqual(len(context["nearby_payslips"]), 50)
        self.assertTrue(context["nearby_truncated"])
        future = next(row for row in context["nearby_payslips"] if row["id"] == 53)
        self.assertTrue(future["future_dated"])
        self.assertTrue(future["outside_selected_week"])
        self.assertEqual(context["payslips"], [])
        self.assertFalse(context["nearby_payslips"][-1]["future_dated"])
        self.assertFalse(self.week_context(driver_id=None, include_nearby=True)["nearby_loaded"])

    def test_duplicate_day_scalars_are_visible_and_conflicting_status_not_guessed(self):
        day = self.add_day(on_date=self.start, additional_earned=100)
        basis = _week_basis(self.start)
        conflicting = dict(basis["days"][0], id=day + 100, status="holiday", additional_earned=200)
        basis["days"].append(conflicting)
        context = self.week_context(basis)
        self.assertEqual(len(context["days"][0]["entries"]), 2)
        self.assertTrue(context["days"][0]["duplicate_entries"])
        self.assertEqual(context["summary"]["duplicate_day_groups"], 1)
        self.assertEqual(context["summary"]["recorded_days"], 1)
        self.assertEqual(context["summary"]["working_days"], 0)
        self.assertEqual(context["summary"]["holiday_days"], 0)
        self.assertEqual(context["summary"]["earnings"], 300)

    def test_read_does_not_flush_or_overwrite_unrelated_pending_edits(self):
        day = self.add_day(on_date=self.start)
        job = self.add_job(day)
        self.add_payslip(on_date=self.start - timedelta(days=1))
        basis = _week_basis(self.start)
        pending_job = db.session.get(Job, job)
        pending_driver = db.session.get(Driver, 1)
        pending_job.notes = "Unrelated unsaved note"
        pending_driver.first_name = "Unsaved"
        queries = []

        def capture(connection, cursor, statement, parameters, context, executemany):
            queries.append(statement.lower().lstrip())

        event.listen(db.engine, "before_cursor_execute", capture)
        try:
            self.week_context(basis, include_nearby=True)
        finally:
            event.remove(db.engine, "before_cursor_execute", capture)
        self.assertFalse(any(sql.startswith(("insert", "update", "delete")) for sql in queries))
        self.assertIn(pending_job, db.session.dirty)
        self.assertIn(pending_driver, db.session.dirty)
        self.assertEqual(pending_driver.first_name, "Unsaved")
        self.assertEqual(pending_job.notes, "Unrelated unsaved note")

    def test_exact_record_scope_is_derived_without_relationship_queries(self):
        day = self.add_day(driver_id=2, on_date=self.start)
        job = self.add_job(day)
        context = self.week_context(driver_id=None, target_type="job", target_id=job)
        self.assertEqual(context["scope"], "driver")
        self.assertEqual(context["driver_id"], 2)
        self.assertTrue(context["days"][0]["highlighted"])
        self.assertEqual(context["driver_name"], "Driver2 Test")
