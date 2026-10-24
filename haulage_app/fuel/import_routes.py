"""Temporary spreadsheet upload and editable fuel review, without saving."""

from collections import defaultdict

from flask import current_app, jsonify, make_response, render_template, request, url_for
from flask_wtf.csrf import generate_csrf, validate_csrf
from sqlalchemy.exc import SQLAlchemyError
from wtforms.validators import ValidationError

from haulage_app import db
from haulage_app.fuel import fuel_bp
from haulage_app.models import Truck


XLSX_MIMETYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _private_response(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def _error(code, message, status):
    response = jsonify(error={"code": code, "message": message})
    response.status_code = status
    return _private_response(response)


def _normalise_registration(value):
    return "".join((value or "").split()).upper()


def _preview_payload(report):
    # Read only the fields needed for choosing a truck. A source registration
    # never creates a new truck or chooses a driver/day on the user's behalf.
    with db.session.no_autoflush:
        trucks = db.session.query(Truck.id, Truck.registration).order_by(
            Truck.registration, Truck.id,
        ).all()
    choices = [{"id": truck.id, "registration": truck.registration} for truck in trucks]
    registrations = defaultdict(list)
    for truck in choices:
        registrations[_normalise_registration(truck["registration"])].append(truck["id"])

    rows = []
    for row in report.rows:
        registration = _normalise_registration(row.transaction_registration)
        card_registration = _normalise_registration(row.card_registration)
        candidates = registrations.get(registration, []) if registration else []
        if not registration:
            status = "missing_registration"
        elif card_registration and card_registration != registration:
            status = "registration_conflict"
        elif len(candidates) == 1:
            status = "matched"
        elif candidates:
            status = "ambiguous"
        else:
            status = "unmatched"
        rows.append({
            "source_row": row.source_row,
            "transaction_date": row.transaction_date.isoformat(),
            "transaction_time": row.transaction_time.isoformat() if row.transaction_time else None,
            "transaction_registration": row.transaction_registration,
            "card_registration": row.card_registration,
            "card_type": row.card_type,
            "product": row.product,
            # Decimal pounds/litres, not the database's integer hundredths.
            "quantity": format(row.quantity, ".2f"),
            "cost": format(row.cost, ".2f"),
            "unit_price": str(row.unit_price),
            "issues": list(row.issues),
            "truck_id": candidates[0] if status == "matched" else None,
            "match_status": status,
            "candidate_truck_ids": candidates,
        })
    return {
        "report": {
            "source_format": report.source_format,
            "fuel_card_name": report.fuel_card_name,
            "sheet_name": report.sheet_name,
            "header_row": report.header_row,
            "transaction_count": len(report.rows),
            "totals": {
                "quantity": format(report.calculated_total_quantity, ".2f"),
                "cost": format(report.calculated_total_cost, ".2f"),
            },
        },
        "trucks": choices,
        "rows": rows,
    }


@fuel_bp.route("/import", methods=["GET"])
def import_preview():
    with db.session.no_autoflush:
        response = make_response(render_template(
            "fuel/import_preview.html",
            csrf_token=generate_csrf(),
            read_url=url_for("fuel.read_import_xlsx"),
        ))
    return _private_response(response)


@fuel_bp.route("/import/read", methods=["POST"])
def read_import_xlsx():
    if current_app.config.get("WTF_CSRF_ENABLED", True):
        try:
            validate_csrf(request.headers.get("X-CSRFToken"))
        except ValidationError:
            return _error("csrf_failed", "Refresh this page and choose the spreadsheet again.", 403)

    from haulage_app.fuel.xlsx_processing import (
        FuelXLSXProcessingError, read_fuel_store_xlsx_isolated,
    )
    from haulage_app.fuel.xlsx_reader import FuelXLSXError, MAX_XLSX_BYTES

    if request.mimetype != XLSX_MIMETYPE:
        return _error("unsupported_media_type", "Choose The Fuel Store's Transactions .xlsx export.", 415)
    if request.content_length is not None and request.content_length > MAX_XLSX_BYTES:
        return _error("too_large", "The spreadsheet is too large. Use an export under 10 MB.", 413)

    # Read a raw bounded body, not multipart data that could spool a document to
    # disk. The isolated reader returns the full report or a fixed safe error.
    content = request.stream.read(MAX_XLSX_BYTES + 1)
    if len(content) > MAX_XLSX_BYTES:
        return _error("too_large", "The spreadsheet is too large. Use an export under 10 MB.", 413)
    try:
        report = read_fuel_store_xlsx_isolated(content)
        payload = _preview_payload(report)
    except FuelXLSXError as error:
        status = 413 if error.code == "too_large" else 503 if error.code == "reader_unavailable" else 422
        return _error(error.code, str(error), status)
    except FuelXLSXProcessingError as error:
        return _error(error.code, str(error), 503)
    except SQLAlchemyError:
        return _error("preview_unavailable", "Truck choices could not be loaded. Please try again.", 503)
    except Exception:
        # Do not send parser/SQL exception messages or private cell contents to
        # the browser or application logs, even for an unexpected worker fault.
        return _error("processing_failed", "The spreadsheet could not be processed. Please try again.", 503)
    return _private_response(jsonify(payload))
