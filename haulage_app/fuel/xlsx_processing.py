"""Isolated Excel parsing for the upload preview, with bounded pipe traffic."""

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


PROCESS_TIMEOUT_SECONDS = 10
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
_WORKER = Path(__file__).with_name("xlsx_worker.py")
_ERROR_MESSAGES = {
    "processing_failed": "The spreadsheet could not be processed safely. Try the original Transactions export.",
    "processing_timeout": "Reading this spreadsheet took too long. Try a smaller Transactions export.",
}
_ISSUES = frozenset({
    "missing_transaction_registration", "registration_mismatch", "unsupported_product",
    "non_positive_quantity", "non_positive_cost", "cost_price_mismatch",
})
_ROW_KEYS = frozenset({
    "source_row", "transaction_date", "transaction_time", "transaction_registration",
    "card_registration", "card_type", "product", "quantity", "cost", "unit_price", "issues",
})


class FuelXLSXProcessingError(ValueError):
    """Fixed infrastructure error; contains no source or subprocess details."""

    def __init__(self, code):
        self.code = code
        super().__init__(_ERROR_MESSAGES[code])


def _failed():
    return FuelXLSXProcessingError("processing_failed")


def _run_worker(content):
    """Drain and fill both pipes without allowing unlimited output buffering."""
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
        # In particular, do not leave a parser running after a timeout, early
        # disconnect, parent cancellation or output limit failure.
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


def _number(value, *, two_decimals=False):
    if not isinstance(value, str) or len(value) > 64:
        raise _failed()
    pattern = r"-?[0-9]{1,12}\.[0-9]{2}" if two_decimals else r"-?[0-9]+(?:\.[0-9]+)?(?:[Ee][+-]?[0-9]+)?"
    if not re.fullmatch(pattern, value):
        raise _failed()
    try:
        number = Decimal(value)
        if not number.is_finite() or abs(number) > Decimal("999999999999.99"):
            raise _failed()
    except InvalidOperation:
        raise _failed() from None
    return number


def _report(data):
    if (not isinstance(data, dict)
            or set(data) != {"sheet_name", "header_row", "source_format", "fuel_card_name", "rows"}
            or not isinstance(data["sheet_name"], str) or len(data["sheet_name"]) > 200
            or " ".join(data["sheet_name"].split()).casefold() != "transactions"
            or type(data["header_row"]) is not int
            or not 1 <= data["header_row"] <= xlsx_reader.MAX_HEADER_ROWS
            or data["source_format"] != "fuel-store-transactions-xlsx-v1"
            or data["fuel_card_name"] != "The Fuel Store"
            or not isinstance(data["rows"], list)
            or not 0 < len(data["rows"]) <= xlsx_reader.MAX_ROWS):
        raise _failed()
    rows = []
    previous_row = data["header_row"]
    for value in data["rows"]:
        if (not isinstance(value, dict) or set(value) != _ROW_KEYS
                or type(value["source_row"]) is not int
                or not previous_row < value["source_row"] <= xlsx_reader.MAX_ROWS + xlsx_reader.MAX_HEADER_ROWS
                or not isinstance(value["issues"], list)
                or not all(isinstance(issue, str) and issue in _ISSUES for issue in value["issues"])
                or len(value["issues"]) != len(set(value["issues"]))):
            raise _failed()
        previous_row = value["source_row"]
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
            source_row=value["source_row"], transaction_date=on_date, transaction_time=at_time,
            transaction_registration=_text(value["transaction_registration"], optional=True),
            card_registration=_text(value["card_registration"], optional=True),
            card_type=_text(value["card_type"]), product=_text(value["product"]),
            quantity=_number(value["quantity"], two_decimals=True),
            cost=_number(value["cost"], two_decimals=True), unit_price=_number(value["unit_price"]),
            issues=tuple(value["issues"]),
        ))
    return xlsx_reader.FuelTransactionsReport(
        sheet_name=data["sheet_name"], header_row=data["header_row"], rows=tuple(rows),
    )


def read_fuel_store_xlsx_isolated(content: bytes) -> xlsx_reader.FuelTransactionsReport:
    """Read an upload without parsing its ZIP/XML in the Flask process."""
    if not isinstance(content, bytes):
        raise xlsx_reader.FuelXLSXError("invalid_workbook")
    if len(content) > xlsx_reader.MAX_XLSX_BYTES:
        raise xlsx_reader.FuelXLSXError("too_large")
    if not content.startswith(b"PK\x03\x04"):
        raise xlsx_reader.FuelXLSXError("invalid_workbook")
    try:
        returncode, output = _run_worker(content)
    except subprocess.TimeoutExpired:
        raise FuelXLSXProcessingError("processing_timeout") from None
    except (OSError, subprocess.SubprocessError):
        raise _failed() from None
    if returncode != 0:
        if returncode == -getattr(signal, "SIGXCPU", 24):
            raise FuelXLSXProcessingError("processing_timeout")
        raise _failed()
    if not isinstance(output, bytes) or len(output) > MAX_OUTPUT_BYTES:
        raise _failed()
    try:
        data = json.loads(output)
    except (ValueError, UnicodeError, RecursionError):
        raise _failed() from None
    if isinstance(data, dict) and set(data) == {"error"}:
        code = data["error"]
        if isinstance(code, str) and code in xlsx_reader._MESSAGES:
            raise xlsx_reader.FuelXLSXError(code)
        if isinstance(code, str) and code in _ERROR_MESSAGES:
            raise FuelXLSXProcessingError(code)
        raise _failed()
    return _report(data)
