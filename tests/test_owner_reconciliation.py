"""Independent reconciliation must stay local and avoid multiplied source sums."""

from datetime import date
import sqlite3
import unittest
from unittest.mock import patch
from sqlalchemy.engine import make_url

from tools.reconcile_owner_analysis import (
    compare_breakdowns, local_database_url, month_weeks, parse_week,
    read_only_database, source_totals,
)


class ReconciliationSafetyTests(unittest.TestCase):
    def test_rejects_remote_implicit_or_service_database_connections(self):
        invalid = [
            "postgresql://user@database.example/owner_test",
            "postgresql://user@127.0.0.2/owner_test",
            "postgresql:///owner_test",  # PGHOST environment is not explicit.
            "postgresql://localhost/production",
            "postgresql://localhost/owner_test?hostaddr=8.8.8.8",
            "postgresql://localhost/owner_test?service=production",
            "postgresql://localhost/owner_test?options=-c+default_transaction_read_only=off",
            "postgresql://localhost/owner_test?host=localhost&host=database.example",
            "postgresql://localhost/owner_test?host=localhost,database.example",
            "postgresql://database.example/owner_test?host=/tmp/socket",
            "sqlite://",
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                local_database_url(value)

    def test_explicit_loopback_and_unix_socket_test_copies_are_accepted(self):
        for value in ("postgresql://localhost/owner_test", "postgresql://127.0.0.1/owner_rehearsal",
                      "postgresql://[::1]/owner_reconciliation", "postgresql:///owner_historical?host=/tmp/socket"):
            with self.subTest(value=value):
                self.assertEqual(make_url(local_database_url(value)), make_url(value))

    def test_connections_force_readonly_and_cleanup_on_failure(self):
        with patch("tools.reconcile_owner_analysis.psycopg2.connect") as connect:
            connection = connect.return_value
            with self.assertRaises(RuntimeError):
                with read_only_database("postgresql://localhost/owner_test"):
                    raise RuntimeError("Unexpected report failure")
            connection.set_session.assert_called_once_with(readonly=True)
            connection.rollback.assert_called_once()
            connection.close.assert_called_once()


class ReconciliationCalendarTests(unittest.TestCase):
    def test_payroll_week_requires_saturday(self):
        self.assertEqual(parse_week("2024-11-02"), date(2024, 11, 2))
        with self.assertRaises(ValueError):
            parse_week("2024-11-03")

    def test_month_includes_complete_whole_weeks_across_calendar_boundary(self):
        expected, completed = month_weeks("2024-10", date(2024, 12, 22))
        self.assertEqual(expected, [date(2024, 9, 28)] + [date(2024, 10, day) for day in (5, 12, 19, 26)])
        self.assertEqual(completed, expected)

    def test_friday_is_unfinished_until_saturday(self):
        _, friday = month_weeks("2024-11", date(2024, 11, 8))
        _, saturday = month_weeks("2024-11", date(2024, 11, 9))
        self.assertEqual(friday, [])
        self.assertEqual(saturday, [date(2024, 11, 2)])


class _SQLiteCursor:
    def __init__(self, connection):
        self.cursor = connection.cursor()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.cursor.close()

    def execute(self, statement, parameters):
        # The independent aggregation is ordinary SQL supported by both DBs;
        # only parameter syntax changes for this small in-memory source fixture.
        self.cursor.execute(statement.replace("%s", "?"), [str(value) if isinstance(value, date) else value for value in parameters])

    def __iter__(self):
        return iter(self.cursor)


class _SQLiteConnection:
    def __init__(self, connection):
        self.connection = connection

    def cursor(self):
        return _SQLiteCursor(self.connection)


class ReconciliationSourceTests(unittest.TestCase):
    def test_independent_totals_do_not_multiply_day_amounts_and_keep_unlinked_sources(self):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        connection.executescript("""
            CREATE TABLE day (id INTEGER, date TEXT, driver_id INTEGER, additional_earned INTEGER, status TEXT);
            CREATE TABLE job (id INTEGER, day_id INTEGER, earned INTEGER);
            CREATE TABLE payslip (id INTEGER, date TEXT, driver_id INTEGER, total_cost_to_employer INTEGER);
            CREATE TABLE fuel (id INTEGER, date TEXT, truck_id INTEGER, fuel_cost INTEGER, fuel_volume INTEGER);
            INSERT INTO day VALUES (1,'2024-11-04',1,600,'working'), (2,'2024-11-05',1,0,'holiday'),
                                   (3,'2024-11-06',2,0,'absent'), (4,'2024-11-11',1,999,'working');
            INSERT INTO job VALUES (1,1,1000), (2,1,2000), (3,4,999);
            INSERT INTO payslip VALUES (1,'2024-11-08',1,10000), (2,'2024-11-08',3,3000), (3,'2024-11-15',1,999);
            INSERT INTO fuel VALUES (1,'2024-11-03',2,1000,100), (2,'2024-11-09',2,999,999);
        """)
        totals = source_totals(_SQLiteConnection(connection), [date(2024, 11, 2)])
        self.assertEqual(totals["earnings"], 3600)  # additional earnings counted once for two jobs.
        self.assertEqual(totals["employer_cost"], 13000)  # includes a driver without a day.
        self.assertEqual(totals["fuel_spending"], 1000)  # no day/driver link required.
        self.assertEqual(totals["fuel_volume"], 100)
        drivers = {row["driver_id"]: row for row in totals["drivers"]}
        self.assertEqual(drivers[1]["working_days"], 1)
        self.assertEqual(drivers[1]["holiday_days"], 1)
        self.assertEqual(drivers[2]["absent_days"], 1)
        self.assertEqual(drivers[3]["payroll_entries"], 1)

    def test_breakdown_comparison_exposes_mismatches_and_allows_zero_expectation_rows(self):
        source = {"drivers": [{"driver_id": 1, "earnings": 300}], "trucks": [{"truck_id": 2, "fuel_spending": 500}]}
        report = {"drivers": {1: {"earnings": 301}, 3: {"earnings": 0}}, "trucks": {2: {"fuel_spending": 500}, 4: {"fuel_spending": 0}}}
        matches = compare_breakdowns(source, report)
        self.assertFalse(matches["driver:1:earnings"])
        self.assertTrue(matches["driver:3:earnings"])
        self.assertTrue(matches["truck:2:fuel_spending"])
        self.assertTrue(matches["truck:4:fuel_spending"])
