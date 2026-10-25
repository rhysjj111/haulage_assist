"""Opt-in fuel Save tests on a new disposable PostgreSQL cluster.

FUEL_TEST_POSTGRES_BIN=/path/to/postgresql/bin python -m unittest discover \
    -s tests -p test_fuel_import_save_postgres.py -v

Each case uses its own database in a private Unix-socket-only cluster. Configured
application databases and PG connection overrides are never used. These tests
exercise transactions and importer locking on current model DDL, not migrations
or uniqueness across the separate manual entry workflow.
"""

import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
import uuid


BIN = os.environ.get("FUEL_TEST_POSTGRES_BIN")
ROOT = Path(__file__).resolve().parents[1]
PORT = "55441"
USER = "fuel_test"


def _isolated_environment():
    return {key: value for key, value in os.environ.items()
            if not key.startswith("PG") and key not in {
                "DB_URL", "HEROKU_POSTGRESQL_CHARCOAL_URL",
            }}


@unittest.skipUnless(BIN, "Set FUEL_TEST_POSTGRES_BIN for disposable PostgreSQL fuel Save tests")
class FuelImportSavePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory(prefix="fuel-save-pg-")
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
        database = "fuel_test_" + uuid.uuid4().hex
        self.command("createdb", "-h", str(self.socket), "-p", PORT, "-U", USER, database)
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--postgres-worker",
             self._testMethodName, str(self.root), database], cwd=ROOT,
            env=self.environment, capture_output=True, text=True, timeout=90,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_batch_saves_exact_amounts_unique_day_links_and_anomaly_cleanup(self):
        self.run_case()

    def test_repeat_request_preserves_original_records_and_returns_conflict(self):
        self.run_case()

    def test_concurrent_reversed_batches_wait_for_truck_locks_and_save_once(self):
        self.run_case()

    def test_record_inserted_after_preview_blocks_entire_batch(self):
        self.run_case()

    def test_later_insert_failure_rolls_back_first_insert_and_preserves_anomalies(self):
        self.run_case()

    def test_anomaly_feedback_delete_failure_rolls_back_all_fuel_inserts(self):
        self.run_case()

    def test_silvey_saves_its_supplier_and_ignores_other_supplier_duplicate_candidates(self):
        self.run_case()

    def test_concurrent_silvey_batches_wait_for_locks_and_save_once(self):
        self.run_case()


def _run_worker(case, cluster_root, database):
    from urllib.parse import urlencode
    import types

    cluster_root = Path(cluster_root).resolve()
    socket = cluster_root / "socket"
    if (cluster_root.parent != Path(tempfile.gettempdir()).resolve()
            or not cluster_root.name.startswith("fuel-save-pg-")
            or cluster_root.stat().st_uid != os.getuid()
            or not (cluster_root / "data" / "PG_VERSION").is_file()
            or not socket.is_dir()
            or not re.fullmatch(r"fuel_test_[0-9a-f]{32}", database)):
        raise RuntimeError("Refusing a PostgreSQL target outside this disposable test cluster")
    for key in list(os.environ):
        if key.startswith("PG"):
            del os.environ[key]
    os.environ.update(
        DEVELOPMENT="True", SECRET_KEY="disposable-postgres-fuel-tests-only",
        DB_URL=f"postgresql://{USER}@/{database}?" + urlencode({"host": str(socket), "port": PORT}),
    )
    sys.modules["env"] = types.ModuleType("env")
    sys.path.insert(0, str(ROOT))

    from concurrent.futures import ThreadPoolExecutor
    from datetime import date
    import time
    from sqlalchemy import event, select, text
    from haulage_app import app, db
    from haulage_app.models import Day, Driver, Fuel, Truck
    from haulage_app.verification.models import MissingEntryAnomaly, TableName, UserFeedback

    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)

    class SaveCases(unittest.TestCase):
        def setUp(self):
            self.first = date(2026, 10, 5)
            self.second = date(2026, 10, 6)
            self.multiple = date(2026, 10, 7)
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
                    for identity in (1, 2):
                        connection.execute(Truck.__table__.insert(), dict(
                            id=identity, registration=f"ZZ26 AB{identity}", make="Volvo", model="FH",
                        ))
                        connection.execute(Driver.__table__.insert(), dict(
                            id=identity, first_name=f"Driver{identity}", last_name="Disposable",
                            basic_wage=50000, daily_bonus_threshold=35000,
                            daily_bonus_percentage=0.25, weekly_bonus_threshold=250000,
                            weekly_bonus_percentage=0.2, overnight_value=2500, truck_id=None,
                        ))
                    for identity, driver_id, on_date in ((11, 1, self.first),
                                                          (21, 1, self.multiple),
                                                          (22, 2, self.multiple)):
                        connection.execute(Day.__table__.insert(), dict(
                            id=identity, driver_id=driver_id, date=on_date,
                            status="working", truck_id=1,
                        ))

        def tearDown(self):
            with app.app_context():
                db.session.remove()
                db.engine.dispose()

        def row(self, source_row=8, **changes):
            row = dict(source_row=source_row, truck_id=1, date=self.first.isoformat(),
                       quantity="143.27", cost="186.25", product="KEYFUELS DIESEL",
                       source_issues=[], review_confirmed=False)
            row.update(changes)
            return row

        def payload(self):
            return {"rows": [self.row(), self.row(9, truck_id=2, date=self.second.isoformat(),
                                                 quantity="211.08", cost="274.40")]}

        def post(self, payload=None, *, supplier=None):
            headers = {} if supplier is None else {"X-Fuel-Supplier": supplier}
            response = app.test_client().post("/fuel/import/save", json=payload or self.payload(), headers=headers)
            self.assertIn("no-store", response.headers.get("Cache-Control", ""))
            self.assertEqual(response.headers.get("Pragma"), "no-cache")
            self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")
            return response.status_code, response.get_json()

        def snapshot(self):
            with self.engine.connect() as connection:
                return {table.name: [tuple(row) for row in connection.execute(
                    select(table).order_by(*table.primary_key.columns))]
                    for table in db.metadata.sorted_tables}

        def add_missing(self, *, truck_id=1, on_date=None, table_name=TableName.FUEL):
            with app.app_context():
                anomaly = MissingEntryAnomaly(
                    description="Fictional missing receipt", date=on_date or self.first,
                    truck_id=truck_id, table_name=table_name,
                )
                db.session.add(anomaly)
                db.session.flush()
                identity = anomaly.id
                db.session.add(UserFeedback(anomaly_id=identity, user_comment="Fictional checked source"))
                db.session.commit()
                return identity

        def test_batch_saves_exact_amounts_unique_day_links_and_anomaly_cleanup(self):
            removed = {self.add_missing(), self.add_missing()}
            remaining = {self.add_missing(on_date=date(2026, 10, 8)),
                         self.add_missing(truck_id=2),
                         self.add_missing(table_name=TableName.PAYSLIP)}
            before = self.snapshot()
            payload = self.payload()
            payload["rows"].append(self.row(10, date=self.multiple.isoformat(),
                                            quantity="10.10", cost="12.75"))
            status, result = self.post(payload)
            self.assertEqual(status, 201, result)
            self.assertEqual(result["saved_count"], 3)
            self.assertEqual(result["history_url"], "/fuel/add_fuel/0/history")
            self.assertEqual([entry["source_row"] for entry in result["fuel_entries"]], [8, 9, 10])
            after = self.snapshot()
            changed = {"fuel", "anomaly", "missing_entry_anomaly", "user_feedback"}
            self.assertEqual({name: rows for name, rows in before.items() if name not in changed},
                             {name: rows for name, rows in after.items() if name not in changed})
            with self.engine.connect() as connection:
                rows = connection.execute(select(
                    Fuel.id, Fuel.truck_id, Fuel.date, Fuel.day_id,
                    Fuel.fuel_volume, Fuel.fuel_cost, Fuel.fuel_card_name,
                ).order_by(Fuel.id)).all()
                self.assertEqual([tuple(row)[1:] for row in rows], [
                    (1, self.first, 11, 14327, 18625, "The Fuel Store"),
                    (2, self.second, None, 21108, 27440, "The Fuel Store"),
                    (1, self.multiple, None, 1010, 1275, "The Fuel Store"),
                ])
                self.assertEqual({row[0] for row in connection.execute(
                    select(MissingEntryAnomaly.id))}, remaining)
                self.assertEqual({row[0] for row in connection.execute(
                    select(UserFeedback.anomaly_id))}, remaining)
                self.assertFalse(removed & {row[0] for row in connection.execute(
                    text("SELECT id FROM anomaly"))})
            self.assertEqual([entry["id"] for entry in result["fuel_entries"]], [row.id for row in rows])

        def test_repeat_request_preserves_original_records_and_returns_conflict(self):
            self.assertEqual(self.post()[0], 201)
            before = self.snapshot()
            status, result = self.post()
            self.assertEqual(status, 409, result)
            self.assertEqual(result["error"]["code"], "review_required")
            self.assertEqual({row["source_row"] for row in result["row_errors"]}, {8, 9})
            self.assertTrue(all(row["code"] == "possible_duplicate_fuel" for row in result["row_errors"]))
            self.assertEqual(self.snapshot(), before)

        def test_concurrent_reversed_batches_wait_for_truck_locks_and_save_once(self):
            payload = self.payload()
            reversed_payload = {"rows": list(reversed(payload["rows"]))}
            with ThreadPoolExecutor(max_workers=2) as pool:
                with self.engine.connect() as blocker:
                    transaction = blocker.begin()
                    blocker.execute(text("SELECT id FROM truck ORDER BY id FOR UPDATE")).all()
                    futures = [pool.submit(self.post, current) for current in (payload, reversed_payload)]
                    try:
                        deadline = time.monotonic() + 10
                        waiting = 0
                        while time.monotonic() < deadline:
                            with self.engine.connect() as observer:
                                waiting = observer.execute(text("""SELECT count(*) FROM pg_stat_activity
                                    WHERE datname=current_database() AND wait_event_type='Lock'
                                    AND pid <> pg_backend_pid()""")).scalar_one()
                            if waiting >= 2:
                                break
                            time.sleep(0.02)
                        self.assertGreaterEqual(waiting, 2, "Both requests must reach the truck lock")
                    finally:
                        transaction.rollback()
                results = [future.result(timeout=20) for future in futures]
            self.assertEqual(sorted(status for status, _ in results), [201, 409], results)
            losing = next(result for result in results if result[0] == 409)[1]
            self.assertTrue(all(row["code"] == "possible_duplicate_fuel" for row in losing["row_errors"]))
            with self.engine.connect() as connection:
                self.assertEqual(connection.execute(text("SELECT count(*) FROM fuel")).scalar_one(), 2)

        def test_record_inserted_after_preview_blocks_entire_batch(self):
            payload = self.payload()
            base = {"rows": [{key: row[key] for key in ("source_row", "truck_id", "date", "quantity", "cost")}
                             for row in payload["rows"]]}
            response = app.test_client().post("/fuel/import/check", json=base)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(all(not row["issues"] for row in response.get_json()["rows"]))
            with self.engine.begin() as connection:
                identity = connection.execute(Fuel.__table__.insert().values(
                    truck_id=2, date=self.second, fuel_volume=21108, fuel_cost=27440,
                    fuel_card_name="  THE FUEL store  ", day_id=None,
                ).returning(Fuel.id)).scalar_one()
            before = self.snapshot()
            status, result = self.post(payload)
            self.assertEqual(status, 409, result)
            self.assertEqual([(row["source_row"], row["code"]) for row in result["row_errors"]],
                             [(9, "possible_duplicate_fuel")])
            self.assertEqual(result["row_errors"][0]["action_url"], f"/fuel/add_fuel/{identity}/edit")
            self.assertEqual(self.snapshot(), before)

        def test_later_insert_failure_rolls_back_first_insert_and_preserves_anomalies(self):
            self.add_missing()
            with self.engine.begin() as connection:
                connection.execute(text("""ALTER TABLE fuel ADD CONSTRAINT fuel_test_later_row
                    CHECK (truck_id <> 2 OR fuel_cost <> 27440)"""))
            inserted = []

            def capture(connection, cursor, statement, parameters, context, executemany):
                if statement.lstrip().startswith("INSERT INTO fuel "):
                    inserted.append(statement)

            before = self.snapshot()
            event.listen(self.engine, "after_cursor_execute", capture)
            try:
                status, result = self.post()
            finally:
                event.remove(self.engine, "after_cursor_execute", capture)
            self.assertEqual(status, 409, result)
            self.assertEqual(len(inserted), 1, "The first insert must actually reach PostgreSQL")
            self.assertEqual(self.snapshot(), before)
            self.assertNotIn("constraint", str(result))
            self.assertNotIn("INSERT", str(result))
            payload = self.payload()
            payload["rows"][1]["cost"] = "274.41"
            self.assertEqual(self.post(payload)[0], 201)

        def test_anomaly_feedback_delete_failure_rolls_back_all_fuel_inserts(self):
            self.add_missing()
            with self.engine.begin() as connection:
                connection.execute(text("""CREATE FUNCTION fuel_test_block_feedback_delete()
                    RETURNS trigger LANGUAGE plpgsql AS $$
                    BEGIN RAISE EXCEPTION 'Fictional cleanup failure' USING ERRCODE='23514'; END;
                    $$"""))
                connection.execute(text("""CREATE TRIGGER fuel_test_cleanup_failure
                    BEFORE DELETE ON user_feedback FOR EACH ROW
                    EXECUTE FUNCTION fuel_test_block_feedback_delete()"""))
            before = self.snapshot()
            status, result = self.post()
            self.assertEqual(status, 409, result)
            self.assertEqual(self.snapshot(), before)
            self.assertNotIn("Fictional cleanup failure", str(result))
            self.assertNotIn("trigger", str(result))
            with self.engine.begin() as connection:
                connection.execute(text("DROP TRIGGER fuel_test_cleanup_failure ON user_feedback"))
            self.assertEqual(self.post()[0], 201)

        def test_silvey_saves_its_supplier_and_ignores_other_supplier_duplicate_candidates(self):
            fuel_store = {"rows": [self.row()]}
            self.assertEqual(self.post(fuel_store)[0], 201)
            silvey = {"rows": [self.row(product="DERV")]}
            status, result = self.post(silvey, supplier="silvey")
            self.assertEqual(status, 201, result)
            with self.engine.connect() as connection:
                rows = connection.execute(select(
                    Fuel.fuel_card_name, Fuel.fuel_volume, Fuel.fuel_cost, Fuel.date, Fuel.day_id,
                ).order_by(Fuel.id)).all()
            self.assertEqual([tuple(row) for row in rows], [
                ("The Fuel Store", 14327, 18625, self.first, 11),
                ("Silvey", 14327, 18625, self.first, 11),
            ])
            before = self.snapshot()
            status, result = self.post(silvey, supplier="silvey")
            self.assertEqual(status, 409, result)
            self.assertEqual([error["code"] for error in result["row_errors"]], ["possible_duplicate_fuel"])
            self.assertEqual(self.snapshot(), before)

        def test_concurrent_silvey_batches_wait_for_locks_and_save_once(self):
            payload = self.payload()
            for row in payload["rows"]:
                row["product"] = "DERV"
            reversed_payload = {"rows": list(reversed(payload["rows"]))}
            with ThreadPoolExecutor(max_workers=2) as pool:
                with self.engine.connect() as blocker:
                    transaction = blocker.begin()
                    blocker.execute(text("SELECT id FROM truck ORDER BY id FOR UPDATE")).all()
                    futures = [pool.submit(self.post, current, supplier="silvey")
                               for current in (payload, reversed_payload)]
                    try:
                        deadline = time.monotonic() + 10
                        waiting = 0
                        while time.monotonic() < deadline:
                            with self.engine.connect() as observer:
                                waiting = observer.execute(text("""SELECT count(*) FROM pg_stat_activity
                                    WHERE datname=current_database() AND wait_event_type='Lock'
                                    AND pid <> pg_backend_pid()""")).scalar_one()
                            if waiting >= 2:
                                break
                            time.sleep(0.02)
                        self.assertGreaterEqual(waiting, 2, "Both Silvey requests must reach the truck lock")
                    finally:
                        transaction.rollback()
                results = [future.result(timeout=20) for future in futures]
            self.assertEqual(sorted(status for status, _ in results), [201, 409], results)
            losing = next(result for status, result in results if status == 409)
            self.assertTrue(all(error["code"] == "possible_duplicate_fuel" for error in losing["row_errors"]))
            with self.engine.connect() as connection:
                rows = connection.execute(select(Fuel.fuel_card_name, Fuel.fuel_volume, Fuel.fuel_cost)
                                          .order_by(Fuel.fuel_volume)).all()
            self.assertEqual([tuple(row) for row in rows], [("Silvey", 14327, 18625), ("Silvey", 21108, 27440)])

    result = unittest.TextTestRunner(verbosity=2).run(SaveCases(case))
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "--postgres-worker":
        _run_worker(*sys.argv[2:])
    else:
        unittest.main()
