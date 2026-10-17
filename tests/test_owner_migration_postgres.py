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

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


BIN = os.environ.get("OWNER_TEST_POSTGRES_BIN")
ROOT = Path(__file__).resolve().parents[1]


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
        self.migrate("b2e7a9c4106f", downgrade=True)
        self.assertEqual(settings_before, self.contents(list(settings_before)))
        self.assertEqual(before, self.contents(core))
        self.migrate("7e9c2a41b6d8", downgrade=True)
        self.assertEqual(before, self.contents(core))
        self.assertFalse(any(name.startswith("owner_") for name in inspect(self.engine).get_table_names()))
