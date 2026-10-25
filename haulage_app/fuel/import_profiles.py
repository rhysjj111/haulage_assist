"""Supported supplier profiles behind the single fuel document upload."""

from dataclasses import dataclass
from types import MappingProxyType


DEFAULT_SUPPLIER_ID = "the-fuel-store"
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
_ERRORS = {
    "supplier_unavailable": (400, "Choose a supplier available in the fuel import list."),
    "invalid_document": (422, "This document could not be recognised. Choose the original document for the selected supplier."),
    "too_large": (413, "The document is too large. Choose a file under 10 MB."),
    "format_unavailable": (422, "This document format is not supported for the selected supplier. Check the supplier and choose its original document."),
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


def read_fuel_document(content, supplier_id=None):
    """Choose an approved supplier reader from bytes, never a file extension.

    Sniffing only checks a bounded prefix; ZIP/XML processing is delegated to
    the existing worker. Recognising a PDF does not imply a supported layout.
    """
    supplier = get_supplier(supplier_id)
    if not isinstance(content, bytes):
        raise FuelDocumentError("invalid_document")
    if len(content) > MAX_DOCUMENT_BYTES:
        raise FuelDocumentError("too_large")
    if content.startswith(b"PK\x03\x04"):
        kind = "xlsx"
    elif content.lstrip().startswith(b"%PDF-"):
        kind = "pdf"
    else:
        raise FuelDocumentError("invalid_document")
    reader = _READERS.get((supplier.id, kind))
    if kind not in supplier.formats or reader is None:
        raise FuelDocumentError("format_unavailable")
    return reader(content)
