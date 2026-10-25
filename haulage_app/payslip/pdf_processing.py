"""Bounded, short-lived PDF processing for the upload-and-review endpoint."""

import json
from pathlib import Path
import signal
import subprocess
import sys

from haulage_app.document_processing import worker_environment

from . import pdf_reader
from .pdf_text import ERROR_MESSAGES, PDFTextError, validate_pdf_bytes


PROCESS_TIMEOUT_SECONDS = 10
_WORKER = Path(__file__).with_name("pdf_text.py")
_FAILED_MESSAGE = "The PDF could not be processed safely. Try the original digital report."
_TIMEOUT_MESSAGE = "Reading this PDF took too long. Try a smaller or freshly exported digital report."


def _failed():
    return pdf_reader.PayrollPDFError("processing_failed", _FAILED_MESSAGE)


def read_payroll_pdf_isolated(content: bytes) -> pdf_reader.PayrollReport:
    """Read one PDF without exposing the web worker to PDF decompression work.

    The child imports no app/database code. Its CPU, memory and file creation
    are limited inside the child; the parent also enforces a wall-clock timeout.
    Document bytes/text exist only in process memory and private stdin/stdout
    pipes, never file paths, command arguments, logs or a persistent cache.
    """
    max_bytes = pdf_reader.MAX_PDF_BYTES
    max_pages = pdf_reader.MAX_PDF_PAGES
    max_text = pdf_reader.MAX_PDF_TEXT_CHARS
    try:
        validate_pdf_bytes(content, max_bytes=max_bytes)
    except PDFTextError as error:
        raise pdf_reader.PayrollPDFError(error.code, str(error)) from None
    try:
        result = subprocess.run(
            [sys.executable, "-B", str(_WORKER), str(max_bytes), str(max_pages), str(max_text)],
            input=content, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=PROCESS_TIMEOUT_SECONDS, check=False, close_fds=True,
            env=worker_environment(),
        )
    except subprocess.TimeoutExpired:
        raise pdf_reader.PayrollPDFError("processing_timeout", _TIMEOUT_MESSAGE) from None
    except (OSError, subprocess.SubprocessError):
        raise _failed() from None
    if result.returncode != 0:
        if result.returncode == -getattr(signal, "SIGXCPU", 24):
            raise pdf_reader.PayrollPDFError("processing_timeout", _TIMEOUT_MESSAGE)
        raise _failed()
    # ensure_ascii=True expands a character by at most six bytes. The worker
    # itself enforces the character/page budgets before emitting this JSON.
    max_output = max_text * 6 + max_pages * 10 + 1024
    if not isinstance(result.stdout, bytes) or len(result.stdout) > max_output:
        raise _failed()
    try:
        data = json.loads(result.stdout)
    except (ValueError, UnicodeError):
        raise _failed() from None
    if not isinstance(data, dict):
        raise _failed()
    if set(data) == {"error"}:
        code = data["error"]
        if not isinstance(code, str) or code not in ERROR_MESSAGES:
            raise _failed()
        raise pdf_reader.PayrollPDFError(code, ERROR_MESSAGES[code])
    pages = data.get("pages")
    if (set(data) != {"pages"} or not isinstance(pages, list)
            or not 0 < len(pages) <= max_pages
            or not all(isinstance(page, str) for page in pages)
            or sum(len(page) for page in pages) > max_text):
        raise _failed()
    return pdf_reader._report_from_pages(pages)
