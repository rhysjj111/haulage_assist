"""Standalone resource-limited Silvey PDF extraction and semantic parsing."""

import json
import logging
from pathlib import Path
import sys
import warnings


MAX_PDF_BYTES = 10 * 1024 * 1024
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
WORKER_MEMORY_BYTES = 256 * 1024 * 1024
WORKER_CPU_SECONDS = 8


def _limit_resources():
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


def _payload(report):
    return {
        "sheet_name": report.sheet_name,
        "header_row": report.header_row,
        "source_format": report.source_format,
        "fuel_card_name": report.fuel_card_name,
        "document_kind": report.document_kind,
        "page_count": report.page_count,
        "printed_total_quantity": format(report.printed_total_quantity, ".2f"),
        "printed_total_cost": format(report.printed_total_cost, ".2f"),
        "rows": [{
            "source_row": row.source_row,
            "source_page": row.source_page,
            "transaction_date": row.transaction_date.isoformat(),
            "transaction_time": row.transaction_time.isoformat() if row.transaction_time else None,
            "transaction_registration": row.transaction_registration,
            "card_registration": row.card_registration,
            "card_type": row.card_type,
            "product": row.product,
            "quantity": format(row.quantity, ".2f"),
            "cost": format(row.cost, ".2f"),
            "unit_price": str(row.unit_price),
            "issues": list(row.issues),
        } for row in report.rows],
    }


def _bounded_json(payload):
    output = bytearray()
    for chunk in json.JSONEncoder(ensure_ascii=True, separators=(",", ":")).iterencode(payload):
        encoded = chunk.encode("ascii")
        if len(output) + len(encoded) > MAX_OUTPUT_BYTES:
            return b'{"error":"too_large"}'
        output.extend(encoded)
    return bytes(output)


def _main():
    logging.disable(logging.CRITICAL)
    result = b'{"error":"processing_failed"}'
    try:
        _limit_resources()
        # Import standalone sibling modules only after the limits apply. This
        # does not run haulage_app/__init__.py or load configured database URLs.
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "payslip"))
        from pdf_text import PDFTextError, extract_pdf_text
        from silvey_reader import SilveyPDFError, _report_from_pages

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                content = sys.stdin.buffer.read(MAX_PDF_BYTES + 1)
                report = _report_from_pages(extract_pdf_text(content))
                result = _bounded_json(_payload(report))
        except (PDFTextError, SilveyPDFError) as error:
            result = _bounded_json({"error": error.code})
    except Exception:
        # Fixed output on exhausted resources, unavailable controls/dependency
        # or parser faults; never source text, paths or exception messages.
        pass
    sys.stdout.buffer.write(result)


if __name__ == "__main__":
    _main()
