"""Read-only payroll review checks use recorded dates and preserve source data."""

from datetime import date, timedelta
import json
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from owner_test_support import OwnerTestCase, db
from haulage_app.models import Job, Payslip


PREVIEW = "/payslip/import"
CHECK = "/payslip/import/check"


class PayslipPDFChecksTests(OwnerTestCase):
    def setUp(self):
        super().setUp()
        self.app.config["WTF_CSRF_ENABLED"] = True
        self.add_truck()
        self.add_driver(first_name="Alice", last_name="Example")

    def csrf_token(self):
        _, context = self.get_page(PREVIEW)
        return context["csrf_token"]

    def check(self, payload=None, *, token=None):
        if token is None:
            token = self.csrf_token()
        if payload is None:
            payload = {"week_start": "2026-09-19", "driver_ids": [1]}
        return self.client.post(CHECK, json=payload, headers={"X-CSRFToken": token})

    def assert_private_response(self, response):
        self.assertIn("no-store", response.headers.get("Cache-Control", ""))
        self.assertEqual(response.headers.get("Pragma"), "no-cache")
        self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")

    def snapshot(self):
        with db.session.no_autoflush:
            return {
                name: [tuple(row) for row in db.session.execute(
                    select(table).order_by(*table.primary_key.columns))]
                for name, table in db.metadata.tables.items()
            }

    def test_preview_exposes_the_read_only_check_endpoint(self):
        response, context = self.get_page(PREVIEW)
        self.assertEqual(context["check_url"], CHECK)
        self.assert_private_response(response)

    def test_checks_include_saturday_and_friday_and_all_legacy_duplicates_only_in_selected_week(self):
        self.add_driver(2, first_name="Ben", last_name="Sample")
        # The fixture deliberately gives every row the same computed week value:
        # a lookup must use actual dates, including historical duplicates.
        self.add_payslip(id=1, on_date=date(2026, 9, 18))
        self.add_payslip(id=3, on_date=date(2026, 9, 19), total_wage=61537,
                         total_cost_to_employer=70638)
        self.add_payslip(id=2, on_date=date(2026, 9, 19), total_wage=10001,
                         total_cost_to_employer=11111)
        self.add_payslip(id=4, on_date=date(2026, 9, 25), total_wage=80120,
                         total_cost_to_employer=92395)
        self.add_payslip(id=5, on_date=date(2026, 9, 26))
        self.add_payslip(id=6, driver_id=2, on_date=date(2026, 9, 25))

        response = self.check()
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.get_json()
        self.assertEqual((payload["week_start"], payload["week_end"]),
                         ("2026-09-19", "2026-09-25"))
        self.assertEqual(len(payload["existing_payslips"]), 1)
        driver = payload["existing_payslips"][0]
        self.assertEqual(driver["driver_id"], 1)
        self.assertEqual([entry["id"] for entry in driver["payslips"]], [2, 3, 4])
        self.assertEqual([entry["date"] for entry in driver["payslips"]],
                         ["2026-09-19", "2026-09-19", "2026-09-25"])
        self.assertEqual(driver["payslips"][1]["total_wage"], "615.37")
        self.assertEqual(driver["payslips"][1]["total_cost_to_employer"], "706.38")
        for entry in driver["payslips"]:
            self.assertEqual(entry["review_url"], f"/payslip/add_payslip/{entry['id']}/edit")
        self.assert_private_response(response)

    def test_checks_follow_a_payroll_week_across_the_calendar_year(self):
        self.add_payslip(id=1, on_date=date(2026, 12, 25))
        self.add_payslip(id=2, on_date=date(2026, 12, 26))
        self.add_payslip(id=3, on_date=date(2027, 1, 1))
        self.add_payslip(id=4, on_date=date(2027, 1, 2))
        response = self.check({"week_start": "2026-12-26", "driver_ids": [1]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.get_json()["week_end"], "2027-01-01")
        self.assertEqual([entry["id"] for entry in response.get_json()["existing_payslips"][0]["payslips"]],
                         [2, 3])

    def test_requested_drivers_without_payslips_and_duplicate_selections_have_explicit_results(self):
        self.add_driver(2)
        response = self.check({"week_start": "2026-09-19", "driver_ids": [2, 1, 2]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.get_json()["existing_payslips"], [
            {"driver_id": 1, "payslips": []},
            {"driver_id": 2, "payslips": []},
        ])
        response = self.check({"week_start": "2026-09-19", "driver_ids": []})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.get_json()["existing_payslips"], [])
        response = self.check({"week_start": "2026-09-19", "driver_ids": [1] * 500})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.get_json()["existing_payslips"], [{"driver_id": 1, "payslips": []}])

    def test_inactive_future_and_nonexistent_drivers_are_rejected_without_returning_other_records(self):
        self.add_driver(2, employment_end=date.today() - timedelta(days=1))
        self.add_driver(3, employment_start=date.today() + timedelta(days=1))
        self.add_payslip(driver_id=2, on_date=date(2026, 9, 25), total_wage=54321)
        for driver_id in (2, 3, 999999, 2 ** 100):
            with self.subTest(driver_id=driver_id):
                response = self.check({"week_start": "2026-09-19", "driver_ids": [1, driver_id]})
                self.assertEqual(response.status_code, 422, response.text)
                self.assertNotIn("existing_payslips", response.get_json())
                self.assertNotIn("543.21", response.text)
                self.assert_private_response(response)

    def test_invalid_calendar_dates_and_non_saturday_weeks_are_rejected(self):
        for week in ("2026-09-20", "2026-02-30", "20260919", "19/09/2026",
                     "2026-09-19T00:00:00", "0000-01-01", "10000-01-01", "9999-12-31",
                     "2026-09-19 private payroll text", "", None, True, 123):
            with self.subTest(week=week):
                response = self.check({"week_start": week, "driver_ids": [1]})
                self.assertEqual(response.status_code, 400, response.text)
                self.assertNotIn("private payroll text", response.text)
                self.assert_private_response(response)

    def test_first_and_last_complete_calendar_weeks_are_valid_without_date_overflow(self):
        for start, end in (("0001-01-06", "0001-01-12"), ("9999-12-25", "9999-12-31")):
            with self.subTest(week=start):
                response = self.check({"week_start": start, "driver_ids": []})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.get_json(), {
                    "week_start": start, "week_end": end, "existing_payslips": [],
                    "entry_date": end, "day_entries": [],
                })

    def test_driver_selection_requires_a_bounded_list_of_positive_integer_ids(self):
        for ids in (None, True, 1, "1", {}, [True], [False], [1.0], ["1"], [0], [-1],
                    [None], [[1]], [1] * 501):
            with self.subTest(driver_ids=repr(ids)[:40]):
                response = self.check({"week_start": "2026-09-19", "driver_ids": ids})
                self.assertEqual(response.status_code, 400, response.text)
                self.assert_private_response(response)

    def test_malformed_or_incomplete_json_is_rejected_without_echoing_input(self):
        token = self.csrf_token()
        for content in (b'{"week_start": "private source', b"\xff", b"null", b"[]", b"42", b'"payroll"',
                        b"{}", b'{"driver_ids":[1]}', b'{"week_start":"2026-09-19"}',
                        b'{"week_start":"2026-09-19","driver_ids":[1],"total_wage":"private source"}'):
            with self.subTest(content=content):
                response = self.client.post(CHECK, data=content, content_type="application/json",
                                            headers={"X-CSRFToken": token})
                self.assertEqual(response.status_code, 400, response.text)
                self.assertNotIn("private source", response.text)
                self.assert_private_response(response)

    def test_missing_or_invalid_csrf_is_rejected_before_decoding_the_body(self):
        self.csrf_token()
        for headers in ({}, {"X-CSRFToken": "not-valid"}):
            with self.subTest(headers=headers):
                response = self.client.post(CHECK, data=b"not JSON private source",
                                            content_type="application/json", headers=headers)
                self.assertEqual(response.status_code, 403, response.text)
                self.assertEqual(response.get_json()["error"]["code"], "csrf_failed")
                self.assertNotIn("private source", response.text)
                self.assert_private_response(response)

    def test_non_json_content_types_are_rejected(self):
        token = self.csrf_token()
        for content_type in ("text/plain", "application/pdf", "multipart/form-data"):
            with self.subTest(content_type=content_type):
                response = self.client.post(CHECK, data=b"private source", content_type=content_type,
                                            headers={"X-CSRFToken": token})
                self.assertEqual(response.status_code, 415, response.text)
                self.assertEqual(response.get_json()["error"]["code"], "unsupported_media_type")
                self.assert_private_response(response)

    def test_oversized_body_is_rejected_before_attempting_to_decode_it(self):
        token = self.csrf_token()
        response = self.client.post(CHECK, data=b"private source" + b" " * 32768,
                                    content_type="application/json", headers={"X-CSRFToken": token})
        self.assertEqual(response.status_code, 413, response.text)
        self.assertNotIn("private source", response.text)
        self.assert_private_response(response)

    def test_database_failure_has_a_generic_retryable_error_without_partial_payslips(self):
        token = self.csrf_token()
        with patch("haulage_app.payslip.import_checks.get_entry_drivers",
                   side_effect=SQLAlchemyError("private driver and wage 615.37")):
            response = self.check(token=token)
        self.assertEqual(response.status_code, 503, response.text)
        self.assertNotIn("existing_payslips", response.get_json())
        self.assertNotIn("private driver", response.text)
        self.assertNotIn("615.37", response.text)
        self.assert_private_response(response)

    def test_repeated_checks_never_write_or_remove_business_records(self):
        self.add_job(self.add_day())
        self.add_payslip(on_date=date(2026, 9, 25))
        token = self.csrf_token()
        before = self.snapshot()
        with patch.object(db.session, "add", side_effect=AssertionError("unexpected add")), \
                patch.object(db.session, "add_all", side_effect=AssertionError("unexpected add_all")), \
                patch.object(db.session, "delete", side_effect=AssertionError("unexpected delete")), \
                patch.object(db.session, "commit", side_effect=AssertionError("unexpected commit")):
            for _ in range(2):
                response = self.check(token=token)
                self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.snapshot(), before)

    def test_checks_do_not_flush_an_unrelated_pending_edit(self):
        self.add_job(self.add_day())
        token = self.csrf_token()
        job = db.session.get(Job, 1)
        job.notes = "Pending and unsaved"
        with patch.object(db.session, "flush", side_effect=AssertionError("unexpected flush")):
            response = self.check(token=token)
            self.assertEqual(response.status_code, 200, response.text)
        self.assertIn(job, db.session.dirty)
        with db.session.no_autoflush:
            stored = db.session.execute(select(Job.__table__.c.notes)).scalar_one()
        self.assertEqual(stored, "")

    def test_existing_payslip_check_reports_stored_values_not_an_unsaved_orm_edit(self):
        self.add_driver(2)
        entry_id = self.add_payslip(on_date=date(2026, 9, 25), total_wage=61537,
                                    total_cost_to_employer=70638)
        token = self.csrf_token()
        before = self.snapshot()
        entry = db.session.get(Payslip, entry_id)
        entry.date = "02/10/2026"
        entry.driver_id = 2
        entry.total_wage = "777.77"
        entry.total_cost_to_employer = "888.88"
        with patch.object(db.session, "flush", side_effect=AssertionError("unexpected flush")):
            response = self.check(token=token)
        self.assertEqual(response.status_code, 200, response.text)
        group = response.get_json()["existing_payslips"][0]
        self.assertEqual(group["driver_id"], 1)
        self.assertEqual(len(group["payslips"]), 1)
        recorded = group["payslips"][0]
        self.assertEqual((recorded["id"], recorded["date"], recorded["total_wage"],
                          recorded["total_cost_to_employer"]),
                         (entry_id, "2026-09-25", "615.37", "706.38"))
        self.assertIn(entry, db.session.dirty)
        self.assertEqual((entry.date, entry.driver_id, entry.total_wage, entry.total_cost_to_employer),
                         (date(2026, 10, 2), 2, 77777, 88888))
        self.assertEqual(self.snapshot(), before)

    def test_checks_do_not_put_names_amounts_dates_or_drafts_in_session_or_review_urls(self):
        self.add_payslip(on_date=date(2026, 9, 25), total_wage=61537,
                         total_cost_to_employer=70638)
        response = self.check()
        self.assertEqual(response.status_code, 200, response.text)
        with self.client.session_transaction() as session:
            session_text = json.dumps(dict(session))
        for value in ("Alice Example", "615.37", "706.38", "2026-09-19", "2026-09-25", "%PDF"):
            self.assertNotIn(value, session_text)
        for group in response.get_json()["existing_payslips"]:
            for entry in group["payslips"]:
                self.assertNotIn("?", entry["review_url"])
                self.assertNotIn("615.37", entry["review_url"])
                self.assertNotIn("Alice", entry["review_url"])
