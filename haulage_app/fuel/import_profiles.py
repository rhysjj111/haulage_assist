"""Supported supplier profiles behind the single fuel document upload."""

from dataclasses import dataclass
from types import MappingProxyType


DEFAULT_SUPPLIER_ID = "the-fuel-store"
AUTO_SUPPLIER_ID = "auto"
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
_ERRORS = {
    "supplier_unavailable": (400, "Choose a supplier available in the fuel import list."),
    "invalid_document": (422, "This document could not be recognised. Choose the original document for the selected supplier."),
    "too_large": (413, "The document is too large. Choose a file under 10 MB."),
    "format_unavailable": (422, "This document format is not supported for the selected supplier. Check the supplier and choose its original document."),
    "supplier_not_recognised": (422, "The supplier could not be identified from this document. Choose a supported supplier and try its original invoice or export, or enter the fuel manually."),
}


class FuelDocumentError(ValueError):
    """Fixed errors, without document contents, filenames or parser details."""

    def __init__(self, code):
        self.code = code
        self.status, message = _ERRORS[code]
        super().__init__(message)


@dataclass(frozen=True)
class FuelImportSupplier:
    id: str
    label: str
    help_text: str
    formats: tuple[str, ...]
    source_formats: tuple[str, ...]
    diesel_products: tuple[str, ...] = ()


_SUPPLIERS = MappingProxyType({
    DEFAULT_SUPPLIER_ID: FuelImportSupplier(
        id=DEFAULT_SUPPLIER_ID,
        label="The Fuel Store",
        help_text="Choose the Transactions export from your Fuel Store account. Up to 10 MB.",
        formats=("xlsx",),
        source_formats=("fuel-store-transactions-xlsx-v1",),
        diesel_products=("DIESEL", "KEYFUELS DIESEL", "UK FUELS DIESEL",
                         "UK FUELS DIESEL (TP)", "ESSO DIESEL", "DIESEL (SHELL)"),
    ),
    "silvey": FuelImportSupplier(
        id="silvey",
        label="Silvey",
        help_text="Choose the original Silvey fuel invoice. Up to 10 MB.",
        formats=("pdf",),
        source_formats=("silvey-fuel-invoice-pdf-v1",),
        diesel_products=("DERV", "DIESEL"),
    ),
})


def get_supplier(supplier_id=None):
    """Resolve only a registered supplier; an absent old-client ID defaults."""
    if supplier_id is None:
        supplier_id = DEFAULT_SUPPLIER_ID
    if not isinstance(supplier_id, str) or supplier_id not in _SUPPLIERS:
        raise FuelDocumentError("supplier_unavailable")
    return _SUPPLIERS[supplier_id]


def supplier_choices():
    """Return JSON-safe public guidance without reader functions or paths."""
    return [{
        "id": supplier.id,
        "label": supplier.label,
        "help_text": supplier.help_text,
        "formats": list(supplier.formats),
        "source_formats": list(supplier.source_formats),
        "diesel_products": list(supplier.diesel_products),
    } for supplier in _SUPPLIERS.values()]


def _read_fuel_store_xlsx(content):
    # Keep parsing in the existing isolated worker. Resolve the function at the
    # time of use, rather than importing an app/reader cycle at module startup.
    from haulage_app.fuel.xlsx_processing import read_fuel_store_xlsx_isolated

    return read_fuel_store_xlsx_isolated(content)


def _read_silvey_pdf(content):
    from haulage_app.fuel.silvey_processing import read_silvey_pdf_isolated

    return read_silvey_pdf_isolated(content)


_READERS = MappingProxyType({
    (DEFAULT_SUPPLIER_ID, "xlsx"): _read_fuel_store_xlsx,
    ("silvey", "pdf"): _read_silvey_pdf,
})


def _document_kind(content):
    if not isinstance(content, bytes):
        raise FuelDocumentError("invalid_document")
    if len(content) > MAX_DOCUMENT_BYTES:
        raise FuelDocumentError("too_large")
    if content.startswith(b"PK\x03\x04"):
        return "xlsx"
    elif content.lstrip().startswith(b"%PDF-"):
        return "pdf"
    raise FuelDocumentError("invalid_document")


def read_fuel_document(content, supplier_id=None):
    """Choose an approved supplier reader from bytes, never a file extension.

    Sniffing only narrows the document kind. The selected isolated reader must
    still validate its complete supported layout and transaction totals.
    """
    supplier = get_supplier(supplier_id)
    kind = _document_kind(content)
    reader = _READERS.get((supplier.id, kind))
    if kind not in supplier.formats or reader is None:
        raise FuelDocumentError("format_unavailable")
    return reader(content)


def detect_fuel_document(content):
    """Read supported document evidence without claiming every layout is an issuer.

    Format only narrows the current reader candidate. A successful, strict
    Silvey parser verifies invoice branding, layout and reconciled totals.
    The Fuel Store export schema has no readable issuer identity, so even a
    successful spreadsheet parse remains a suggestion requiring confirmation.
    Neither filenames nor card-network labels participate in detection.
    """
    try:
        kind = _document_kind(content)
    except FuelDocumentError as error:
        if error.code == "invalid_document":
            raise FuelDocumentError("supplier_not_recognised") from None
        raise
    supplier = get_supplier("silvey" if kind == "pdf" else DEFAULT_SUPPLIER_ID)
    from haulage_app.fuel.silvey_reader import SilveyPDFError
    from haulage_app.fuel.xlsx_reader import FuelXLSXError

    try:
        report = read_fuel_document(content, supplier.id)
    except (SilveyPDFError, FuelXLSXError) as error:
        # Invoices with recognisable identity but wrong totals or incomplete
        # transactions must keep those useful diagnostics, not become guesses.
        if error.code == "unsupported_layout":
            raise FuelDocumentError("supplier_not_recognised") from None
        raise
    if (report.fuel_card_name != supplier.label
            or report.source_format not in supplier.source_formats):
        raise FuelDocumentError("supplier_not_recognised")
    detection = ({"method": "document_identity", "requires_confirmation": False}
                 if supplier.id == "silvey" else
                 {"method": "layout_only", "requires_confirmation": True})
    return supplier, report, detection
