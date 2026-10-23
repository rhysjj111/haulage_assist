"""PDF text extraction shared by the reader and its isolated upload worker.

Running this file directly starts a short-lived, resource-limited process. It
does not import the Flask application, open a database, write document files,
or interpret document text as instructions. Its only output is bounded JSON
sent back through the parent process's private pipe.
"""

from io import BytesIO
import json
import logging
import sys


MAX_PDF_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 20
MAX_PDF_TEXT_CHARS = 250_000
WORKER_MEMORY_BYTES = 256 * 1024 * 1024
WORKER_CPU_SECONDS = 8

ERROR_MESSAGES = {
    "invalid_pdf": "The PDF could not be read. Use the original digital management report.",
    "encrypted_pdf": "Password-protected PDFs are not supported. Use an unprotected copy.",
    "too_large": "The PDF is too large or contains too much text. Use a report under 10 MB.",
    "too_many_pages": "Use a management report with no more than 20 pages.",
    "no_text": "This PDF has no readable text. Scans and photographs are not supported yet.",
    "processing_failed": "The PDF could not be processed safely. Try the original digital report.",
}


class PDFTextError(ValueError):
    """A fixed error code, never extracted document content or a traceback."""

    def __init__(self, code):
        self.code = code
        super().__init__(ERROR_MESSAGES[code])


def validate_pdf_bytes(content, *, max_bytes=MAX_PDF_BYTES):
    if not isinstance(content, bytes):
        raise PDFTextError("invalid_pdf")
    if len(content) > max_bytes:
        raise PDFTextError("too_large")
    if not content.lstrip().startswith(b"%PDF-"):
        raise PDFTextError("invalid_pdf")


def extract_pdf_text(content, *, max_bytes=MAX_PDF_BYTES, max_pages=MAX_PDF_PAGES,
                     max_text_chars=MAX_PDF_TEXT_CHARS):
    """Read exact text under caller-supplied limits; never return partial pages."""
    validate_pdf_bytes(content, max_bytes=max_bytes)
    # Keep this import inside the function: the standalone worker first applies
    # its memory/CPU limits, before loading a PDF library or reading the upload.
    from pypdf import PdfReader

    try:
        reader = PdfReader(BytesIO(content), strict=True)
        if reader.is_encrypted:
            raise PDFTextError("encrypted_pdf")
        if len(reader.pages) > max_pages:
            raise PDFTextError("too_many_pages")
        pages = []
        text_length = 0
        for page in reader.pages:
            text = (page.extract_text() or "").replace("\r\n", "\n").replace("\r", "\n")
            text = text.replace("\xa0", " ").replace("\u2212", "-")
            text_length += len(text)
            if text_length > max_text_chars:
                raise PDFTextError("too_large")
            pages.append(text)
    except PDFTextError:
        raise
    except MemoryError:
        raise PDFTextError("processing_failed") from None
    except Exception:
        # Malformed files can trigger different parser exception types. Never
        # expose their messages: they can contain arbitrary document contents.
        raise PDFTextError("invalid_pdf") from None
    if not any(text.strip() for text in pages):
        raise PDFTextError("no_text")
    return pages


def _limit_resources():
    # Fail closed if the platform cannot supply the limits. Heroku and the
    # supported Codespaces preview run on Linux; no unbounded fallback is used.
    import resource

    def apply(kind, soft, hard=None):
        _, inherited_hard = resource.getrlimit(kind)
        hard = soft if hard is None else hard
        if inherited_hard != resource.RLIM_INFINITY:
            hard = min(hard, inherited_hard)
        resource.setrlimit(kind, (min(soft, hard), hard))

    apply(resource.RLIMIT_AS, WORKER_MEMORY_BYTES)
    apply(resource.RLIMIT_CPU, WORKER_CPU_SECONDS, WORKER_CPU_SECONDS + 1)
    apply(resource.RLIMIT_CORE, 0)
    apply(resource.RLIMIT_FSIZE, 0)
    apply(resource.RLIMIT_NOFILE, 64)


def _main():
    logging.disable(logging.CRITICAL)
    result = {"error": "processing_failed"}
    try:
        _limit_resources()
        defaults = (MAX_PDF_BYTES, MAX_PDF_PAGES, MAX_PDF_TEXT_CHARS)
        limits = tuple(map(int, sys.argv[1:])) if len(sys.argv) > 1 else defaults
        if len(limits) != 3 or any(not 0 < value <= maximum
                                   for value, maximum in zip(limits, defaults)):
            raise ValueError("Unsupported limits")
        max_bytes, max_pages, max_text_chars = limits
        content = sys.stdin.buffer.read(max_bytes + 1)
        result = {"pages": extract_pdf_text(content, max_bytes=max_bytes,
                                            max_pages=max_pages, max_text_chars=max_text_chars)}
    except PDFTextError as error:
        result = {"error": error.code}
    except Exception:
        # This includes unsupported resource controls and exhausted memory.
        # No input, exception message or source path is printed to either pipe.
        pass
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=True).encode("ascii"))


if __name__ == "__main__":
    _main()
