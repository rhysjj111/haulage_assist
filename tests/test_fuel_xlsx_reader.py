"""Fuel transactions are read faithfully without creating business records."""

from dataclasses import FrozenInstanceError, asdict
from datetime import date, datetime, time
from decimal import Decimal
from io import BytesIO
import json
import re
from unittest import TestCase
from unittest.mock import patch
import warnings
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from owner_test_support import OwnerTestCase, db
from fuel_xlsx_fixtures import HEADERS, TRANSACTIONS, changed_zip, transaction, transactions_xlsx
from sqlalchemy import select

from haulage_app.fuel import xlsx_reader
from haulage_app.fuel.xlsx_reader import FuelXLSXError, read_fuel_store_transactions_xlsx


class FuelXLSXReaderTests(TestCase):
    def assert_reader_error(self, content, *codes):
        with self.assertRaises(FuelXLSXError) as raised:
            read_fuel_store_transactions_xlsx(content)
        self.assertIn(raised.exception.code, codes)
        for private_value in ("FICTIONAL-CARD-0001", "Fictional Driver One", "ZZ26 ABC",
                              "private-cell-value", "186.25", "Traceback"):
            self.assertNotIn(private_value, str(raised.exception))
        return raised.exception

    def test_reads_transaction_dates_registrations_exact_displayed_amounts_and_source_rows(self):
        report = read_fuel_store_transactions_xlsx(transactions_xlsx())
        self.assertEqual(report.source_format, "fuel-store-transactions-xlsx-v1")
        self.assertEqual(report.fuel_card_name, "The Fuel Store")
        self.assertEqual((report.sheet_name, report.header_row), ("Transactions", 7))
        self.assertIsInstance(report.rows, tuple)
        first, second = report.rows
        self.assertEqual((first.source_row, second.source_row), (8, 9))
        self.assertEqual(first.transaction_date, date(2027, 2, 9))
        self.assertEqual(first.transaction_time, time(6, 12, 34))
        self.assertEqual(first.transaction_registration, "ZZ26 ABC")
        self.assertEqual(first.card_registration, "ZZ26 ABC")
        self.assertEqual(first.quantity, Decimal("143.27"))
        self.assertEqual(first.unit_price, Decimal("1.3"))
        self.assertEqual(first.cost, Decimal("186.25"))
        self.assertEqual(first.issues, ())
        self.assertEqual(second.cost, Decimal("274.40"))
        self.assertEqual(report.calculated_total_quantity, Decimal("354.35"))
        self.assertEqual(report.calculated_total_cost, Decimal("460.65"))

    def test_keeps_card_networks_separate_from_the_confirmed_invoice_supplier(self):
        labels = ("ESSO", "SHELL CRT", "UK FUELS", "FUEL STORE")
        rows = [transaction({"Card Type": label}) for label in labels]
        report = read_fuel_store_transactions_xlsx(transactions_xlsx(rows=rows))
        self.assertEqual([row.card_type for row in report.rows], list(labels))
        self.assertEqual(report.fuel_card_name, "The Fuel Store")

    def test_finds_the_complete_header_with_case_spacing_and_reordered_columns(self):
        headers = tuple("  " + label.swapcase().replace(" ", "   ") + "  " for label in HEADERS)
        report = read_fuel_store_transactions_xlsx(transactions_xlsx(
            headers=headers, header_row=12, column_order=reversed(range(14))))
        self.assertEqual(report.header_row, 12)
        self.assertEqual(report.rows[0].source_row, 13)
        self.assertEqual(report.rows[0].quantity, Decimal("143.27"))
        self.assertEqual(report.rows[1].transaction_registration, "ZX26 DEF")

    def test_native_dates_are_independent_of_the_workbook_1904_date_system(self):
        for epoch in (False, True):
            with self.subTest(epoch_1904=epoch):
                report = read_fuel_store_transactions_xlsx(transactions_xlsx(epoch_1904=epoch))
                self.assertEqual(report.rows[0].transaction_date, date(2027, 2, 9))
                self.assertEqual(report.rows[0].transaction_time, time(6, 12, 34))

    def test_blank_rows_are_not_transactions_and_original_row_numbers_are_preserved(self):
        report = read_fuel_store_transactions_xlsx(transactions_xlsx(
            rows=(TRANSACTIONS[0], None, TRANSACTIONS[1])))
        self.assertEqual([row.source_row for row in report.rows], [8, 10])
        self.assertEqual(report.calculated_total_cost, Decimal("460.65"))

    def test_same_truck_day_and_identical_repeated_transactions_are_not_deduplicated(self):
        same_day = transaction({"Quantity": 100.00, "Cost": 130.00})
        report = read_fuel_store_transactions_xlsx(transactions_xlsx(
            rows=(TRANSACTIONS[0], TRANSACTIONS[0], same_day)))
        self.assertEqual(len(report.rows), 3)
        self.assertEqual([row.transaction_date for row in report.rows], [date(2027, 2, 9)] * 3)
        self.assertEqual([row.transaction_registration for row in report.rows], ["ZZ26 ABC"] * 3)
        self.assertEqual(report.calculated_total_cost, Decimal("502.50"))

    def test_all_known_diesel_product_labels_are_kept_without_product_warning(self):
        products = ("KEYFUELS DIESEL", "UK FUELS DIESEL", "UK FUELS DIESEL (TP)",
                    "ESSO DIESEL", "DIESEL (SHELL)", "DIESEL")
        report = read_fuel_store_transactions_xlsx(transactions_xlsx(
            rows=[transaction({"Product": product}) for product in products]))
        self.assertEqual([row.product for row in report.rows], list(products))
        self.assertTrue(all("unsupported_product" not in row.issues for row in report.rows))

    def test_unknown_products_and_non_positive_values_remain_explicitly_reviewable(self):
        rows = (transaction({"Product": "ADBLUE", "Quantity": 0, "Cost": 0}),
                transaction({"Product": "CREDIT", "Quantity": -25, "Cost": -32.50}))
        report = read_fuel_store_transactions_xlsx(transactions_xlsx(rows=rows))
        self.assertEqual(len(report.rows), 2)
        self.assertEqual(report.rows[0].quantity, Decimal("0.00"))
        self.assertEqual(report.rows[1].cost, Decimal("-32.50"))
        for row in report.rows:
            self.assertTrue({"unsupported_product", "non_positive_quantity", "non_positive_cost"}
                            .issubset(set(row.issues)))

    def test_missing_transaction_registration_does_not_silently_use_the_card_registration(self):
        report = read_fuel_store_transactions_xlsx(transactions_xlsx(
            rows=[transaction({"Tran VRN": None})]))
        row = report.rows[0]
        self.assertIsNone(row.transaction_registration)
        self.assertEqual(row.card_registration, "ZZ26 ABC")
        self.assertIn("missing_transaction_registration", row.issues)

    def test_conflicting_registrations_are_flagged_but_case_and_spaces_do_not_conflict(self):
        rows = (transaction({"Card VRN": " zx26 def "}),
                transaction({"Card VRN": "zz26abc", "Tran VRN": "  ZZ26   ABC  "}))
        report = read_fuel_store_transactions_xlsx(transactions_xlsx(rows=rows))
        self.assertIn("registration_mismatch", report.rows[0].issues)
        self.assertNotIn("registration_mismatch", report.rows[1].issues)
        self.assertEqual(report.rows[0].transaction_registration, "ZZ26 ABC")

    def test_binary_numeric_noise_is_normalized_to_the_two_decimal_source_display(self):
        row = transaction({"Quantity": 143.27000427246094, "Cost": 186.24998474121094,
                           "Unit Price": 1.3000000000000003})
        report = read_fuel_store_transactions_xlsx(transactions_xlsx(rows=[row]))
        actual = report.rows[0]
        self.assertEqual(actual.quantity, Decimal("143.27"))
        self.assertEqual(actual.cost, Decimal("186.25"))
        self.assertNotIn("cost_price_mismatch", actual.issues)

    def test_display_rounding_is_explicit_and_does_not_recalculate_the_cost_column(self):
        report = read_fuel_store_transactions_xlsx(transactions_xlsx(
            rows=[transaction({"Quantity": 10.125, "Unit Price": 2.0, "Cost": 20.255})]))
        self.assertEqual(report.rows[0].quantity, Decimal("10.13"))
        self.assertEqual(report.rows[0].cost, Decimal("20.26"))
        self.assertIn("cost_price_mismatch", report.rows[0].issues)

    def test_price_reconciliation_flags_a_disagreement_without_replacing_source_cost(self):
        report = read_fuel_store_transactions_xlsx(transactions_xlsx(
            rows=[transaction({"Cost": 99.99})]))
        self.assertEqual(report.rows[0].cost, Decimal("99.99"))
        self.assertIn("cost_price_mismatch", report.rows[0].issues)

    def test_report_is_immutable_and_excludes_cardholder_and_account_details(self):
        report = read_fuel_store_transactions_xlsx(transactions_xlsx())
        serialized = json.dumps(asdict(report), default=str)
        for source_only in ("FICTIONAL-CARD-0001", "Fictional Driver One", "Fictional depot",
                            "Fictional service station", "123456", "FAKE-01"):
            self.assertNotIn(source_only, serialized)
        with self.assertRaises(FrozenInstanceError):
            report.header_row = 99
        with self.assertRaises(FrozenInstanceError):
            report.rows[0].cost = Decimal("1.00")

    def test_ignored_card_details_do_not_leak_through_spreadsheet_library_warnings(self):
        fictional_card_number = 9000000000000000
        content = transactions_xlsx(rows=[transaction({"Card No": fictional_card_number})],
                                    formats={"Card No": "dd/mm/yyyy"})
        with warnings.catch_warnings(record=True) as emitted:
            warnings.simplefilter("always")
            filters_before = list(warnings.filters)
            report = read_fuel_store_transactions_xlsx(content)
            self.assertEqual(warnings.filters, filters_before)
            self.assertEqual(emitted, [])
            warnings.warn("A later unrelated warning remains visible", UserWarning)
            self.assertEqual([str(item.message) for item in emitted],
                             ["A later unrelated warning remains visible"])
        self.assertEqual(len(report.rows), 1)
        self.assertNotIn(str(fictional_card_number), "\n".join(str(item.message) for item in emitted))
        self.assertNotIn(str(fictional_card_number), json.dumps(asdict(report), default=str))

    def test_missing_duplicate_or_unrecognized_headers_are_not_guessed(self):
        for replacement in ("Cost wrong", "Quantity", "private-cell-value"):
            headers = (*HEADERS[:-1], replacement)
            with self.subTest(header=replacement):
                self.assert_reader_error(transactions_xlsx(headers=headers), "unsupported_layout")
        self.assert_reader_error(transactions_xlsx(header_row=51), "unsupported_layout")

    def test_empty_or_additional_sheet_layouts_are_rejected_instead_of_returning_partial_data(self):
        self.assert_reader_error(transactions_xlsx(rows=[]), "unsupported_layout")
        self.assert_reader_error(transactions_xlsx(sheet_name="Other export"), "unsupported_layout")
        self.assert_reader_error(transactions_xlsx(configure=lambda wb: wb.create_sheet("Another export")),
                                 "unsupported_layout")

    def test_a_broken_later_row_rejects_the_whole_workbook_and_does_not_echo_values(self):
        rows = (TRANSACTIONS[0], transaction({"Date": None, "Product": "private-cell-value"}))
        self.assert_reader_error(transactions_xlsx(rows=rows), "invalid_transaction")
        self.assert_reader_error(transactions_xlsx(rows=(TRANSACTIONS[0], {"Cost Centre": "Totals"})),
                                 "invalid_transaction")

    def test_dates_must_be_native_calendar_dates_rather_than_ambiguous_text_or_numbers(self):
        for value in ("09/02/2027", "2027-02-09", True, 12345):
            with self.subTest(value=value):
                formats = {"Date": "General"}
                self.assert_reader_error(transactions_xlsx(rows=[transaction({"Date": value})],
                                                           formats=formats), "invalid_transaction")

    def test_numeric_amounts_do_not_accept_text_booleans_or_missing_values(self):
        for field in ("Quantity", "Unit Price", "Cost"):
            for value in (None, True, "private-cell-value", "12.34"):
                with self.subTest(field=field, value=value):
                    self.assert_reader_error(transactions_xlsx(rows=[transaction({field: value})]),
                                             "invalid_transaction")
        # Edit the numeric XML rather than relying on a writer that sanitizes
        # non-finite floats into empty cells before the reader sees them.
        content = transactions_xlsx()
        with ZipFile(BytesIO(content)) as archive:
            sheet = archive.read("xl/worksheets/sheet1.xml")
        for value in (b"NaN", b"Infinity", b"-Infinity"):
            altered = re.sub(rb'(<c r="L8"[^>]*><v>)[^<]*(</v>)',
                             lambda match: match[1] + value + match[2], sheet)
            self.assertNotEqual(altered, sheet)
            self.assert_reader_error(changed_zip(content, replace={"xl/worksheets/sheet1.xml": altered}),
                                     "invalid_transaction", "invalid_workbook")

    def test_formulas_in_any_transaction_column_are_rejected_without_using_cached_values(self):
        for field in ("Date", "Quantity", "Cost", "Card No"):
            with self.subTest(field=field):
                self.assert_reader_error(transactions_xlsx(rows=[transaction({field: '=1+2'})]),
                                         "formula_not_supported")

    def test_three_decimal_quantity_or_cost_formats_require_an_explicit_precision_decision(self):
        for field in ("Quantity", "Cost"):
            with self.subTest(field=field):
                self.assert_reader_error(transactions_xlsx(formats={field: "0.000"}),
                                         "unsupported_precision")

    def test_invalid_zip_and_non_workbook_content_have_clear_sanitized_errors(self):
        for content in (b"", b"private-cell-value", b"PK\x03\x04not a spreadsheet", None, "not bytes"):
            with self.subTest(content_type=type(content).__name__):
                self.assert_reader_error(content, "invalid_workbook")

    def test_macro_and_external_link_parts_are_rejected_before_interpretation(self):
        for name in ("xl/vbaProject.bin", "xl/externalLinks/externalLink1.xml"):
            with self.subTest(part=name):
                workbook = changed_zip(transactions_xlsx(), append=[(name, b"private-cell-value")])
                self.assert_reader_error(workbook, "unsupported_layout", "invalid_workbook")

    def test_archive_size_expansion_and_declared_dimensions_are_bounded(self):
        content = transactions_xlsx()
        with patch.object(xlsx_reader, "MAX_XLSX_BYTES", len(content) - 1):
            self.assert_reader_error(content, "too_large")
        with patch.object(xlsx_reader, "MAX_EXPANDED_BYTES", 100):
            self.assert_reader_error(content, "too_large")
        with patch.object(xlsx_reader, "MAX_ZIP_MEMBERS", 1):
            self.assert_reader_error(content, "too_large")
        def too_wide(wb):
            wb.active.cell(8, 65, "Unexpected extra column")
        self.assert_reader_error(transactions_xlsx(configure=too_wide), "too_large")
        def too_tall(wb):
            wb.active.cell(10051, 1, "Unexpected remote row")
        self.assert_reader_error(transactions_xlsx(configure=too_tall), "too_large")
        for configure in (too_wide, too_tall):
            with self.subTest(understated_dimension=configure.__name__):
                oversized = transactions_xlsx(configure=configure)
                with ZipFile(BytesIO(oversized)) as archive:
                    sheet = archive.read("xl/worksheets/sheet1.xml")
                altered = re.sub(rb'<dimension ref="[^"]+"', b'<dimension ref="A7:N9"', sheet)
                self.assertNotEqual(altered, sheet)
                self.assert_reader_error(changed_zip(oversized, replace={
                    "xl/worksheets/sheet1.xml": altered}), "too_large")
        with patch.object(xlsx_reader, "MAX_ROWS", 1):
            self.assert_reader_error(content, "too_large")

    def test_ambiguous_duplicate_cell_references_are_not_allowed_to_override_a_cost(self):
        content = transactions_xlsx()
        with ZipFile(BytesIO(content)) as archive:
            sheet = archive.read("xl/worksheets/sheet1.xml")
        cost_cell = re.search(rb'<c r="N8"[^>]*>.*?</c>', sheet)
        self.assertIsNotNone(cost_cell)
        altered = sheet[:cost_cell.end()] + cost_cell[0] + sheet[cost_cell.end():]
        self.assert_reader_error(changed_zip(content, replace={"xl/worksheets/sheet1.xml": altered}),
                                 "unsupported_layout")

    def test_relocated_worksheet_part_cannot_hide_a_column_outside_the_read_bounds(self):
        content = transactions_xlsx(configure=lambda wb: wb.active.cell(
            8, 65, "Unexpected extra fictional column"))
        original_part = "xl/worksheets/sheet1.xml"
        alternate_part = "xl/custom_sheet.xml"
        with ZipFile(BytesIO(content)) as archive:
            sheet = archive.read(original_part)
            relationships = archive.read("xl/_rels/workbook.xml.rels")
            content_types = archive.read("[Content_Types].xml")
        self.assertIn(b"worksheets/sheet1.xml", relationships)
        self.assertIn(b"/xl/worksheets/sheet1.xml", content_types)
        sheet = re.sub(rb'<dimension ref="[^"]+"', b'<dimension ref="A7:N9"', sheet)
        relocated = changed_zip(content, rename={original_part: alternate_part}, replace={
            original_part: sheet,
            "xl/_rels/workbook.xml.rels": relationships.replace(
                b"worksheets/sheet1.xml", b"custom_sheet.xml"),
            "[Content_Types].xml": content_types.replace(
                b"/xl/worksheets/sheet1.xml", b"/xl/custom_sheet.xml"),
        })
        # A reader may intentionally restrict part paths for this single export
        # format, or inspect the resolved part. Neither may omit the extra cell.
        self.assert_reader_error(relocated, "too_large", "unsupported_layout")

    def test_used_sheet_relationship_cannot_bypass_checks_with_an_unused_valid_decoy(self):
        normal = transactions_xlsx()
        oversized = transactions_xlsx(configure=lambda wb: wb.active.cell(
            8, 65, "Unexpected extra fictional column"))
        with ZipFile(BytesIO(normal)) as archive:
            dummy_sheet = archive.read("xl/worksheets/sheet1.xml")
        with ZipFile(BytesIO(oversized)) as archive:
            actual_sheet = archive.read("xl/worksheets/sheet1.xml")
            relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
            content_types = ET.fromstring(archive.read("[Content_Types].xml"))
        actual_sheet = re.sub(rb'<dimension ref="[^"]+"', b'<dimension ref="A7:N9"', actual_sheet)
        used = next(item for item in relationships if item.get("Type", "").endswith("/worksheet"))
        ordinary_type = used.get("Type")
        used.set("Type", ordinary_type.rsplit("/", 1)[0] + "/nonstandard")
        used.set("Target", "/xl/custom_sheet.xml")
        ET.SubElement(relationships, used.tag, {
            "Id": "rIdUnused", "Type": ordinary_type, "Target": "/xl/worksheets/dummy.xml",
        })
        worksheet_type = next(item for item in content_types
                              if item.get("PartName") == "/xl/worksheets/sheet1.xml")
        worksheet_type.set("PartName", "/xl/custom_sheet.xml")
        ET.SubElement(content_types, worksheet_type.tag, {
            "PartName": "/xl/worksheets/dummy.xml", "ContentType": worksheet_type.get("ContentType"),
        })
        altered = changed_zip(oversized, rename={"xl/worksheets/sheet1.xml": "xl/custom_sheet.xml"},
                              replace={
                                  "xl/worksheets/sheet1.xml": actual_sheet,
                                  "xl/_rels/workbook.xml.rels": ET.tostring(relationships),
                                  "[Content_Types].xml": ET.tostring(content_types),
                              }, append=[("xl/worksheets/dummy.xml", dummy_sheet)])
        self.assert_reader_error(altered, "unsupported_layout")

    def test_relocated_main_workbook_is_not_validated_through_unused_conventional_parts(self):
        content = transactions_xlsx()
        with ZipFile(BytesIO(content)) as archive:
            workbook = archive.read("xl/workbook.xml")
            workbook_relationships = archive.read("xl/_rels/workbook.xml.rels")
            root_relationships = ET.fromstring(archive.read("_rels/.rels"))
            content_types = ET.fromstring(archive.read("[Content_Types].xml"))
        document = next(item for item in root_relationships
                        if item.get("Type", "").endswith("/officeDocument"))
        document.set("Target", "xl/custom_book.xml")
        manifest_workbook = next(item for item in content_types
                                 if item.get("PartName") == "/xl/workbook.xml")
        manifest_workbook.set("PartName", "/xl/custom_book.xml")
        # The old conventional parts deliberately remain in the ZIP as unused
        # decoys. Validation must apply to the workbook selected by the manifest.
        altered = changed_zip(content, replace={
            "_rels/.rels": ET.tostring(root_relationships),
            "[Content_Types].xml": ET.tostring(content_types),
        }, append=[("xl/custom_book.xml", workbook),
                   ("xl/_rels/custom_book.xml.rels", workbook_relationships)])
        self.assert_reader_error(altered, "unsupported_layout")


class FuelXLSXReadOnlyTests(OwnerTestCase):
    def test_reading_does_not_modify_or_flush_business_records(self):
        self.add_truck()
        self.add_driver()
        self.add_day()
        def snapshot():
            with db.session.no_autoflush:
                return {name: [tuple(row) for row in db.session.execute(
                    select(table).order_by(*table.primary_key.columns))]
                    for name, table in db.metadata.tables.items()}
        before = snapshot()
        with patch.object(db.session, "add", side_effect=AssertionError("unexpected add")), \
                patch.object(db.session, "add_all", side_effect=AssertionError("unexpected add_all")), \
                patch.object(db.session, "flush", side_effect=AssertionError("unexpected flush")), \
                patch.object(db.session, "commit", side_effect=AssertionError("unexpected commit")):
            report = read_fuel_store_transactions_xlsx(transactions_xlsx())
            self.assertEqual(len(report.rows), 2)
        self.assertEqual(snapshot(), before)
