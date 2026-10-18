"""Preview setup stays on disposable data and provides useful review scenarios."""

import builtins
from contextlib import nullcontext, redirect_stderr, redirect_stdout
from datetime import date, timedelta
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.exc import IntegrityError

from owner_test_support import OwnerTestCase, db
from haulage_app.models import Day, Driver, Fuel, Job, Payslip
from haulage_app.owner_analysis.models import OwnerOverheadSetting
from haulage_app.verification.models import Anomaly, IncorrectMileage, MissingEntryAnomaly
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

    def test_successful_setup_and_guarded_cleanup_exit_successfully_with_clear_messages(self):
        periods = setup_review.review_dates(date(2026, 10, 21))
        cases = (
            (dict(seeded=True, **periods), "Created an isolated review database"),
            (dict(seeded=False, sample_weekends_removed=8, sample_weekends_cleanup_skipped=False),
             "Removed 8 unchanged synthetic weekend absences"),
            (dict(seeded=False, sample_weekends_removed=0, sample_weekends_cleanup_skipped=True),
             "Sample weekend cleanup skipped"),
            (dict(seeded=False, sample_weekends_removed=0, sample_weekends_cleanup_skipped=False),
             "All records and edits were preserved"),
            (dict(seeded=False, sample_weekends_removed=0, sample_weekends_cleanup_skipped=False,
                  issue_decisions_updated=True), "Updated the review decision options"),
        )
        imported_module = ModuleType("haulage_app")
        imported_module.app = SimpleNamespace(
            config={"SQLALCHEMY_DATABASE_URI": REVIEW_URL}, app_context=lambda: nullcontext())
        imported_module.db = SimpleNamespace(metadata=Mock(), engine=SimpleNamespace(
            url=SimpleNamespace(render_as_string=lambda **kwargs: REVIEW_URL),
            begin=lambda: nullcontext(Mock()),
        ))
        for result, message in cases:
            with self.subTest(message=message), patch.dict("sys.modules", {"haulage_app": imported_module}):
                with patch.dict("os.environ", self.environment(), clear=True):
                    with patch.object(setup_review, "setup_review_database", return_value=result):
                        with redirect_stdout(StringIO()) as output:
                            self.assertEqual(setup_review.main(), 0)
                self.assertIn(message, output.getvalue())


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

    def test_normal_weekends_are_blank_and_occasional_saturday_work_is_recorded(self):
        self.seed()
        periods = setup_review.review_dates(self.today)
        clean_days = db.session.execute(select(Day).where(
            Day.date.between(periods["clean_week"], periods["clean_week"] + timedelta(days=6)))).scalars().all()
        self.assertEqual(len(clean_days), 20)
        self.assertTrue(all(day.date.weekday() < 5 for day in clean_days))
        saturday = db.session.execute(select(Day).where(
            Day.date == periods["issue_week"])).scalars().all()
        self.assertEqual(len(saturday), 1)
        self.assertEqual(saturday[0].status, "working")
        self.assertEqual(len(saturday[0].jobs), 2)
        self.assertEqual(len(saturday[0].fuel_entries), 1)

    def legacy_weekend_rows(self):
        """Recreate only the old fixture's erroneous empty weekend records."""
        self.seed()
        stamp = db.session.get(Driver, 1).timestamp
        # PostgreSQL's CURRENT_TIMESTAMP is one value for the seed transaction;
        # SQLite's second-resolution clock can tick during a fixture insertion.
        for name in ("driver", "truck", "driver_employment_history", "day", "job", "fuel", "payslip"):
            table = db.metadata.tables[name]
            db.session.execute(table.update().values(timestamp=stamp))
        current = setup_review.review_dates(self.today)["first_week"]
        ids = []
        while current <= self.today:
            if current.weekday() >= 5:
                for driver_id in range(1, 5):
                    exists = db.session.execute(select(Day.id).where(
                        Day.date == current, Day.driver_id == driver_id)).first()
                    if exists:
                        continue
                    ids.append(db.session.execute(Day.__table__.insert().returning(Day.id), dict(
                        date=current, driver_id=driver_id, truck_id=None, status="absent",
                        overnight=False, fuel=False, start_mileage=0, end_mileage=0,
                        additional_earned=0, additional_wages=0, timestamp=stamp)).scalar_one())
            current += timedelta(days=1)
        db.session.commit()
        return ids

    def test_existing_original_sample_weekend_cleanup_is_idempotent(self):
        legacy_ids = self.legacy_weekend_rows()
        clean = setup_review.review_dates(self.today)["clean_week"]
        before = calculate_weekly_report(clean, as_of=self.today)
        result = setup_review.setup_review_database(
            db.session.connection(), db.metadata, today=self.today)
        db.session.commit()
        self.assertFalse(result["seeded"])
        self.assertFalse(result["sample_weekends_cleanup_skipped"])
        self.assertEqual(result["sample_weekends_removed"], len(legacy_ids))
        self.assertEqual(db.session.execute(select(Day.id).where(Day.id.in_(legacy_ids))).all(), [])
        after = calculate_weekly_report(clean, as_of=self.today)
        for key in ("earnings", "employer_cost", "fuel_spending", "overheads", "estimated_operating_result"):
            self.assertEqual(after[key], before[key])
        second = setup_review.setup_review_database(
            db.session.connection(), db.metadata, today=self.today + timedelta(days=30))
        self.assertEqual(second["sample_weekends_removed"], 0)
        self.assertFalse(second["sample_weekends_cleanup_skipped"])

    def test_cleanup_preserves_modified_weekend_entries_and_unrelated_user_changes(self):
        legacy_ids = self.legacy_weekend_rows()
        changes = ({"status": "holiday"}, {"status": "working"}, {"truck_id": 1},
                   {"overnight": True}, {"fuel": True}, {"start_mileage": 1},
                   {"end_mileage": 1}, {"additional_earned": 1}, {"additional_wages": 1},
                   {"timestamp": date(2020, 1, 1)})
        protected = legacy_ids[:len(changes)]
        for identifier, values in zip(protected, changes):
            db.session.execute(Day.__table__.update().where(Day.id == identifier).values(**values))
        # User changes elsewhere must not block cleanup or be reset.
        selected_job = db.session.execute(select(Job.id).order_by(Job.id).limit(1)).scalar_one()
        db.session.execute(Job.__table__.update().where(Job.id == selected_job).values(earned=77777))
        db.session.execute(OwnerOverheadSetting.__table__.update().values(allowance_per_truck=99999))
        db.session.commit()
        result = setup_review.setup_review_database(
            db.session.connection(), db.metadata, today=self.today)
        db.session.commit()
        self.assertEqual(result["sample_weekends_removed"], len(legacy_ids) - len(protected))
        self.assertEqual(set(db.session.execute(select(Day.id).where(Day.id.in_(legacy_ids))).scalars()),
                         set(protected))
        self.assertEqual(db.session.get(Job, selected_job).earned, 77777)
        self.assertEqual(set(db.session.execute(select(OwnerOverheadSetting.allowance_per_truck)).scalars()),
                         {99999})

    def test_cleanup_preserves_weekend_rows_with_job_fuel_or_payslip_links(self):
        legacy_ids = self.legacy_weekend_rows()
        self.add_job(legacy_ids[0], earned=123)
        self.add_fuel(day_id=legacy_ids[1])
        self.add_payslip(day_id=legacy_ids[2], on_date=self.today + timedelta(days=90))
        result = setup_review.setup_review_database(
            db.session.connection(), db.metadata, today=self.today)
        db.session.commit()
        self.assertEqual(result["sample_weekends_removed"], len(legacy_ids) - 3)
        self.assertEqual(set(db.session.execute(select(Day.id).where(Day.id.in_(legacy_ids))).scalars()),
                         set(legacy_ids[:3]))

    def test_cleanup_preserves_all_legacy_anomaly_day_references(self):
        legacy_ids = self.legacy_weekend_rows()
        dates = dict(db.session.execute(select(Day.id, Day.date).where(Day.id.in_(legacy_ids[:3]))).all())
        db.session.execute(Anomaly.__table__.insert(), dict(id=10000, type="missing_entry"))
        db.session.execute(MissingEntryAnomaly.__table__.insert(), dict(
            id=10000, date=dates[legacy_ids[0]], driver_id=1, truck_id=None,
            day_id=legacy_ids[0], table_name="JOB"))
        db.session.execute(Anomaly.__table__.insert(), dict(id=10001, type="incorrect_mileage"))
        db.session.execute(IncorrectMileage.__table__.insert(), dict(
            id=10001, previous_date=dates[legacy_ids[1]], next_date=dates[legacy_ids[2]],
            previous_end_mileage=0, next_start_mileage=0, truck_id=1,
            previous_day_id=legacy_ids[1], next_day_id=legacy_ids[2]))
        db.session.commit()
        result = setup_review.setup_review_database(
            db.session.connection(), db.metadata, today=self.today)
        db.session.commit()
        self.assertEqual(result["sample_weekends_removed"], len(legacy_ids) - 3)
        self.assertEqual(set(db.session.execute(select(Day.id).where(Day.id.in_(legacy_ids))).scalars()),
                         set(legacy_ids[:3]))
        self.assertEqual(db.session.execute(select(MissingEntryAnomaly.day_id)).scalar_one(), legacy_ids[0])
        mileage = db.session.execute(select(IncorrectMileage.previous_day_id, IncorrectMileage.next_day_id)).one()
        self.assertEqual(tuple(mileage), tuple(legacy_ids[1:3]))

    def test_cleanup_refuses_an_unrecognised_fixture_and_preserves_all_records(self):
        legacy_ids = self.legacy_weekend_rows()
        db.session.execute(Driver.__table__.update().where(Driver.id == 1).values(first_name="Real"))
        db.session.commit()
        result = setup_review.setup_review_database(
            db.session.connection(), db.metadata, today=self.today)
        self.assertTrue(result["sample_weekends_cleanup_skipped"])
        self.assertEqual(result["sample_weekends_removed"], 0)
        self.assertEqual(len(db.session.execute(select(Day.id).where(Day.id.in_(legacy_ids))).all()),
                         len(legacy_ids))

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


class ReviewDecisionCompatibilityTests(OwnerTestCase):
    def set_decision_constraint(self, expression):
        from alembic import op
        with Operations.context(MigrationContext.configure(db.session.connection())):
            with op.batch_alter_table("owner_issue_verification") as batch:
                batch.drop_constraint("ck_owner_issue_decision", type_="check")
                batch.create_check_constraint("ck_owner_issue_decision", expression)
        db.session.commit()

    def add_note(self, decision="verified", scope="test"):
        db.session.execute(text("""INSERT INTO owner_issue_verification
            (week_start,scope_key,decision,note,source_fingerprint)
            VALUES ('2026-10-03',:scope,:decision,'Original explanation',:fingerprint)"""),
            dict(scope=scope, decision=decision, fingerprint="a" * 64))
        db.session.commit()

    def notes(self):
        return db.session.execute(text("SELECT * FROM owner_issue_verification ORDER BY id")).all()

    def test_existing_preview_constraint_upgrade_preserves_records_edits_and_notes(self):
        setup_review.seed_review_data(db.session.connection(), db.metadata.tables, today=date(2026, 10, 21))
        db.session.execute(Job.__table__.update().where(Job.id == 1).values(earned=77777))
        db.session.execute(OwnerOverheadSetting.__table__.update().values(allowance_per_truck=99999))
        db.session.commit()
        self.set_decision_constraint("decision IN ('verified', 'confirmed_zero', 'note')")
        self.add_note()
        before = self.notes()
        with patch.object(setup_review, "seed_review_data", side_effect=AssertionError("must not reseed")):
            result = setup_review.setup_review_database(
                db.session.connection(), db.metadata, today=date(2026, 10, 21))
        db.session.commit()
        self.assertTrue(result["issue_decisions_updated"])
        self.assertFalse(result["seeded"])
        self.assertEqual(self.notes(), before)
        self.assertEqual(db.session.get(Job, 1).earned, 77777)
        self.assertEqual(set(db.session.execute(select(OwnerOverheadSetting.allowance_per_truck)).scalars()),
                         {99999})
        self.add_note("dismissed", "dismissal")
        self.add_note("awaiting_invoice", "invoice")
        again = setup_review.setup_review_database(
            db.session.connection(), db.metadata, today=date(2026, 11, 21))
        self.assertFalse(again["issue_decisions_updated"])
        self.assertEqual(len(self.notes()), 3)
        with self.assertRaises(IntegrityError):
            self.add_note("unexpected", "invalid")
        db.session.rollback()

    def test_unknown_or_missing_constraint_is_refused_without_changing_records(self):
        for expression in ("decision IN ('verified', 'confirmed_zero', 'note', 'unexpected')",
                           "decision IN ('verified', 'confirmed_zero', 'note') OR length(note) > 5"):
            with self.subTest(expression=expression):
                self.set_decision_constraint(expression)
                before = self.notes()
                with self.assertRaisesRegex(RuntimeError, "constraint is incompatible"):
                    setup_review.setup_review_database(
                        db.session.connection(), db.metadata, today=date(2026, 10, 21))
                self.assertEqual(self.notes(), before)
                self.assertEqual(next(item["sqltext"] for item in inspect(db.session.connection()).get_check_constraints(
                    "owner_issue_verification") if item["name"] == "ck_owner_issue_decision"), expression)

        from alembic import op
        with Operations.context(MigrationContext.configure(db.session.connection())):
            with op.batch_alter_table("owner_issue_verification") as batch:
                batch.drop_constraint("ck_owner_issue_decision", type_="check")
        db.session.commit()
        with self.assertRaisesRegex(RuntimeError, "missing or incompatible"):
            setup_review.setup_review_database(db.session.connection(), db.metadata, today=date(2026, 10, 21))
