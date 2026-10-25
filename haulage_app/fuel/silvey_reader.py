"""Read the recognised Silvey digital invoice layout into proposed purchases.

This module is also imported directly by the isolated worker, without importing
the Flask package. Card/account details are used only to validate groups and are
never returned, logged, evaluated or retained in a report.
"""

from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import re

if __package__:
    from .xlsx_reader import FuelTransaction, FuelTransactionsReport
else:
    from xlsx_reader import FuelTransaction, FuelTransactionsReport


MAX_PDF_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 20
MAX_PDF_TEXT_CHARS = 250_000
MAX_LINE_CHARS = 4_000
MAX_TRANSACTIONS = 10_000
ERROR_MESSAGES = {
    "invalid_pdf": "The PDF could not be read. Choose the original Silvey invoice.",
    "encrypted_pdf": "Password-protected PDFs are not supported. Choose an unprotected Silvey invoice.",
    "too_large": "The invoice is too large or contains too much text. Choose a file under 10 MB.",
    "too_many_pages": "Choose a Silvey invoice with no more than 20 pages.",
    "no_text": "This PDF has no readable text. Choose the original digital Silvey invoice.",
    "reader_unavailable": "The invoice reader is unavailable. Install the app requirements and try again.",
    "processing_failed": "The PDF could not be processed safely. Try the original Silvey invoice.",
    "unsupported_layout": "This does not match the supported Silvey invoice layout. Choose the original digital invoice.",
    "incomplete_transactions": "The invoice transaction table is incomplete or ambiguous. Check the original invoice.",
    "reconciliation_failed": "The transaction amounts or litres do not match the invoice totals. Check the original invoice.",
}
_CENT = Decimal("0.01")
_MAX_NUMBER = Decimal("999999999999.99")
_DIGITS = r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)"
_MONEY = rf"-?{_DIGITS}\.[0-9]{{2}}"
_RATE = rf"-?{_DIGITS}(?:\.[0-9]{{1,6}})?"
_SUMMARY_HEADER = "PRODUCT DESCRIPTION QUANTITY £ UNIT PRICE £ VALUE VAT CODE"
_TABLE_HEADER = "CARD NO SITE CODE & NAME DATE TIME REG. ODOMETER LITRES PRICE"
_SUMMARY_ROW = re.compile(
    rf"(?P<product>[A-Za-z][A-Za-z0-9 &()/.-]{{0,100}}?)\s+"
    rf"(?P<quantity>{_MONEY})\s+(?P<rate>{_RATE})\s+(?P<cost>{_MONEY})\s+(?P<vat>[A-Za-z0-9]{{1,3}})\Z"
)
_TRANSACTION = re.compile(
    rf"(?P<card>[0-9]{{4,20}})\s+(?P<site>[0-9]{{1,10}})\s+"
    rf"(?P<place>.{{1,120}}?)\s+(?P<product>[A-Za-z][A-Za-z0-9()/.-]{{0,49}})\s+"
    rf"(?P<date>[0-9]{{1,2}}/[0-9]{{1,2}}/[0-9]{{2}})\s+"
    rf"(?P<time>[0-9]{{1,2}}:[0-9]{{2}})\s*"
    rf"(?P<registration>[A-Za-z0-9][A-Za-z0-9 -]{{0,19}}?)\s+"
    rf"(?P<odometer>[0-9]{{1,12}})\s+(?P<quantity>{_MONEY})\s+(?P<cost>{_MONEY})\Z"
)
_CARD_TOTAL = re.compile(rf"TOTAL FOR CARD:\s*(?P<cost>{_MONEY})\Z", re.IGNORECASE)
_GRAND_TOTAL = re.compile(rf"GRAND TOTAL:\s*(?P<cost>{_MONEY})\Z", re.IGNORECASE)
_STANDALONE_AMOUNT = re.compile(rf"{_MONEY}\Z")
_FOOTER_START = re.compile(r"TRADING\s*&\s*REGISTERED\s+OF(?:FI|F)?CE\s*:", re.IGNORECASE)
_SUPPLIER = re.compile(r"(?:SILVEY\s+FLEET|SILVEY\s*\.\s*CO\s*\.\s*UK|SILVEYF(?:LE|E)ET\s*\.\s*CO\s*\.\s*UK)", re.IGNORECASE)
_INVOICE_DATE = re.compile(r"\b([0-9]{1,2})-([A-Za-z]{3})-([0-9]{4})\b")
_MONTHS = {name: index for index, name in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}


class SilveyPDFError(ValueError):
    """A fixed public error; never contains document data or parser details."""

    def __init__(self, code):
        self.code = code
        super().__init__(ERROR_MESSAGES[code])


def _number(value):
    try:
        result = Decimal(value.replace(",", ""))
        if not result.is_finite() or abs(result) > _MAX_NUMBER:
            raise SilveyPDFError("incomplete_transactions")
        return result
    except InvalidOperation:
        raise SilveyPDFError("incomplete_transactions") from None


def _product(value):
    return re.sub(r"^KEYFUELS?\s+", "", " ".join(value.split()).upper())


def _lines(pages):
    if (not isinstance(pages, (list, tuple)) or not pages
            or not all(isinstance(page, str) for page in pages)):
        raise SilveyPDFError("invalid_pdf")
    if len(pages) > MAX_PDF_PAGES:
        raise SilveyPDFError("too_many_pages")
    if sum(len(page) for page in pages) > MAX_PDF_TEXT_CHARS:
        raise SilveyPDFError("too_large")
    result = []
    for page in pages:
        lines = page.replace("\xa0", " ").replace("\u2212", "-").splitlines()
        if any(len(line) > MAX_LINE_CHARS for line in lines):
            raise SilveyPDFError("too_large")
        result.append([" ".join(line.split()) for line in lines if line.strip()])
    if not any(result):
        raise SilveyPDFError("no_text")
    return result


def _summary(first_page):
    try:
        start = next(index for index, line in enumerate(first_page)
                     if line.upper() == _SUMMARY_HEADER)
    except StopIteration:
        raise SilveyPDFError("unsupported_layout") from None
    summary = defaultdict(lambda: [Decimal("0.00"), Decimal("0.00")])
    for line in first_page[start + 1:]:
        match = _SUMMARY_ROW.fullmatch(line)
        if not match:
            if (_STANDALONE_AMOUNT.fullmatch(line) or line.upper().startswith(("VAT CODE", "£ TOTAL", "TERMS:"))):
                break
            raise SilveyPDFError("unsupported_layout")
        key = _product(match["product"]), _number(match["rate"])
        quantity, cost = _number(match["quantity"]), _number(match["cost"])
        summary[key][0] += quantity
        summary[key][1] += cost
    if not summary:
        raise SilveyPDFError("unsupported_layout")
    return summary


def _invoice_date(first_page):
    # The payment due date is not an invoice-date candidate. In particular,
    # "May" is both a full month name and a three-letter abbreviation.
    try:
        summary_start = next(index for index, line in enumerate(first_page)
                             if line.upper() == _SUMMARY_HEADER)
    except StopIteration:
        raise SilveyPDFError("unsupported_layout") from None
    dates = set()
    for day, month, year in _INVOICE_DATE.findall("\n".join(first_page[:summary_start])):
        try:
            dates.add(datetime(int(year), _MONTHS[month.lower()], int(day)).date())
        except (KeyError, ValueError):
            raise SilveyPDFError("unsupported_layout") from None
    if len(dates) != 1:
        raise SilveyPDFError("unsupported_layout")
    return dates.pop()


def _purchase_date(value, issued):
    day, month, year = map(int, value.split("/"))
    # The printed invoice year anchors two-digit transaction years. Previous
    # December may appear on a January invoice; a machine-era pivot may not.
    years = [candidate for candidate in (issued.year - 1, issued.year)
             if candidate >= 1 and candidate % 100 == year]
    try:
        if len(years) != 1:
            raise ValueError("Ambiguous year")
        result = datetime(years[0], month, day).date()
        if result > issued:
            raise ValueError("Transaction follows invoice")
        return result
    except ValueError:
        raise SilveyPDFError("incomplete_transactions") from None


def _purchase_like(line):
    return bool(_TRANSACTION.fullmatch(line)
                or re.match(r"[0-9]{4,20}\s+[0-9]{1,10}\b", line)
                or re.search(r"\b[0-9]{1,2}/[0-9]{1,2}/[0-9]{2}\b", line)
                or line.upper().startswith(("TOTAL FOR CARD:", "GRAND TOTAL:")))


def _report_from_pages(pages):
    """Validate every transaction, card total and product/rate summary."""
    lines_by_page = _lines(pages)
    text = "\n".join(line for page in lines_by_page for line in page)
    if not _SUPPLIER.search(text) or "SALES INVOICE" not in text.upper():
        raise SilveyPDFError("unsupported_layout")
    issued = _invoice_date(lines_by_page[0])
    summary = _summary(lines_by_page[0])
    actual_summary = defaultdict(lambda: [Decimal("0.00"), Decimal("0.00")])
    rows = []
    current_card = None
    card_cost = Decimal("0.00")
    closed_cards = set()
    grand_total = None
    for page_number, lines in enumerate(lines_by_page, start=1):
        table_started = False
        footer = False
        for line in lines:
            if line.upper() == _TABLE_HEADER:
                if table_started or grand_total is not None:
                    raise SilveyPDFError("incomplete_transactions")
                table_started = True
                footer = False
                continue
            if not table_started:
                # Only the first page may have the invoice summary before the
                # transaction table; continuation pages must start their table.
                if page_number > 1 or _purchase_like(line):
                    raise SilveyPDFError("incomplete_transactions")
                continue
            if _FOOTER_START.match(line):
                footer = True
                continue
            if footer:
                # A transaction-looking line must never disappear into a
                # footer, even when a malformed file repeats supplier text.
                if _purchase_like(line):
                    raise SilveyPDFError("incomplete_transactions")
                continue
            card_total = _CARD_TOTAL.fullmatch(line)
            if card_total:
                if current_card is None or _number(card_total["cost"]) != card_cost:
                    raise SilveyPDFError("reconciliation_failed")
                closed_cards.add(current_card)
                current_card, card_cost = None, Decimal("0.00")
                continue
            total = _GRAND_TOTAL.fullmatch(line)
            if total:
                if current_card is not None or grand_total is not None or not rows:
                    raise SilveyPDFError("incomplete_transactions")
                grand_total = _number(total["cost"])
                continue
            if grand_total is not None:
                raise SilveyPDFError("incomplete_transactions")
            match = _TRANSACTION.fullmatch(line)
            if not match or len(rows) >= MAX_TRANSACTIONS:
                raise SilveyPDFError("incomplete_transactions")
            card = match["card"]
            if card in closed_cards or current_card is not None and card != current_card:
                raise SilveyPDFError("incomplete_transactions")
            current_card = card
            quantity, cost = _number(match["quantity"]), _number(match["cost"])
            product = _product(match["product"])
            with localcontext() as context:
                context.prec = 50
                rates = [rate for (candidate, rate) in summary
                         if candidate == product and (quantity * rate).quantize(_CENT, rounding=ROUND_HALF_UP) == cost]
            if len(rates) != 1:
                raise SilveyPDFError("reconciliation_failed")
            unit_price = rates[0]
            actual_summary[(product, unit_price)][0] += quantity
            actual_summary[(product, unit_price)][1] += cost
            try:
                on_date = _purchase_date(match["date"], issued)
                hour, minute = map(int, match["time"].split(":"))
                at_time = datetime(2000, 1, 1, hour, minute).time()
            except ValueError:
                raise SilveyPDFError("incomplete_transactions") from None
            registration = " ".join(match["registration"].upper().split())
            issues = []
            if product not in {"DERV", "DIESEL"}:
                issues.append("unsupported_product")
            if quantity <= 0:
                issues.append("non_positive_quantity")
            if cost <= 0:
                issues.append("non_positive_cost")
            rows.append(FuelTransaction(
                source_row=len(rows) + 1, transaction_date=on_date, transaction_time=at_time,
                transaction_registration=registration, card_registration=None,
                card_type="Silvey", product=match["product"], quantity=quantity,
                cost=cost, unit_price=unit_price, issues=tuple(issues), source_page=page_number,
            ))
            card_cost += cost
        if not table_started:
            raise SilveyPDFError("incomplete_transactions")
    total_quantity = sum((row.quantity for row in rows), Decimal("0.00"))
    total_cost = sum((row.cost for row in rows), Decimal("0.00"))
    if (current_card is not None or grand_total is None or grand_total != total_cost
            or dict(actual_summary) != dict(summary)):
        raise SilveyPDFError("reconciliation_failed")
    return FuelTransactionsReport(
        sheet_name="Silvey invoice", header_row=1, rows=tuple(rows),
        source_format="silvey-fuel-invoice-pdf-v1", fuel_card_name="Silvey",
        document_kind="pdf", page_count=len(pages),
        printed_total_quantity=total_quantity, printed_total_cost=grand_total,
    )


def read_silvey_pdf(content):
    """Read trusted local PDF bytes; HTTP uploads must use the isolated wrapper."""
    if not isinstance(content, bytes):
        raise SilveyPDFError("invalid_pdf")
    if len(content) > MAX_PDF_BYTES:
        raise SilveyPDFError("too_large")
    if not content.lstrip().startswith(b"%PDF-"):
        raise SilveyPDFError("invalid_pdf")
    try:
        from haulage_app.payslip.pdf_text import extract_pdf_text, PDFTextError
        pages = extract_pdf_text(content, max_bytes=MAX_PDF_BYTES, max_pages=MAX_PDF_PAGES,
                                 max_text_chars=MAX_PDF_TEXT_CHARS)
    except ImportError:
        raise SilveyPDFError("reader_unavailable") from None
    except PDFTextError as error:
        raise SilveyPDFError(error.code) from None
    return _report_from_pages(pages)
