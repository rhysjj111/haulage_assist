"""Temporary spreadsheet review, checks and explicit batch fuel saving."""

from collections import defaultdict
import json

from flask import current_app, jsonify, make_response, render_template, request, url_for
from flask_wtf.csrf import generate_csrf, validate_csrf
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from wtforms.validators import ValidationError

from haulage_app import db
from haulage_app.fuel import fuel_bp
from haulage_app.fuel.import_profiles import (
    AUTO_SUPPLIER_ID, MAX_DOCUMENT_BYTES, FuelDocumentError,
    detect_fuel_document, get_supplier, read_fuel_document, supplier_choices,
)
from haulage_app.models import Truck


XLSX_MIMETYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DOCUMENT_MIMETYPES = frozenset({XLSX_MIMETYPE, "application/octet-stream", "application/pdf"})


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


def _request_supplier():
    return get_supplier(request.headers.get("X-Fuel-Supplier"))


def _preview_payload(report, supplier):
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

    # Fuel Store's Card VRN identifies the truck assigned to the card. Tran VRN
    # is driver-entered and can contain typos; retain it and its source warnings
    # without using it as a fallback. Other suppliers keep their own mapping.
    card_primary = supplier.id == "the-fuel-store" and report.document_kind == "xlsx"
    rows = []
    for row in report.rows:
        registration = _normalise_registration(
            row.card_registration if card_primary else row.transaction_registration,
        )
        card_registration = _normalise_registration(row.card_registration)
        candidates = registrations.get(registration, []) if registration else []
        if not registration:
            status = "missing_registration"
        elif not card_primary and card_registration and card_registration != registration:
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
    payload = {
        "report": {
            "supplier_id": supplier.id,
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
    if report.document_kind == "pdf":
        payload["report"].update({
            "document_kind": "pdf",
            "page_count": report.page_count,
            "printed_totals": {
                "quantity": format(report.printed_total_quantity, ".2f"),
                "cost": format(report.printed_total_cost, ".2f"),
            },
        })
        for proposed, source in zip(payload["rows"], report.rows):
            proposed["source_page"] = source.source_page
    return payload


@fuel_bp.route("/import", methods=["GET"])
def import_preview():
    with db.session.no_autoflush:
        response = make_response(render_template(
            "fuel/import_preview.html",
            csrf_token=generate_csrf(),
            read_url=url_for("fuel.read_import_document"),
            check_url=url_for("fuel.check_import_preview"),
            save_url=url_for("fuel.save_import_fuel"),
            supplier_profiles=supplier_choices(),
            default_supplier_id=AUTO_SUPPLIER_ID,
        ))
    return _private_response(response)


@fuel_bp.route("/import/read", methods=["POST"])
def read_import_document():
    if current_app.config.get("WTF_CSRF_ENABLED", True):
        try:
            validate_csrf(request.headers.get("X-CSRFToken"))
        except ValidationError:
            return _error("csrf_failed", "Refresh this page and choose the document again.", 403)

    automatic = request.headers.get("X-Fuel-Supplier") == AUTO_SUPPLIER_ID
    try:
        supplier = None if automatic else _request_supplier()
    except FuelDocumentError as error:
        return _error(error.code, str(error), error.status)

    from haulage_app.fuel.xlsx_processing import FuelXLSXProcessingError
    from haulage_app.fuel.xlsx_reader import FuelXLSXError
    from haulage_app.fuel.silvey_reader import SilveyPDFError
    from haulage_app.fuel.silvey_processing import SilveyPDFProcessingError

    if request.mimetype not in DOCUMENT_MIMETYPES:
        return _error("unsupported_media_type", "Choose a supported fuel document.", 415)
    if request.content_length is not None and request.content_length > MAX_DOCUMENT_BYTES:
        return _error("too_large", "The document is too large. Choose a file under 10 MB.", 413)

    # One bounded raw body for all supported document types, without multipart
    # spooling. Only byte-signature detection runs here; parsing stays isolated.
    content = request.stream.read(MAX_DOCUMENT_BYTES + 1)
    if len(content) > MAX_DOCUMENT_BYTES:
        return _error("too_large", "The document is too large. Choose a file under 10 MB.", 413)
    try:
        if automatic:
            supplier, report, detection = detect_fuel_document(content)
        else:
            report = read_fuel_document(content, supplier.id)
            detection = {"method": "manual", "requires_confirmation": False}
        if (report.fuel_card_name != supplier.label
                or report.source_format not in supplier.source_formats):
            raise FuelDocumentError("invalid_document")
        payload = _preview_payload(report, supplier)
        payload["detection"] = detection
    except FuelDocumentError as error:
        return _error(error.code, str(error), error.status)
    except FuelXLSXError as error:
        status = 413 if error.code == "too_large" else 503 if error.code == "reader_unavailable" else 422
        return _error(error.code, str(error), status)
    except FuelXLSXProcessingError as error:
        return _error(error.code, str(error), 503)
    except SilveyPDFError as error:
        status = 413 if error.code == "too_large" else 503 if error.code == "reader_unavailable" else 422
        return _error(error.code, str(error), status)
    except SilveyPDFProcessingError as error:
        return _error(error.code, str(error), 503)
    except SQLAlchemyError:
        return _error("preview_unavailable", "Truck choices could not be loaded. Please try again.", 503)
    except Exception:
        # Do not send parser/SQL exception messages or private cell contents to
        # the browser or application logs, even for an unexpected worker fault.
        return _error("processing_failed", "The document could not be processed. Please try again.", 503)
    return _private_response(jsonify(payload))


@fuel_bp.route("/import/check", methods=["POST"])
def check_import_preview():
    if current_app.config.get("WTF_CSRF_ENABLED", True):
        try:
            validate_csrf(request.headers.get("X-CSRFToken"))
        except ValidationError:
            return _error("csrf_failed", "Refresh this page and choose the document again.", 403)

    try:
        supplier = _request_supplier()
    except FuelDocumentError as error:
        return _error(error.code, str(error), error.status)

    from haulage_app.fuel.import_checks import (
        MAX_CHECK_BYTES, ImportCheckInputError, check_fuel_for_preview,
    )

    if request.mimetype != "application/json":
        return _error("unsupported_media_type", "Send the selected fuel entries as JSON.", 415)
    if request.content_length is not None and request.content_length > MAX_CHECK_BYTES:
        return _error("too_large", "The review request is too large. Select fewer entries.", 413)
    content = request.stream.read(MAX_CHECK_BYTES + 1)
    if len(content) > MAX_CHECK_BYTES:
        return _error("too_large", "The review request is too large. Select fewer entries.", 413)
    try:
        payload = json.loads(content.decode("utf-8"))
    except (ValueError, UnicodeError, RecursionError):
        return _error("invalid_check", "Choose valid fuel entries to check.", 400)
    try:
        result = check_fuel_for_preview(payload, supplier_id=supplier.id)
    except ImportCheckInputError as error:
        return _error(error.code, str(error), error.status)
    except Exception:
        # Checks are read-only; never return SQL, edited amounts, parser text or
        # a partial result that could be mistaken for a completed check.
        return _error("checks_unavailable", "Fuel entries could not be checked. Please try again.", 503)
    return _private_response(jsonify(result))


@fuel_bp.route("/import/save", methods=["POST"])
def save_import_fuel():
    if current_app.config.get("WTF_CSRF_ENABLED", True):
        try:
            validate_csrf(request.headers.get("X-CSRFToken"))
        except ValidationError:
            return _error("csrf_failed", "Refresh this page and choose the document again.", 403)

    try:
        supplier = _request_supplier()
    except FuelDocumentError as error:
        return _error(error.code, str(error), error.status)

    from haulage_app.fuel.import_save import MAX_SAVE_BYTES, ImportSaveError, save_reviewed_fuel

    if request.mimetype != "application/json":
        return _error("unsupported_media_type", "Send the reviewed fuel entries as JSON.", 415)
    if request.content_length is not None and request.content_length > MAX_SAVE_BYTES:
        return _error("too_large", "The save request is too large. Select fewer entries.", 413)
    content = request.stream.read(MAX_SAVE_BYTES + 1)
    if len(content) > MAX_SAVE_BYTES:
        return _error("too_large", "The save request is too large. Select fewer entries.", 413)
    try:
        payload = json.loads(content.decode("utf-8"))
    except (ValueError, UnicodeError, RecursionError):
        return _error("invalid_save", "Choose valid reviewed fuel entries to save.", 400)
    try:
        result = save_reviewed_fuel(payload, supplier_id=supplier.id)
    except ImportSaveError as error:
        response = jsonify(error={"code": error.code, "message": str(error)}, row_errors=error.row_errors)
        response.status_code = error.status
        return _private_response(response)
    except IntegrityError:
        return _error("save_conflict", "The batch conflicts with another record or a recent change. "
                      "Nothing was saved. Recheck the selected entries.", 409)
    except Exception:
        # A COMMIT may have succeeded before its acknowledgement was lost.
        # Do not promise a rollback or encourage an automatic Save retry.
        return _error("save_unavailable", "The save could not be confirmed. "
                      "Review fuel history and recheck entries before trying again.", 503)
    response = jsonify(result)
    response.status_code = 201
    return _private_response(response)
