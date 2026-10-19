"""Recorded owner popup details stay within the selected entity and period."""

from datetime import date, datetime, timedelta

from sqlalchemy import event

from owner_test_support import OwnerTestCase, db
from haulage_app.models import Day, Driver, Truck
from haulage_app.owner_analysis.entity_details import build_entity_details


class OwnerEntityDetailTests(OwnerTestCase):
    def setUp(self):
        super().setUp()
        self.add_truck()
        self.add_truck(2)
        self.add_driver()
        self.add_driver(2)
        self.as_of = date(2026, 11, 1)

    def details(self, kind="driver", subject=1, **kwargs):
        if "month" not in kwargs and "week_start" not in kwargs:
            kwargs["week_start"] = self.start
        kwargs.setdefault("as_of", self.as_of)
        return build_entity_details(kind, subject, **kwargs)

    def test_driver_week_shows_recorded_jobs_swaps_weekend_and_own_payroll(self):
        saturday = self.add_day(on_date=self.start)
        monday = self.add_day(on_date=self.start + timedelta(days=2), additional_earned=1234)
        tuesday = self.add_day(on_date=self.start + timedelta(days=3), truck_id=2)
        holiday = self.add_day(on_date=self.start + timedelta(days=4), status="holiday", truck_id=None)
        self.add_job(saturday, earned=20000, collection="Quarry", delivery="Port")
        self.add_job(monday, earned=31001, collection="Depot", delivery="Bristol",
                     notes="Night delivery", split=True)
        self.add_job(monday, earned=14789, collection="Cardiff", delivery="Yard")
        self.add_job(tuesday, earned=50000)
        other_day = self.add_day(driver_id=2, on_date=self.start + timedelta(days=2))
        self.add_job(other_day, earned=99999)
        self.add_payslip(total_wage=61000, total_cost_to_employer=72000)
        self.add_payslip(driver_id=2, total_wage=99000, total_cost_to_employer=100000)
        details = self.details()
        week = details["weeks"][0]
        self.assertEqual(len(week["days"]), 7)
        self.assertEqual(week["days"][0]["entries"][0]["jobs"][0]["collection"], "Quarry")
        self.assertEqual(week["days"][1]["label"], "Not scheduled")
        self.assertEqual(week["days"][5]["label"], "No entry")
        entry = week["days"][2]["entries"][0]
        self.assertEqual(entry["earnings"], 31001 + 14789 + 1234)
        self.assertEqual(entry["jobs"][0]["notes"], "Night delivery")
        self.assertTrue(entry["jobs"][0]["split"])
        self.assertEqual(week["days"][3]["entries"][0]["truck_registration"], "AA26 002")
        self.assertEqual(week["days"][4]["entries"][0]["id"], holiday)
        self.assertEqual(details["summary"]["working_days"], 3)
        self.assertEqual(details["summary"]["holiday_days"], 1)
        self.assertEqual(details["summary"]["absent_days"], 0)
        self.assertEqual(details["summary"]["earnings"], 117024)
        self.assertEqual(details["summary"]["employer_cost"], 72000)
        self.assertEqual([row["driver_id"] for row in week["payslips"]], [1])

    def test_partial_week_excludes_future_entries_jobs_and_payslips(self):
        monday = self.add_day(on_date=date(2026, 10, 5))
        wednesday = self.add_day(on_date=date(2026, 10, 7))
        self.add_job(monday, earned=23000)
        self.add_job(wednesday, earned=99000)
        self.add_payslip(on_date=date(2026, 10, 9))
        details = self.details(as_of=date(2026, 10, 6))
        week = details["weeks"][0]
        self.assertEqual(details["summary"]["earnings"], 23000)
        self.assertEqual(week["payslips"], [])
        self.assertEqual(week["recorded_through"], date(2026, 10, 6))
        self.assertTrue(week["days"][4]["is_future"])
        self.assertEqual(week["days"][4]["label"], "Not yet due")
        self.assertEqual(week["days"][4]["entries"], [])

    def test_month_uses_only_finished_whole_weeks_assigned_by_tuesday(self):
        # 26 September's Tuesday belongs to September; 31 October's to November.
        for day, earned in ((date(2026, 9, 30), 10000), (date(2026, 10, 5), 20000),
                            (date(2026, 10, 12), 30000), (date(2026, 10, 19), 40000),
                            (date(2026, 10, 31), 50000)):
            self.add_job(self.add_day(on_date=day), earned=earned)
        details = self.details(month=date(2026, 10, 1), as_of=date(2026, 10, 18))
        self.assertEqual([week["week_start"] for week in details["weeks"]],
                         [date(2026, 10, 3), date(2026, 10, 10)])
        self.assertEqual(details["period_end"], date(2026, 10, 16))
        self.assertEqual(details["summary"]["earnings"], 50000)
        self.assertEqual(details["pending_week_count"], 2)
        complete = self.details(month=date(2026, 10, 1), as_of=date(2026, 11, 7))
        self.assertEqual(complete["period_end"], date(2026, 10, 30))
        self.assertEqual(complete["summary"]["earnings"], 90000)
        friday = self.details(month=date(2026, 10, 1), as_of=date(2026, 10, 9))
        self.assertEqual(friday["weeks"], [])
        saturday = self.details(month=date(2026, 10, 1), as_of=date(2026, 10, 10))
        self.assertEqual(len(saturday["weeks"]), 1)

    def test_empty_future_month_needs_only_subject_lookup(self):
        statements = []
        def record(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)
        event.listen(db.engine, "before_cursor_execute", record)
        try:
            details = self.details(month=date(2027, 2, 1))
        finally:
            event.remove(db.engine, "before_cursor_execute", record)
        self.assertEqual(details["weeks"], [])
        self.assertIsNone(details["period_start"])
        self.assertEqual(details["pending_week_count"], 4)
        self.assertEqual(len(statements), 1)
        self.assertEqual(details["summary"]["earnings"], 0)

    def test_historical_driver_without_current_employment_can_be_reviewed(self):
        self.add_driver(3, employment=False, first_name="Past", last_name="Driver")
        self.add_day(driver_id=3)
        details = self.details(subject=3)
        self.assertEqual(details["name"], "Past Driver")
        self.assertEqual(details["summary"]["recorded_days"], 1)

    def test_truck_reads_each_assignment_and_actual_dated_unlinked_receipts(self):
        first = self.add_day(on_date=date(2026, 10, 5), fuel=True,
                             start_mileage=10000000, end_mileage=10025000)
        second = self.add_day(driver_id=2, on_date=date(2026, 10, 5), fuel=True,
                              start_mileage=10020000, end_mileage=10045000)
        self.add_day(on_date=date(2026, 10, 6), fuel=True)
        self.add_day(driver_id=2, on_date=date(2026, 10, 6), truck_id=2)
        self.add_job(first, earned=88888)
        self.add_payslip()
        fuel_id = self.add_fuel(on_date=date(2026, 10, 5), fuel_cost=22345, fuel_volume=18901,
                                day_id=None, fuel_card_name="Fleet")
        orphan = self.add_fuel(on_date=date(2026, 10, 8), day_id=999, fuel_cost=8000)
        self.add_fuel(truck_id=2, fuel_cost=99999)
        self.add_fuel(on_date=date(2026, 9, 30), fuel_cost=99999)
        details = self.details("truck")
        week = details["weeks"][0]
        rows = week["days"][2]["entries"]
        self.assertEqual([row["id"] for row in rows], [first, second])
        self.assertEqual([row["distance"] for row in rows], [25000, 25000])
        self.assertEqual([row["driver_name"] for row in rows], ["Driver1 Test", "Driver2 Test"])
        self.assertTrue(all(not row["missing_fuel_receipt"] for row in rows))
        self.assertTrue(week["days"][3]["entries"][0]["missing_fuel_receipt"])
        self.assertEqual(week["days"][5]["label"], "Fuel recorded")
        self.assertEqual([row["id"] for row in week["fuel_entries"]], [fuel_id, orphan])
        self.assertEqual(details["summary"]["fuel_spending"], 30345)
        self.assertEqual(details["summary"]["multiple_assignment_days"], 1)
        self.assertIsNone(details["summary"]["distance"])
        self.assertEqual(week["payslips"], [])
        for entry in rows:
            self.assertNotIn("earnings", entry)
            self.assertNotIn("additional_earned", entry)
            self.assertNotIn("jobs", entry)
        self.assertNotIn("earnings", details["summary"])

    def test_invalid_or_missing_mileages_are_shown_without_guessed_distances(self):
        self.add_day(on_date=date(2026, 10, 5), start_mileage=12000, end_mileage=11000)
        self.add_day(on_date=date(2026, 10, 6), start_mileage=0, end_mileage=15000)
        self.add_day(on_date=date(2026, 10, 7), start_mileage=16000, end_mileage=16000)
        details = self.details("truck")
        rows = [entry for day in details["weeks"][0]["days"] for entry in day["entries"]]
        self.assertEqual([row["mileage_valid"] for row in rows], [False, False, True])
        self.assertEqual([row["distance"] for row in rows], [None, None, 0])
        self.assertEqual(rows[0]["start_mileage"], 12000)
        self.assertEqual(rows[0]["end_mileage"], 11000)
        self.assertEqual(details["summary"]["invalid_mileage_count"], 2)
        self.assertIsNone(details["summary"]["distance"])
        self.assertEqual(details["weeks"][0]["days"][1]["label"], "No recorded activity")

    def test_truck_future_receipts_are_excluded_and_month_bounds_match(self):
        self.add_fuel(on_date=date(2026, 10, 5), fuel_cost=20000)
        self.add_fuel(on_date=date(2026, 10, 7), fuel_cost=30000)
        self.add_fuel(on_date=date(2026, 10, 12), fuel_cost=40000)
        self.add_fuel(on_date=date(2026, 10, 19), fuel_cost=50000)
        weekly = self.details("truck", as_of=date(2026, 10, 6))
        self.assertEqual(weekly["summary"]["fuel_spending"], 20000)
        monthly = self.details("truck", month=date(2026, 10, 1), as_of=date(2026, 10, 18))
        self.assertEqual(monthly["summary"]["fuel_spending"], 90000)
        self.assertEqual(len(monthly["weeks"]), 2)

    def test_service_never_flushes_or_overwrites_dirty_session_objects(self):
        day_id = self.add_day()
        person = db.session.get(Driver, 1)
        day = db.session.get(Day, day_id)
        removed = db.session.get(Truck, 2)
        person.first_name = "Pending"
        day.status = "holiday"
        pending = Truck(registration="ZZ99 ZZZ", make="Test", model="Test")
        db.session.add(pending)
        db.session.delete(removed)
        statements = []
        def record(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)
        event.listen(db.engine, "before_cursor_execute", record)
        try:
            details = self.details()
            truck = self.details("truck")
        finally:
            event.remove(db.engine, "before_cursor_execute", record)
        self.assertEqual(details["name"], "Driver1 Test")
        self.assertEqual(details["summary"]["working_days"], 1)
        self.assertEqual(truck["weeks"][0]["days"][2]["entries"][0]["driver_name"], "Driver1 Test")
        self.assertEqual(person.first_name, "Pending")
        self.assertEqual(day.status, "holiday")
        self.assertIn(pending, db.session.new)
        self.assertIn(removed, db.session.deleted)
        self.assertTrue(all(statement.lstrip().upper().startswith("SELECT") for statement in statements))
        self.assertLessEqual(len(statements), 9)

    def test_rejects_invalid_subjects_dates_and_ambiguous_periods(self):
        with self.assertRaises(LookupError):
            self.details(subject=999)
        bad = [dict(kind="company", subject_id=1), dict(kind="driver", subject_id=True),
               dict(kind="driver", subject_id="1"), dict(kind="truck", subject_id=0)]
        for kwargs in bad:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                build_entity_details(**kwargs, week_start=self.start)
        for kwargs in ({}, {"week_start": date(2026, 10, 5)},
                       {"week_start": self.start, "month": date(2026, 10, 1)},
                       {"month": date(2026, 10, 3)}, {"month": "2026-10"},
                       {"week_start": datetime(2026, 10, 3)},
                       {"week_start": self.start, "as_of": "2026-10-09"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                build_entity_details("driver", 1, **kwargs)


if __name__ == "__main__":
    import unittest
    unittest.main()
