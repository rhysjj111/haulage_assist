"""Silvey uploads parse in bounded children and return only complete reports."""

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from unittest import TestCase
from unittest.mock import patch

import owner_test_support  # Select the isolated test app before package imports.
from payroll_pdf_fixtures import text_pdf
from silvey_pdf_fixtures import invoice_pdf
from haulage_app.fuel import silvey_processing
from haulage_app.fuel.silvey_reader import SilveyPDFError, read_silvey_pdf


def report_payload():
    return {
        "sheet_name": "Silvey invoice", "header_row": 1,
        "source_format": "silvey-fuel-invoice-pdf-v1", "fuel_card_name": "Silvey",
        "document_kind": "pdf", "page_count": 2,
        "printed_total_quantity": "143.27", "printed_total_cost": "186.25",
        "rows": [{
            "source_row": 1, "source_page": 2,
            "transaction_date": "2027-02-09", "transaction_time": "06:12:00",
            "transaction_registration": "ZZ26 ABC", "card_registration": None,
            "card_type": "Silvey", "product": "DERV", "quantity": "143.27",
            "cost": "186.25", "unit_price": "1.3", "issues": [],
        }],
    }


class SilveyPDFProcessingTests(TestCase):
    def test_real_isolated_worker_preserves_direct_report_fields_pages_and_exact_totals(self):
        content = invoice_pdf()
        expected = read_silvey_pdf(content)
        actual = silvey_processing.read_silvey_pdf_isolated(content)
        self.assertEqual(actual, expected)
        self.assertEqual(actual.fuel_card_name, "Silvey")
        self.assertEqual(actual.document_kind, "pdf")
        self.assertEqual(actual.page_count, 2)
        self.assertEqual(actual.calculated_total_quantity, actual.printed_total_quantity)
        self.assertEqual(actual.calculated_total_cost, actual.printed_total_cost)
        self.assertTrue(all(row.source_page in (1, 2) for row in actual.rows))
        self.assertTrue(any("unsupported_product" in row.issues for row in actual.rows))

    def test_extraction_errors_keep_fixed_messages_without_source_values(self):
        documents = (
            (b"%PDF-1.7\nprivate-card-value ZZ26 ABC 186.25 broken", "invalid_pdf"),
            (text_pdf([["private-card-value"]], password="fictional-password"), "encrypted_pdf"),
            (text_pdf([[]]), "no_text"),
            (text_pdf([["private-card-value"]] * 21), "too_many_pages"),
            (text_pdf([["private-card-value"]]), "unsupported_layout"),
        )
        for content, code in documents:
            with self.subTest(code=code):
                with self.assertRaises(SilveyPDFError) as raised:
                    silvey_processing.read_silvey_pdf_isolated(content)
                self.assertEqual(raised.exception.code, code)
                for private in ("private-card-value", "ZZ26 ABC", "186.25", "Traceback"):
                    self.assertNotIn(private, str(raised.exception))

    def test_byte_type_magic_and_size_fail_before_a_child_starts(self):
        with patch.object(silvey_processing, "_run_worker") as launch:
            for content in (None, "PDF", b"invalid", b"PK\x03\x04"):
                with self.subTest(content_type=type(content).__name__):
                    with self.assertRaises(SilveyPDFError) as raised:
                        silvey_processing.read_silvey_pdf_isolated(content)
                    self.assertEqual(raised.exception.code, "invalid_pdf")
            with patch.object(silvey_processing, "MAX_PDF_BYTES", 4):
                with self.assertRaises(SilveyPDFError) as raised:
                    silvey_processing.read_silvey_pdf_isolated(b"%PDF-")
                self.assertEqual(raised.exception.code, "too_large")
            launch.assert_not_called()

    def assert_output_rejected(self, output):
        with patch.object(silvey_processing, "_run_worker", return_value=(0, output)):
            with self.assertRaises(silvey_processing.SilveyPDFProcessingError) as raised:
                silvey_processing.read_silvey_pdf_isolated(b"%PDF-")
        self.assertEqual(raised.exception.code, "processing_failed")
        self.assertNotIn("private-worker-value", str(raised.exception))

    def test_parent_rejects_invalid_json_unknown_errors_and_partial_report_output(self):
        for output in (b"private-worker-value", b"[]", b"null", b'{"error":[]}',
                       b'{"error":"private-worker-value"}',
                       b'{"error":"invalid_pdf","rows":[]}', b'{}'):
            with self.subTest(output=output):
                self.assert_output_rejected(output)
        with patch.object(silvey_processing, "MAX_OUTPUT_BYTES", 4):
            self.assert_output_rejected(b"too-long")

    def test_parent_validates_pages_dates_identity_decimal_precision_and_reconciled_totals(self):
        original = report_payload()
        invalid_rows = (
            ("source_row", True), ("source_row", 2), ("source_page", 0),
            ("source_page", True), ("source_page", 3),
            ("transaction_date", "2027-02-30"), ("transaction_date", "20270209"),
            ("transaction_time", "06:12:00+00:00"), ("transaction_time", 42),
            ("transaction_registration", []), ("card_type", "private-worker-value"),
            ("card_registration", "private-worker-value"), ("product", "x" * 201),
            ("quantity", "1.234"), ("cost", 186.25), ("cost", "NaN"),
            ("unit_price", "Infinity"), ("unit_price", "1E+9999999999999999999999999"),
            ("issues", ["private-worker-value"]), ("issues", ["unsupported_product"] * 2),
        )
        for field, value in invalid_rows:
            payload = deepcopy(original)
            payload["rows"][0][field] = value
            with self.subTest(field=field, value_type=type(value).__name__):
                self.assert_output_rejected(json.dumps(payload).encode())
        invalid_reports = (
            ("sheet_name", "Other report"), ("header_row", False), ("header_row", 7),
            ("source_format", "unknown"), ("fuel_card_name", "The Fuel Store"),
            ("document_kind", "xlsx"), ("page_count", False), ("page_count", 0),
            ("page_count", 21), ("printed_total_quantity", "143.28"),
            ("printed_total_cost", "186.24"), ("printed_total_cost", "186.250"),
            ("rows", []),
        )
        for field, value in invalid_reports:
            payload = deepcopy(original)
            payload[field] = value
            with self.subTest(field=field, value_type=type(value).__name__):
                self.assert_output_rejected(json.dumps(payload).encode())
        payload = deepcopy(original)
        payload["rows"] *= 2
        self.assert_output_rejected(json.dumps(payload).encode())

    def test_timeout_kills_and_reaps_a_real_sleeping_child(self):
        children = []
        real_popen = subprocess.Popen

        def track(*args, **kwargs):
            child = real_popen(*args, **kwargs)
            children.append(child)
            return child

        with tempfile.TemporaryDirectory(prefix="silvey-worker-test-") as directory:
            worker = Path(directory) / "slow.py"
            worker.write_text("import time\ntime.sleep(30)\n")
            started = time.monotonic()
            with patch.object(silvey_processing, "_WORKER", worker), \
                    patch.object(silvey_processing, "PROCESS_TIMEOUT_SECONDS", 0.05), \
                    patch.object(silvey_processing.subprocess, "Popen", side_effect=track):
                with self.assertRaises(silvey_processing.SilveyPDFProcessingError) as raised:
                    silvey_processing.read_silvey_pdf_isolated(b"%PDF-")
            self.assertLess(time.monotonic() - started, 3)
        self.assertEqual(raised.exception.code, "processing_timeout")
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].poll())

    def test_parent_output_cap_kills_a_chatty_child_before_buffering_unbounded_data(self):
        children = []
        real_popen = subprocess.Popen

        def track(*args, **kwargs):
            child = real_popen(*args, **kwargs)
            children.append(child)
            return child

        with tempfile.TemporaryDirectory(prefix="silvey-worker-test-") as directory:
            worker = Path(directory) / "chatty.py"
            worker.write_text("import sys\nwhile True: sys.stdout.buffer.write(b'x' * 65536)\n")
            with patch.object(silvey_processing, "_WORKER", worker), \
                    patch.object(silvey_processing, "MAX_OUTPUT_BYTES", 1024), \
                    patch.object(silvey_processing.subprocess, "Popen", side_effect=track):
                with self.assertRaises(silvey_processing.SilveyPDFProcessingError) as raised:
                    silvey_processing.read_silvey_pdf_isolated(b"%PDF-")
        self.assertEqual(raised.exception.code, "processing_failed")
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].poll())

    def test_sanitized_environment_drops_parent_credential_sentinel(self):
        with tempfile.TemporaryDirectory(prefix="silvey-worker-test-") as directory:
            worker = Path(directory) / "environment.py"
            worker.write_text(
                "import json, os, sys\n"
                "assert not os.environ.get('SILVEY_TEST_PRIVATE_SENTINEL')\n"
                "assert not any(k.startswith('haulage_app') for k in sys.modules)\n"
                "print(" + repr(json.dumps(report_payload())) + ")\n"
            )
            with patch.dict(os.environ, {"SILVEY_TEST_PRIVATE_SENTINEL": "synthetic-only"}), \
                    patch.object(silvey_processing, "_WORKER", worker):
                report = silvey_processing.read_silvey_pdf_isolated(b"%PDF-")
        self.assertEqual(report.rows[0].source_page, 2)

    def test_actual_worker_has_no_application_package_import(self):
        actual = silvey_processing._WORKER
        with tempfile.TemporaryDirectory(prefix="silvey-worker-test-") as directory:
            worker = Path(directory) / "no_application.py"
            worker.write_text(
                "import runpy, sys\n"
                "class BlockApp:\n"
                "    def find_spec(self, fullname, path=None, target=None):\n"
                "        if fullname == 'haulage_app' or fullname.startswith('haulage_app.'):\n"
                "            raise RuntimeError('unexpected app import')\n"
                "sys.meta_path.insert(0, BlockApp())\n"
                "sys.path.insert(0, " + repr(str(actual.parent)) + ")\n"
                "runpy.run_path(" + repr(str(actual)) + ", run_name='__main__')\n"
            )
            with patch.object(silvey_processing, "_WORKER", worker):
                actual_report = silvey_processing.read_silvey_pdf_isolated(invoice_pdf())
        self.assertEqual(actual_report, read_silvey_pdf(invoice_pdf()))

    def test_worker_fails_closed_without_resource_controls(self):
        actual = silvey_processing._WORKER
        with tempfile.TemporaryDirectory(prefix="silvey-worker-test-") as directory:
            worker = Path(directory) / "unsupported.py"
            worker.write_text(
                "import runpy, sys\n"
                "sys.path.insert(0, " + repr(str(actual.parent)) + ")\n"
                "scope = runpy.run_path(" + repr(str(actual)) + ")\n"
                "def fail(): raise RuntimeError('private-worker-value')\n"
                "scope['_main'].__globals__['_limit_resources'] = fail\n"
                "scope['_main']()\n"
            )
            with patch.object(silvey_processing, "_WORKER", worker):
                with self.assertRaises(silvey_processing.SilveyPDFProcessingError) as raised:
                    silvey_processing.read_silvey_pdf_isolated(b"%PDF-")
        self.assertEqual(raised.exception.code, "processing_failed")
