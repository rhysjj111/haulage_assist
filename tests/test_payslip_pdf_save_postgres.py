"""Opt-in Save integration tests using a new disposable PostgreSQL cluster.

PAYSLIP_TEST_POSTGRES_BIN=/path/to/postgresql/bin python -m unittest discover \
    -s tests -p test_payslip_pdf_save_postgres.py -v

The cluster listens only on its private Unix socket. Configured database URLs
and PG connection settings are never used. Each case imports the real app in a
separate process, avoiding the SQLite app already imported by other tests. This
exercises current model DDL, including the generated payroll week and retained
yearless unique constraint; it is not a migration rehearsal.
"""

import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
import uuid


BIN = os.environ.get("PAYSLIP_TEST_POSTGRES_BIN")
ROOT = Path(__file__).resolve().parents[1]
PORT = "55439"
USER = "payslip_test"


def _isolated_environment():
    return {key: value for key, value in os.environ.items()
            if not key.startswith("PG") and key not in {
                "DB_URL", "HEROKU_POSTGRESQL_CHARCOAL_URL",
            }}


@unittest.skipUnless(BIN, "Set PAYSLIP_TEST_POSTGRES_BIN for disposable PostgreSQL Save tests")
class PayslipPDFSavePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory(prefix="payslip-save-pg-")
        cls.root = Path(cls.scratch.name)
        cls.socket = cls.root / "socket"
        cls.socket.mkdir(mode=0o700)
        cls.data = cls.root / "data"
        cls.started = False
        cls.environment = _isolated_environment()
        try:
            cls.command("initdb", "-D", str(cls.data), "--username=" + USER,
                        "--auth-local=trust", "--auth-host=reject", "--no-instructions",
                        "--no-locale", "--encoding=UTF8")
            cls.command("pg_ctl", "-D", str(cls.data), "-l", str(cls.root / "postgres.log"),
                        "-o", f"-k {cls.socket} -h '' -p {PORT}", "-w", "-t", "15", "start")
            cls.started = True
        except Exception:
            cls.tearDownClass()
            raise

    @classmethod
    def command(cls, binary, *arguments):
        result = subprocess.run([str(Path(BIN) / binary), *arguments],
                                env=cls.environment, capture_output=True, text=True, timeout=30)
        if result.returncode:
            log = cls.root / "postgres.log"
            details = log.read_text() if log.is_file() else ""
            raise RuntimeError(f"Disposable PostgreSQL {binary} failed:\n{result.stdout}{result.stderr}{details}")

    @classmethod
    def tearDownClass(cls):
        try:
            if cls.started:
                cls.command("pg_ctl", "-D", str(cls.data), "-m", "immediate", "-w", "stop")
        finally:
            cls.scratch.cleanup()

    def run_case(self):
        database = "payslip_test_" + uuid.uuid4().hex
        self.command("createdb", "-h", str(self.socket), "-p", PORT, "-U", USER, database)
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--postgres-worker",
             self._testMethodName, str(self.root), database], cwd=ROOT,
            env=self.environment, capture_output=True, text=True, timeout=90,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_batch_commits_exact_pence_friday_links_and_generated_weeks(self):
        self.run_case()

    def test_retry_returns_review_conflict_and_preserves_original_rows(self):
        self.run_case()

    def test_concurrent_requests_wait_for_driver_lock_then_save_once(self):
        self.run_case()

    def test_existing_saturday_is_detected_by_dates_despite_different_generated_week(self):
        self.run_case()

    def test_yearless_legacy_constraint_conflict_rolls_back_entire_batch(self):
        self.run_case()

    def test_later_row_database_failure_rolls_back_first_insert(self):
        self.run_case()


def _run_worker(case, cluster_root, database):
    """Import the app only after constructing and checking our private target."""
    from urllib.parse import urlencode
    import types

    cluster_root = Path(cluster_root).resolve()
    socket = cluster_root / "socket"
    if (cluster_root.parent != Path(tempfile.gettempdir()).resolve()
            or not cluster_root.name.startswith("payslip-save-pg-")
            or cluster_root.stat().st_uid != os.getuid()
            or not (cluster_root / "data" / "PG_VERSION").is_file()
            or not socket.is_dir()
            or not re.fullmatch(r"payslip_test_[0-9a-f]{32}", database)):
        raise RuntimeError("Refusing a PostgreSQL target outside this disposable test cluster")
    for key in list(os.environ):
        if key.startswith("PG"):
            del os.environ[key]
    os.environ.update(
        DEVELOPMENT="True", SECRET_KEY="disposable-postgres-payslip-tests-only",
        DB_URL=f"postgresql://{USER}@/{database}?" + urlencode({"host": str(socket), "port": PORT}),
    )
    sys.modules["env"] = types.ModuleType("env")
    sys.path.insert(0, str(ROOT))

    from concurrent.futures import ThreadPoolExecutor
    from datetime import date
    import time
    from sqlalchemy import event, inspect, select, text
    from haulage_app import app, db
    from haulage_app.models import Day, Driver, DriverEmploymentHistory, EmploymentStatus, Payslip

    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)

    class SaveCases(unittest.TestCase):
        def setUp(self):
            self.start = date(2026, 9, 19)
            self.friday = date(2026, 9, 25)
            with app.app_context():
                self.engine = db.engine
                target = self.engine.url
                if (target.get_backend_name() != "postgresql" or target.database != database
                        or target.query.get("host") != str(socket) or target.host is not None):
                    raise RuntimeError("Refusing unexpected application database configuration")
                db.create_all()
                with self.engine.begin() as connection:
                    self.assertEqual(connection.execute(text("SHOW listen_addresses")).scalar_one(), "")
                    self.assertEqual(connection.execute(text("SHOW unix_socket_directories")).scalar_one(), str(socket))
                    for driver_id in (1, 2):
                        connection.execute(Driver.__table__.insert(), dict(
                            id=driver_id, first_name=f"Driver{driver_id}", last_name="Disposable",
                            basic_wage=50000, daily_bonus_threshold=35000,
                            daily_bonus_percentage=0.25, weekly_bonus_threshold=250000,
                            weekly_bonus_percentage=0.2, overnight_value=2500, truck_id=None,
                        ))
                        connection.execute(DriverEmploymentHistory.__table__.insert(), dict(
                            driver_id=driver_id, start_date=date(2020, 1, 1), end_date=None,
                            employment_status=EmploymentStatus.ACTIVE,
                        ))
                        connection.execute(Day.__table__.insert(), dict(
                            id=10 + driver_id, driver_id=driver_id, date=self.friday,
                            status="working", truck_id=None,
                        ))

        def tearDown(self):
            with app.app_context():
                db.session.remove()
                db.engine.dispose()

        def payload(self):
            return {"week_start": self.start.isoformat(), "rows": [
                {"source_index": 1, "driver_id": 1, "total_wage": "615.37",
                 "total_cost_to_employer": "706.38"},
                {"source_index": 2, "driver_id": 2, "total_wage": "801.20",
                 "total_cost_to_employer": "923.95"},
            ]}

        def post(self, payload=None):
            # Each request owns its app context and scoped session, including
            # when the two race requests run on different threads.
            response = app.test_client().post("/payslip/import/save", json=payload or self.payload())
            self.assertIn("no-store", response.headers.get("Cache-Control", ""))
            self.assertEqual(response.headers.get("Pragma"), "no-cache")
            return response.status_code, response.get_json()

        def snapshot(self):
            with self.engine.connect() as connection:
                return {table.name: [tuple(row) for row in connection.execute(
                    select(table).order_by(*table.primary_key.columns))]
                    for table in db.metadata.sorted_tables}

        def add_existing(self, driver_id, on_date):
            with self.engine.begin() as connection:
                return connection.execute(Payslip.__table__.insert().values(
                    driver_id=driver_id, date=on_date, day_id=None,
                    total_wage=54321, total_cost_to_employer=65432,
                ).returning(Payslip.id)).scalar_one()

        def assert_conflict(self, result, code):
            status, payload = result
            self.assertEqual(status, 409, payload)
            self.assertEqual(payload["error"]["code"], code)

        def test_batch_commits_exact_pence_friday_links_and_generated_weeks(self):
            before = self.snapshot()
            status, payload = self.post()
            self.assertEqual(status, 201, payload)
            self.assertEqual(payload["saved_count"], 2)
            self.assertEqual((payload["week_start"], payload["week_end"], payload["entry_date"]),
                             ("2026-09-19", "2026-09-25", "2026-09-25"))
            self.assertEqual([row["source_index"] for row in payload["payslips"]], [1, 2])
            after = self.snapshot()  # A separate connection proves the request committed.
            self.assertEqual({k: v for k, v in before.items() if k != "payslip"},
                             {k: v for k, v in after.items() if k != "payslip"})
            with self.engine.connect() as connection:
                rows = connection.execute(select(
                    Payslip.id, Payslip.driver_id, Payslip.day_id, Payslip.date,
                    Payslip.total_wage, Payslip.total_cost_to_employer, Payslip.week_number_mtf,
                ).order_by(Payslip.driver_id)).all()
            self.assertEqual([tuple(row)[1:] for row in rows], [
                (1, 11, self.friday, 61537, 70638, 39),
                (2, 12, self.friday, 80120, 92395, 39),
            ])
            self.assertEqual([row["id"] for row in payload["payslips"]], [row.id for row in rows])
            columns = {column["name"]: column for column in inspect(self.engine).get_columns("payslip")}
            self.assertTrue(columns["week_number_mtf"]["computed"]["persisted"])
            constraints = inspect(self.engine).get_unique_constraints("payslip")
            self.assertIn({"driver_id", "week_number_mtf"},
                          [set(item["column_names"]) for item in constraints])

        def test_retry_returns_review_conflict_and_preserves_original_rows(self):
            self.assertEqual(self.post()[0], 201)
            before = self.snapshot()
            result = self.post()
            self.assert_conflict(result, "review_required")
            self.assertEqual({row["driver_id"] for row in result[1]["row_errors"]}, {1, 2})
            self.assertTrue(all(row["code"] == "existing_payslip" for row in result[1]["row_errors"]))
            self.assertEqual(self.snapshot(), before)

        def test_concurrent_requests_wait_for_driver_lock_then_save_once(self):
            with ThreadPoolExecutor(max_workers=2) as pool:
                with self.engine.connect() as blocker:
                    transaction = blocker.begin()
                    blocker.execute(text("SELECT id FROM driver ORDER BY id FOR UPDATE")).all()
                    futures = [pool.submit(self.post) for _ in range(2)]
                    try:
                        deadline = time.monotonic() + 10
                        while time.monotonic() < deadline:
                            with self.engine.connect() as observer:
                                waiting = observer.execute(text("""SELECT count(*) FROM pg_stat_activity
                                    WHERE datname=current_database() AND wait_event_type='Lock'
                                    AND pid <> pg_backend_pid()""")).scalar_one()
                            if waiting >= 2:
                                break
                            time.sleep(0.02)
                        self.assertGreaterEqual(waiting, 2, "Both Save requests must reach the database lock")
                    finally:
                        transaction.rollback()
                results = [future.result(timeout=20) for future in futures]
            self.assertEqual(sorted(status for status, _ in results), [201, 409], results)
            losing_result = next(result for result in results if result[0] == 409)
            self.assert_conflict(losing_result, "review_required")
            self.assertTrue(all(row["code"] == "existing_payslip"
                                for row in losing_result[1]["row_errors"]))
            with self.engine.connect() as connection:
                self.assertEqual(connection.execute(text("SELECT count(*) FROM payslip")).scalar_one(), 2)
                self.assertEqual(connection.execute(text("SELECT count(DISTINCT driver_id) FROM payslip")).scalar_one(), 2)

        def test_existing_saturday_is_detected_by_dates_despite_different_generated_week(self):
            existing_id = self.add_existing(1, self.start)
            before = self.snapshot()
            with self.engine.connect() as connection:
                generated = connection.execute(select(Payslip.week_number_mtf)
                                               .where(Payslip.id == existing_id)).scalar_one()
            self.assertEqual(generated, 38)  # The requested Friday generates 39.
            result = self.post()
            self.assert_conflict(result, "review_required")
            self.assertEqual([(row["driver_id"], row["code"]) for row in result[1]["row_errors"]],
                             [(1, "existing_payslip")])
            self.assertIn(str(existing_id), result[1]["row_errors"][0]["action_url"])
            self.assertEqual(self.snapshot(), before)

        def assert_database_failure_rolls_back_first_insert(self):
            successful_inserts = []

            def inserted(connection, cursor, statement, parameters, context, executemany):
                if statement.lstrip().startswith("INSERT INTO payslip "):
                    successful_inserts.append(statement)

            before = self.snapshot()
            event.listen(self.engine, "after_cursor_execute", inserted)
            try:
                result = self.post()
            finally:
                event.remove(self.engine, "after_cursor_execute", inserted)
            self.assert_conflict(result, "save_conflict")
            self.assertEqual(len(successful_inserts), 1, "The first row must actually reach PostgreSQL")
            self.assertEqual(self.snapshot(), before)
            self.assertNotIn("INSERT", str(result[1]))
            self.assertNotIn("constraint", str(result[1]))

        def test_yearless_legacy_constraint_conflict_rolls_back_entire_batch(self):
            existing_id = self.add_existing(2, date(2025, 9, 26))
            with self.engine.connect() as connection:
                generated = connection.execute(select(Payslip.week_number_mtf)
                                               .where(Payslip.id == existing_id)).scalar_one()
            self.assertEqual(generated, 39)
            self.assert_database_failure_rolls_back_first_insert()

        def test_later_row_database_failure_rolls_back_first_insert(self):
            with self.engine.begin() as connection:
                connection.execute(text("""ALTER TABLE payslip ADD CONSTRAINT payslip_test_later_row
                    CHECK (driver_id <> 2 OR total_cost_to_employer <> 92395)"""))
            self.assert_database_failure_rolls_back_first_insert()
            # A valid follow-up proves the failed request released its locks
            # and left the application session usable after rollback.
            payload = self.payload()
            payload["rows"][1]["total_cost_to_employer"] = "923.96"
            self.assertEqual(self.post(payload)[0], 201)

    result = unittest.TextTestRunner(verbosity=2).run(SaveCases(case))
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "--postgres-worker":
        _run_worker(*sys.argv[2:])
    else:
        unittest.main()
