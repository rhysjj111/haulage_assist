"""The upload worker isolates parsing and rejects unsafe or oversized results."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from unittest import TestCase
from unittest.mock import patch

import owner_test_support  # Select the isolated test app before package imports.
from payroll_pdf_fixtures import report_pdf
from haulage_app.payslip import pdf_processing, pdf_reader
from haulage_app.payslip.pdf_reader import PayrollPDFError, read_payroll_pdf


class PayslipPDFProcessingTests(TestCase):
    def assert_processing_failed(self, output):
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout=output)
        with patch.object(pdf_processing.subprocess, "run", return_value=result):
            with self.assertRaises(PayrollPDFError) as raised:
                pdf_processing.read_payroll_pdf_isolated(report_pdf())
        self.assertEqual(raised.exception.code, "processing_failed")
        self.assertNotIn("private-worker-value", str(raised.exception))

    def test_isolated_worker_preserves_the_complete_direct_reader_result(self):
        content = report_pdf()
        expected = read_payroll_pdf(content)
        actual = pdf_processing.read_payroll_pdf_isolated(content)
        self.assertEqual(actual, expected)

    def test_wall_timeout_kills_and_reaps_a_real_sleeping_child(self):
        real_popen = subprocess.Popen
        children = []

        def track_child(*args, **kwargs):
            child = real_popen(*args, **kwargs)
            children.append(child)
            return child

        with tempfile.TemporaryDirectory(prefix="payroll-worker-test-") as directory:
            worker = Path(directory) / "slow_worker.py"
            worker.write_text("import time\ntime.sleep(30)\n")
            started = time.monotonic()
            with patch.object(pdf_processing, "_WORKER", worker), \
                    patch.object(pdf_processing, "PROCESS_TIMEOUT_SECONDS", 0.05), \
                    patch.object(pdf_processing.subprocess, "Popen", side_effect=track_child):
                with self.assertRaises(PayrollPDFError) as raised:
                    pdf_processing.read_payroll_pdf_isolated(report_pdf())
            self.assertLess(time.monotonic() - started, 3)
        self.assertEqual(raised.exception.code, "processing_timeout")
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].poll(), "Timed-out parser child was left running")
        self.assertNotIn("Alice Example", str(raised.exception))
        self.assertNotIn("615.37", str(raised.exception))

    def test_parent_rejects_malformed_worker_output_and_page_or_text_budget_breaches(self):
        malformed = (
            b"private-worker-value: not JSON",
            json.dumps({"pages": [42]}).encode(),
            json.dumps({"error": "private-worker-value"}).encode(),
            json.dumps({"pages": ["x"] * (pdf_reader.MAX_PDF_PAGES + 1)}).encode(),
        )
        for output in malformed:
            with self.subTest(output_type=output[:35]):
                self.assert_processing_failed(output)
        with patch.object(pdf_reader, "MAX_PDF_TEXT_CHARS", 32):
            self.assert_processing_failed(json.dumps({"pages": ["x" * 33]}).encode())
            # Also reject a response too large to decode, independently of its
            # JSON shape or the parser's claimed text/page counts.
            self.assert_processing_failed(b"x" * 4096)

    def test_long_table_line_is_rejected_before_unbounded_financial_row_matching(self):
        content = report_pdf(row_lines=["Long Example " + "9" * 100_000])
        started = time.monotonic()
        with self.assertRaises(PayrollPDFError) as raised:
            pdf_processing.read_payroll_pdf_isolated(content)
        self.assertEqual(raised.exception.code, "too_large")
        self.assertLess(time.monotonic() - started, 5)
        self.assertNotIn("Long Example", str(raised.exception))

    def test_child_environment_does_not_receive_parent_secret_variables(self):
        # The synthetic worker returns a valid report only when the sentinel is
        # absent. No actual configured secret is read or copied into a fixture.
        page = (
            "Weekly Pay Run : 99 Pay Date : 25 Sep 2026\n"
            "Section 4 - Employer Costs\n"
            "Employee Total Payments Employer Pension Contrib. "
            "Employer NI Employer NI (Class 1A) Total Cost Per Employee\n"
            "Alice Example 615.37 13.59 77.42 0.00 706.38\n"
            "Totals 615.37 13.59 77.42 0.00 706.38\n"
        )
        with tempfile.TemporaryDirectory(prefix="payroll-worker-test-") as directory:
            worker = Path(directory) / "environment_worker.py"
            worker.write_text(
                "import json, os\n"
                "if os.environ.get('PAYROLL_TEST_PRIVATE_SENTINEL'):\n"
                "    print(json.dumps({'error': 'private-worker-value'}))\n"
                "else:\n"
                "    print(json.dumps({'pages': [" + repr(page) + "]}))\n"
            )
            with patch.dict(os.environ, {"PAYROLL_TEST_PRIVATE_SENTINEL": "synthetic-only"}), \
                    patch.object(pdf_processing, "_WORKER", worker):
                report = pdf_processing.read_payroll_pdf_isolated(report_pdf())
        self.assertEqual(len(report.rows), 1)
        self.assertEqual(report.rows[0].employee_name, "Alice Example")
