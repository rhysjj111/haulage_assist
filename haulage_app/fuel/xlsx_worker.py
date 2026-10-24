"""Standalone, bounded Excel worker; deliberately imports no Flask package.

The spreadsheet travels only through private pipes. The reader is imported by
its sibling module name after resource limits apply, so app/database startup
and configured credentials are absent from this process.
"""

import json
import logging
import sys


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

    # Fail closed on platforms without the Linux controls used in production.
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
        "rows": [{
            "source_row": row.source_row,
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
        # Direct sibling import, never `haulage_app.fuel`, which boots Flask.
        from xlsx_reader import FuelXLSXError, MAX_XLSX_BYTES, read_fuel_store_transactions_xlsx

        try:
            content = sys.stdin.buffer.read(MAX_XLSX_BYTES + 1)
            result = _bounded_json(_payload(read_fuel_store_transactions_xlsx(content)))
        except FuelXLSXError as error:
            result = _bounded_json({"error": error.code})
    except Exception:
        # Never expose parser exceptions, worksheet cells, paths or tracebacks.
        pass
    sys.stdout.buffer.write(result)


if __name__ == "__main__":
    _main()
