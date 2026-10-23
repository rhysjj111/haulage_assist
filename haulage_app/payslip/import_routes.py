"""Temporary PDF-to-preview endpoints; no payslip-saving action."""

from collections import defaultdict

from flask import current_app, jsonify, make_response, render_template, request, url_for
from flask_wtf.csrf import generate_csrf, validate_csrf
from sqlalchemy.exc import SQLAlchemyError
from wtforms.validators import ValidationError

from haulage_app import db
from haulage_app.driver.choices import get_entry_drivers
from haulage_app.payslip import payslip_bp


def _private_response(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def _error(code, message, status):
    response = jsonify(error={"code": code, "message": message})
    response.status_code = status
    return _private_response(response)


def _normalise_name(value):
    return " ".join(value.split()).casefold()


def _preview_payload(report):
    # Use the same active-driver list as manual Add Payslip. Suggestions do not
    # create drivers, change employment records or silently guess a near match.
    with db.session.no_autoflush:
        drivers = get_entry_drivers()
    choices = [{"id": driver.id, "name": driver.full_name} for driver in drivers]
    names = defaultdict(list)
    for driver in choices:
        names[_normalise_name(driver["name"])].append(driver["id"])
    rows = []
    for index, row in enumerate(report.rows, start=1):
        candidates = names.get(_normalise_name(row.employee_name), [])
        status = "matched" if len(candidates) == 1 else "ambiguous" if candidates else "unmatched"
        rows.append({
            "source_index": index,
            "employee_name": row.employee_name,
            "driver_id": candidates[0] if len(candidates) == 1 else None,
            "match_status": status,
            "candidate_driver_ids": candidates,
            # These are Decimal pounds for the review controls, not DB pence.
            "total_wage": format(row.total_payments, ".2f"),
            "total_cost_to_employer": format(row.total_cost_to_employer, ".2f"),
            "page_number": row.page_number,
        })
    return {
        "report": {
            "pay_date": report.pay_date.isoformat(),
            "week_start": report.week_start.isoformat(),
            "week_end": report.week_end.isoformat(),
            "employee_count": len(report.rows),
            "totals": {
                "total_payments": format(report.totals.total_payments, ".2f"),
                "total_cost_to_employer": format(report.totals.total_cost_to_employer, ".2f"),
            },
        },
        "drivers": choices,
        "rows": rows,
    }


@payslip_bp.route("/import", methods=["GET"])
def import_preview():
    with db.session.no_autoflush:
        response = make_response(render_template(
            "payslip/import_preview.html",
            csrf_token=generate_csrf(),
            read_url=url_for("payslip.read_import_pdf"),
        ))
    return _private_response(response)


@payslip_bp.route("/import/read", methods=["POST"])
def read_import_pdf():
    if current_app.config.get("WTF_CSRF_ENABLED", True):
        try:
            validate_csrf(request.headers.get("X-CSRFToken"))
        except ValidationError:
            return _error("csrf_failed", "Refresh this page and choose the PDF again.", 403)

    # Import after application setup, avoiding eager blueprint/app cycles and
    # allowing tests to exercise the exact worker used by the upload endpoint.
    from haulage_app.payslip.pdf_processing import read_payroll_pdf_isolated
    from haulage_app.payslip.pdf_reader import MAX_PDF_BYTES, PayrollPDFError

    if request.mimetype != "application/pdf":
        return _error("unsupported_media_type", "Choose the original digital PDF management report.", 415)
    if request.content_length is not None and request.content_length > MAX_PDF_BYTES:
        return _error("too_large", "The PDF is too large. Use a report under 10 MB.", 413)

    # A raw PDF body avoids multipart temporary-file spooling. Neither request
    # bytes nor proposed rows are stored in a cookie, session draft or archive.
    content = request.stream.read(MAX_PDF_BYTES + 1)
    if len(content) > MAX_PDF_BYTES:
        return _error("too_large", "The PDF is too large. Use a report under 10 MB.", 413)
    try:
        report = read_payroll_pdf_isolated(content)
        payload = _preview_payload(report)
    except PayrollPDFError as error:
        status = 413 if error.code == "too_large" else 503 if error.code in {
            "processing_timeout", "processing_failed",
        } else 422
        return _error(error.code, str(error), status)
    except SQLAlchemyError:
        return _error("preview_unavailable", "Driver choices could not be loaded. Please try again.", 503)
    return _private_response(jsonify(payload))
