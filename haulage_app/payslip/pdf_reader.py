"""Read section 4 of a digital weekly payroll management report.

This module extracts proposed amounts only. It never matches drivers, calls an
AI service, writes files, or creates/updates payslips. Monetary values are
Decimal pounds; ``total_payments`` is the report's pre-deduction total, not net
pay. The supplied report's Pay Date selects the Saturday-Friday working week.
"""

from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import re

from haulage_app.owner_analysis.dates import payroll_week_start, week_end
from .pdf_text import PDFTextError, extract_pdf_text


MAX_PDF_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 20
MAX_PDF_TEXT_CHARS = 250_000
MAX_TABLE_LINE_CHARS = 2048


class PayrollPDFError(ValueError):
    """A safe, actionable failure without document text or private amounts."""

    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class PayrollTotals:
    total_payments: Decimal
    employer_pension: Decimal
    employer_ni: Decimal
    employer_ni_class_1a: Decimal
    total_cost_to_employer: Decimal


@dataclass(frozen=True)
class PayrollRow:
    employee_name: str
    total_payments: Decimal
    employer_pension: Decimal
    employer_ni: Decimal
    employer_ni_class_1a: Decimal
    total_cost_to_employer: Decimal
    page_number: int


@dataclass(frozen=True)
class PayrollReport:
    pay_date: date
    week_start: date
    week_end: date
    rows: tuple[PayrollRow, ...]
    totals: PayrollTotals


_SECTION = re.compile(r"^Section\s+(\d+)\s*[-\u2013\u2014:]\s*(.*?)\s*$", re.IGNORECASE)
_PAY_DATE = re.compile(r"\bPay\s+Date\s*:\s*([^\n\r]+)", re.IGNORECASE)
_DATE_TEXT = re.compile(r"^(\d{1,2})\s+([a-z]+)\s+(\d{4})$", re.IGNORECASE)
_DATE_NUMERIC = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_MONTHS = {
    name: index
    for index, names in enumerate((
        ("jan", "january"), ("feb", "february"), ("mar", "march"),
        ("apr", "april"), ("may",), ("jun", "june"), ("jul", "july"),
        ("aug", "august"), ("sep", "sept", "september"),
        ("oct", "october"), ("nov", "november"), ("dec", "december"),
    ), start=1)
    for name in names
}
_HEADER = re.compile(
    r"^Employee\s+Total\s+Payments\s+Employer\s+Pension\s+Contrib\.?\s+"
    r"Employer\s+NI\s+Employer\s+NI\s*\(\s*Class\s*1A\s*\)\s+"
    r"Total\s+Cost\s+Per\s+Employee$",
    re.IGNORECASE | re.MULTILINE,
)
_NUMBER = r"(?:\d{1,3}(?:,\d{3}){1,3}|\d{1,12})\.\d{2}"
_MONEY = rf"(?:-?{_NUMBER}|\({_NUMBER}\))"
_ROW = re.compile(r"^(.+?)\s+" + r"\s+".join([f"({_MONEY})"] * 5) + r"$")
_HAS_MONEY = re.compile(_MONEY)
_PAGE_LABEL = re.compile(r"^(?:Page\s+)?\d+\s+(?:of|/)\s+\d+$", re.IGNORECASE)
_WEEKLY_RUN = re.compile(r"\bWeekly\s+Pay\s+Run\s*:", re.IGNORECASE)
_HEADER_FRAGMENT = re.compile(
    r"^(?:Employee|Total\s+Payments|Employer\s+(?:Pension|NI)|"
    r"Contrib\.?|\(Class\s*1A\)|Total\s+Cost\s+Per)\s*$",
    re.IGNORECASE,
)
_COLUMN_LABEL = re.compile(
    r"\b(?:Total\s+Payments|Total\s+Cost\s+Per|Employer\s+(?:Pension|NI))\b",
    re.IGNORECASE,
)
_FIELDS = (
    "total_payments", "employer_pension", "employer_ni",
    "employer_ni_class_1a", "total_cost_to_employer",
)


def _extract_pages(content):
    try:
        return extract_pdf_text(content, max_bytes=MAX_PDF_BYTES,
                                max_pages=MAX_PDF_PAGES, max_text_chars=MAX_PDF_TEXT_CHARS)
    except PDFTextError as error:
        raise PayrollPDFError(error.code, str(error)) from None


def _read_pay_date(pages):
    values = [value.strip() for text in pages for value in _PAY_DATE.findall(text)]
    if not values:
        raise PayrollPDFError("missing_pay_date", "The report's Pay Date was not found.")
    dates = set()
    for value in values:
        match = _DATE_TEXT.fullmatch(value)
        numeric = _DATE_NUMERIC.fullmatch(value)
        try:
            if match:
                day, month, year = match.groups()
                parsed = date(int(year), _MONTHS[month.casefold()], int(day))
            elif numeric:
                day, month, year = map(int, numeric.groups())
                parsed = date(year, month, day)
            else:
                raise ValueError
            payroll_week_start(parsed)
            week_end(payroll_week_start(parsed))
        except (ValueError, KeyError):
            raise PayrollPDFError("invalid_pay_date", "The report's Pay Date is invalid or unsupported.") from None
        dates.add(parsed)
    if len(dates) != 1:
        raise PayrollPDFError("conflicting_pay_date", "The PDF contains different Pay Dates. Upload one weekly pay run at a time.")
    return dates.pop()


def _footer_titles(pages):
    """Recognise the repeated company title immediately before run metadata.

    Some report generators emit page headers/footers last in extracted text.
    Only a repeated, non-numeric title is ignored; employee/amount rows are never
    treated as footer metadata.
    """
    candidates = Counter()
    for text in pages:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        seen = set()
        for index, line in enumerate(lines):
            if index and _WEEKLY_RUN.search(line):
                previous = lines[index - 1]
                if (not _HAS_MONEY.search(previous) and not _SECTION.match(previous)
                        and not _HEADER_FRAGMENT.fullmatch(previous)):
                    seen.add(previous)
        candidates.update(seen)
    return {line for line, count in candidates.items() if count > 1}


def _section_lines(pages):
    footers = _footer_titles(pages)
    found = inside = finished = False
    lines = []
    for page_number, text in enumerate(pages, start=1):
        for raw_line in text.splitlines():
            line = " ".join(raw_line.split())
            if not line:
                continue
            if len(line) > MAX_TABLE_LINE_CHARS:
                raise PayrollPDFError("too_large", "A report line is too long to read safely. Use the original digital report.")
            section = _SECTION.fullmatch(line)
            if section:
                number, title = section.groups()
                if number == "4":
                    if finished or title.casefold() != "employer costs":
                        raise PayrollPDFError("unsupported_layout", "Section 4 does not match the supported Employer Costs table.")
                    found = inside = True
                elif inside:
                    inside = False
                    finished = True
                continue
            if not inside:
                continue
            if (line in footers or _WEEKLY_RUN.search(line) or _PAY_DATE.search(line)
                    or _PAGE_LABEL.fullmatch(line)):
                continue
            lines.append((page_number, line))
    if not found:
        raise PayrollPDFError("missing_section", "Section 4 - Employer Costs was not found.")
    return lines


def _table_lines(section_lines):
    text = "\n".join(line for _, line in section_lines)
    headers = list(_HEADER.finditer(text))
    if not headers or headers[0].start() != 0:
        raise PayrollPDFError("unsupported_layout", "The Employer Costs column headings do not match the supported report.")
    starts = []
    offset = 0
    for _, line in section_lines:
        starts.append(offset)
        offset += len(line) + 1
    header_lines = set()
    for header in headers:
        first = bisect_right(starts, header.start()) - 1
        last = bisect_right(starts, header.end() - 1) - 1
        header_lines.update(range(first, last + 1))
    return [item for index, item in enumerate(section_lines) if index not in header_lines]


def _amount(value):
    if value.startswith("("):
        return -Decimal(value[1:-1].replace(",", ""))
    return Decimal(value.replace(",", ""))


def _read_rows(lines):
    rows = []
    totals = None
    pending = []
    pending_page = None
    names = set()
    for page_number, line in lines:
        if totals is not None:
            raise PayrollPDFError("unsupported_layout", "Unexpected content follows the Employer Costs totals.")
        if _HEADER_FRAGMENT.fullmatch(line) or _COLUMN_LABEL.search(line):
            raise PayrollPDFError("unsupported_layout", "The Employer Costs column headings are incomplete or unsupported.")
        combined = " ".join([*pending, line])
        match = _ROW.fullmatch(combined)
        if not match:
            if _HAS_MONEY.search(line):
                raise PayrollPDFError("invalid_row", "An Employer Costs row is incomplete or has an unsupported amount.")
            pending.append(line)
            pending_page = pending_page or page_number
            if len(pending) > 4:
                raise PayrollPDFError("invalid_row", "An Employer Costs employee row could not be read.")
            continue
        name, *raw_amounts = match.groups()
        name = " ".join(name.split())
        if not any(character.isalpha() for character in name) or _HAS_MONEY.search(name):
            raise PayrollPDFError("invalid_row", "An Employer Costs row has no clear employee name.")
        values = dict(zip(_FIELDS, map(_amount, raw_amounts)))
        if name.casefold() == "totals":
            if not rows:
                raise PayrollPDFError("invalid_row", "The Employer Costs table has no employee rows.")
            totals = PayrollTotals(**values)
        else:
            normalised_name = name.casefold()
            if normalised_name in names:
                raise PayrollPDFError("duplicate_employee", "Section 4 contains repeated employee names. Review the report before importing.")
            names.add(normalised_name)
            if sum(values[field] for field in _FIELDS[:-1]) != values[_FIELDS[-1]]:
                raise PayrollPDFError("row_totals_mismatch", "An employee's payments and employer contributions do not match their total cost.")
            rows.append(PayrollRow(employee_name=name, **values, page_number=pending_page or page_number))
        pending = []
        pending_page = None
    if pending:
        raise PayrollPDFError("invalid_row", "The Employer Costs table ends with an incomplete row.")
    if totals is None:
        raise PayrollPDFError("missing_totals", "The Employer Costs totals row is missing. Use the complete management report.")
    if any(sum(getattr(row, field) for row in rows) != getattr(totals, field) for field in _FIELDS):
        raise PayrollPDFError("totals_mismatch", "The extracted employee amounts do not match the report totals. Review the original report.")
    return tuple(rows), totals


def _report_from_pages(pages) -> PayrollReport:
    """Validate already-bounded extracted text without loading PDF objects."""
    pay_date = _read_pay_date(pages)
    rows, totals = _read_rows(_table_lines(_section_lines(pages)))
    start = payroll_week_start(pay_date)
    return PayrollReport(pay_date=pay_date, week_start=start, week_end=week_end(start),
                         rows=rows, totals=totals)


def read_payroll_pdf(content: bytes) -> PayrollReport:
    """Read a complete digital report, or raise :class:`PayrollPDFError`.

    All employee rows are returned for later explicit driver matching. Neither
    a company-wide total nor an employee absent from the driver list should be
    converted into a payslip automatically. Zero/negative amounts remain exact
    source values for the later review stage; this is not permission to save
    them through the existing entry validators.
    """
    return _report_from_pages(_extract_pages(content))
