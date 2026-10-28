"""Fuel spreadsheet uploads propose editable rows without saving business data."""

import base64
from datetime import datetime
from html.parser import HTMLParser
import json
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from owner_test_support import OwnerTestCase, db
from fuel_xlsx_fixtures import TRANSACTIONS, transaction, transactions_xlsx
from haulage_app.models import Job
from haulage_app.fuel.xlsx_reader import (
    MAX_XLSX_BYTES, FuelXLSXError, read_fuel_store_transactions_xlsx,
)


PREVIEW = "/fuel/import"
READ = "/fuel/import/read"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
WORKER = "haulage_app.fuel.xlsx_processing.read_fuel_store_xlsx_isolated"


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


class FuelImportPreviewTests(OwnerTestCase):
    def setUp(self):
        super().setUp()
        self.app.config["WTF_CSRF_ENABLED"] = True
        self.add_truck(registration="ZZ26 ABC")

    def csrf_token(self):
        _, context = self.get_page(PREVIEW)
        token = context["csrf_token"]
        self.assertIsInstance(token, str)
        self.assertTrue(token)
        return token

    def post_xlsx(self, content=None, *, token=None, content_type=XLSX_MIME,
                  **kwargs):
        if token is None:
            token = self.csrf_token()
        return self.client.post(
            READ, data=transactions_xlsx() if content is None else content,
            content_type=content_type, headers={"X-CSRFToken": token}, **kwargs,
        )

    def preview_rows(self, rows):
        content = transactions_xlsx(rows=rows)
        report = read_fuel_store_transactions_xlsx(content)
        token = self.csrf_token()
        with patch(WORKER, return_value=report):
            response = self.post_xlsx(content, token=token)
        self.assertEqual(response.status_code, 200, response.text)
        return response.get_json()

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

    def test_upload_page_has_one_document_picker_and_csrf_without_a_fuel_save_form(self):
        response, context = self.get_page(PREVIEW)
        parsed = _PreviewHTML(response.text)
        file_inputs = [field for field in parsed.inputs if field.get("type") == "file"]
        self.assertEqual(len(file_inputs), 1)
        self.assertIn(".xlsx", file_inputs[0].get("accept", ""))
        self.assertIn(".pdf", file_inputs[0].get("accept", ""))
        self.assertIsInstance(context["csrf_token"], str)
        self.assertEqual(context["read_url"], READ)
        self.assertIn("Import fuel", response.text)
        self.assertFalse(any("add_fuel" in form.get("action", "")
                             or "edit_fuel" in form.get("action", "")
                             or "save" in form.get("action", "")
                             for form in parsed.forms))
        self.assert_private_response(response)

    def test_manual_fuel_page_links_to_the_spreadsheet_preview(self):
        response = self.client.get("/fuel/add_fuel/0/entry")
        self.assertEqual(response.status_code, 200)
        self.assertIn('href="' + PREVIEW + '"', response.text)

    def test_real_worker_returns_source_rows_dates_times_and_exact_displayed_amounts(self):
        response = self.post_xlsx()
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.get_json()
        self.assertEqual(payload["report"], {
            "supplier_id": "the-fuel-store",
            "source_format": "fuel-store-transactions-xlsx-v1",
            "fuel_card_name": "The Fuel Store",
            "sheet_name": "Transactions", "header_row": 7, "transaction_count": 2,
            "totals": {"quantity": "354.35", "cost": "460.65"},
        })
        self.assertEqual(payload["trucks"], [{"id": 1, "registration": "ZZ26 ABC"}])
        self.assertEqual(payload["rows"][0], {
            "source_row": 8,
            "transaction_date": "2027-02-09", "transaction_time": "06:12:34",
            "transaction_registration": "ZZ26 ABC", "card_registration": "ZZ26 ABC",
            "card_type": "FUEL STORE", "product": "KEYFUELS DIESEL",
            "quantity": "143.27", "cost": "186.25", "unit_price": "1.3",
            "issues": [], "truck_id": 1, "match_status": "matched",
            "candidate_truck_ids": [1],
        })
        second = payload["rows"][1]
        self.assertEqual(second["source_row"], 9)
        self.assertEqual(second["transaction_date"], "2027-02-10")
        self.assertEqual(second["quantity"], "211.08")
        self.assertEqual(second["cost"], "274.40")
        self.assertEqual(second["match_status"], "unmatched")
        self.assertIsNone(second["truck_id"])
        self.assert_private_response(response)

    def test_matching_ignores_registration_case_and_spaces_but_does_not_guess(self):
        payload = self.preview_rows((
            transaction({"Tran VRN": "ZZ26ABC", "Card VRN": "  zz26abc  "}),
            transaction({"Tran VRN": "ZZ26 ABC", "Card VRN": "ZZ26 ABD"}),
        ))
        exact, near = payload["rows"]
        self.assertEqual((exact["truck_id"], exact["match_status"]), (1, "matched"))
        self.assertEqual(exact["candidate_truck_ids"], [1])
        self.assertIsNone(near["truck_id"])
        self.assertEqual(near["match_status"], "unmatched")
        self.assertEqual(near["candidate_truck_ids"], [])

    def test_ambiguous_normalized_registrations_require_an_explicit_truck_choice(self):
        self.add_truck(2, registration="ZZ26ABC")
        self.add_truck(3, registration="ZX26 DEF")
        payload = self.preview_rows((transaction({"Tran VRN": "ZX26 DEF"}),))
        row = payload["rows"][0]
        self.assertEqual(row["match_status"], "ambiguous")
        self.assertIsNone(row["truck_id"])
        self.assertCountEqual(row["candidate_truck_ids"], [1, 2])
        self.assertIn("registration_mismatch", row["issues"])

    def test_unmatched_card_does_not_fall_back_to_an_exact_transaction_match(self):
        payload = self.preview_rows((transaction({"Card VRN": "ZX26 DEF"}),))
        row = payload["rows"][0]
        self.assertEqual(row["match_status"], "unmatched")
        self.assertIsNone(row["truck_id"])
        self.assertEqual(row["candidate_truck_ids"], [])
        self.assertIn("registration_mismatch", row["issues"])
        self.assertEqual(row["card_registration"], "ZX26 DEF")
        self.assertEqual(row["transaction_registration"], "ZZ26 ABC")

    def test_card_match_survives_missing_transaction_registration_with_source_warning(self):
        payload = self.preview_rows((transaction({"Tran VRN": None}),))
        row = payload["rows"][0]
        self.assertEqual((row["truck_id"], row["match_status"]), (1, "matched"))
        self.assertEqual(row["candidate_truck_ids"], [1])
        self.assertIn("missing_transaction_registration", row["issues"])
        self.assertEqual(row["card_registration"], "ZZ26 ABC")
        self.assertIsNone(row["transaction_registration"])

    def test_missing_card_registration_requires_manual_mapping_without_transaction_fallback(self):
        for missing in (None, "   "):
            with self.subTest(card_registration=missing):
                row = self.preview_rows((transaction({"Card VRN": missing}),))["rows"][0]
                self.assertEqual(row["match_status"], "missing_registration")
                self.assertIsNone(row["truck_id"])
                self.assertEqual(row["candidate_truck_ids"], [])
                self.assertEqual(row["transaction_registration"], "ZZ26 ABC")

    def test_card_registration_wins_when_transaction_names_another_truck_or_has_a_typo(self):
        self.add_truck(2, registration="ZX26 DEF")
        before = self.source_snapshot()
        payload = self.preview_rows((
            transaction({"Tran VRN": "ZX26 DEF"}),
            transaction({"Tran VRN": "ZZ26 ABD"}),
        ))
        self.assertEqual([row["transaction_registration"] for row in payload["rows"]],
                         ["ZX26 DEF", "ZZ26 ABD"])
        for row in payload["rows"]:
            self.assertEqual((row["truck_id"], row["match_status"]), (1, "matched"))
            self.assertEqual(row["candidate_truck_ids"], [1])
            self.assertEqual(row["card_registration"], "ZZ26 ABC")
            self.assertIn("registration_mismatch", row["issues"])
        self.assertEqual(self.source_snapshot(), before)

    def test_network_labels_do_not_change_the_confirmed_fuel_store_supplier(self):
        rows = tuple(transaction({"Card Type": label})
                     for label in ("ESSO", "SHELL CRT", "UK FUELS", "FUEL STORE"))
        payload = self.preview_rows(rows)
        self.assertEqual(payload["report"]["fuel_card_name"], "The Fuel Store")
        self.assertEqual([row["card_type"] for row in payload["rows"]],
                         ["ESSO", "SHELL CRT", "UK FUELS", "FUEL STORE"])

    def test_source_issues_repeated_purchases_and_different_weeks_are_not_dropped(self):
        rows = (
            TRANSACTIONS[0], TRANSACTIONS[0],
            transaction({"Date": datetime(2027, 3, 1, 10, 0),
                         "Product": "ADBLUE", "Quantity": -5, "Cost": -6.50}),
        )
        payload = self.preview_rows(rows)
        self.assertEqual(payload["report"]["transaction_count"], 3)
        self.assertEqual([row["source_row"] for row in payload["rows"]], [8, 9, 10])
        self.assertEqual([row["transaction_date"] for row in payload["rows"]],
                         ["2027-02-09", "2027-02-09", "2027-03-01"])
        last = payload["rows"][-1]
        self.assertEqual(last["quantity"], "-5.00")
        self.assertEqual(last["cost"], "-6.50")
        self.assertCountEqual(last["issues"],
                              ["unsupported_product", "non_positive_quantity", "non_positive_cost"])

    def test_excluded_card_driver_site_and_odometer_columns_are_not_returned(self):
        response = self.post_xlsx()
        self.assertEqual(response.status_code, 200, response.text)
        for value in ("FICTIONAL-CARD-0001", "Fictional Driver One", "Fictional depot",
                      "Fictional service station", "FAKE-01", "123456"):
            self.assertNotIn(value, response.text)

    def test_missing_or_invalid_csrf_is_rejected_before_processing(self):
        self.csrf_token()
        with patch(WORKER) as worker:
            for headers in ({}, {"X-CSRFToken": "invalid-csrf-token"}):
                with self.subTest(has_header=bool(headers)):
                    response = self.client.post(READ, data=transactions_xlsx(),
                                                content_type=XLSX_MIME, headers=headers)
                    self.assertEqual(response.status_code, 403)
                    self.assertEqual(response.get_json()["error"]["code"], "csrf_failed")
                    self.assert_private_response(response)
            worker.assert_not_called()

    def test_other_content_types_are_rejected_without_parsing_a_form_or_file(self):
        token = self.csrf_token()
        with patch(WORKER) as worker:
            for content_type in ("application/json", "text/plain", "multipart/form-data",
                                 "image/png", "application/vnd.ms-excel"):
                with self.subTest(content_type=content_type):
                    response = self.post_xlsx(b"private-body", token=token,
                                               content_type=content_type)
                    self.assertEqual(response.status_code, 415)
                    self.assertEqual(response.get_json()["error"]["code"],
                                     "unsupported_media_type")
                    self.assert_private_response(response)
            worker.assert_not_called()

    def test_oversize_upload_is_rejected_before_worker_processing(self):
        token = self.csrf_token()
        with patch(WORKER) as worker:
            response = self.post_xlsx(b"PK\x03\x04" + b" " * MAX_XLSX_BYTES, token=token)
            self.assertEqual(response.status_code, 413)
            self.assertEqual(response.get_json()["error"]["code"], "too_large")
            self.assert_private_response(response)
            worker.assert_not_called()

    def test_body_limit_also_applies_when_the_server_reports_no_content_length(self):
        token = self.csrf_token()
        with patch(WORKER) as worker:
            response = self.post_xlsx(
                b"PK\x03\x04" + b" " * MAX_XLSX_BYTES, token=token,
                environ_overrides={"CONTENT_LENGTH": "", "wsgi.input_terminated": True},
            )
            self.assertEqual(response.status_code, 413, response.text)
            self.assertEqual(response.get_json()["error"]["code"], "too_large")
            self.assert_private_response(response)
            worker.assert_not_called()

    def test_unreadable_workbook_has_a_safe_error_without_source_values(self):
        response = self.post_xlsx(b"PK\x03\x04private-card-value ZZ26 ABC 186.25 broken")
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.get_json()["error"]["code"], "invalid_workbook")
        for value in ("private-card-value", "ZZ26 ABC", "186.25", "Traceback"):
            self.assertNotIn(value, response.text)
        self.assertNotIn("rows", response.get_json())
        self.assert_private_response(response)

    def test_reader_error_codes_are_safely_mapped_without_partial_rows(self):
        token = self.csrf_token()
        for code, status in (("too_large", 413), ("unsupported_layout", 422),
                             ("unsupported_precision", 422), ("formula_not_supported", 422),
                             ("reader_unavailable", 503)):
            with self.subTest(code=code), patch(WORKER, side_effect=FuelXLSXError(code)):
                response = self.post_xlsx(token=token)
                self.assertEqual(response.status_code, status, response.text)
                self.assertEqual(response.get_json()["error"]["code"], code)
                self.assertNotIn("rows", response.get_json())
                self.assert_private_response(response)

    def test_worker_failures_have_service_errors_and_no_source_details(self):
        from haulage_app.fuel.xlsx_processing import FuelXLSXProcessingError

        token = self.csrf_token()
        for code in ("processing_timeout", "processing_failed"):
            with self.subTest(code=code), patch(WORKER, side_effect=FuelXLSXProcessingError(code)):
                response = self.post_xlsx(token=token)
                self.assertEqual(response.status_code, 503, response.text)
                self.assertEqual(response.get_json()["error"]["code"], code)
                self.assertNotIn("rows", response.get_json())
                self.assert_private_response(response)

    def test_failed_truck_lookup_does_not_echo_sql_or_return_incomplete_choices(self):
        token = self.csrf_token()
        report = read_fuel_store_transactions_xlsx(transactions_xlsx())
        with patch(WORKER, return_value=report), \
                patch.object(db.session, "query", side_effect=SQLAlchemyError(
                    "private SQL parameters ZZ26 ABC 186.25")):
            response = self.post_xlsx(token=token)
        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(response.get_json()["error"]["code"], "preview_unavailable")
        self.assertNotIn("rows", response.get_json())
        for value in ("private SQL", "ZZ26 ABC", "186.25", "Traceback"):
            self.assertNotIn(value, response.text)
        self.assert_private_response(response)

    def test_unexpected_failure_is_sanitized_without_a_traceback_or_source_values(self):
        token = self.csrf_token()
        with patch(WORKER, side_effect=RuntimeError("private-worker-value ZZ26 ABC 186.25")):
            response = self.post_xlsx(token=token)
        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(response.get_json()["error"]["code"], "processing_failed")
        for value in ("private-worker-value", "ZZ26 ABC", "186.25", "RuntimeError", "Traceback"):
            self.assertNotIn(value, response.text)
        self.assert_private_response(response)

    def test_repeated_preview_requests_never_write_business_rows_or_archive_uploads(self):
        self.add_driver()
        self.add_job(self.add_day())
        self.add_payslip(total_wage=54321, total_cost_to_employer=65432)
        self.add_fuel(fuel_card_name="The Fuel Store", fuel_volume=10000, fuel_cost=13000)
        token = self.csrf_token()
        before = self.source_snapshot()
        content = transactions_xlsx()
        report = read_fuel_store_transactions_xlsx(content)
        with patch(WORKER, return_value=report), \
                patch.object(db.session, "add", side_effect=AssertionError("unexpected add")), \
                patch.object(db.session, "add_all", side_effect=AssertionError("unexpected add_all")), \
                patch.object(db.session, "commit", side_effect=AssertionError("unexpected commit")), \
                patch("werkzeug.datastructures.FileStorage.save",
                      side_effect=AssertionError("unexpected document archive")), \
                patch("tempfile.TemporaryFile", side_effect=AssertionError("unexpected temp file")), \
                patch("tempfile.NamedTemporaryFile", side_effect=AssertionError("unexpected temp file")):
            self.assertEqual(self.client.get(PREVIEW).status_code, 200)
            for _ in range(2):
                response = self.post_xlsx(content, token=token)
                self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.source_snapshot(), before)

    def test_get_and_upload_do_not_flush_a_pending_unrelated_edit(self):
        self.add_driver()
        self.add_job(self.add_day())
        token = self.csrf_token()
        job = db.session.get(Job, 1)
        job.notes = "Pending source edit must remain unsaved"
        content = transactions_xlsx()
        report = read_fuel_store_transactions_xlsx(content)
        with patch(WORKER, return_value=report), \
                patch.object(db.session, "flush", side_effect=AssertionError("unexpected flush")):
            self.assertEqual(self.client.get(PREVIEW).status_code, 200)
            response = self.post_xlsx(content, token=token)
            self.assertEqual(response.status_code, 200, response.text)
        self.assertIn(job, db.session.dirty)
        with db.session.no_autoflush:
            stored = db.session.execute(select(Job.__table__.c.notes)).scalar_one()
        self.assertEqual(stored, "")

    def test_original_bytes_and_review_draft_are_not_persisted_in_the_session(self):
        content = transactions_xlsx()
        response = self.post_xlsx(content)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn(base64.b64encode(content).decode("ascii"), response.text)
        with self.client.session_transaction() as session:
            saved_session = json.dumps(dict(session))
        for value in ("ZZ26 ABC", "ZX26 DEF", "143.27", "186.25", "FICTIONAL-CARD",
                      "Fictional Driver One", "2027-02-09", "KEYFUELS DIESEL"):
            self.assertNotIn(value, saved_session)

    def test_review_edits_cannot_be_saved_through_the_preview_or_reader(self):
        token = self.csrf_token()
        before = self.source_snapshot()
        edited = {"truck_id": 1, "date": "2027-02-09", "quantity": "143.27", "cost": "186.25"}
        response = self.client.post(PREVIEW, json=edited, headers={"X-CSRFToken": token})
        self.assertEqual(response.status_code, 405)
        response = self.client.post(READ, json=edited, headers={"X-CSRFToken": token})
        self.assertEqual(response.status_code, 415)
        response = self.client.post("/fuel/import/save", json=edited,
                                    headers={"X-CSRFToken": token})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.source_snapshot(), before)
