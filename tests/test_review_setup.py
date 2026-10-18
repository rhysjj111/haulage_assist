"""Preview setup stays on disposable data and provides useful review scenarios."""

import builtins
from contextlib import nullcontext, redirect_stderr
from datetime import date, timedelta
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from sqlalchemy import create_engine, event, inspect, select, text

from owner_test_support import OwnerTestCase, db
from haulage_app.models import Day, Driver, Fuel, Job, Payslip
from haulage_app.owner_analysis.calculations import calculate_weekly_report
from tools import setup_review


REVIEW_URL = "postgresql://review:review@review-db:5432/haulage_review"


class ReviewTargetSafetyTests(unittest.TestCase):
    def environment(self, **overrides):
        values = dict(DEVELOPMENT="True", HAULAGE_REVIEW="True", DB_URL=REVIEW_URL)
        values.update(overrides)
        return values

    def test_rejects_database_targets_or_connection_overrides_outside_review_service(self):
        rejected = (
            "postgresql://review:review@production.example/haulage_review",
            "postgresql://review:review@127.0.0.1/haulage_review",
            "postgresql://review:review@review-db/production",
            "postgresql://admin:review@review-db/haulage_review",
            "postgresql://review:other@review-db/haulage_review",
            "postgresql://review:review@review-db:5433/haulage_review",
            "sqlite://",
            REVIEW_URL + "?host=production.example",
            REVIEW_URL + "?hostaddr=192.0.2.1",
            REVIEW_URL + "?service=production",
            REVIEW_URL + "?options=-csearch_path=public",
            REVIEW_URL + "#production",
        )
        for value in rejected:
            with self.subTest(url=value), self.assertRaises(RuntimeError):
                setup_review.validate_review_url(value)
        self.assertTrue(setup_review.validate_review_url(REVIEW_URL))

    def test_requires_explicit_review_mode_and_refuses_inherited_libpq_overrides(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            rejected = (
                self.environment(HAULAGE_REVIEW="False"),
                self.environment(HAULAGE_REVIEW=""),
                self.environment(DEVELOPMENT="False"),
                self.environment(DEVELOPMENT="true"),
                self.environment(PGSERVICE="production"),
                self.environment(PGHOSTADDR="192.0.2.1"),
                self.environment(PGOPTIONS="-csearch_path=public"),
                self.environment(DB_URL="postgresql://review:review@heroku.example/haulage_review"),
            )
            for environment in rejected:
                with self.subTest(keys=sorted(environment)), self.assertRaises(RuntimeError):
                    setup_review.validate_review_environment(environment, repository=root, cwd=root)
            self.assertTrue(setup_review.validate_review_environment(
                self.environment(), repository=root, cwd=root))

    def test_refuses_legacy_env_file_in_repository_or_working_directory(self):
        with TemporaryDirectory() as directory:
            repository = Path(directory) / "repository"
            working = Path(directory) / "working"
            repository.mkdir()
            working.mkdir()
            for target in (repository, working):
                with self.subTest(location=target.name):
                    legacy = target / "env.py"
                    legacy.write_text("raise AssertionError('must not execute legacy settings')\n")
                    try:
                        with self.assertRaises(RuntimeError):
                            setup_review.validate_review_environment(
                                self.environment(), repository=repository, cwd=working)
                    finally:
                        legacy.unlink()

    def test_invalid_setup_stops_before_application_import(self):
        real_import = builtins.__import__

        def reject_app_import(name, *args, **kwargs):
            if name == "haulage_app" or name.startswith("haulage_app."):
                raise AssertionError("Invalid preview settings must fail before importing the app")
            return real_import(name, *args, **kwargs)

        with patch.dict("os.environ", self.environment(HAULAGE_REVIEW="False"), clear=True):
            with patch("builtins.__import__", side_effect=reject_app_import):
                with redirect_stderr(StringIO()) as errors:
                    self.assertEqual(setup_review.main(), 1)
                self.assertIn("HAULAGE_REVIEW", errors.getvalue())

    def test_rechecks_imported_app_and_engine_targets_before_connecting(self):
        remote = "postgresql://review:review@production.example/haulage_review"
        for configured, actual in ((remote, REVIEW_URL), (REVIEW_URL, remote)):
            with self.subTest(configured=configured, actual=actual):
                imported_app = SimpleNamespace(
                    config={"SQLALCHEMY_DATABASE_URI": configured},
                    app_context=Mock(return_value=nullcontext()),
                )
                imported_db = SimpleNamespace(engine=SimpleNamespace(
                    url=SimpleNamespace(render_as_string=Mock(return_value=actual)),
                    begin=Mock(side_effect=AssertionError("Unsafe target must never connect")),
                ))
                imported_module = ModuleType("haulage_app")
                imported_module.app = imported_app
                imported_module.db = imported_db
                with patch.dict("sys.modules", {"haulage_app": imported_module}):
                    with patch.dict("os.environ", self.environment(), clear=True):
                        with redirect_stderr(StringIO()):
                            self.assertEqual(setup_review.main(), 1)
                imported_db.engine.begin.assert_not_called()
                if configured == remote:
                    imported_app.app_context.assert_not_called()


class ReviewSampleDataTests(OwnerTestCase):
    today = date(2026, 10, 21)

    def seed(self):
        summary = setup_review.seed_review_data(
            db.session.connection(), db.metadata.tables, today=self.today)
        db.session.commit()
        return summary

    def test_complete_sample_week_has_independently_known_totals(self):
        self.seed()
        clean = setup_review.review_dates(self.today)["clean_week"]
        report = calculate_weekly_report(clean, as_of=self.today)
        self.assertEqual(report["earnings"], 962500)
        self.assertEqual(report["employer_cost"], 312800)
        self.assertEqual(report["fuel_spending"], 149000)
        self.assertEqual(report["overheads"], 140000)
        self.assertEqual(report["estimated_operating_result"], 360700)
        self.assertEqual(report["issues"], [])

    def test_issue_week_contains_actionable_missing_entries_and_legacy_amount(self):
        self.seed()
        issue_week = setup_review.review_dates(self.today)["issue_week"]
        report = calculate_weekly_report(issue_week, as_of=self.today)
        codes = {issue["code"] for issue in report["issues"]}
        self.assertTrue({"missing_day", "missing_payslip", "missing_fuel_receipt",
                         "job_amount_out_of_range"} <= codes)
        self.assertIsNone(report["estimated_operating_result"])

    def test_payslip_seed_omits_database_generated_week_column(self):
        payslip_inserts = []

        def record_insert(connection, cursor, statement, parameters, context, executemany):
            if statement.lstrip().lower().startswith("insert into payslip"):
                payslip_inserts.append(statement)

        event.listen(db.engine, "before_cursor_execute", record_insert)
        try:
            self.seed()
        finally:
            event.remove(db.engine, "before_cursor_execute", record_insert)
        self.assertTrue(payslip_inserts)
        for statement in payslip_inserts:
            self.assertNotIn("week_number_mtf", statement.lower())

    def test_partial_database_is_refused_without_creating_remaining_tables(self):
        engine = create_engine("sqlite://")
        try:
            with engine.begin() as connection:
                connection.execute(text("CREATE TABLE truck (id INTEGER PRIMARY KEY)"))
                with self.assertRaises(RuntimeError):
                    setup_review.setup_review_database(connection, db.metadata, today=self.today)
                self.assertEqual(inspect(connection).get_table_names(), ["truck"])
                self.assertEqual([column["name"] for column in inspect(connection).get_columns("truck")],
                                 ["id"])
        finally:
            engine.dispose()

    def test_first_sample_week_supports_duplicate_payroll_review(self):
        self.seed()
        first = setup_review.review_dates(self.today)["first_week"]
        report = calculate_weekly_report(first, as_of=self.today)
        self.assertTrue(any(issue["code"] == "multiple_payslips" for issue in report["issues"]))

    def test_current_sample_week_is_partial_and_future_purchases_do_not_enter_totals(self):
        self.seed()
        current = setup_review.review_dates(self.today)["current_week"]
        before = calculate_weekly_report(current, as_of=self.today)
        self.assertEqual(before["period_state"], "in_progress")
        self.assertGreater(before["earnings"], 0)
        self.assertIsNone(before["estimated_operating_result"])
        truck = db.session.execute(select(Fuel.truck_id).limit(1)).scalar_one()
        db.session.execute(Fuel.__table__.insert(), dict(
            date=current + timedelta(days=6), truck_id=truck, day_id=None,
            fuel_card_name="Future test receipt", fuel_cost=99999, fuel_volume=50000))
        db.session.commit()
        after = calculate_weekly_report(current, as_of=self.today)
        self.assertEqual(after["fuel_spending"], before["fuel_spending"])
        self.assertEqual(after["fuel_volume"], before["fuel_volume"])
        self.assertFalse(any(issue.get("date", self.today) > self.today for issue in after["issues"]))

    def test_existing_preview_setup_preserves_manual_changes_and_does_not_reseed(self):
        self.seed()
        selected = db.session.execute(select(Job.id).order_by(Job.id).limit(1)).scalar_one()
        db.session.execute(Job.__table__.update().where(Job.id == selected).values(earned=77777))
        db.session.commit()
        counts = {table: db.session.execute(select(db.func.count()).select_from(model)).scalar_one()
                  for table, model in (("day", Day), ("job", Job), ("fuel", Fuel),
                                       ("payslip", Payslip), ("driver", Driver))}
        with patch.object(setup_review, "seed_review_data", side_effect=AssertionError("must not reseed")):
            result = setup_review.setup_review_database(
                db.session.connection(), db.metadata, today=self.today + timedelta(days=7))
        db.session.commit()
        db.session.expire_all()
        self.assertFalse(result["seeded"])
        self.assertEqual(db.session.get(Job, selected).earned, 77777)
        for table, model in (("day", Day), ("job", Job), ("fuel", Fuel),
                             ("payslip", Payslip), ("driver", Driver)):
            self.assertEqual(db.session.execute(select(db.func.count()).select_from(model)).scalar_one(),
                             counts[table])
