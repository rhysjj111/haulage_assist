"""Automatic fuel detection reports evidence strength without guessing an issuer."""

from dataclasses import replace
from io import BytesIO
from unittest.mock import patch

from pypdf import PdfWriter
from sqlalchemy import select

from owner_test_support import OwnerTestCase, db
from fuel_xlsx_fixtures import transaction, transactions_xlsx
from payroll_pdf_fixtures import report_pdf, text_pdf
from silvey_pdf_fixtures import invoice_pages, invoice_pdf
from haulage_app.fuel import import_profiles
from haulage_app.fuel.silvey_reader import SilveyPDFError
from haulage_app.fuel.xlsx_reader import FuelXLSXError, read_fuel_store_transactions_xlsx


READ = "/fuel/import/read"
XLSX_WORKER = "haulage_app.fuel.xlsx_processing.read_fuel_store_xlsx_isolated"
PDF_WORKER = "haulage_app.fuel.silvey_processing.read_silvey_pdf_isolated"
CHECKER = "haulage_app.fuel.import_checks.check_fuel_for_preview"
SAVER = "haulage_app.fuel.import_save.save_reviewed_fuel"


class FuelSupplierDetectionTests(OwnerTestCase):
    def setUp(self):
        super().setUp()
        self.app.config["WTF_CSRF_ENABLED"] = True
        self.add_truck(registration="ZZ26 ABC")

    def token(self):
        return self.get_page("/fuel/import")[1]["csrf_token"]

    def read(self, content, *, supplier="auto", mimetype="application/octet-stream", token=None, **kwargs):
        headers = {"X-CSRFToken": token or self.token()}
        if supplier is not None:
            headers["X-Fuel-Supplier"] = supplier
        return self.client.post(READ, data=content, content_type=mimetype, headers=headers, **kwargs)

    def assert_private(self, response):
        self.assertIn("no-store", response.headers.get("Cache-Control", ""))
        self.assertEqual(response.headers.get("Pragma"), "no-cache")
        self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")

    def snapshot(self):
        with db.session.no_autoflush:
            return {name: [tuple(row) for row in db.session.execute(
                select(table).order_by(*table.primary_key.columns))]
                for name, table in db.metadata.tables.items()}

    def test_auto_is_a_page_default_not_a_financial_supplier(self):
        _, context = self.get_page("/fuel/import")
        self.assertEqual(context["default_supplier_id"], "auto")
        self.assertNotIn("auto", {profile["id"] for profile in context["supplier_profiles"]})
        with self.assertRaises(import_profiles.FuelDocumentError) as raised:
            import_profiles.get_supplier("auto")
        self.assertEqual(raised.exception.code, "supplier_unavailable")
        self.assertEqual(import_profiles.get_supplier().id, "the-fuel-store")

    def test_real_silvey_identity_is_detected_only_after_reconciled_pdf_parsing(self):
        before = self.snapshot()
        response = self.read(invoice_pdf())
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.get_json()
        self.assertEqual(payload["report"]["supplier_id"], "silvey")
        self.assertEqual(payload["report"]["fuel_card_name"], "Silvey")
        self.assertEqual(payload["report"]["transaction_count"], 6)
        self.assertEqual(payload["report"]["printed_totals"], payload["report"]["totals"])
        self.assertEqual(payload["detection"], {"method": "document_identity", "requires_confirmation": False})
        self.assertEqual(self.snapshot(), before)
        self.assert_private(response)

    def test_spreadsheet_schema_only_suggests_fuel_store_and_requires_confirmation(self):
        response = self.read(transactions_xlsx())
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.get_json()
        self.assertEqual(payload["report"]["supplier_id"], "the-fuel-store")
        self.assertEqual(payload["report"]["source_format"], "fuel-store-transactions-xlsx-v1")
        self.assertEqual(payload["detection"], {"method": "layout_only", "requires_confirmation": True})
        self.assert_private(response)

    def test_card_network_labels_do_not_prove_or_change_the_spreadsheet_issuer(self):
        content = transactions_xlsx(rows=tuple(transaction({"Card Type": network})
                                               for network in ("SILVEY", "ESSO", "SHELL CRT", "UK FUELS")))
        response = self.read(content)
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.get_json()
        self.assertEqual(payload["report"]["supplier_id"], "the-fuel-store")
        self.assertEqual(payload["detection"], {"method": "layout_only", "requires_confirmation": True})
        self.assertEqual([row["card_type"] for row in payload["rows"]],
                         ["SILVEY", "ESSO", "SHELL CRT", "UK FUELS"])

    def test_transport_mime_does_not_prove_supplier_or_format(self):
        cases = ((invoice_pdf(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "silvey", False),
                 (transactions_xlsx(), "application/pdf", "the-fuel-store", True))
        token = self.token()
        for content, mimetype, supplier, confirmation in cases:
            with self.subTest(mimetype=mimetype):
                response = self.read(content, mimetype=mimetype, token=token)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.get_json()["report"]["supplier_id"], supplier)
                self.assertIs(response.get_json()["detection"]["requires_confirmation"], confirmation)

    def test_explicit_supplier_and_omitted_legacy_header_stay_manual(self):
        token = self.token()
        for supplier, content, canonical in (("silvey", invoice_pdf(), "silvey"),
                                              ("the-fuel-store", transactions_xlsx(), "the-fuel-store"),
                                              (None, transactions_xlsx(), "the-fuel-store")):
            with self.subTest(supplier=supplier):
                response = self.read(content, supplier=supplier, token=token)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.get_json()["report"]["supplier_id"], canonical)
                self.assertEqual(response.get_json()["detection"],
                                 {"method": "manual", "requires_confirmation": False})

    def test_manual_mismatches_do_not_fall_back_to_another_reader(self):
        for supplier, content in (("silvey", transactions_xlsx()), ("the-fuel-store", invoice_pdf())):
            with self.subTest(supplier=supplier):
                response = self.read(content, supplier=supplier)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(response.get_json()["error"]["code"], "format_unavailable")
                self.assertNotIn("detection", response.get_json())
                self.assertNotIn("rows", response.get_json())

    def test_unknown_bytes_and_unsupported_layouts_fail_without_identity_or_private_echo(self):
        pages = [page.replace("Silvey Fleet Ltd", "Fictional Other Supplier")
                 .replace("www.silveyfleet.co.uk", "www.fictional.invalid") for page in invoice_pages()]
        unbranded = text_pdf([page.splitlines() for page in pages])
        content_cases = (b"private-source-value", report_pdf(), unbranded,
                         transactions_xlsx(sheet_name="Other layout"))
        before = self.snapshot()
        for content in content_cases:
            with self.subTest(length=len(content)):
                response = self.read(content)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(response.get_json()["error"]["code"], "supplier_not_recognised")
                self.assertNotIn("rows", response.get_json())
                self.assertNotIn("detection", response.get_json())
                for private in ("private-source-value", "Fictional Other Supplier", "Alice Example", "ZZ26 ABC"):
                    self.assertNotIn(private, response.text)
                self.assert_private(response)
        self.assertEqual(self.snapshot(), before)

    def test_reconciliation_incomplete_and_amount_errors_keep_their_diagnostic_codes(self):
        token = self.token()
        for worker, content, error in (
            (PDF_WORKER, invoice_pdf(), SilveyPDFError("incomplete_transactions")),
            (PDF_WORKER, invoice_pdf(), SilveyPDFError("reconciliation_failed")),
            (XLSX_WORKER, transactions_xlsx(), FuelXLSXError("invalid_transaction")),
            (XLSX_WORKER, transactions_xlsx(), FuelXLSXError("unsupported_precision")),
        ):
            with self.subTest(code=error.code), patch(worker, side_effect=error):
                response = self.read(content, token=token)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(response.get_json()["error"]["code"], error.code)
                self.assertNotIn("rows", response.get_json())
                self.assertNotIn("detection", response.get_json())

    def test_real_bad_totals_protected_and_image_only_pdfs_never_produce_detection(self):
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        stream = BytesIO()
        writer.write(stream)
        for content, code in ((invoice_pdf(grand_total="999.99"), "reconciliation_failed"),
                              (invoice_pdf(password="fictional-password"), "encrypted_pdf"),
                              (stream.getvalue(), "no_text")):
            with self.subTest(code=code):
                response = self.read(content)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(response.get_json()["error"]["code"], code)
                self.assertNotIn("detection", response.get_json())
                self.assertNotIn("fictional-password", response.text)

    def test_auto_reader_result_identity_is_validated_before_database_lookup(self):
        report = read_fuel_store_transactions_xlsx(transactions_xlsx())
        token = self.token()
        for altered in (replace(report, fuel_card_name="Fictional other supplier"),
                        replace(report, source_format="unsupported-source-layout")):
            with self.subTest(format=altered.source_format), patch(XLSX_WORKER, return_value=altered), \
                    patch.object(db.session, "query", side_effect=AssertionError("unexpected lookup")):
                response = self.read(transactions_xlsx(), token=token)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(response.get_json()["error"]["code"], "supplier_not_recognised")
                self.assertNotIn("Fictional other supplier", response.text)

    def test_auto_is_rejected_for_check_and_save_before_mutation_or_json_decoding(self):
        token = self.token()
        before = self.snapshot()
        with patch(CHECKER) as checker, patch(SAVER) as saver, \
                patch.object(db.session, "query", side_effect=AssertionError("unexpected query")), \
                patch.object(db.session, "commit", side_effect=AssertionError("unexpected commit")):
            for endpoint in ("/fuel/import/check", "/fuel/import/save"):
                response = self.client.post(endpoint, data=b"private-malformed-json", content_type="application/json",
                                            headers={"X-CSRFToken": token, "X-Fuel-Supplier": "auto"})
                self.assertEqual(response.status_code, 400, response.text)
                self.assertEqual(response.get_json()["error"]["code"], "supplier_unavailable")
                self.assertNotIn("private-malformed-json", response.text)
                self.assert_private(response)
            checker.assert_not_called()
            saver.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_csrf_and_raw_size_limits_precede_auto_reader_calls(self):
        token = self.token()
        with patch("haulage_app.fuel.import_routes.detect_fuel_document") as detector:
            response = self.client.post(READ, data=b"private-value", content_type="application/octet-stream",
                                        headers={"X-CSRFToken": "invalid", "X-Fuel-Supplier": "auto"})
            self.assertEqual(response.status_code, 403)
            self.assert_private(response)
            with patch("haulage_app.fuel.import_routes.MAX_DOCUMENT_BYTES", 8):
                for extra in ({}, {"environ_overrides": {"CONTENT_LENGTH": "", "wsgi.input_terminated": True}}):
                    response = self.read(b"%PDF-1.7\nprivate-value", token=token, **extra)
                    self.assertEqual(response.status_code, 413, response.text)
                    self.assert_private(response)
            detector.assert_not_called()

    def test_auto_read_preserves_all_records_and_pending_edits_without_archiving(self):
        token = self.token()
        before = self.snapshot()
        with patch.object(db.session, "add", side_effect=AssertionError("unexpected add")), \
                patch.object(db.session, "commit", side_effect=AssertionError("unexpected commit")), \
                patch.object(db.session, "flush", side_effect=AssertionError("unexpected flush")), \
                patch("werkzeug.datastructures.FileStorage.save", side_effect=AssertionError("unexpected archive")):
            for content in (invoice_pdf(), transactions_xlsx()):
                response = self.read(content, token=token)
                self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.snapshot(), before)
