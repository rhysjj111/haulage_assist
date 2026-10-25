"""The shared upload dispatches only approved supplier/format combinations."""

from dataclasses import FrozenInstanceError
import json
from unittest import TestCase
from unittest.mock import patch

import owner_test_support  # Select the isolated app before package imports.
from fuel_xlsx_fixtures import transactions_xlsx
from haulage_app.fuel import import_profiles
from haulage_app.fuel.xlsx_reader import FuelXLSXError, read_fuel_store_transactions_xlsx
from haulage_app.fuel.xlsx_processing import FuelXLSXProcessingError


WORKER = "haulage_app.fuel.xlsx_processing.read_fuel_store_xlsx_isolated"


class FuelImportProfilesTests(TestCase):
    def test_supported_supplier_profiles_and_default_are_immutable(self):
        supplier = import_profiles.get_supplier()
        self.assertEqual(supplier.id, "the-fuel-store")
        self.assertEqual(import_profiles.DEFAULT_SUPPLIER_ID, supplier.id)
        self.assertEqual(supplier.label, "The Fuel Store")
        self.assertEqual(supplier.formats, ("xlsx",))
        self.assertEqual(supplier.source_formats, ("fuel-store-transactions-xlsx-v1",))
        self.assertIs(import_profiles.get_supplier("the-fuel-store"), supplier)
        silvey = import_profiles.get_supplier("silvey")
        self.assertEqual(silvey.label, "Silvey")
        self.assertEqual(silvey.formats, ("pdf",))
        self.assertEqual(silvey.source_formats, ("silvey-fuel-invoice-pdf-v1",))
        self.assertIn("DERV", silvey.diesel_products)
        self.assertNotIn("ADBLUE", silvey.diesel_products)
        with self.assertRaises(FrozenInstanceError):
            supplier.label = "Other supplier"

    def test_public_metadata_is_safe_json_and_mutating_it_does_not_change_registry(self):
        choices = import_profiles.supplier_choices()
        self.assertEqual({choice["id"] for choice in choices}, {"the-fuel-store", "silvey"})
        self.assertEqual(set(choices[0]), {"id", "label", "help_text", "formats", "source_formats", "diesel_products"})
        self.assertEqual(json.loads(json.dumps(choices)), choices)
        self.assertNotIn("pdf", choices[0]["formats"])
        choices[0]["formats"].append("pdf")
        choices[0]["source_formats"].clear()
        choices[0]["label"] = "Other supplier"
        self.assertEqual(import_profiles.supplier_choices()[0]["formats"], ["xlsx"])
        self.assertEqual(import_profiles.get_supplier().label, "The Fuel Store")
        self.assertEqual(import_profiles.get_supplier().source_formats,
                         ("fuel-store-transactions-xlsx-v1",))

    def test_explicit_missing_unknown_or_wrong_type_supplier_is_not_guessed(self):
        invalid = ("", " ", "THE-FUEL-STORE", "the-fuel-store ", "The Fuel Store",
                   "unknown-supplier", "private-account-value", 1, True, [], {})
        for value in invalid:
            with self.subTest(value_type=type(value).__name__), patch(WORKER) as worker:
                with self.assertRaises(import_profiles.FuelDocumentError) as raised:
                    import_profiles.read_fuel_document(b"PK\x03\x04", value)
                self.assertEqual(raised.exception.code, "supplier_unavailable")
                self.assertEqual(raised.exception.status, 400)
                self.assertNotIn("private-account-value", str(raised.exception))
                worker.assert_not_called()

    def test_real_spreadsheet_dispatch_preserves_the_complete_existing_reader_result(self):
        content = transactions_xlsx()
        expected = read_fuel_store_transactions_xlsx(content)
        self.assertEqual(import_profiles.read_fuel_document(content), expected)
        self.assertEqual(import_profiles.read_fuel_document(content, "the-fuel-store"), expected)

    def test_dispatch_uses_document_bytes_without_an_extension_or_mime_parameter(self):
        sentinel = object()
        with patch(WORKER, return_value=sentinel) as worker:
            self.assertIs(import_profiles.read_fuel_document(b"PK\x03\x04synthetic"), sentinel)
        worker.assert_called_once_with(b"PK\x03\x04synthetic")

    def test_pdf_is_identified_but_is_never_sent_to_the_spreadsheet_worker(self):
        for content in (b"%PDF-1.7\nprivate-source-value", b" \r\n%PDF-1.7\nprivate-source-value"):
            with self.subTest(prefix=content[:5]), patch(WORKER) as worker:
                with self.assertRaises(import_profiles.FuelDocumentError) as raised:
                    import_profiles.read_fuel_document(content)
                self.assertEqual(raised.exception.code, "format_unavailable")
                self.assertEqual(raised.exception.status, 422)
                self.assertTrue(str(raised.exception))
                self.assertNotIn("private-source-value", str(raised.exception))
                worker.assert_not_called()

    def test_invalid_documents_and_wrong_types_fail_without_parser_or_content_echo(self):
        invalid = (None, "PK\x03\x04private-source-value", bytearray(b"PK\x03\x04"), b"",
                   b"private-source-value", b"\x89PNG\r\n\x1a\nprivate-source-value",
                   b"\xd0\xcf\x11\xe0private-source-value")
        for content in invalid:
            with self.subTest(content_type=type(content).__name__), patch(WORKER) as worker:
                with self.assertRaises(import_profiles.FuelDocumentError) as raised:
                    import_profiles.read_fuel_document(content)
                self.assertEqual(raised.exception.code, "invalid_document")
                self.assertEqual(raised.exception.status, 422)
                self.assertNotIn("private-source-value", str(raised.exception))
                worker.assert_not_called()

    def test_size_cap_applies_before_sniffing_either_document_kind(self):
        with patch.object(import_profiles, "MAX_DOCUMENT_BYTES", 8), patch(WORKER) as worker:
            for content in (b"PK\x03\x04" + b"x" * 9, b"%PDF-1.7" + b"x" * 9,
                            b"invalid" + b"x" * 9):
                with self.subTest(prefix=content[:4]):
                    with self.assertRaises(import_profiles.FuelDocumentError) as raised:
                        import_profiles.read_fuel_document(content)
                    self.assertEqual(raised.exception.code, "too_large")
                    self.assertEqual(raised.exception.status, 413)
            worker.assert_not_called()

    def test_invalid_zip_still_uses_the_existing_bounded_reader_validation(self):
        with self.assertRaises(FuelXLSXError) as raised:
            import_profiles.read_fuel_document(b"PK\x03\x04private-not-a-real-workbook")
        self.assertEqual(raised.exception.code, "invalid_workbook")
        self.assertNotIn("private-not-a-real-workbook", str(raised.exception))

    def test_worker_input_and_resource_errors_preserve_their_fixed_codes(self):
        for error in (FuelXLSXError("invalid_transaction"), FuelXLSXProcessingError("processing_timeout")):
            with self.subTest(error_type=type(error).__name__), patch(WORKER, side_effect=error):
                with self.assertRaises(type(error)) as raised:
                    import_profiles.read_fuel_document(b"PK\x03\x04")
                self.assertIs(raised.exception, error)
