"""Entry-page regression checks: python -m unittest discover -s tests -v.

Use an isolated in-memory database, regardless of the developer's DB_URL.
The unrelated PostgreSQL-only payslip computed column is not needed here.
"""

import os
import re
import unittest
from collections import Counter
from contextlib import contextmanager
from datetime import date, timedelta

os.environ["DEVELOPMENT"] = "True"
os.environ["DB_URL"] = "sqlite://"
os.environ["SECRET_KEY"] = "entry-page-tests-only"

from flask import template_rendered
from sqlalchemy import event

from haulage_app import app, db
from haulage_app.analysis.functions import get_start_of_week
from haulage_app.day.forms import DayForm
from haulage_app.functions import get_week_number_sat_to_fri
from haulage_app.models import Day, Driver, DriverEmploymentHistory, EmploymentStatus, Job, Truck
from haulage_app.verification.models import IncorrectMileage, MissingEntryAnomaly, TableName


@contextmanager
def record_request():
    contexts, statements = [], []

    def rendered(sender, template, context, **extra):
        contexts.append(context)

    def queried(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.lower().split()))

    db.session.remove()  # Each request starts without previously loaded objects.
    template_rendered.connect(rendered, app)
    event.listen(db.engine, "before_cursor_execute", queried)
    try:
        yield contexts, statements
    finally:
        template_rendered.disconnect(rendered, app)
        event.remove(db.engine, "before_cursor_execute", queried)


class EntryLoadingTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        self.context = app.app_context()
        self.context.push()
        if db.engine.url.get_backend_name() != "sqlite" or db.engine.url.database not in (None, "", ":memory:"):
            self.context.pop()
            raise RuntimeError("Entry tests require isolated in-memory SQLite; refusing to change this database")
        self.tables = [table for table in db.metadata.sorted_tables if table.name != "payslip"]
        db.metadata.create_all(db.engine, tables=self.tables)
        self.client = app.test_client()
        self.start = date(2026, 1, 3)  # Saturday: cutoff deliberately falls midweek.
        db.session.execute(Truck.__table__.insert(), [
            dict(id=1, registration="AA26 ONE", make="Volvo", model="FH"),
            dict(id=2, registration="BB26 TWO", make="Scania", model="R"),
        ])
        db.session.execute(Driver.__table__.insert(), [
            dict(id=driver_id, first_name=first_name, last_name="Test", basic_wage=50000,
                 daily_bonus_threshold=35000, daily_bonus_percentage=0.25,
                 weekly_bonus_threshold=250000, weekly_bonus_percentage=0.2,
                 overnight_value=2500, truck_id=driver_id)
            for driver_id, first_name in [(1, "Alice"), (2, "Bob")]
        ])
        db.session.execute(DriverEmploymentHistory.__table__.insert(), [
            dict(driver_id=driver_id, start_date=date.today() - timedelta(days=365),
                 end_date=None, employment_status=EmploymentStatus.ACTIVE)
            for driver_id in (1, 2)
        ])
        self.days = []
        for driver_id, count in [(1, 42), (2, 35)]:
            # Insert latest first, keeping the fixture independent of insertion order.
            for offset in reversed(range(count)):
                self.days.append(dict(
                    id=driver_id * 1000 + offset, driver_id=driver_id,
                    date=self.start + timedelta(days=offset), truck_id=driver_id,
                    status="working", start_mileage=100000, end_mileage=110000,
                    overnight=False, fuel=False, additional_earned=0, additional_wages=0,
                ))
        for row in self.days:
            if (row["driver_id"], row["date"]) in [(1, self.start + timedelta(days=1)),
                                                      (1, self.start + timedelta(days=15))]:
                row["start_mileage"] = 0
            if (row["driver_id"], row["date"]) == (2, self.start + timedelta(days=14)):
                row["end_mileage"] = 0
        db.session.execute(Day.__table__.insert(), self.days)
        db.session.execute(Job.__table__.insert(), [
            dict(id=index + 1, day_id=row["id"], earned=12345,
                 collection="Collection", delivery="Delivery", notes="Keep me", split=False)
            for index, row in enumerate(self.days[:56])
        ])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.metadata.drop_all(db.engine, tables=self.tables)
        self.context.pop()

    def get_page(self, path):
        with record_request() as (contexts, statements):
            response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(contexts), 1)
        return response, contexts[0], statements

    def test_day_history_uses_latest_30_for_each_driver_and_prioritizes_mileage(self):
        response, context, statements = self.get_page("/day/add_day/0/history")
        entries = context["list"]
        self.assertEqual(Counter(entry.driver_id for entry in entries), {1: 30, 2: 30})
        for driver_id in (1, 2):
            expected = sorted((row for row in self.days if row["driver_id"] == driver_id),
                              key=lambda row: row["date"], reverse=True)[:30]
            self.assertEqual({entry.id for entry in entries if entry.driver_id == driver_id},
                             {row["id"] for row in expected})
        self.assertEqual([entry.id for entry in entries[:2]], [1015, 2014])
        self.assertNotIn(1001, [entry.id for entry in entries])
        self.assertEqual(len(re.findall(r'<div id="modal_delete_\d+"', response.text)), 60)
        self.assertEqual(sum(bool(re.search(r"\bfrom truck\b", sql)) for sql in statements), 1)

    def test_week_editors_cover_only_visible_weeks_and_keep_complete_cutoff_week(self):
        response, context, _ = self.get_page("/day/add_day/0/history")
        visible_weeks = {(entry.driver_id, *get_week_number_sat_to_fri(entry.date))
                         for entry in context["list"]}
        editors = context["driver_weeks_forms"]
        self.assertEqual({(driver_id, *week) for driver_id, weeks in editors.items() for week in weeks},
                         visible_weeks)
        cutoff = min(entry.date for entry in context["list"] if entry.driver_id == 1)
        year, week = get_week_number_sat_to_fri(cutoff)
        week_dates, forms = editors[1][(year, week)]
        week_start = get_start_of_week(year, week)
        self.assertLess(week_start, cutoff)
        self.assertEqual(week_dates, [week_start + timedelta(days=i) for i in range(7)])
        self.assertTrue(all(forms[day_date] is not None for day_date in week_dates))
        self.assertIn(f'name="1-{week_start}-id"', response.text)
        self.assertEqual(forms[week_start].truck.choices, [(1, "AA26 ONE"), (2, "BB26 TWO")])
        old_week = get_week_number_sat_to_fri(self.start)
        self.assertNotIn(old_week, editors[1])

    def test_old_warning_links_load_affected_dates_and_week_editors(self):
        year, week = get_week_number_sat_to_fri(self.start)
        db.session.add_all([
            IncorrectMileage(id=1, truck_id=1, year=year, week_number=week,
                             previous_date=self.start, next_date=self.start + timedelta(days=1),
                             previous_end_mileage=110000, next_start_mileage=0),
            MissingEntryAnomaly(id=2, driver_id=1, date=self.start, year=year,
                                week_number=week, table_name=TableName.DAY),
        ])
        db.session.commit()
        _, context, _ = self.get_page("/day/add_day/0/history?anomaly_id=1")
        self.assertEqual({entry.id for entry in context["list"]}, {1000, 1001})
        self.assertIn((year, week), context["driver_weeks_forms"][1])
        self.assertIsNone(context["recent_entries_limit"])
        _, context, _ = self.get_page("/day/add_day/0/history?anomaly_id=2")
        self.assertIn(1000, [entry.id for entry in context["list"]])
        self.assertTrue(all(entry.driver_id == 1 for entry in context["list"]))
        self.assertEqual(context["day"], {"driver_id": 1, "date": self.start})

    def test_day_queries_stay_bounded_as_old_history_grows(self):
        _, context, initial = self.get_page("/day/add_day/0/entry")
        initial_ids = {entry.id for entry in context["list"]}
        old_days = [dict(self.days[0], id=3000 + offset,
                         date=self.start - timedelta(days=offset + 1)) for offset in range(240)]
        db.session.execute(Day.__table__.insert(), old_days)
        db.session.commit()
        _, context, grown = self.get_page("/day/add_day/0/entry")
        self.assertEqual(len(context["list"]), 60)
        self.assertEqual({entry.id for entry in context["list"]}, initial_ids)
        self.assertEqual(len(initial), len(grown))
        self.assertLessEqual(len(grown), 12)
        self.assertLessEqual(sum(bool(re.search(r"\bfrom job\b", sql)) for sql in grown), 1)

    def test_empty_database_renders_without_history_or_week_editors(self):
        for model in (Job, Day, DriverEmploymentHistory, Driver, Truck):
            db.session.execute(model.__table__.delete())
        db.session.commit()
        for path in ("/day/add_day/0/entry", "/job/add_job/0/entry"):
            _, context, _ = self.get_page(path)
            self.assertEqual(context["list"], [])
            self.assertEqual(context.get("driver_weeks_forms", {}), {})

    def test_cutoff_week_editor_keeps_days_on_both_sides_of_new_year(self):
        db.session.execute(Job.__table__.delete())
        db.session.execute(Day.__table__.delete())
        start = date(2025, 12, 20)
        db.session.execute(Day.__table__.insert(), [
            dict(self.days[0], id=4000 + offset, date=start + timedelta(days=offset))
            for offset in range(42)
        ])
        db.session.commit()
        response, context, _ = self.get_page("/day/add_day/0/history")
        self.assertEqual(len(context["list"]), 30)
        cutoff = min(entry.date for entry in context["list"])
        self.assertEqual(cutoff, date(2026, 1, 1))
        year, week = get_week_number_sat_to_fri(cutoff)
        week_dates, forms = context["driver_weeks_forms"][1][(year, week)]
        self.assertEqual(week_dates, [date(2025, 12, 27) + timedelta(days=i) for i in range(7)])
        self.assertTrue(all(forms[day_date] is not None for day_date in week_dates))
        for day_date in week_dates:
            self.assertIn(f'name="1-{day_date}-id"', response.text)

    def test_day_form_retains_default_truck_choices_and_accepts_explicit_empty_choices(self):
        with app.test_request_context():
            with record_request() as (_, statements):
                self.assertEqual(DayForm(truck_choices=[]).truck.choices, [])
            self.assertEqual(statements, [])
            self.assertEqual(DayForm().truck.choices, [(1, "AA26 ONE"), (2, "BB26 TWO")])

    def test_day_add_and_cutoff_week_submission_preserve_values(self):
        response = self.client.post("/day/add_day/0/entry", data={
            "date": "14/02/2026", "driver_id": "1", "status": "working", "truck_id": "1",
            "start_mileage": "1500.25", "end_mileage": "1600.50", "fuel": "on",
            "additional_earned": "12.50", "additional_wages": "3.25",
        })
        self.assertEqual(response.status_code, 302)
        added = Day.query.filter_by(driver_id=1, date=date(2026, 2, 14)).one()
        self.assertEqual((added.start_mileage, added.end_mileage, added.additional_earned,
                          added.additional_wages, added.fuel), (150025, 160050, 1250, 325, True))
        # This older day is outside history but belongs to its first visible week.
        day_date = date(2026, 1, 10)
        year, week = get_week_number_sat_to_fri(day_date)
        prefix = f"1-{day_date}"
        response = self.client.post("/day/edit_days", data={
            "driver_id": "1", "year": str(year), "week": str(week),
            f"{prefix}-id": "1007", f"{prefix}-status": "working", f"{prefix}-truck": "2",
            f"{prefix}-start_mileage": "1800.25", f"{prefix}-end_mileage": "1900.50",
            f"{prefix}-fuel": "y", f"{prefix}-overnight": "y",
        })
        self.assertEqual(response.status_code, 302)
        edited = db.session.get(Day, 1007)
        self.assertEqual((edited.truck_id, edited.start_mileage, edited.end_mileage,
                          edited.fuel, edited.overnight), (2, 180025, 190050, True, True))

    def test_job_history_keeps_50_and_uses_linked_day_for_edit_defaults(self):
        response, context, statements = self.get_page("/job/add_job/0/history")
        self.assertEqual([entry.id for entry in context["list"]], list(range(56, 6, -1)))
        self.assertNotIn("days", context["components"])
        self.assertFalse(any(re.search(r"\bfrom day\b", sql) for sql in statements))
        self.assertLessEqual(len(statements), 8)
        for entry in context["list"]:
            modal = response.text.split(f'<div id="modal_edit_{entry.id}"', 1)[1]
            driver_select = modal.split('<select name="driver_id"', 1)[1].split("</select>", 1)[0]
            self.assertRegex(driver_select, rf'<option value="{entry.day.driver_id}" selected>')
            self.assertIn(f'value="{entry.day.date}"', modal.split("</form>", 1)[0])

    def test_job_add_split_and_edit_keep_database_relationships(self):
        response = self.client.post("/job/add_job/0/entry", data={
            "date_cd": "10/01/2026", "driver_id": "2", "earned": "240.00",
            "collection": "Depot", "delivery": "Port", "notes": "Split check", "split": "on",
        })
        self.assertEqual(response.status_code, 200)
        added = Job.query.filter_by(notes="Split check").order_by(Job.id).all()
        self.assertEqual(len(added), 2)
        self.assertEqual([entry.day.date for entry in added], [date(2026, 1, 10), date(2026, 1, 11)])
        self.assertTrue(all(entry.day.driver_id == 2 and entry.earned == 12000 and entry.split
                            for entry in added))
        response = self.client.post(f"/job/edit_job/{added[0].id}", data={
            "date_cd": "12/01/2026", "driver_id": "1", "earned": "175.25",
            "collection": "Depot", "delivery": "Town", "notes": "Edited",
        })
        self.assertEqual(response.status_code, 302)
        db.session.expire_all()
        edited = db.session.get(Job, added[0].id)
        self.assertEqual((edited.day.driver_id, edited.day.date, edited.earned, edited.split),
                         (1, date(2026, 1, 12), 17525, False))


if __name__ == "__main__":
    unittest.main()
