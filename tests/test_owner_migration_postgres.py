"""Opt-in additive migration rehearsal on a disposable local PostgreSQL cluster.

OWNER_TEST_POSTGRES_BIN=/path/to/postgresql/bin python -m unittest discover \
    -s tests -p test_owner_migration_postgres.py -v

This starts no TCP listener and never uses an environment database URL. The old
head is a deliberately small synthetic fixture, not a claim that the complete
legacy migration history can bootstrap an empty database or matches production.
"""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from datetime import date

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


BIN = os.environ.get("OWNER_TEST_POSTGRES_BIN")
ROOT = Path(__file__).resolve().parents[1]


class OwnerDecisionMigrationSqliteTests(unittest.TestCase):
    def test_decision_upgrade_and_downgrade_preserve_notes_and_constraints(self):
        def load(revision):
            path = next((ROOT / "migrations" / "versions").glob(revision + "*.py"))
            spec = importlib.util.spec_from_file_location("owner_sqlite_" + revision, path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module

        engine = create_engine("sqlite://")
        try:
            with engine.begin() as connection:
                with Operations.context(MigrationContext.configure(connection)):
                    load("b2e7a9c4106f").upgrade()
                    load("d4a8f6c239b1").upgrade()
                for decision in ("verified", "dismissed", "awaiting_invoice"):
                    connection.execute(text("""INSERT INTO owner_issue_verification
                        (week_start,scope_key,decision,note,source_fingerprint)
                        VALUES ('2026-10-03',:decision,:decision,'Original explanation',:fingerprint)"""),
                        dict(decision=decision, fingerprint="a" * 64))
                before = [dict(row._mapping) for row in connection.execute(text(
                    "SELECT * FROM owner_issue_verification ORDER BY id"))]
                with Operations.context(MigrationContext.configure(connection)):
                    load("d4a8f6c239b1").downgrade()
                after = [dict(row._mapping) for row in connection.execute(text(
                    "SELECT * FROM owner_issue_verification ORDER BY id"))]
                self.assertEqual(after, [dict(row, decision={
                    "dismissed": "verified", "awaiting_invoice": "note"}.get(row["decision"], row["decision"]))
                    for row in before])
            with self.assertRaises(IntegrityError), engine.begin() as connection:
                connection.execute(text("""INSERT INTO owner_issue_verification
                    (week_start,scope_key,decision,note,source_fingerprint)
                    VALUES ('2026-10-03','invalid','dismissed','Note',:fingerprint)"""),
                    {"fingerprint": "a" * 64})
            self.assertEqual({item["name"] for item in inspect(engine).get_check_constraints(
                "owner_issue_verification")}, {"ck_owner_issue_decision", "ck_owner_issue_note_required",
                                               "ck_owner_issue_fingerprint_length"})
        finally:
            engine.dispose()


@unittest.skipUnless(BIN, "Set OWNER_TEST_POSTGRES_BIN for the isolated PostgreSQL migration rehearsal")
class OwnerMigrationPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory(prefix="owner-migrations-")
        cls.root = Path(cls.scratch.name)
        cls.socket = cls.root / "socket"
        cls.socket.mkdir(mode=0o700)
        cls.data = cls.root / "pgdata"
        cls.started = False
        for name in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS"):
            os.environ.pop(name, None)
        try:
            cls.command("initdb", "-D", str(cls.data), "--auth-local=trust", "--auth-host=reject", "--no-instructions")
            cls.command("pg_ctl", "-D", str(cls.data), "-l", str(cls.root / "postgres.log"),
                        "-o", f"-k {cls.socket} -h '' -p 55438", "start")
            cls.started = True
            cls.command("createdb", "-h", str(cls.socket), "-p", "55438", "owner_test_migrations")
            cls.engine = create_engine(f"postgresql:///owner_test_migrations?host={cls.socket}&port=55438")
        except Exception:
            cls.tearDownClass()
            raise

    @classmethod
    def command(cls, binary, *args):
        result = subprocess.run([str(Path(BIN) / binary), *args], text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError(f"Isolated PostgreSQL {binary} failed: {result.stdout}")

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "engine"):
            cls.engine.dispose()
        if cls.started:
            cls.command("pg_ctl", "-D", str(cls.data), "-m", "fast", "stop")
        cls.scratch.cleanup()

    def load_migration(self, revision):
        path = next((ROOT / "migrations" / "versions").glob(revision + "*.py"))
        spec = importlib.util.spec_from_file_location("owner_migration_" + revision, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def migrate(self, revision, *, downgrade=False):
        module = self.load_migration(revision)
        with self.engine.begin() as connection:
            current = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            self.assertEqual(current, module.revision if downgrade else module.down_revision)
            with Operations.context(MigrationContext.configure(connection)):
                (module.downgrade if downgrade else module.upgrade)()
            connection.execute(text("UPDATE alembic_version SET version_num=:version"),
                               {"version": module.down_revision if downgrade else module.revision})

    def contents(self, tables):
        with self.engine.connect() as connection:
            return {table: json.dumps([list(row) for row in connection.execute(text(f"SELECT * FROM {table} ORDER BY id"))], default=str)
                    for table in tables}

    def assert_rejected(self, statement):
        with self.assertRaises(IntegrityError):
            with self.engine.begin() as connection:
                connection.execute(text(statement))

    def test_additive_upgrade_preserves_sources_settings_and_constraints(self):
        # A synthetic previous-head fixture. Values are test data, not the
        # owner's real allowance/count or historical configuration.
        core = ["driver", "day", "job", "fuel", "payslip", "expense"]
        with self.engine.begin() as connection:
            connection.execute(text("CREATE TABLE alembic_version (version_num varchar(32) NOT NULL PRIMARY KEY)"))
            connection.execute(text("INSERT INTO alembic_version VALUES ('859d6ebe2110')"))
            for table in core:
                connection.execute(text(f"CREATE TABLE {table} (id integer PRIMARY KEY, retained_value integer NOT NULL)"))
                connection.execute(text(f"INSERT INTO {table} VALUES (1, 12345), (2, 0)"))
        before = self.contents(core)
        self.migrate("7e9c2a41b6d8")
        with self.engine.begin() as connection:
            connection.execute(text("INSERT INTO owner_overhead_setting (id,effective_week_start,truck_count,allowance_per_truck) VALUES (1,'2026-10-03',3,12345)"))
            connection.execute(text("INSERT INTO owner_weekly_overhead (id,week_start,truck_count,allowance_per_truck,source_setting_id) VALUES (1,'2026-10-03',3,12345,1)"))
        settings_before = self.contents(["owner_overhead_setting", "owner_weekly_overhead"])
        self.migrate("b2e7a9c4106f")
        self.assertEqual(before, self.contents(core))
        self.assertEqual(settings_before, self.contents(list(settings_before)))
        with self.engine.begin() as connection:
            connection.execute(text("INSERT INTO owner_issue_verification (week_start,scope_key,decision,note,source_fingerprint) VALUES ('2026-10-03','fixture','verified','Receipts checked',repeat('a',64))"))
            connection.execute(text("INSERT INTO owner_week_review (week_start,source_fingerprint) VALUES ('2026-10-03',repeat('b',64))"))
            created = connection.execute(text("SELECT created_at FROM owner_week_review")).scalar_one()
            self.assertIsNotNone(created.tzinfo)
        self.assert_rejected("INSERT INTO owner_overhead_setting (id,effective_week_start,truck_count,allowance_per_truck) VALUES (2,'2026-10-03',3,1)")
        self.assert_rejected("INSERT INTO owner_overhead_setting (id,effective_week_start,truck_count,allowance_per_truck) VALUES (2,'2026-10-10',-1,1)")
        self.assert_rejected("INSERT INTO owner_overhead_setting (id,effective_week_start,truck_count,allowance_per_truck) VALUES (2,'2026-10-10',3,-1)")
        self.assert_rejected("DELETE FROM owner_overhead_setting WHERE id=1")
        self.assert_rejected("INSERT INTO owner_issue_verification (week_start,scope_key,decision,note,source_fingerprint) VALUES ('2026-10-03','fixture','unknown','Note',repeat('a',64))")
        self.assert_rejected("INSERT INTO owner_issue_verification (week_start,scope_key,decision,note,source_fingerprint) VALUES ('2026-10-03','fixture','verified','  ',repeat('a',64))")
        self.assert_rejected("INSERT INTO owner_week_review (week_start,source_fingerprint) VALUES ('2026-10-03','short')")
        original_notes = self.contents(["owner_issue_verification", "owner_week_review"])
        self.migrate("d4a8f6c239b1")
        self.assertEqual(original_notes, self.contents(list(original_notes)))
        self.assertEqual(settings_before, self.contents(list(settings_before)))
        self.assertEqual(before, self.contents(core))
        for decision in ("dismissed", "awaiting_invoice"):
            with self.engine.begin() as connection:
                connection.execute(text("""INSERT INTO owner_issue_verification
                    (week_start,scope_key,decision,note,source_fingerprint)
                    VALUES ('2026-10-03',:decision,:decision,'Preserved explanation',repeat('c',64))"""),
                    {"decision": decision})
        self.assert_rejected("INSERT INTO owner_issue_verification (week_start,scope_key,decision,note,source_fingerprint) VALUES ('2026-10-03','fixture','unknown','Note',repeat('a',64))")
        self.assert_rejected("INSERT INTO owner_issue_verification (week_start,scope_key,decision,note,source_fingerprint) VALUES ('2026-10-03','fixture','dismissed',' ',repeat('a',64))")
        self.assert_rejected("INSERT INTO owner_issue_verification (week_start,scope_key,decision,note,source_fingerprint) VALUES ('2026-10-03','fixture','awaiting_invoice','Note','short')")
        with self.engine.connect() as connection:
            new_notes = [dict(row._mapping) for row in connection.execute(text(
                "SELECT * FROM owner_issue_verification ORDER BY id"))]
        self.migrate("d4a8f6c239b1", downgrade=True)
        with self.engine.connect() as connection:
            downgraded = [dict(row._mapping) for row in connection.execute(text(
                "SELECT * FROM owner_issue_verification ORDER BY id"))]
        self.assertEqual(downgraded, [dict(row, decision={
            "dismissed": "verified", "awaiting_invoice": "note"}.get(row["decision"], row["decision"]))
            for row in new_notes])
        self.assert_rejected("INSERT INTO owner_issue_verification (week_start,scope_key,decision,note,source_fingerprint) VALUES ('2026-10-03','fixture','dismissed','Note',repeat('a',64))")
        self.migrate("d4a8f6c239b1")
        # Compare all new table column nullability/types/index/constraint names
        # with the app metadata; source fixtures intentionally are not model DDL.
        from owner_test_support import db
        from haulage_app.owner_analysis import models  # noqa: F401
        inspector = inspect(self.engine)
        for name in ("owner_overhead_setting", "owner_weekly_overhead", "owner_issue_verification", "owner_week_review"):
            table = db.metadata.tables[name]
            actual = {column["name"]: column for column in inspector.get_columns(name)}
            self.assertEqual(set(actual), set(table.columns.keys()))
            for column in table.columns:
                self.assertEqual(actual[column.name]["nullable"], column.nullable)
                self.assertEqual(actual[column.name]["type"]._type_affinity, column.type._type_affinity)
            self.assertEqual({item["name"] for item in inspector.get_indexes(name) if not item.get("duplicates_constraint")},
                             {item.name for item in table.indexes})
        # New-feature rollback removes its own tables only; old source data and
        # overhead snapshots survive rollback of the review migration.
        self.migrate("d4a8f6c239b1", downgrade=True)
        self.migrate("b2e7a9c4106f", downgrade=True)
        self.assertEqual(settings_before, self.contents(list(settings_before)))
        self.assertEqual(before, self.contents(core))
        self.migrate("7e9c2a41b6d8", downgrade=True)
        self.assertEqual(before, self.contents(core))
        self.assertFalse(any(name.startswith("owner_") for name in inspect(self.engine).get_table_names()))

    def test_existing_codespace_schema_widens_decisions_without_reseeding_or_stamping(self):
        from owner_test_support import db
        from haulage_app.owner_analysis import models  # noqa: F401
        from tools import setup_review

        self.command("createdb", "-h", str(self.socket), "-p", "55438", "owner_test_preview")
        engine = create_engine(f"postgresql:///owner_test_preview?host={self.socket}&port=55438")
        try:
            with engine.begin() as connection:
                db.metadata.create_all(connection)
                setup_review.seed_review_data(connection, db.metadata.tables, today=date(2026, 10, 21))
                connection.execute(text("ALTER TABLE owner_issue_verification DROP CONSTRAINT ck_owner_issue_decision"))
                connection.execute(text("ALTER TABLE owner_issue_verification ADD CONSTRAINT ck_owner_issue_decision CHECK (decision IN ('verified','confirmed_zero','note'))"))
                connection.execute(text("UPDATE job SET earned=77777 WHERE id=1"))
                connection.execute(text("UPDATE owner_overhead_setting SET allowance_per_truck=99999"))
                connection.execute(text("""INSERT INTO owner_issue_verification
                    (week_start,scope_key,decision,note,source_fingerprint)
                    VALUES ('2026-10-03','original','verified','Keep this explanation',repeat('a',64))"""))

            def contents():
                with engine.connect() as connection:
                    return {name: json.dumps([list(row) for row in connection.execute(text(
                        f"SELECT * FROM {name} ORDER BY id"))], default=str)
                        for name in db.metadata.tables}

            before = contents()
            # A failed surrounding setup transaction must leave even the old
            # CHECK untouched, rather than partly changing an existing preview.
            with self.assertRaisesRegex(RuntimeError, "rollback rehearsal"):
                with engine.begin() as connection:
                    self.assertTrue(setup_review.update_review_issue_decisions(connection))
                    raise RuntimeError("rollback rehearsal")
            self.assertEqual(contents(), before)
            with engine.begin() as connection:
                self.assertTrue(setup_review.update_review_issue_decisions(connection))
                self.assertFalse(setup_review.update_review_issue_decisions(connection))
            self.assertEqual(contents(), before)
            with engine.begin() as connection:
                result = setup_review.setup_review_database(connection, db.metadata, today=date(2026, 11, 21))
                self.assertFalse(result["seeded"])
                self.assertFalse(result["issue_decisions_updated"])
                for decision in ("dismissed", "awaiting_invoice"):
                    connection.execute(text("""INSERT INTO owner_issue_verification
                        (week_start,scope_key,decision,note,source_fingerprint)
                        VALUES ('2026-10-03',:decision,:decision,'Invoice explanation',repeat('b',64))"""),
                        {"decision": decision})
                self.assertNotIn("alembic_version", inspect(connection).get_table_names())
            after = contents()
            self.assertEqual({key: value for key, value in before.items() if key != "owner_issue_verification"},
                             {key: value for key, value in after.items() if key != "owner_issue_verification"})
        finally:
            engine.dispose()
