"""Fuel upload parsing is isolated and never returns partial/unchecked output."""

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from unittest import TestCase
from unittest.mock import patch

import owner_test_support  # Select the isolated app before package imports.
from fuel_xlsx_fixtures import transaction, transactions_xlsx
from haulage_app.fuel import xlsx_processing, xlsx_reader


def report_payload():
    return {
        "sheet_name": "Transactions", "header_row": 7,
        "source_format": "fuel-store-transactions-xlsx-v1", "fuel_card_name": "The Fuel Store",
        "rows": [{
            "source_row": 8, "transaction_date": "2027-02-09", "transaction_time": "06:12:34",
            "transaction_registration": "ZZ26 ABC", "card_registration": "ZZ26 ABC",
            "card_type": "FUEL STORE", "product": "KEYFUELS DIESEL", "quantity": "143.27",
            "cost": "186.25", "unit_price": "1.3", "issues": [],
        }],
    }


class FuelXLSXProcessingTests(TestCase):
    def test_real_worker_matches_direct_reader_with_flags_and_exact_values(self):
        content = transactions_xlsx(rows=(transaction(), transaction({
            "Tran VRN": None, "Card VRN": "ZX26 DEF", "Product": "Fictional other product",
            "Quantity": -3.50, "Cost": -4.55,
        })))
        self.assertEqual(xlsx_processing.read_fuel_store_xlsx_isolated(content),
                         xlsx_reader.read_fuel_store_transactions_xlsx(content))

    def test_reader_errors_are_fixed_codes_without_source_values(self):
        content = transactions_xlsx(rows=(transaction({"Cost": "private-worksheet-value"}),))
        with self.assertRaises(xlsx_reader.FuelXLSXError) as raised:
            xlsx_processing.read_fuel_store_xlsx_isolated(content)
        self.assertEqual(raised.exception.code, "invalid_transaction")
        self.assertNotIn("private-worksheet-value", str(raised.exception))

    def test_bad_magic_and_size_are_rejected_before_launching_a_child(self):
        with patch.object(xlsx_processing, "_run_worker") as launch:
            for content, code in ((b"invalid", "invalid_workbook"), (None, "invalid_workbook")):
                with self.subTest(code=code, content_type=type(content).__name__):
                    with self.assertRaises(xlsx_reader.FuelXLSXError) as raised:
                        xlsx_processing.read_fuel_store_xlsx_isolated(content)
                    self.assertEqual(raised.exception.code, code)
            with patch.object(xlsx_reader, "MAX_XLSX_BYTES", 3):
                with self.assertRaises(xlsx_reader.FuelXLSXError) as raised:
                    xlsx_processing.read_fuel_store_xlsx_isolated(b"PK\x03\x04")
                self.assertEqual(raised.exception.code, "too_large")
            launch.assert_not_called()

    def assert_output_rejected(self, output):
        with patch.object(xlsx_processing, "_run_worker", return_value=(0, output)):
            with self.assertRaises(xlsx_processing.FuelXLSXProcessingError) as raised:
                xlsx_processing.read_fuel_store_xlsx_isolated(b"PK\x03\x04")
        self.assertEqual(raised.exception.code, "processing_failed")

    def test_parent_rejects_unknown_error_or_invalid_json_without_exception_details(self):
        for output in (b"private-worker-value", b"[]", b"null", b'{"error":"private-worker-value"}',
                       b'{"error":[]}', b'{"error":"invalid_workbook","rows":[]}'):
            with self.subTest(output=output):
                self.assert_output_rejected(output)

    def test_parent_validates_source_rows_amounts_dates_and_all_metadata(self):
        original = report_payload()
        invalid_fields = (
            ("source_row", True), ("source_row", 7), ("source_row", 20000),
            ("transaction_date", "2027-02-30"), ("transaction_date", "20270209"),
            ("transaction_time", "06:12:34+00:00"), ("transaction_time", 42),
            ("transaction_registration", []), ("card_type", "x" * 201),
            ("product", ""), ("quantity", "1.234"), ("cost", "NaN"),
            ("cost", 186.25), ("unit_price", "Infinity"),
            ("unit_price", "99999999999999999999999999999999999999999999"),
            ("issues", ["private-worker-value"]), ("issues", ["unsupported_product"] * 2),
        )
        for field, value in invalid_fields:
            payload = deepcopy(original)
            payload["rows"][0][field] = value
            with self.subTest(field=field, value_type=type(value).__name__):
                self.assert_output_rejected(json.dumps(payload).encode())
        for field, value in (("sheet_name", "Other sheet"), ("header_row", False),
                             ("fuel_card_name", "Shell"), ("source_format", "unknown"),
                             ("rows", [])):
            payload = deepcopy(original)
            payload[field] = value
            with self.subTest(field=field):
                self.assert_output_rejected(json.dumps(payload).encode())
        payload = deepcopy(original)
        payload["rows"] *= 2
        self.assert_output_rejected(json.dumps(payload).encode())
        with patch.object(xlsx_processing, "MAX_OUTPUT_BYTES", 4):
            self.assert_output_rejected(b"too-long")

    def test_timeout_kills_and_reaps_a_real_child(self):
        children = []
        real_popen = subprocess.Popen

        def track(*args, **kwargs):
            child = real_popen(*args, **kwargs)
            children.append(child)
            return child

        with tempfile.TemporaryDirectory(prefix="fuel-worker-test-") as directory:
            worker = Path(directory) / "slow.py"
            worker.write_text("import time\ntime.sleep(30)\n")
            started = time.monotonic()
            with patch.object(xlsx_processing, "_WORKER", worker), \
                    patch.object(xlsx_processing, "PROCESS_TIMEOUT_SECONDS", 0.05), \
                    patch.object(xlsx_processing.subprocess, "Popen", side_effect=track):
                with self.assertRaises(xlsx_processing.FuelXLSXProcessingError) as raised:
                    xlsx_processing.read_fuel_store_xlsx_isolated(b"PK\x03\x04")
            self.assertLess(time.monotonic() - started, 3)
        self.assertEqual(raised.exception.code, "processing_timeout")
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].poll())

    def test_output_cap_kills_and_reaps_chatty_child_before_buffering_it_all(self):
        children = []
        real_popen = subprocess.Popen

        def track(*args, **kwargs):
            child = real_popen(*args, **kwargs)
            children.append(child)
            return child

        with tempfile.TemporaryDirectory(prefix="fuel-worker-test-") as directory:
            worker = Path(directory) / "chatty.py"
            worker.write_text("import sys\nwhile True: sys.stdout.buffer.write(b'x' * 65536)\n")
            with patch.object(xlsx_processing, "_WORKER", worker), \
                    patch.object(xlsx_processing, "MAX_OUTPUT_BYTES", 1024), \
                    patch.object(xlsx_processing.subprocess, "Popen", side_effect=track):
                with self.assertRaises(xlsx_processing.FuelXLSXProcessingError) as raised:
                    xlsx_processing.read_fuel_store_xlsx_isolated(b"PK\x03\x04")
        self.assertEqual(raised.exception.code, "processing_failed")
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].poll())

    def test_sanitized_child_environment_drops_synthetic_parent_credentials(self):
        with tempfile.TemporaryDirectory(prefix="fuel-worker-test-") as directory:
            worker = Path(directory) / "environment.py"
            worker.write_text(
                "import json, os, sys\n"
                "assert not os.environ.get('FUEL_TEST_PRIVATE_SENTINEL')\n"
                "assert not any(k.startswith('haulage_app') for k in sys.modules)\n"
                "print(" + repr(json.dumps(report_payload())) + ")\n"
            )
            with patch.dict(os.environ, {"FUEL_TEST_PRIVATE_SENTINEL": "synthetic-only"}), \
                    patch.object(xlsx_processing, "_WORKER", worker):
                report = xlsx_processing.read_fuel_store_xlsx_isolated(b"PK\x03\x04")
        self.assertEqual(report.rows[0].source_row, 8)

    def test_worker_fails_closed_when_resource_limits_cannot_apply(self):
        # Run the actual standalone module's main with only a synthetic failing
        # resource hook. No app package or parser runs in that child.
        actual_worker = xlsx_processing._WORKER
        with tempfile.TemporaryDirectory(prefix="fuel-worker-test-") as directory:
            wrapper = Path(directory) / "unsupported.py"
            wrapper.write_text(
                "import runpy, sys\n"
                "sys.path.insert(0, " + repr(str(actual_worker.parent)) + ")\n"
                "scope = runpy.run_path(" + repr(str(actual_worker)) + ")\n"
                "def fail(): raise RuntimeError('private-source-value')\n"
                "scope['_main'].__globals__['_limit_resources'] = fail\n"
                "scope['_main']()\n"
            )
            with patch.object(xlsx_processing, "_WORKER", wrapper):
                with self.assertRaises(xlsx_processing.FuelXLSXProcessingError) as raised:
                    xlsx_processing.read_fuel_store_xlsx_isolated(b"PK\x03\x04")
        self.assertEqual(raised.exception.code, "processing_failed")
        self.assertNotIn("private-source-value", str(raised.exception))
