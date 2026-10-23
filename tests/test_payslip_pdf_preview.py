"""Temporary payroll uploads propose editable entries without saving records."""

import base64
from datetime import date, timedelta
from html.parser import HTMLParser
import json
from unittest.mock import patch

from sqlalchemy import select

from owner_test_support import OwnerTestCase, db
from payroll_pdf_fixtures import EMPLOYEES, report_pdf
from haulage_app.models import Job
from haulage_app.payslip.pdf_reader import MAX_PDF_BYTES, PayrollPDFError


PREVIEW = "/payslip/import"
READ = "/payslip/import/read"
WORKER = "haulage_app.payslip.pdf_processing.read_payroll_pdf_isolated"


class _PreviewHTML(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.inputs = []
        self.forms = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input":
            self.inputs.append(attrs)
        elif tag == "form":
            self.forms.append(attrs)


class PayslipPDFPreviewTests(OwnerTestCase):
    def setUp(self):
        super().setUp()
        self.app.config["WTF_CSRF_ENABLED"] = True
        self.add_truck()
        self.add_driver(first_name="Alice", last_name="Example")

    def csrf_token(self):
        _, context = self.get_page(PREVIEW)
        token = context["csrf_token"]
        self.assertIsInstance(token, str)
        self.assertTrue(token)
        return token

    def post_pdf(self, content=None, *, token=None, content_type="application/pdf"):
        if token is None:
            token = self.csrf_token()
        return self.client.post(
            READ, data=report_pdf() if content is None else content,
            content_type=content_type, headers={"X-CSRFToken": token},
        )

    def assert_private_response(self, response):
        self.assertIn("no-store", response.headers.get("Cache-Control", ""))
        self.assertEqual(response.headers.get("Pragma"), "no-cache")
        self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")

    def source_snapshot(self):
        with db.session.no_autoflush:
            return {
                name: [tuple(row) for row in db.session.execute(
                    select(table).order_by(*table.primary_key.columns))]
                for name, table in db.metadata.tables.items()
            }

    def test_upload_page_has_a_pdf_picker_and_csrf_without_a_payslip_save_form(self):
        response, context = self.get_page(PREVIEW)
        parsed = _PreviewHTML(response.text)
        self.assertTrue(any(field.get("type") == "file" for field in parsed.inputs))
        self.assertIsInstance(context["csrf_token"], str)
        self.assertEqual(context["read_url"], READ)
        self.assertIn("Preview", response.text)
        self.assertFalse(any("add_payslip" in form.get("action", "")
                             or "edit_payslip" in form.get("action", "")
                             for form in parsed.forms))
        self.assert_private_response(response)

    def test_existing_payslip_page_links_to_the_upload_preview(self):
        response = self.client.get("/payslip/add_payslip/0/entry")
        self.assertEqual(response.status_code, 200)
        self.assertIn('href="' + PREVIEW + '"', response.text)

    def test_upload_returns_the_confirmed_week_and_exact_gross_and_employer_amounts(self):
        response = self.post_pdf()
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.get_json()
        self.assertEqual(payload["report"]["pay_date"], "2026-09-25")
        self.assertEqual(payload["report"]["week_start"], "2026-09-19")
        self.assertEqual(payload["report"]["week_end"], "2026-09-25")
        self.assertEqual(payload["report"]["employee_count"], 2)
        self.assertEqual(payload["report"]["totals"]["total_payments"], "1416.57")
        self.assertEqual(payload["report"]["totals"]["total_cost_to_employer"], "1630.33")
        self.assertEqual([row["employee_name"] for row in payload["rows"]],
                         ["Alice Example", "Ben Sample"])
        first = payload["rows"][0]
        self.assertEqual(first["source_index"], 1)
        self.assertEqual(first["page_number"], 1)
        self.assertEqual(first["total_wage"], "615.37")
        self.assertEqual(first["total_cost_to_employer"], "706.38")
        self.assertEqual(first["driver_id"], 1)
        self.assertEqual(first["match_status"], "matched")
        self.assert_private_response(response)

    def test_matching_ignores_case_and_repeated_spaces_without_using_fuzzy_names(self):
        employees = (("  ALICE   EXAMPLE  ", *EMPLOYEES[0][1:]),
                     ("Ben Samples", *EMPLOYEES[1][1:]))
        self.add_driver(2, first_name="Ben", last_name="Sample")
        response = self.post_pdf(report_pdf(employees=employees))
        self.assertEqual(response.status_code, 200, response.text)
        first, second = response.get_json()["rows"]
        self.assertEqual((first["driver_id"], first["match_status"]), (1, "matched"))
        self.assertIsNone(second["driver_id"])
        self.assertEqual(second["match_status"], "unmatched")

    def test_inactive_and_future_drivers_are_not_suggested_but_employees_remain_visible(self):
        self.add_driver(2, first_name="Ben", last_name="Sample",
                        employment_end=date.today() - timedelta(days=1))
        self.add_driver(3, first_name="Future", last_name="Example",
                        employment_start=date.today() + timedelta(days=30))
        response = self.post_pdf()
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.get_json()
        self.assertEqual([driver["id"] for driver in payload["drivers"]], [1])
        self.assertEqual(len(payload["rows"]), 2)
        self.assertEqual(payload["rows"][1]["employee_name"], "Ben Sample")
        self.assertIsNone(payload["rows"][1]["driver_id"])
        self.assertEqual(payload["rows"][1]["match_status"], "unmatched")
        self.assertEqual(payload["rows"][1]["candidate_driver_ids"], [])

    def test_ambiguous_active_driver_names_require_a_choice_instead_of_taking_the_first(self):
        self.add_driver(2, first_name="ALICE", last_name="EXAMPLE")
        response = self.post_pdf()
        self.assertEqual(response.status_code, 200, response.text)
        row = response.get_json()["rows"][0]
        self.assertEqual(row["match_status"], "ambiguous")
        self.assertIsNone(row["driver_id"])
        self.assertCountEqual(row["candidate_driver_ids"], [1, 2])

    def test_missing_or_invalid_csrf_is_rejected_before_pdf_processing(self):
        self.csrf_token()
        with patch(WORKER) as worker:
            for headers in ({}, {"X-CSRFToken": "not-a-valid-token"}):
                with self.subTest(has_header=bool(headers)):
                    response = self.client.post(READ, data=report_pdf(),
                                                content_type="application/pdf", headers=headers)
                    self.assertEqual(response.status_code, 403)
                    self.assertEqual(response.get_json()["error"]["code"], "csrf_failed")
                    self.assert_private_response(response)
            worker.assert_not_called()

    def test_other_content_types_are_rejected_without_parsing_form_or_document_data(self):
        token = self.csrf_token()
        with patch(WORKER) as worker:
            for content_type in ("application/json", "text/plain", "multipart/form-data"):
                with self.subTest(content_type=content_type):
                    response = self.post_pdf(b"private body", token=token, content_type=content_type)
                    self.assertEqual(response.status_code, 415)
                    self.assertEqual(response.get_json()["error"]["code"], "unsupported_media_type")
                    self.assert_private_response(response)
            worker.assert_not_called()

    def test_oversize_upload_is_rejected_before_worker_processing(self):
        token = self.csrf_token()
        with patch(WORKER) as worker:
            response = self.post_pdf(b"%PDF-1.7\n" + b" " * MAX_PDF_BYTES, token=token)
            self.assertEqual(response.status_code, 413)
            self.assertEqual(response.get_json()["error"]["code"], "too_large")
            self.assert_private_response(response)
            worker.assert_not_called()

    def test_unreadable_pdf_has_a_safe_json_error_and_does_not_echo_private_contents(self):
        response = self.post_pdf(b"%PDF-1.7\nAlice Example 615.37 broken private document")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.get_json()["error"]["code"], "invalid_pdf")
        for value in ("Alice Example", "615.37", "Traceback", "broken private document"):
            self.assertNotIn(value, response.text)
        self.assert_private_response(response)

    def test_worker_resource_failure_is_reported_without_any_report_rows(self):
        token = self.csrf_token()
        with patch(WORKER, side_effect=PayrollPDFError(
                "processing_timeout", "The report took too long to read. Try a smaller report.")):
            response = self.post_pdf(token=token)
        self.assertEqual(response.status_code, 503)
        payload = response.get_json()
        self.assertEqual(payload["error"]["code"], "processing_timeout")
        self.assertNotIn("rows", payload)
        self.assert_private_response(response)

    def test_repeated_preview_requests_preserve_all_business_records_and_never_commit(self):
        self.add_job(self.add_day(on_date=date(2026, 9, 25)))
        self.add_payslip(on_date=date(2026, 9, 25), total_wage=54321,
                         total_cost_to_employer=65432)
        token = self.csrf_token()
        before = self.source_snapshot()
        with patch.object(db.session, "add", side_effect=AssertionError("unexpected add")), \
                patch.object(db.session, "add_all", side_effect=AssertionError("unexpected add_all")), \
                patch.object(db.session, "commit", side_effect=AssertionError("unexpected commit")):
            for _ in range(2):
                response = self.post_pdf(token=token)
                self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.source_snapshot(), before)

    def test_get_and_upload_do_not_flush_an_unrelated_pending_source_edit(self):
        self.add_job(self.add_day())
        token = self.csrf_token()
        job = db.session.get(Job, 1)
        job.notes = "Pending source edit must remain unsaved"
        with patch.object(db.session, "flush", side_effect=AssertionError("unexpected flush")):
            self.assertEqual(self.client.get(PREVIEW).status_code, 200)
            response = self.post_pdf(token=token)
            self.assertEqual(response.status_code, 200, response.text)
        self.assertIn(job, db.session.dirty)
        with db.session.no_autoflush:
            stored = db.session.execute(select(Job.__table__.c.notes)).scalar_one()
        self.assertEqual(stored, "")

    def test_report_and_original_bytes_are_not_persisted_in_the_session_or_returned_as_a_file(self):
        content = report_pdf()
        response = self.post_pdf(content)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn(content.decode("latin1"), response.text)
        self.assertNotIn(base64.b64encode(content).decode("ascii"), response.text)
        with self.client.session_transaction() as session:
            saved_session = json.dumps(dict(session))
        for value in ("Alice Example", "Ben Sample", "615.37", "706.38", "%PDF", "2026-09-25"):
            self.assertNotIn(value, saved_session)

    def test_review_edits_cannot_be_posted_to_a_payslip_saving_action(self):
        token = self.csrf_token()
        before = self.source_snapshot()
        response = self.client.post(PREVIEW, json={"driver_id": 1, "total_wage": "615.37"},
                                    headers={"X-CSRFToken": token})
        self.assertEqual(response.status_code, 405)
        response = self.client.post(READ, json={"driver_id": 1, "total_wage": "615.37"},
                                    headers={"X-CSRFToken": token})
        self.assertEqual(response.status_code, 415)
        self.assertEqual(self.source_snapshot(), before)
