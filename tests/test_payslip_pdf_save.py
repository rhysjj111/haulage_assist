"""Explicit payroll imports validate the full batch and commit it atomically."""

from copy import deepcopy
from datetime import date, timedelta
import json
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.sql.dml import Insert

from owner_test_support import OwnerTestCase, db
from haulage_app.models import Day, Driver, Job, Payslip
from haulage_app.verification.models import (
    Anomaly, MissingEntryAnomaly, TableName, UserFeedback,
)


PREVIEW = "/payslip/import"
CHECK = "/payslip/import/check"
SAVE = "/payslip/import/save"
FRIDAY = date(2026, 9, 25)


class PayslipPDFSaveTests(OwnerTestCase):
    def setUp(self):
        super().setUp()
        self.app.config["WTF_CSRF_ENABLED"] = True
        self.add_truck()
        self.add_driver(1, first_name="Alice", last_name="Example")
        self.add_driver(2, first_name="Ben", last_name="Sample")
        self.alice_day = self.add_day(driver_id=1, on_date=FRIDAY)
        self.ben_day = self.add_day(driver_id=2, on_date=FRIDAY, status="holiday")

    def payload(self, *, week="2026-09-19", rows=None):
        # Nonconsecutive source indexes represent explicitly excluded employees.
        return {"week_start": week, "rows": deepcopy(rows if rows is not None else [
            {"source_index": 3, "driver_id": 1, "total_wage": "615.37",
             "total_cost_to_employer": "706.38"},
            {"source_index": 9, "driver_id": 2, "total_wage": "801.20",
             "total_cost_to_employer": "923.95"},
        ])}

    def csrf_token(self):
        _, context = self.get_page(PREVIEW)
        return context["csrf_token"]

    def save(self, payload=None, *, token=None):
        if token is None:
            token = self.csrf_token()
        return self.client.post(SAVE, json=self.payload() if payload is None else payload,
                                headers={"X-CSRFToken": token})

    def snapshot(self):
        with db.session.no_autoflush:
            return {name: [tuple(row) for row in db.session.execute(
                select(table).order_by(*table.primary_key.columns))]
                for name, table in db.metadata.tables.items()}

    def stored_payslips(self):
        with db.session.no_autoflush:
            return [dict(row) for row in db.session.execute(
                select(Payslip.__table__).order_by(Payslip.id)).mappings()]

    def assert_private(self, response):
        self.assertIn("no-store", response.headers.get("Cache-Control", ""))
        self.assertEqual(response.headers.get("Pragma"), "no-cache")
        self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")

    def assert_row_error(self, response, source_index, field):
        errors = response.get_json().get("row_errors", [])
        self.assertTrue(any(row.get("source_index") == source_index
                            and row.get("field") == field for row in errors), response.text)

    def anomaly(self, *, driver_id=1, on_date=FRIDAY, table_name=TableName.PAYSLIP,
                feedback=False):
        anomaly = MissingEntryAnomaly(
            date=on_date, driver_id=driver_id, table_name=table_name,
            description="Fictional missing entry", is_read=False, is_recurring=False,
        )
        db.session.add(anomaly)
        db.session.flush()
        anomaly_id = anomaly.id
        if feedback:
            db.session.add(UserFeedback(anomaly_id=anomaly_id,
                                        user_comment="Fictional review note"))
        db.session.commit()
        return anomaly_id

    def test_page_exposes_an_explicit_separate_save_action(self):
        response, context = self.get_page(PREVIEW)
        self.assertEqual(context["save_url"], SAVE)
        self.assertIn('data-save-url="' + SAVE + '"', response.text)
        self.assertEqual(self.stored_payslips(), [])

    def test_selected_batch_is_saved_once_with_exact_pence_friday_and_existing_day_links(self):
        token = self.csrf_token()
        before = self.snapshot()
        real_commit = db.session.commit
        with patch.object(db.session, "commit", wraps=real_commit) as commit:
            response = self.save(token=token)
            self.assertEqual(response.status_code, 201, response.text)
            self.assertEqual(commit.call_count, 1)
        result = response.get_json()
        self.assertEqual((result["saved_count"], result["week_start"], result["week_end"],
                          result["entry_date"]),
                         (2, "2026-09-19", "2026-09-25", "2026-09-25"))
        rows = self.stored_payslips()
        self.assertEqual([(row["driver_id"], row["date"], row["day_id"],
                           row["total_wage"], row["total_cost_to_employer"]) for row in rows], [
            (1, FRIDAY, self.alice_day, 61537, 70638),
            (2, FRIDAY, self.ben_day, 80120, 92395),
        ])
        self.assertTrue(all(type(row["total_wage"]) is int for row in rows))
        self.assertEqual([row["source_index"] for row in result["payslips"]], [3, 9])
        self.assertEqual([row["driver_id"] for row in result["payslips"]], [1, 2])
        for entry in result["payslips"]:
            self.assertEqual(entry["review_url"], f"/payslip/add_payslip/{entry['id']}/edit")
        self.assertEqual(result["history_url"], "/payslip/add_payslip/0/history")
        after = self.snapshot()
        self.assertEqual({key: value for key, value in before.items() if key != "payslip"},
                         {key: value for key, value in after.items() if key != "payslip"})
        self.assert_private(response)

    def test_only_submitted_employees_are_saved_and_excluded_driver_records_are_untouched(self):
        existing = self.add_payslip(driver_id=2, on_date=FRIDAY, total_wage=42001,
                                    total_cost_to_employer=48002)
        before = self.stored_payslips()
        response = self.save(self.payload(rows=[self.payload()["rows"][0]]))
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.get_json()["saved_count"], 1)
        rows = self.stored_payslips()
        self.assertEqual(next(row for row in rows if row["id"] == existing), before[0])
        self.assertEqual([row["driver_id"] for row in rows], [2, 1])

    def test_changed_week_uses_its_own_friday_day_record_and_handles_year_boundary(self):
        friday = date(2027, 1, 1)
        matching_day = self.add_day(driver_id=1, on_date=friday)
        response = self.save(self.payload(week="2026-12-26", rows=[self.payload()["rows"][0]]))
        self.assertEqual(response.status_code, 201, response.text)
        row = self.stored_payslips()[0]
        self.assertEqual((row["date"], row["day_id"]), (friday, matching_day))
        self.assertEqual(response.get_json()["entry_date"], "2027-01-01")

    def test_missing_friday_day_prevents_every_row_even_if_another_day_exists(self):
        db.session.execute(Day.__table__.delete().where(Day.id == self.ben_day))
        db.session.commit()
        self.add_day(driver_id=2, on_date=FRIDAY - timedelta(days=1))
        before = self.snapshot()
        response = self.save()
        self.assertEqual(response.status_code, 422, response.text)
        self.assert_row_error(response, 9, "day")
        error = next(item for item in response.get_json()["row_errors"]
                     if item["source_index"] == 9 and item["field"] == "day")
        self.assertEqual(error["action_url"], "/day/add_day/0/entry")
        self.assertEqual(self.snapshot(), before)

    def test_preview_check_reports_friday_readiness_without_creating_a_missing_day(self):
        db.session.execute(Day.__table__.delete().where(Day.id == self.ben_day))
        db.session.commit()
        token = self.csrf_token()
        before = self.snapshot()
        response = self.client.post(CHECK, json={"week_start": "2026-09-19", "driver_ids": [1, 2]},
                                    headers={"X-CSRFToken": token})
        self.assertEqual(response.status_code, 200, response.text)
        result = response.get_json()
        self.assertEqual(result["entry_date"], "2026-09-25")
        self.assertEqual([(row["driver_id"], row["date"], row["status"])
                          for row in result["day_entries"]], [
            (1, "2026-09-25", "ready"), (2, "2026-09-25", "missing"),
        ])
        self.assertTrue(all(row["add_url"] == "/day/add_day/0/entry"
                            for row in result["day_entries"]))
        self.assertEqual(self.snapshot(), before)
        self.assert_private(response)

    def test_any_existing_payslip_in_the_selected_week_blocks_whole_batch_without_overwriting(self):
        for existing_date in (date(2026, 9, 19), FRIDAY):
            with self.subTest(existing_date=existing_date):
                self.add_payslip(driver_id=2, on_date=existing_date, total_wage=34567)
                before = self.snapshot()
                response = self.save()
                self.assertEqual(response.status_code, 409, response.text)
                self.assert_row_error(response, 9, "existing_payslip")
                self.assertEqual(self.snapshot(), before)

    def test_neighboring_weeks_and_another_year_do_not_count_as_selected_week_duplicates(self):
        self.add_payslip(on_date=date(2026, 9, 18))
        self.add_payslip(on_date=date(2026, 9, 26))
        self.add_payslip(on_date=date(2025, 9, 25))
        response = self.save()
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(len(self.stored_payslips()), 5)

    def test_repeated_same_submission_cannot_create_more_payslips(self):
        token = self.csrf_token()
        self.assertEqual(self.save(token=token).status_code, 201)
        before = self.snapshot()
        response = self.save(token=token)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.get_json()["error"]["code"], "review_required")
        self.assertEqual(self.snapshot(), before)

    def test_save_rechecks_records_added_after_a_successful_preview_check(self):
        token = self.csrf_token()
        response = self.client.post(CHECK, json={"week_start": "2026-09-19", "driver_ids": [1, 2]},
                                    headers={"X-CSRFToken": token})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(all(not row["payslips"] for row in response.get_json()["existing_payslips"]))
        self.add_payslip(driver_id=2, on_date=FRIDAY)
        before = self.snapshot()
        response = self.save(token=token)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.snapshot(), before)

    def test_inactive_future_and_missing_driver_cannot_be_saved(self):
        self.add_driver(3, employment_end=date.today() - timedelta(days=1))
        self.add_driver(4, employment_start=date.today() + timedelta(days=1))
        token = self.csrf_token()
        for driver_id in (3, 4, 99999):
            with self.subTest(driver_id=driver_id):
                payload = self.payload()
                payload["rows"][1]["driver_id"] = driver_id
                before = self.snapshot()
                response = self.save(payload, token=token)
                self.assertEqual(response.status_code, 422, response.text)
                self.assert_row_error(response, 9, "driver_id")
                self.assertEqual(self.snapshot(), before)

    def test_duplicate_selected_driver_flags_both_rows_and_saves_neither(self):
        payload = self.payload()
        payload["rows"][1]["driver_id"] = 1
        response = self.save(payload)
        self.assertEqual(response.status_code, 422, response.text)
        self.assert_row_error(response, 3, "driver_id")
        self.assert_row_error(response, 9, "driver_id")
        self.assertEqual(self.stored_payslips(), [])

    def test_invalid_money_is_not_rounded_coerced_or_partially_saved(self):
        token = self.csrf_token()
        invalid = (None, True, 615.37, 61537, "", "0", "-15.00", "1.00", "3000.00",
                   "9999.00", "615.371", "1e2", "NaN", "Infinity", "615,37", " 615.37 ",
                   "１２.３４", "9" * 33)
        for field in ("total_wage", "total_cost_to_employer"):
            for value in invalid:
                with self.subTest(field=field, value=repr(value)[:25]):
                    payload = self.payload()
                    payload["rows"][1][field] = value
                    response = self.save(payload, token=token)
                    self.assertEqual(response.status_code, 422, response.text)
                    self.assert_row_error(response, 9, field)
                    self.assertEqual(self.stored_payslips(), [])
                    self.assert_private(response)

    def test_employer_cost_below_wage_requires_review_before_any_row_is_saved(self):
        payload = self.payload()
        payload["rows"][1]["total_cost_to_employer"] = "800.99"
        response = self.save(payload)
        self.assertEqual(response.status_code, 422, response.text)
        self.assert_row_error(response, 9, "total_cost_to_employer")
        self.assertEqual(self.stored_payslips(), [])

    def test_malformed_batch_shapes_and_ids_are_rejected_without_echoing_source_data(self):
        token = self.csrf_token()
        invalid = [[], {}, {"week_start": "2026-09-19"},
                   {**self.payload(), "private_source": "Alice Example payroll"},
                   self.payload(rows=[]), self.payload(rows=[self.payload()["rows"][0]] * 501)]
        for field in ("driver_id", "source_index"):
            for value in (None, True, 1.0, "1", 0, -1, 2 ** 31):
                payload = self.payload()
                payload["rows"][0][field] = value
                invalid.append(payload)
        duplicate_source = self.payload()
        duplicate_source["rows"][1]["source_index"] = 3
        invalid.append(duplicate_source)
        for remove in ("driver_id", "total_wage", "total_cost_to_employer", "source_index"):
            payload = self.payload()
            del payload["rows"][0][remove]
            invalid.append(payload)
        for payload in invalid:
            with self.subTest(shape=repr(payload)[:60]):
                response = self.save(payload, token=token)
                self.assertEqual(response.status_code, 400, response.text)
                self.assertEqual(response.get_json()["error"]["code"], "invalid_save")
                self.assertNotIn("Alice Example payroll", response.text)
                self.assertEqual(self.stored_payslips(), [])
                self.assert_private(response)

    def test_invalid_and_non_saturday_weeks_are_rejected(self):
        token = self.csrf_token()
        for week in ("2026-09-20", "2026-02-30", "20260919", "19/09/2026", "", None,
                     True, "0000-01-01", "9999-12-31", "private date"):
            with self.subTest(week=week):
                response = self.save(self.payload(week=week), token=token)
                self.assertEqual(response.status_code, 400, response.text)
                self.assertEqual(self.stored_payslips(), [])

    def test_csrf_is_required_before_body_decoding_or_database_work(self):
        self.csrf_token()
        before = self.snapshot()
        for headers in ({}, {"X-CSRFToken": "not-valid"}):
            with self.subTest(headers=headers):
                response = self.client.post(SAVE, data=b"private invalid JSON",
                                            content_type="application/json", headers=headers)
                self.assertEqual(response.status_code, 403, response.text)
                self.assertEqual(response.get_json()["error"]["code"], "csrf_failed")
                self.assertNotIn("private invalid", response.text)
                self.assert_private(response)
        self.assertEqual(self.snapshot(), before)

    def test_json_content_type_body_cap_and_malformed_json_do_not_trigger_saving(self):
        token = self.csrf_token()
        for content_type in ("application/pdf", "text/plain", "multipart/form-data"):
            with self.subTest(content_type=content_type):
                response = self.client.post(SAVE, data=b"private source", content_type=content_type,
                                            headers={"X-CSRFToken": token})
                self.assertEqual(response.status_code, 415, response.text)
                self.assert_private(response)
        response = self.client.post(SAVE, data=b"private source" + b" " * 131072,
                                    content_type="application/json", headers={"X-CSRFToken": token})
        self.assertEqual(response.status_code, 413, response.text)
        self.assert_private(response)
        response = self.client.post(SAVE, data=b'{"private payroll', content_type="application/json",
                                    headers={"X-CSRFToken": token})
        self.assertEqual(response.status_code, 400, response.text)
        self.assertNotIn("private payroll", response.text)
        self.assertEqual(self.stored_payslips(), [])

    def test_integrity_failure_after_first_insert_rolls_back_the_whole_batch(self):
        token = self.csrf_token()
        before = self.snapshot()
        real_execute = db.session.execute
        insert_count = 0

        def fail_second_insert(statement, *args, **kwargs):
            nonlocal insert_count
            if isinstance(statement, Insert) and statement.table.name == "payslip":
                insert_count += 1
                if insert_count == 2:
                    raise IntegrityError("private insert", {}, Exception("private constraint"))
            return real_execute(statement, *args, **kwargs)

        with patch.object(db.session, "execute", side_effect=fail_second_insert):
            response = self.save(token=token)
        self.assertEqual(insert_count, 2)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.get_json()["error"]["code"], "save_conflict")
        self.assertNotIn("private", response.text)
        self.assertEqual(self.snapshot(), before)
        self.assert_private(response)

    def test_success_removes_only_resolved_friday_payslip_anomalies_and_their_feedback(self):
        resolved = self.anomaly(feedback=True)
        retained = [
            self.anomaly(driver_id=2),
            self.anomaly(on_date=FRIDAY - timedelta(days=1)),
            self.anomaly(table_name=TableName.DAY),
        ]
        response = self.save(self.payload(rows=[self.payload()["rows"][0]]))
        self.assertEqual(response.status_code, 201, response.text)
        self.assertIsNone(db.session.get(MissingEntryAnomaly, resolved))
        self.assertIsNone(db.session.get(Anomaly, resolved))
        self.assertEqual(db.session.query(UserFeedback).filter_by(anomaly_id=resolved).count(), 0)
        self.assertEqual({row.id for row in MissingEntryAnomaly.query.all()}, set(retained))

    def test_commit_failure_restores_inserted_rows_and_anomaly_inheritance_deletions(self):
        self.anomaly(feedback=True)
        token = self.csrf_token()
        before = self.snapshot()
        real_flush = db.session.flush

        def fail_after_flush():
            # Exercise rollback after child/parent anomaly and feedback deletes
            # really reached SQLite, as well as after the two Core inserts.
            real_flush()
            raise SQLAlchemyError("private payroll storage failure")

        with patch.object(db.session, "commit", side_effect=fail_after_flush):
            response = self.save(token=token)
        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(response.get_json()["error"]["code"], "save_unavailable")
        self.assertNotIn("private payroll", response.text)
        self.assertEqual(self.snapshot(), before)
        self.assert_private(response)

    def test_lost_commit_acknowledgement_is_uncertain_and_retry_does_not_duplicate_saved_batch(self):
        token = self.csrf_token()
        real_commit = db.session.commit

        def commit_then_lose_acknowledgement():
            real_commit()
            raise SQLAlchemyError("Synthetic lost commit acknowledgement")

        with patch.object(db.session, "commit", side_effect=commit_then_lose_acknowledgement):
            response = self.save(token=token)
        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(response.get_json()["error"]["code"], "save_unavailable")
        self.assertNotIn("nothing was saved", response.text.lower())
        self.assertNotIn("Synthetic lost", response.text)
        self.assertEqual([(row["driver_id"], row["total_wage"])
                          for row in self.stored_payslips()], [(1, 61537), (2, 80120)])
        committed = self.snapshot()
        retry = self.save(token=token)
        self.assertEqual(retry.status_code, 409, retry.text)
        self.assertEqual(self.snapshot(), committed)
        self.assert_private(response)

    def test_save_does_not_commit_or_discard_unrelated_pending_edits(self):
        self.add_job(self.add_day(on_date=FRIDAY - timedelta(days=1)))
        token = self.csrf_token()
        job = db.session.get(Job, 1)
        job.notes = "Pending unrelated source edit"
        with patch.object(db.session, "flush", side_effect=AssertionError("unexpected flush")), \
                patch.object(db.session, "commit", side_effect=AssertionError("unexpected commit")), \
                patch.object(db.session, "rollback", side_effect=AssertionError("unexpected rollback")):
            response = self.save(token=token)
            self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.get_json()["error"]["code"], "save_unavailable")
        self.assertIn(job, db.session.dirty)
        with db.session.no_autoflush:
            self.assertEqual(db.session.execute(select(Job.__table__.c.notes)).scalar_one(), "")
        self.assertEqual(self.stored_payslips(), [])

    def test_saved_amounts_and_employee_information_are_not_put_in_cookie_session_or_urls(self):
        response = self.save()
        self.assertEqual(response.status_code, 201, response.text)
        with self.client.session_transaction() as session:
            session_text = json.dumps(dict(session))
        for value in ("Alice Example", "Ben Sample", "615.37", "706.38", "2026-09-19", "%PDF"):
            self.assertNotIn(value, session_text)
        for entry in response.get_json()["payslips"]:
            self.assertNotIn("?", entry["review_url"])
            self.assertNotIn("615.37", entry["review_url"])
