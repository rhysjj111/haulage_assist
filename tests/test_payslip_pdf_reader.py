"""Payroll PDFs are read without changing entries or guessing missing values."""

from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal
from unittest import TestCase
from unittest.mock import patch

from owner_test_support import db
from payroll_pdf_fixtures import (
    EMPLOYEES, EMPLOYER_HEADER, employee_lines, report_pdf, text_pdf, total_row,
)
from haulage_app.payslip import pdf_reader
from haulage_app.payslip.pdf_reader import PayrollPDFError, read_payroll_pdf


class PayslipPDFReaderTests(TestCase):
    def assert_pdf_error(self, content, *codes):
        with self.assertRaises(PayrollPDFError) as raised:
            read_payroll_pdf(content)
        self.assertIn(raised.exception.code, codes)
        # Failures should not echo employee details or the uploaded document.
        for private_value in ("Alice Example", "Ben Sample", "615.37", "706.38"):
            self.assertNotIn(private_value, str(raised.exception))
        return raised.exception

    def test_reads_section_four_after_page_break_and_ignores_other_sections(self):
        content = text_pdf([
            ["Section 1 - Employee Payslip Summary", "Employee Net Pay",
             "Decoy Person 999.99", "Section 4 - Employer Costs",
             "Fictional Haulage Ltd", "Weekly Pay Run : 99 Pay Date : 25 Sep 2026"],
            [*EMPLOYER_HEADER, *employee_lines(), total_row(),
             "Section 5 - Liability Totals", "Employee Net Pay",
             "Another Decoy 888.88", "Fictional Haulage Ltd",
             "Weekly Pay Run : 99 Pay Date : 25 Sep 2026"],
        ])
        report = read_payroll_pdf(content)
        self.assertEqual(report.pay_date, date(2026, 9, 25))
        self.assertEqual(report.week_start, date(2026, 9, 19))
        self.assertEqual(report.week_end, date(2026, 9, 25))
        self.assertEqual([row.employee_name for row in report.rows],
                         ["Alice Example", "Ben Sample"])
        self.assertEqual([row.page_number for row in report.rows], [2, 2])
        first = report.rows[0]
        self.assertEqual(first.total_payments, Decimal("615.37"))
        self.assertEqual(first.total_cost_to_employer, Decimal("706.38"))
        self.assertEqual(first.employer_pension, Decimal("13.59"))
        self.assertEqual(first.employer_ni, Decimal("77.42"))
        self.assertEqual(first.employer_ni_class_1a, Decimal("0.00"))
        self.assertEqual(report.totals.total_payments, Decimal("1416.57"))
        self.assertEqual(report.totals.total_cost_to_employer, Decimal("1630.33"))

    def test_uses_pay_date_across_calendar_year_not_payroll_run_number(self):
        report = read_payroll_pdf(report_pdf(pay_date="01 Jan 2027"))
        self.assertEqual(report.week_start, date(2026, 12, 26))
        self.assertEqual(report.week_end, date(2027, 1, 1))

    def test_continued_table_headers_and_footer_do_not_create_employee_rows(self):
        content = text_pdf([
            ["Section 4 - Employer Costs", *EMPLOYER_HEADER,
             *employee_lines(EMPLOYEES[:1]), "Fictional Haulage Ltd",
             "Weekly Pay Run : 99 Pay Date : 25 Sep 2026"],
            [*EMPLOYER_HEADER, *employee_lines(EMPLOYEES[1:]), total_row(),
             "Fictional Haulage Ltd", "Weekly Pay Run : 99 Pay Date : 25 Sep 2026"],
        ])
        report = read_payroll_pdf(content)
        self.assertEqual(len(report.rows), 2)
        self.assertEqual([row.page_number for row in report.rows], [1, 2])

    def test_wrapped_employee_name_and_thousands_separator_preserve_values(self):
        employees = (("ALEXANDRA LONG EXAMPLE", "1,234.56", "25.00", "180.00", "0.00", "1,439.56"),)
        content = report_pdf(employees=employees, row_lines=[
            "ALEXANDRA LONG", "EXAMPLE 1,234.56 25.00 180.00 0.00 1,439.56",
        ])
        row = read_payroll_pdf(content).rows[0]
        self.assertEqual(row.employee_name, "ALEXANDRA LONG EXAMPLE")
        self.assertEqual(row.total_payments, Decimal("1234.56"))
        self.assertEqual(row.total_cost_to_employer, Decimal("1439.56"))

    def test_zero_and_negative_source_amounts_are_preserved_for_later_review(self):
        employees = (
            ("Zero Example", "0.00", "0.00", "0.00", "0.00", "0.00"),
            ("Adjustment Example", "-12.34", "0.00", "-1.85", "0.00", "-14.19"),
        )
        report = read_payroll_pdf(report_pdf(employees=employees))
        self.assertEqual(report.rows[0].total_payments, Decimal("0.00"))
        self.assertEqual(report.rows[1].total_payments, Decimal("-12.34"))
        self.assertEqual(report.totals.total_cost_to_employer, Decimal("-14.19"))

    def test_result_is_immutable_and_reading_never_writes_payslips(self):
        with patch.object(db.session, "add", side_effect=AssertionError("unexpected add")), \
                patch.object(db.session, "commit", side_effect=AssertionError("unexpected commit")), \
                patch.object(db.session, "flush", side_effect=AssertionError("unexpected flush")):
            report = read_payroll_pdf(report_pdf())
        self.assertIsInstance(report.rows, tuple)
        with self.assertRaises(FrozenInstanceError):
            report.pay_date = date(2026, 1, 1)

    def test_rejects_wrong_section_even_when_it_contains_same_column_names(self):
        content = text_pdf([["Weekly Pay Run : 99 Pay Date : 25 Sep 2026",
                             "Section 3 - Deductions Summary", *EMPLOYER_HEADER,
                             *employee_lines(), total_row()]])
        self.assert_pdf_error(content, "missing_section")

    def test_rejects_changed_column_order_instead_of_swapping_amounts(self):
        header = ("Employee Total Cost Per Employee Employer Pension Contrib.",
                  "Employer NI Employer NI (Class 1A) Total Payments")
        self.assert_pdf_error(report_pdf(header=header), "unsupported_layout")

    def test_rejects_changed_continuation_header_instead_of_using_it_as_a_name(self):
        content = text_pdf([
            ["Section 4 - Employer Costs", *EMPLOYER_HEADER,
             *employee_lines(EMPLOYEES[:1]), "Fictional Haulage Ltd",
             "Weekly Pay Run : 99 Pay Date : 25 Sep 2026"],
            [" ".join(EMPLOYER_HEADER) + " EXTRA COLUMN",
             *employee_lines(EMPLOYEES[1:]), total_row(),
             "Fictional Haulage Ltd", "Weekly Pay Run : 99 Pay Date : 25 Sep 2026"],
        ])
        self.assert_pdf_error(content, "unsupported_layout")

    def test_rejects_missing_employee_amount_instead_of_returning_partial_report(self):
        content = report_pdf(row_lines=["Alice Example 615.37 13.59 77.42 0.00",
                                        *employee_lines(EMPLOYEES[1:])])
        self.assert_pdf_error(content, "invalid_row")

    def test_rejects_truncated_section_without_printed_totals(self):
        content = text_pdf([["Weekly Pay Run : 99 Pay Date : 25 Sep 2026",
                             "Section 4 - Employer Costs", *EMPLOYER_HEADER,
                             *employee_lines()]])
        self.assert_pdf_error(content, "missing_totals")

    def test_rejects_totals_that_do_not_match_extracted_employees(self):
        content = report_pdf(totals="Totals 1416.58 33.59 177.92 2.25 1630.34")
        self.assert_pdf_error(content, "totals_mismatch")

    def test_rejects_employer_cost_that_does_not_equal_employee_row_components(self):
        employees = (("Alice Example", "615.37", "13.59", "77.42", "0.00", "700.00"),)
        self.assert_pdf_error(report_pdf(employees=employees), "row_totals_mismatch")

    def test_rejects_duplicate_employee_names_that_cannot_be_matched_safely(self):
        employees = (EMPLOYEES[0], ("ALICE   EXAMPLE", *EMPLOYEES[1][1:]))
        self.assert_pdf_error(report_pdf(employees=employees), "duplicate_employee")

    def test_rejects_missing_pay_date_without_using_payroll_run_number(self):
        content = text_pdf([["Weekly Pay Run : 25", "Section 4 - Employer Costs",
                             *EMPLOYER_HEADER, *employee_lines(), total_row()]])
        self.assert_pdf_error(content, "missing_pay_date")

    def test_rejects_impossible_calendar_date(self):
        self.assert_pdf_error(report_pdf(pay_date="31 Feb 2026"), "invalid_pay_date")

    def test_rejects_conflicting_pay_dates_from_different_pages(self):
        content = text_pdf([
            ["Weekly Pay Run : 99 Pay Date : 25 Sep 2026", "Section 4 - Employer Costs"],
            [*EMPLOYER_HEADER, *employee_lines(), total_row(),
             "Weekly Pay Run : 99 Pay Date : 02 Oct 2026"],
        ])
        self.assert_pdf_error(content, "conflicting_pay_date")

    def test_rejects_non_pdf_and_broken_pdf_with_safe_error(self):
        for content in (b"not a PDF: Alice Example 615.37", b"%PDF-1.7\ntruncated"):
            with self.subTest(content_type=content[:8]):
                self.assert_pdf_error(content, "invalid_pdf")

    def test_rejects_encrypted_pdf(self):
        content = text_pdf([["Private payroll text"]], password="test-password")
        self.assert_pdf_error(content, "encrypted_pdf")

    def test_rejects_image_only_or_blank_pdf_without_guessing(self):
        self.assert_pdf_error(text_pdf([[]]), "no_text")

    def test_rejects_file_and_page_limits_before_processing_contents(self):
        self.assert_pdf_error(b"%PDF-1.7\n" + b" " * pdf_reader.MAX_PDF_BYTES, "too_large")
        self.assert_pdf_error(text_pdf([[]] * (pdf_reader.MAX_PDF_PAGES + 1)), "too_many_pages")

    def test_rejects_extracted_text_over_budget(self):
        with patch.object(pdf_reader, "MAX_PDF_TEXT_CHARS", 32):
            self.assert_pdf_error(report_pdf(), "too_large")
