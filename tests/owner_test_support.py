"""Isolated fixtures for owner analysis; never connect to a configured database."""

import os
import sys
import types
import unittest
from contextlib import contextmanager
from datetime import date

# Set these before importing the app, even when a local env.py exists.
os.environ["DEVELOPMENT"] = "True"
os.environ["DB_URL"] = "sqlite://"
os.environ["SECRET_KEY"] = "owner-analysis-tests-only"
sys.modules.setdefault("env", types.ModuleType("env"))

from flask import template_rendered
from sqlalchemy import text

from haulage_app import app, db
from haulage_app.models import (
    Day, Driver, DriverEmploymentHistory, EmploymentStatus, Fuel, Job, Payslip, Truck,
)


@contextmanager
def captured_templates():
    contexts = []

    def receiver(sender, template, context, **extra):
        contexts.append(context)

    template_rendered.connect(receiver, app)
    try:
        yield contexts
    finally:
        template_rendered.disconnect(receiver, app)


class OwnerTestCase(unittest.TestCase):
    """Raw table inserts preserve pence values and permit legacy bad data tests."""

    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        self.app = app
        self.context = app.app_context()
        self.context.push()
        url = db.engine.url
        if url.get_backend_name() != "sqlite" or url.database not in (None, "", ":memory:"):
            self.context.pop()
            raise RuntimeError("Owner tests require isolated in-memory SQLite; refusing database writes")
        self.tables = [table for table in db.metadata.sorted_tables if table.name != "payslip"]
        db.metadata.create_all(db.engine, tables=self.tables)
        # Production uses a PostgreSQL generated expression here. A deliberately
        # ordinary SQLite column lets fixtures include duplicate historical rows.
        db.session.execute(text("""
            CREATE TABLE payslip (
              id INTEGER PRIMARY KEY, day_id INTEGER, timestamp DATETIME,
              date DATE NOT NULL, driver_id INTEGER NOT NULL,
              total_wage INTEGER NOT NULL, total_cost_to_employer INTEGER NOT NULL,
              week_number_mtf INTEGER NOT NULL DEFAULT 0
            )
        """))
        db.session.commit()
        self.client = app.test_client()
        self.start = date(2026, 10, 3)

    def tearDown(self):
        db.session.rollback()
        db.session.remove()
        db.session.execute(text("DROP TABLE IF EXISTS payslip"))
        db.session.commit()
        db.session.remove()
        db.metadata.drop_all(db.engine, tables=self.tables)
        self.context.pop()

    def insert(self, model_class, **values):
        db.session.execute(model_class.__table__.insert(), values)
        db.session.commit()
        return values["id"]

    def add_truck(self, truck_id=1, **overrides):
        id = overrides.pop("id", truck_id)
        values = dict(id=id, registration=f"AA26 {id:03d}", make="Volvo", model="FH")
        values.update(overrides)
        return self.insert(Truck, **values)

    def add_driver(self, driver_id=1, *, employment_start=date(2025, 1, 1),
                   employment_end=None, employment=True, **overrides):
        id = overrides.pop("id", driver_id)
        values = dict(id=id, first_name=f"Driver{id}", last_name="Test", basic_wage=50000,
                      daily_bonus_threshold=35000, daily_bonus_percentage=0.25,
                      weekly_bonus_threshold=250000, weekly_bonus_percentage=0.2,
                      overnight_value=2500, truck_id=1)
        values.update(overrides)
        driver = self.insert(Driver, **values)
        if employment and employment_start is not None:
            db.session.execute(DriverEmploymentHistory.__table__.insert(), dict(
                driver_id=id, start_date=employment_start, end_date=employment_end,
                employment_status=(EmploymentStatus.INACTIVE if employment_end else EmploymentStatus.ACTIVE),
            ))
            db.session.commit()
        return driver

    def add_day(self, day_id=None, *, driver_id=1, on_date=date(2026, 10, 5), **overrides):
        id = overrides.pop("id", day_id)
        if id is None:
            id = (db.session.query(db.func.max(Day.id)).scalar() or 0) + 1
        values = dict(id=id, date=on_date, driver_id=1, truck_id=1, status="working",
                      overnight=False, fuel=False, start_mileage=100000, end_mileage=130000,
                      additional_earned=0, additional_wages=0)
        values["driver_id"] = driver_id
        values.update(overrides)
        return self.insert(Day, **values)

    def add_job(self, day_id, *, earned=50000, **overrides):
        id = overrides.pop("id", (db.session.query(db.func.max(Job.id)).scalar() or 0) + 1)
        values = dict(id=id, day_id=day_id, earned=50000, collection="Depot",
                      delivery="Port", notes="", split=False)
        values["earned"] = earned
        values.update(overrides)
        return self.insert(Job, **values)

    def add_fuel(self, *, truck_id=1, on_date=date(2026, 10, 5), **overrides):
        id = overrides.pop("id", (db.session.query(db.func.max(Fuel.id)).scalar() or 0) + 1)
        values = dict(id=id, date=on_date, truck_id=1, day_id=None,
                      fuel_card_name="Fleet", fuel_volume=10000, fuel_cost=12000)
        values["truck_id"] = truck_id
        values.update(overrides)
        return self.insert(Fuel, **values)

    def add_payslip(self, *, driver_id=1, on_date=date(2026, 10, 9), **overrides):
        id = overrides.pop("id", (db.session.query(db.func.max(Payslip.id)).scalar() or 0) + 1)
        values = dict(id=id, date=on_date, driver_id=1, day_id=None,
                      total_wage=50000, total_cost_to_employer=55000, week_number_mtf=0)
        values["driver_id"] = driver_id
        values.update(overrides)
        # SQLAlchemy correctly omits generated columns from normal ORM inserts;
        # this raw text insert targets our ordinary SQLite fixture column only.
        db.session.execute(text("""
            INSERT INTO payslip
              (id, date, driver_id, day_id, total_wage, total_cost_to_employer, week_number_mtf)
            VALUES (:id, :date, :driver_id, :day_id, :total_wage, :total_cost_to_employer, :week_number_mtf)
        """), values)
        db.session.commit()
        return id

    def configure_overheads(self, week_start=None, truck_count=4,
                            allowance_per_truck=50000, **kwargs):
        from haulage_app.owner_analysis.overheads import set_overhead_settings
        setting = set_overhead_settings(week_start or self.start, truck_count, allowance_per_truck, **kwargs)
        db.session.commit()
        return setting

    def get_page(self, path):
        with captured_templates() as contexts:
            response = self.client.get(path)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertTrue(contexts, "The page did not render a template")
        return response, contexts[-1]


# Kept explicit for service tests that prefer a descriptive fixture name.
OwnerAnalysisTestCase = OwnerTestCase
OwnerDatabaseTestCase = OwnerTestCase
