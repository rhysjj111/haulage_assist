"""Bounded, short-lived Silvey PDF processing for the fuel upload."""

from datetime import date, time
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import sys
import time as clock

from haulage_app.document_processing import worker_environment

from . import xlsx_reader


MAX_PDF_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 20
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
PROCESS_TIMEOUT_SECONDS = 10
_WORKER = Path(__file__).with_name("silvey_worker.py")
_ERROR_MESSAGES = {
    "processing_failed": "The PDF could not be processed safely. Try the original Silvey invoice.",
    "processing_timeout": "Reading this PDF took too long. Try a smaller or freshly downloaded Silvey invoice.",
}
_ISSUES = frozenset({
    "missing_transaction_registration", "registration_mismatch", "unsupported_product",
    "non_positive_quantity", "non_positive_cost", "cost_price_mismatch",
})
_REPORT_KEYS = frozenset({
    "sheet_name", "header_row", "source_format", "fuel_card_name", "document_kind",
    "page_count", "printed_total_quantity", "printed_total_cost", "rows",
})
_ROW_KEYS = frozenset({
    "source_row", "source_page", "transaction_date", "transaction_time",
    "transaction_registration", "card_registration", "card_type", "product",
    "quantity", "cost", "unit_price", "issues",
})


class SilveyPDFProcessingError(ValueError):
    """A fixed infrastructure error, without document or subprocess details."""

    def __init__(self, code):
        self.code = code
        super().__init__(_ERROR_MESSAGES[code])


def _failed():
    return SilveyPDFProcessingError("processing_failed")


def _run_worker(content):
    """Bound both pipe traffic and wall time, then reap every child."""
    process = subprocess.Popen(
        [sys.executable, "-B", str(_WORKER)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        close_fds=True,
        env=worker_environment(),
    )
    deadline = clock.monotonic() + PROCESS_TIMEOUT_SECONDS
    output = bytearray()
    position = 0
    try:
        with selectors.DefaultSelector() as selector:
            os.set_blocking(process.stdin.fileno(), False)
            os.set_blocking(process.stdout.fileno(), False)
            selector.register(process.stdin, selectors.EVENT_WRITE)
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - clock.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(process.args, PROCESS_TIMEOUT_SECONDS)
                ready = selector.select(remaining)
                if not ready:
                    raise subprocess.TimeoutExpired(process.args, PROCESS_TIMEOUT_SECONDS)
                for key, _ in ready:
                    if key.fileobj is process.stdin:
                        try:
                            position += os.write(key.fd, memoryview(content)[position:position + 65536])
                        except BrokenPipeError:
                            position = len(content)
                        if position >= len(content):
                            selector.unregister(process.stdin)
                            process.stdin.close()
                    else:
                        chunk = os.read(key.fd, 65536)
                        if not chunk:
                            selector.unregister(process.stdout)
                        elif len(output) + len(chunk) > MAX_OUTPUT_BYTES:
                            raise _failed()
                        else:
                            output.extend(chunk)
        returncode = process.wait(timeout=max(0.001, deadline - clock.monotonic()))
        return returncode, bytes(output)
    except BaseException:
        # Timeout, cancellation and over-large output must not leave a parser
        # consuming CPU/memory after the parent has stopped using its result.
        if process.poll() is None:
            process.kill()
        process.wait()
        raise
    finally:
        process.stdin.close()
        process.stdout.close()


def _text(value, *, optional=False):
    if optional and value is None:
        return None
    if not isinstance(value, str) or not 0 < len(value) <= 200 or not value.strip():
        raise _failed()
    return value


def _number(value, *, two_decimals=False, total=False):
    if not isinstance(value, str) or len(value) > 64:
        raise _failed()
    digits = 16 if total else 12
    pattern = rf"-?[0-9]{{1,{digits}}}\.[0-9]{{2}}" if two_decimals else r"-?[0-9]+(?:\.[0-9]+)?(?:[Ee][+-]?[0-9]+)?"
    if not re.fullmatch(pattern, value):
        raise _failed()
    try:
        number = Decimal(value)
        limit = Decimal("9999999999999999.99" if total else "999999999999.99")
        if not number.is_finite() or abs(number) > limit:
            raise _failed()
    except InvalidOperation:
        raise _failed() from None
    return number


def _report(data):
    if (not isinstance(data, dict) or set(data) != _REPORT_KEYS
            or data["sheet_name"] != "Silvey invoice"
            or type(data["header_row"]) is not int or data["header_row"] != 1
            or data["source_format"] != "silvey-fuel-invoice-pdf-v1"
            or data["fuel_card_name"] != "Silvey" or data["document_kind"] != "pdf"
            or type(data["page_count"]) is not int
            or not 1 <= data["page_count"] <= MAX_PDF_PAGES
            or not isinstance(data["rows"], list)
            or not 0 < len(data["rows"]) <= xlsx_reader.MAX_ROWS):
        raise _failed()
    printed_quantity = _number(data["printed_total_quantity"], two_decimals=True, total=True)
    printed_cost = _number(data["printed_total_cost"], two_decimals=True, total=True)
    rows = []
    previous_page = 1
    for index, value in enumerate(data["rows"], start=1):
        if (not isinstance(value, dict) or set(value) != _ROW_KEYS
                or type(value["source_row"]) is not int or value["source_row"] != index
                or type(value["source_page"]) is not int
                or not previous_page <= value["source_page"] <= data["page_count"]
                or value["card_type"] != "Silvey"
                or value["card_registration"] is not None
                or not isinstance(value["issues"], list)
                or not all(isinstance(issue, str) and issue in _ISSUES for issue in value["issues"])
                or len(value["issues"]) != len(set(value["issues"]))):
            raise _failed()
        previous_page = value["source_page"]
        try:
            if not isinstance(value["transaction_date"], str) or len(value["transaction_date"]) != 10:
                raise _failed()
            on_date = date.fromisoformat(value["transaction_date"])
            if on_date.isoformat() != value["transaction_date"]:
                raise _failed()
            at_time = None
            if value["transaction_time"] is not None:
                if not isinstance(value["transaction_time"], str) or len(value["transaction_time"]) > 15:
                    raise _failed()
                at_time = time.fromisoformat(value["transaction_time"])
                if at_time.tzinfo is not None or at_time.isoformat() != value["transaction_time"]:
                    raise _failed()
        except (ValueError, TypeError):
            raise _failed() from None
        rows.append(xlsx_reader.FuelTransaction(
            source_row=index, source_page=value["source_page"],
            transaction_date=on_date, transaction_time=at_time,
            transaction_registration=_text(value["transaction_registration"], optional=True),
            card_registration=None, card_type="Silvey", product=_text(value["product"]),
            quantity=_number(value["quantity"], two_decimals=True),
            cost=_number(value["cost"], two_decimals=True), unit_price=_number(value["unit_price"]),
            issues=tuple(value["issues"]),
        ))
    report = xlsx_reader.FuelTransactionsReport(
        sheet_name="Silvey invoice", header_row=1, rows=tuple(rows),
        source_format="silvey-fuel-invoice-pdf-v1", fuel_card_name="Silvey",
        document_kind="pdf", page_count=data["page_count"],
        printed_total_quantity=printed_quantity, printed_total_cost=printed_cost,
    )
    if (report.calculated_total_quantity != printed_quantity
            or report.calculated_total_cost != printed_cost):
        raise _failed()
    return report


def read_silvey_pdf_isolated(content: bytes) -> xlsx_reader.FuelTransactionsReport:
    """Read a full invoice in an isolated parser; never return partial rows."""
    from .silvey_reader import ERROR_MESSAGES, SilveyPDFError

    if not isinstance(content, bytes):
        raise SilveyPDFError("invalid_pdf")
    if len(content) > MAX_PDF_BYTES:
        raise SilveyPDFError("too_large")
    if not content.lstrip().startswith(b"%PDF-"):
        raise SilveyPDFError("invalid_pdf")
    try:
        returncode, output = _run_worker(content)
    except subprocess.TimeoutExpired:
        raise SilveyPDFProcessingError("processing_timeout") from None
    except (OSError, subprocess.SubprocessError):
        raise _failed() from None
    if returncode != 0:
        if returncode == -getattr(signal, "SIGXCPU", 24):
            raise SilveyPDFProcessingError("processing_timeout")
        raise _failed()
    if not isinstance(output, bytes) or len(output) > MAX_OUTPUT_BYTES:
        raise _failed()
    try:
        data = json.loads(output)
    except (ValueError, UnicodeError, RecursionError):
        raise _failed() from None
    if isinstance(data, dict) and set(data) == {"error"}:
        code = data["error"]
        if isinstance(code, str) and code in _ERROR_MESSAGES:
            raise SilveyPDFProcessingError(code)
        if isinstance(code, str) and code in ERROR_MESSAGES:
            raise SilveyPDFError(code)
        raise _failed()
    return _report(data)
