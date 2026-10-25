"""Silvey invoices preserve exact purchases and reconcile every printed group."""

from dataclasses import FrozenInstanceError
from datetime import date, time
from decimal import Decimal
from unittest import TestCase
from unittest.mock import patch

import owner_test_support  # Select isolated app settings before package imports.
from payroll_pdf_fixtures import text_pdf
from silvey_pdf_fixtures import (
    FOOTER, SUMMARY_HEADER, TABLE_HEADER, TRANSACTIONS, invoice_pages, invoice_pdf,
    transaction, transaction_line,
)
from haulage_app.fuel import silvey_reader
from haulage_app.fuel.silvey_reader import SilveyPDFError, _report_from_pages, read_silvey_pdf


class SilveyPDFReaderTests(TestCase):
    def assert_error(self, pages, code):
        with self.assertRaises(SilveyPDFError) as raised:
            _report_from_pages(pages)
        self.assertEqual(raised.exception.code, code)
        self.assertNotIn("private-source-value", str(raised.exception))
        return raised.exception

    def test_real_pdf_extraction_returns_exact_transactions_pages_and_printed_totals(self):
        report = read_silvey_pdf(invoice_pdf())
        self.assertEqual(report.fuel_card_name, "Silvey")
        self.assertEqual(report.source_format, "silvey-fuel-invoice-pdf-v1")
        self.assertEqual(report.document_kind, "pdf")
        self.assertEqual(report.page_count, 2)
        self.assertEqual(report.sheet_name, "Silvey invoice")
        self.assertEqual(report.header_row, 1)
        self.assertEqual(len(report.rows), 6)
        self.assertEqual([row.source_row for row in report.rows], list(range(1, 7)))
        self.assertEqual([row.source_page for row in report.rows], [1, 1, 1, 1, 2, 2])
        first = report.rows[0]
        self.assertEqual(first.transaction_date, date(2026, 10, 1))
        self.assertEqual(first.transaction_time, time(6, 5))
        self.assertEqual(first.transaction_registration, "ZZ26 ABC")
        self.assertIsNone(first.card_registration)
        self.assertEqual(first.card_type, "Silvey")
        self.assertEqual(first.quantity, Decimal("10.00"))
        self.assertEqual(first.cost, Decimal("12.00"))
        self.assertEqual(first.unit_price, Decimal("1.20"))
        self.assertEqual(first.issues, ())
        self.assertEqual(report.printed_total_quantity, Decimal("155.35"))
        self.assertEqual(report.printed_total_cost, Decimal("206.44"))
        self.assertEqual(report.calculated_total_quantity, report.printed_total_quantity)
        self.assertEqual(report.calculated_total_cost, report.printed_total_cost)

    def test_extended_price_is_copied_not_misread_as_a_unit_price_or_gross_total(self):
        report = _report_from_pages(invoice_pages())
        for row, expected in zip(report.rows, TRANSACTIONS):
            self.assertEqual(row.cost, Decimal(expected["cost"]))
            self.assertEqual(row.quantity, Decimal(expected["quantity"]))
            self.assertEqual(row.unit_price, Decimal(expected["rate"]))
        self.assertNotEqual(report.printed_total_cost, Decimal("247.73"))

    def test_adblue_is_retained_as_an_unsupported_product_without_contaminating_diesel(self):
        report = _report_from_pages(invoice_pages())
        excluded = [row for row in report.rows if "unsupported_product" in row.issues]
        self.assertEqual(len(excluded), 1)
        self.assertEqual(excluded[0].source_row, 3)
        self.assertEqual(excluded[0].product, "ADBLUE")
        diesel = [row for row in report.rows if "unsupported_product" not in row.issues]
        self.assertEqual(sum(row.cost for row in diesel), Decimal("196.44"))
        self.assertEqual(sum(row.quantity for row in diesel), Decimal("150.35"))

    def test_glued_time_registration_and_variable_date_widths_are_supported(self):
        content = invoice_pdf(glued_time=True)
        report = read_silvey_pdf(content)
        self.assertEqual(report.rows[0].transaction_time, time(6, 5))
        self.assertEqual(report.rows[0].transaction_registration, "ZZ26 ABC")

    def test_card_continuation_does_not_reset_the_open_card_at_a_page_boundary(self):
        report = _report_from_pages(invoice_pages())
        self.assertEqual(report.rows[3].transaction_registration, "ZX26 DEF")
        self.assertEqual(report.rows[4].transaction_registration, "ZX26 DEF")
        self.assertNotEqual(report.rows[3].source_page, report.rows[4].source_page)
        self.assertEqual(report.printed_total_cost, Decimal("206.44"))

    def test_duplicate_purchases_remain_distinct_source_rows(self):
        rows = (transaction(), transaction())
        report = _report_from_pages(invoice_pages(rows=rows, split_after=10))
        self.assertEqual(len(report.rows), 2)
        self.assertEqual([row.source_row for row in report.rows], [1, 2])
        self.assertEqual(report.rows[0].cost, report.rows[1].cost)

    def test_comma_formatted_printed_numbers_are_exact(self):
        pages = invoice_pages(rows=(transaction({"quantity": "1234.50", "cost": "1481.40"}),), split_after=10)
        pages = [page.replace("1234.50", "1,234.50").replace("1481.40", "1,481.40") for page in pages]
        report = _report_from_pages(pages)
        self.assertEqual(report.rows[0].quantity, Decimal("1234.50"))
        self.assertEqual(report.rows[0].cost, Decimal("1481.40"))

    def test_unknown_non_diesel_product_is_visible_and_flagged(self):
        rows = (transaction({"product": "SCREENWASH", "rate": "2.0", "quantity": "5.00", "cost": "10.00"}),)
        report = _report_from_pages(invoice_pages(rows=rows))
        self.assertEqual(report.rows[0].product, "SCREENWASH")
        self.assertEqual(report.rows[0].issues, ("unsupported_product",))

    def test_negative_credit_values_are_not_silently_dropped_or_made_positive(self):
        rows = (transaction({"product": "ADBLUE", "rate": "2.0", "quantity": "-5.00", "cost": "-10.00"}),)
        report = _report_from_pages(invoice_pages(rows=rows))
        self.assertEqual(report.rows[0].quantity, Decimal("-5.00"))
        self.assertEqual(report.rows[0].cost, Decimal("-10.00"))
        self.assertCountEqual(report.rows[0].issues,
                              ("unsupported_product", "non_positive_quantity", "non_positive_cost"))

    def test_card_total_and_grand_total_disagreements_fail_the_whole_report(self):
        self.assert_error(invoice_pages(card_total_overrides={"900001": "46.31"}), "reconciliation_failed")
        self.assert_error(invoice_pages(grand_total="206.45"), "reconciliation_failed")

    def test_missing_transaction_or_card_total_or_grand_total_never_returns_a_partial_report(self):
        pages = invoice_pages()
        self.assert_error([page.replace(transaction_line(TRANSACTIONS[0]) + "\n", "") for page in pages],
                          "reconciliation_failed")
        self.assert_error([page.replace("Total For Card: 46.30\n", "") for page in pages],
                          "incomplete_transactions")
        self.assert_error([page.replace("Grand Total: 206.44\n", "") for page in pages],
                          "reconciliation_failed")

    def test_summary_quantity_and_rate_group_costs_must_match_not_only_the_grand_total(self):
        pages = invoice_pages()
        self.assert_error([page.replace("KEYFUELS DERV 70.25 1.2000 84.30", "KEYFUELS DERV 70.24 1.2000 84.30") for page in pages],
                          "reconciliation_failed")
        # Offset the two group costs so their total remains identical. Group
        # reconciliation must still catch an incorrect summary allocation.
        self.assert_error([page.replace("1.2000 84.30", "1.2000 84.31").replace("1.4000 112.14", "1.4000 112.13") for page in pages],
                          "reconciliation_failed")

    def test_invoice_aggregation_may_differ_from_rounding_group_litres_times_rate(self):
        rows = (transaction({"quantity": "1.01", "rate": "1.005", "cost": "1.02"}),
                transaction({"quantity": "1.01", "rate": "1.005", "cost": "1.02"}))
        report = _report_from_pages(invoice_pages(rows=rows))
        self.assertEqual(report.printed_total_cost, Decimal("2.04"))

    def test_unit_price_must_have_one_unambiguous_matching_product_summary(self):
        rows = (transaction(),)
        self.assert_error(invoice_pages(rows=rows, summary_lines=[
            "KEYFUELS DERV 10.00 1.2000 12.00 1",
            "KEYFUELS DERV 0.00 1.2001 0.00 1",
        ]), "reconciliation_failed")

    def test_wrong_supplier_or_missing_summary_or_transaction_headers_are_rejected(self):
        pages = invoice_pages()
        self.assert_error([page.replace("Silvey", "Other").replace("silveyfleet", "otherfleet") for page in pages],
                          "unsupported_layout")
        self.assert_error([page.replace(SUMMARY_HEADER, "OTHER COLUMNS") for page in pages], "unsupported_layout")
        self.assert_error([page.replace(TABLE_HEADER, "OTHER COLUMNS") for page in pages], "incomplete_transactions")

    def test_invoice_date_anchors_century_and_year_crossing_without_machine_pivot(self):
        rows = (transaction({"date": "31/12/69"}), transaction({"date": "1/1/70"}))
        report = _report_from_pages(invoice_pages(rows=rows, invoice_date="2-Jan-2070"))
        self.assertEqual([row.transaction_date for row in report.rows], [date(2069, 12, 31), date(2070, 1, 1)])
        report = _report_from_pages(invoice_pages(rows=rows, invoice_date="2-Jan-1970"))
        self.assertEqual([row.transaction_date for row in report.rows], [date(1969, 12, 31), date(1970, 1, 1)])

    def test_payment_due_date_in_may_is_not_mistaken_for_another_invoice_date(self):
        pages = invoice_pages(rows=(transaction({"date": "1/5/26"}),), invoice_date="6-May-2026")
        pages[0] = pages[0].replace("VAT Code VAT Rate £ VAT £ Taxable", "VAT Code VAT Rate £ VAT £ Taxable\n10-May-2026")
        report = _report_from_pages(pages)
        self.assertEqual(report.rows[0].transaction_date, date(2026, 5, 1))

    def test_missing_ambiguous_invalid_or_future_invoice_dates_fail_closed(self):
        pages = invoice_pages()
        self.assert_error([page.replace("6-Oct-2026", "date unknown") for page in pages], "unsupported_layout")
        self.assert_error([page.replace("6-Oct-2026", "6-Oct-2026 7-Oct-2026") for page in pages], "unsupported_layout")
        self.assert_error([page.replace("6-Oct-2026", "31-Feb-2026") for page in pages], "unsupported_layout")
        self.assert_error(invoice_pages(rows=(transaction({"date": "7/10/26"}),)), "incomplete_transactions")
        self.assert_error(invoice_pages(rows=(transaction({"date": "1/10/24"}),)), "incomplete_transactions")

    def test_invalid_calendar_date_or_time_or_malformed_transaction_fails_without_source_echo(self):
        for changes in ({"date": "31/2/26"}, {"time": "24:01"}, {"registration": "private-source-value!"}):
            with self.subTest(changes=changes):
                self.assert_error(invoice_pages(rows=(transaction(changes),)), "incomplete_transactions")

    def test_unexpected_transaction_text_even_after_a_footer_is_rejected(self):
        pages = invoice_pages()
        bad = "900009 800009 private-source-value malformed 1/10/26 1:00 ZZ26 ABC 123 10.00"
        pages[0] += "\n" + bad
        self.assert_error(pages, "incomplete_transactions")

    def test_transactions_and_totals_before_the_table_cannot_be_silently_skipped(self):
        for text in (transaction_line(TRANSACTIONS[0]), "Total For Card: 12.000", "Grand Total: 12.00"):
            pages = invoice_pages()
            pages[0] = pages[0].replace(TABLE_HEADER, text + "\n" + TABLE_HEADER)
            self.assert_error(pages, "incomplete_transactions")
        pages = invoice_pages()
        pages[0] = pages[0].replace("Total For Card: 46.30", "private-source-value\nTotal For Card: 46.30")
        self.assert_error(pages, "incomplete_transactions")

    def test_closed_cards_cannot_reopen_and_extra_pages_cannot_be_silently_ignored(self):
        rows = (transaction(), transaction({"card": "900002"}), transaction())
        self.assert_error(invoice_pages(rows=rows), "incomplete_transactions")
        self.assert_error(invoice_pages() + ["private-source-value"], "incomplete_transactions")

    def test_limits_apply_before_semantic_processing_and_no_text_is_distinct(self):
        self.assert_error([" "], "no_text")
        self.assert_error(["x"] * (silvey_reader.MAX_PDF_PAGES + 1), "too_many_pages")
        self.assert_error(["x" * (silvey_reader.MAX_LINE_CHARS + 1)], "too_large")
        with patch.object(silvey_reader, "MAX_PDF_TEXT_CHARS", 2):
            self.assert_error(["xxx"], "too_large")
        with patch.object(silvey_reader, "MAX_PDF_BYTES", 2):
            with self.assertRaises(SilveyPDFError) as raised:
                read_silvey_pdf(b"not a PDF")
            self.assertEqual(raised.exception.code, "too_large")

    def test_unreadable_encrypted_and_image_only_files_have_fixed_errors(self):
        cases = ((b"private-source-value", "invalid_pdf"),
                 (invoice_pdf(password="fictional-only"), "encrypted_pdf"),
                 (text_pdf([[]]), "no_text"))
        for content, code in cases:
            with self.subTest(code=code):
                with self.assertRaises(SilveyPDFError) as raised:
                    read_silvey_pdf(content)
                self.assertEqual(raised.exception.code, code)
                self.assertNotIn("private-source-value", str(raised.exception))

    def test_trusted_reader_resource_errors_remain_fixed_document_errors(self):
        from haulage_app.payslip.pdf_text import PDFTextError

        with patch("haulage_app.payslip.pdf_text.extract_pdf_text", side_effect=PDFTextError("processing_failed")):
            with self.assertRaises(SilveyPDFError) as raised:
                read_silvey_pdf(invoice_pdf())
        self.assertEqual(raised.exception.code, "processing_failed")

    def test_returned_report_and_rows_are_immutable_and_exclude_card_account_site_odometer(self):
        report = _report_from_pages(invoice_pages())
        with self.assertRaises(FrozenInstanceError):
            report.fuel_card_name = "Other"
        with self.assertRaises(FrozenInstanceError):
            report.rows[0].cost = Decimal("0.00")
        for value in ("900001", "800001", "FICTIONAL NORTH SERVICES", "10101", "9123456", "Fictional Customer"):
            self.assertNotIn(value, repr(report))
