"""Driver choices use current employment without breaking historical entries.

Run with python -m unittest discover -s tests -v. All data lives in memory;
the test-only payslip table omits its PostgreSQL computed week expression,
which is unrelated to driver selection.
"""

import re
import unittest
from datetime import date, timedelta

# This module sets the isolated DB_URL before importing the application.
from test_entry_loading import app, db, record_request
from sqlalchemy import text

from haulage_app import f
from haulage_app.driver.choices import get_entry_drivers
from haulage_app.functions import get_week_number_sat_to_fri
from haulage_app.models import (
    Day, Driver, DriverEmploymentHistory, EmploymentStatus, Job, Payslip, Truck,
)
from haulage_app.verification.models import MissingEntryAnomaly, TableName


def driver_options(html):
    """Return IDs and selected IDs from the first driver dropdown in HTML."""
    select = re.search(r'<select\b[^>]*\bname="driver_id"[^>]*>(.*?)</select>',
                       html, re.DOTALL)
    if select is None:
        raise AssertionError("Driver dropdown missing")
    options = re.findall(r'<option\b([^>]*)>', select.group(1))
    values, selected = [], []
    for attrs in options:
        value = re.search(r'\bvalue="(\d+)"', attrs)
        if value:
            driver_id = int(value.group(1))
            values.append(driver_id)
            if re.search(r'\bselected\b', attrs):
                selected.append(driver_id)
    return values, selected


class ActiveDriverChoiceTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        self.context = app.app_context()
        self.context.push()
        if db.engine.url.get_backend_name() != "sqlite" or db.engine.url.database not in (None, "", ":memory:"):
            self.context.pop()
            raise RuntimeError("Driver-choice tests require isolated in-memory SQLite")
        self.tables = [table for table in db.metadata.sorted_tables if table.name != "payslip"]
        db.metadata.create_all(db.engine, tables=self.tables)
        db.session.execute(text("""
            CREATE TABLE payslip (
                id INTEGER PRIMARY KEY, day_id INTEGER, timestamp DATETIME,
                date DATE NOT NULL, driver_id INTEGER NOT NULL,
                total_wage INTEGER NOT NULL, total_cost_to_employer INTEGER NOT NULL,
                week_number_mtf INTEGER DEFAULT 1 NOT NULL,
                UNIQUE (driver_id, week_number_mtf)
            )
        """))
        self.client = app.test_client()
        self.today = date.today()
        self.old_date = self.today - timedelta(days=400)
        names = ["Alice", "Bob", "Cara", "Dara", "Ella", "Finn", "Gina", "Helen",
                 "Ian", "Jane", "Kate"]
        db.session.execute(Truck.__table__.insert(), [
            dict(id=1, registration="AA26 ONE", make="Volvo", model="FH"),
        ])
        db.session.execute(Driver.__table__.insert(), [
            dict(id=driver_id, first_name=name, last_name="Test", basic_wage=50000,
                 daily_bonus_threshold=35000, daily_bonus_percentage=0.25,
                 weekly_bonus_threshold=250000, weekly_bonus_percentage=0.2,
                 overnight_value=2500, truck_id=1)
            for driver_id, name in enumerate(names, 1)
        ])

        def employment(driver_id, start, end=None, status=EmploymentStatus.ACTIVE):
            return dict(driver_id=driver_id, start_date=self.today + timedelta(days=start),
                        end_date=None if end is None else self.today + timedelta(days=end),
                        employment_status=status)

        db.session.execute(DriverEmploymentHistory.__table__.insert(), [
            employment(1, -30),                              # Current, open-ended.
            employment(2, -500, -100, EmploymentStatus.INACTIVE),
            employment(3, 1),                                # Has not started yet.
            # Driver 4 has no employment history.
            employment(5, -30, 0),                           # Last working date is today.
            employment(6, 0),                                # First working date is today.
            employment(7, -30, -1),                          # Ended, despite ACTIVE status.
            employment(8, -30, None, EmploymentStatus.INACTIVE),
            employment(9, -500, -50, EmploymentStatus.INACTIVE),
            employment(9, -1),                               # Rehired.
            employment(10, -30, 30, EmploymentStatus.INACTIVE),
            employment(11, -30, 30),                         # Scheduled future end.
        ])
        self.active_ids = [1, 5, 6, 9, 11]
        db.session.execute(Day.__table__.insert(), [
            dict(id=driver_id, driver_id=driver_id, date=self.old_date, truck_id=1,
                 status="working", start_mileage=100000, end_mileage=110000,
                 overnight=False, fuel=False, additional_earned=0, additional_wages=0)
            for driver_id in (1, 2, 4)
        ])
        db.session.execute(Job.__table__.insert(), [
            dict(id=1, day_id=2, earned=12345, collection="Depot", delivery="Port",
                 notes="Historical job", split=False),
            dict(id=2, day_id=4, earned=12345, collection="Depot", delivery="Port",
                 notes="Other historical job", split=False),
        ])
        db.session.execute(Payslip.__table__.insert(), [
            dict(id=1, day_id=2, driver_id=2, date=self.old_date,
                 total_wage=50000, total_cost_to_employer=60000, week_number_mtf=1),
            dict(id=2, day_id=4, driver_id=4, date=self.old_date,
                 total_wage=50000, total_cost_to_employer=60000, week_number_mtf=1),
        ])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        with db.engine.begin() as connection:
            connection.execute(text("DROP TABLE payslip"))
        db.metadata.drop_all(db.engine, tables=self.tables)
        self.context.pop()

    def page(self, path):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        return response.text

    def test_current_employment_is_filtered_in_one_query(self):
        with record_request() as (_, statements):
            drivers = get_entry_drivers(on_date=self.today)
            self.assertEqual([driver.id for driver in drivers], self.active_ids)
            self.assertEqual([driver.full_name for driver in drivers],
                             ["Alice Test", "Ella Test", "Finn Test", "Ian Test", "Kate Test"])
        self.assertEqual(len(statements), 1)
        self.assertIn("exists", statements[0])

    def test_employment_start_and_end_dates_are_inclusive(self):
        yesterday = {driver.id for driver in get_entry_drivers(on_date=self.today - timedelta(days=1))}
        tomorrow = {driver.id for driver in get_entry_drivers(on_date=self.today + timedelta(days=1))}
        self.assertNotIn(6, yesterday)
        self.assertIn(7, yesterday)
        self.assertNotIn(3, yesterday)
        self.assertIn(3, tomorrow)
        self.assertNotIn(5, tomorrow)
        self.assertNotIn(7, tomorrow)

    def test_explicit_selection_adds_only_that_inactive_driver(self):
        for driver_id in ("2", 2):
            with self.subTest(driver_id=driver_id):
                with record_request() as (_, statements):
                    choices = get_entry_drivers(selected_driver_id=driver_id, on_date=self.today)
                    self.assertEqual([driver.id for driver in choices], [1, 2, 5, 6, 9, 11])
                self.assertEqual(len(statements), 1)
        self.assertEqual([driver.id for driver in get_entry_drivers(selected_driver_id=1)], self.active_ids)
        self.assertEqual([driver.id for driver in get_entry_drivers(selected_driver_id=99999)], self.active_ids)
        self.assertEqual([driver.id for driver in get_entry_drivers(selected_driver_id="invalid")], self.active_ids)

    def test_new_day_job_and_payslip_dropdowns_offer_only_active_drivers(self):
        for entry_type in ("day", "job", "payslip"):
            with self.subTest(entry_type=entry_type):
                html = self.page(f"/{entry_type}/add_{entry_type}/0/entry")
                self.assertEqual(driver_options(html), (self.active_ids, []))

    def test_no_active_drivers_does_not_fall_back_to_all_drivers(self):
        db.session.execute(DriverEmploymentHistory.__table__.update().values(
            employment_status=EmploymentStatus.INACTIVE,
        ))
        db.session.commit()
        for entry_type in ("day", "job", "payslip"):
            with self.subTest(entry_type=entry_type):
                html = self.page(f"/{entry_type}/add_{entry_type}/0/entry")
                self.assertEqual(driver_options(html), ([], []))
                if entry_type != "day":
                    modal = html.split('<div id="modal_edit_1"', 1)[1]
                    self.assertEqual(driver_options(modal), ([2], [2]))

    def test_job_and_payslip_edit_dropdowns_keep_saved_inactive_driver(self):
        for entry_type in ("job", "payslip"):
            with self.subTest(entry_type=entry_type):
                html = self.page(f"/{entry_type}/add_{entry_type}/0/history")
                modal = html.split('<div id="modal_edit_1"', 1)[1]
                self.assertEqual(driver_options(modal), ([1, 2, 5, 6, 9, 11], [2]))
                # An edit exception must not leak into the new-entry dropdown.
                self.assertEqual(driver_options(html), (self.active_ids, []))

    def test_shared_day_edit_macro_keeps_saved_inactive_driver(self):
        with app.test_request_context():
            macro = app.jinja_env.get_template("macros.html").module.day
            html = macro("edit", db.session.get(Day, 2),
                         {"drivers": get_entry_drivers(), "trucks": Truck.query.all()}, f)
        self.assertEqual(driver_options(str(html)), ([1, 2, 5, 6, 9, 11], [2]))

    def test_older_warning_links_keep_the_affected_inactive_driver_selected(self):
        year, week = get_week_number_sat_to_fri(self.old_date)
        for anomaly_id, table_name in [(1, TableName.DAY), (2, TableName.PAYSLIP)]:
            db.session.add(MissingEntryAnomaly(
                id=anomaly_id, driver_id=2, date=self.old_date, year=year,
                week_number=week, table_name=table_name,
            ))
        db.session.commit()
        for entry_type, anomaly_id in [("day", 1), ("payslip", 2)]:
            with self.subTest(entry_type=entry_type):
                html = self.page(f"/{entry_type}/add_{entry_type}/0/entry?anomaly_id={anomaly_id}")
                self.assertEqual(driver_options(html), ([1, 2, 5, 6, 9, 11], [2]))
                self.assertIn(str(self.old_date), html)

    def test_failed_posts_preserve_the_selected_inactive_driver(self):
        submissions = [
            ("day", dict(date="bad date", driver_id="2", status="working", truck_id="1")),
            ("job", dict(date_cd="bad date", driver_id="2", earned="100.00",
                         collection="Depot", delivery="Port")),
            # A valid date with no Day follows the existing missing-day error path.
            ("payslip", dict(date=self.today.strftime("%d/%m/%Y"), driver_id="2",
                             total_wage="500.00", total_cost_to_employer="600.00")),
        ]
        for entry_type, data in submissions:
            with self.subTest(entry_type=entry_type):
                response = self.client.post(f"/{entry_type}/add_{entry_type}/0/entry", data=data)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(driver_options(response.text), ([1, 2, 5, 6, 9, 11], [2]))

    def test_warning_and_error_exceptions_do_not_leak_into_unrelated_edit_forms(self):
        year, week = get_week_number_sat_to_fri(self.old_date)
        db.session.add(MissingEntryAnomaly(
            id=1, driver_id=2, date=self.old_date, year=year,
            week_number=week, table_name=TableName.PAYSLIP,
        ))
        db.session.commit()
        payslip_html = self.page("/payslip/add_payslip/0/entry?anomaly_id=1")
        response = self.client.post("/job/add_job/0/entry", data={
            "date_cd": "bad date", "driver_id": "2", "earned": "100.00",
            "collection": "Depot", "delivery": "Port",
        })
        self.assertEqual(response.status_code, 200)
        for html in (payslip_html, response.text):
            # Bob is retained for the warning/error in the new-entry form.
            self.assertEqual(driver_options(html), ([1, 2, 5, 6, 9, 11], [2]))
            # Dara's independent historical editor retains Dara, but not Bob.
            other_modal = html.split('<div id="modal_edit_2"', 1)[1]
            self.assertEqual(driver_options(other_modal), ([1, 4, 5, 6, 9, 11], [4]))

    def test_historical_job_and_payslip_can_still_be_saved_for_inactive_driver(self):
        old_date = self.old_date.strftime("%d/%m/%Y")
        response = self.client.post("/job/edit_job/1", data={
            "date_cd": old_date, "driver_id": "2", "earned": "175.25",
            "collection": "Depot", "delivery": "Town", "notes": "Edited historical job",
        })
        self.assertEqual(response.status_code, 302)
        edited_job = db.session.get(Job, 1)
        self.assertEqual((edited_job.day.driver_id, edited_job.earned), (2, 17525))
        response = self.client.post("/payslip/edit_payslip/1", data={
            "date": old_date, "driver_id": "2", "total_wage": "550.00",
            "total_cost_to_employer": "650.00",
        })
        self.assertEqual(response.status_code, 302)
        edited_payslip = db.session.get(Payslip, 1)
        self.assertEqual((edited_payslip.driver_id, edited_payslip.total_wage,
                          edited_payslip.total_cost_to_employer), (2, 55000, 65000))

    def test_week_editor_for_inactive_driver_keeps_historical_days_editable(self):
        html = self.page("/day/add_day/0/history")
        year, week = get_week_number_sat_to_fri(self.old_date)
        self.assertIn(f'id="driverModal2{year}{week}"', html)
        prefix = f"2-{self.old_date}"
        response = self.client.post("/day/edit_days", data={
            "driver_id": "2", "year": str(year), "week": str(week),
            f"{prefix}-id": "2", f"{prefix}-status": "working", f"{prefix}-truck": "1",
            f"{prefix}-start_mileage": "1200.00", f"{prefix}-end_mileage": "1300.00",
        })
        self.assertEqual(response.status_code, 302)
        edited_day = db.session.get(Day, 2)
        self.assertEqual((edited_day.driver_id, edited_day.start_mileage, edited_day.end_mileage),
                         (2, 120000, 130000))


if __name__ == "__main__":
    unittest.main()
