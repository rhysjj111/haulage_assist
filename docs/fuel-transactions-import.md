# Fuel document import

Read **The Fuel Store's Transactions export** or a supported **Silvey digital
PDF invoice**, review its purchases, then explicitly save the selected fuel entries.
Reading and checking do not
write business records; Save adds the reviewed batch in one transaction. There
is no truck creation, document archive or AI service. The supplied workbook is
private and is not a repository fixture.

The user confirmed **The Fuel Store** as the supplier and **Cost** as the amount
normally entered in the app. Card Type contains different networks, so it does
not determine the app's fuel-card supplier.
For **Silvey**, the confirmed fuel-cost column is transaction **PRICE**, before
the separately listed VAT. AdBlue stays visible but excluded from diesel saving.

## Confirmed field mapping

The Fuel Store Transactions export:

| Spreadsheet column | Meaning for the app |
| --- | --- |
| Date | The individual purchase date; retain the source time for review |
| Tran VRN | Proposed truck registration |
| Quantity | Litres, using the source's two-decimal display |
| Cost | Fuel cost, copied directly without a VAT adjustment |
| Card Type | Source network/card-type information for review |
| Card VRN | Additional registration evidence; flag disagreements |

Silvey digital invoice:

| Invoice column | Meaning for the app |
| --- | --- |
| DATE | Purchase date, resolved against the printed invoice date |
| TIME | Source purchase time for comparison |
| REG. | Proposed truck registration |
| LITRES | Exact printed litres |
| PRICE | Exact transaction cost before VAT; this is not a unit price |
| PRODUCT | DERV is diesel; AdBlue and other unsupported products stay excluded |

All Fuel Store spreadsheet rows use the supplier label **The Fuel Store**, including transactions whose
Card Type says Esso, Shell or UK Fuels. The reader itself does not match
registrations to database trucks. It returns both registration columns and flags
a missing transaction registration or a disagreement, without silently
substituting the card registration. Registration comparisons ignore case and spaces.

The export contains transaction dates rather than an invoice-wide payroll week.
Multiple purchases for the same truck/day, including identical rows, remain
separate source transactions. Card numbers, driver names, cost centres, sites
and odometer readings are not included in the returned report.

## Reading a workbook

Install `requirements.txt` in the application's virtual environment. The reader
uses pinned `openpyxl`, `et_xmlfile` and `defusedxml` packages; it makes no network
requests and does not need AI credentials.

```python
from haulage_app.fuel.xlsx_reader import (
    FuelXLSXError,
    read_fuel_store_transactions_xlsx,
)

try:
    report = read_fuel_store_transactions_xlsx(workbook_bytes)
except FuelXLSXError as error:
    message = str(error)  # Fixed text; never includes source cell contents.
```

The immutable report identifies the source format, supplier, worksheet and
header row. Its immutable transaction rows retain their original spreadsheet
row numbers, purchase dates/times, registrations, network, product, quantity,
cost and unit price. Monetary values and litres are `Decimal` values in pounds
and litres, not the database's integer hundredths.

Quantity and Cost in the supplied export use two-decimal Excel formats, while
their stored numeric values contain small floating-point artifacts. The reader
deliberately follows that display precision and rounds with `ROUND_HALF_UP`.
It rejects unsupported precision formats rather than guessing how to import
genuinely higher-precision quantities. Unit Price is preserved separately as a
source value in pounds per litre; it never replaces the supplied Cost.

Calculated quantity/cost totals are sums of the returned transactions. They are
**not printed invoice totals**: the supplied export has no footer total to
reconcile. A quantity/price disagreement is retained as a review issue, not
corrected by replacing the source Cost.

Unknown products and nonpositive values are retained with review issues. The
later review stage must handle those explicitly; they must not be silently
saved as ordinary diesel or dropped from the source report.

## Limits and errors

The reader recognises this export's Transactions sheet and complete column
header. Headers may move within the supported leading rows or reorder their
known columns. Incomplete rows, ambiguous layouts, invalid dates, unsupported
cell types and formulas fail without returning a partial report.

Archive size, expanded size, member count and worksheet dimensions are bounded.
The reader does not extract archive members onto disk or execute formulas,
macros, links or instructions in cells. Unreadable or unsupported files return
fixed error messages without source values or parser tracebacks.

These are direct-reader input checks, not a complete resource sandbox for
arbitrary uploads. The preview endpoint uses the isolated worker described below
rather than running ZIP/XML processing directly in the Flask process.

## Upload and editable review

Open **Add Fuel → Import fuel**, or `/fuel/import`. Choose the document and click
**Read document**; there is no supplier selection at upload.
The recognised supplier is shown above the review. A Silvey invoice is identified
by its branding and validated invoice layout. A Fuel Store-shaped spreadsheet
shows a **Choose supplier** dropdown in its review, with **The Fuel Store** first
among the compatible choices. Selecting the supplier confirms it and enables
checks; no separate confirmation button is needed. The layout alone does not
prove which company supplied the export. The Fuel Store uses
its Transactions export; Silvey uses the recognised digital invoice layout.
The preview contains every
source row, its purchase date, proposed truck, litres and cost. Each row has an
original-row expansion with the extracted values, both registrations, source
time, network, product and unit price. This is an extracted comparison, not an
embedded Excel viewer; the workbook is not sent to an external document service.

Truck suggestions use exact registration matches after ignoring whitespace and
case. Unknown or ambiguous registrations, a missing Tran VRN, or disagreement
between Tran VRN and Card VRN require an explicit truck choice. There is no fuzzy
matching, truck creation, driver inference or day linking. All existing trucks
are available, as on the manual fuel form.

The truck dropdown controls inclusion, matching the payslip import's driver
dropdown. Choosing a truck includes a row; choosing **Exclude** leaves it out of
the checks, selected totals and Save. Excluded date/amount controls are disabled,
but their edited values remain available when a truck is chosen again. There is
no separate Include checkbox.

Users can edit the purchase date, truck, litres and cost, or exclude a row.
Unmatched/conflicting rows, unsupported products and nonpositive amounts start
excluded but remain visible with their source issues. Source details and flags
remain unchanged when review fields are edited. The supplier stays the selected
profile's canonical label; network values do not change it. Dates may span several payroll weeks.

Displayed source totals are calculated sums of the extracted rows. Selected
totals use edited values and exact integer hundredths. Local field feedback
follows the existing fuel form's volume/cost limits. The read-only checks below
compare selected entries with recorded receipts without claiming they are ready
to save. Larger exports are paged in the browser, retaining edits and totals
across pages.

Drafts live only in the current page's memory and are discarded by Clear,
choosing another file or leaving/reloading the page. Until Save is clicked,
neither reading nor editing creates fuel entries. Source documents and review
drafts are not stored in browser storage, session cookies or an upload archive.
Cancelling the file chooser preserves the current draft on both import pages.
The common **Read document**, **Clear**, **Recheck entries** and saved-history
actions do not change which file layouts each reader supports: the recognised
Fuel Store spreadsheet and Silvey digital invoice are enabled.

## One upload for supplier documents

There is one file chooser and **Read document** action, with no initial supplier
selector or manual spreadsheet/PDF mode. Supplier choices come from a registry of
enabled profiles; unsupported suppliers are not offered as working importers.
The chooser accepts common spreadsheet/PDF files so the app can explain an
unsupported document rather than requiring the user to identify its format.
It makes no promise that every PDF or supplier layout is supported.

The browser sends a bounded raw body as `application/octet-stream` with
`X-Fuel-Supplier: auto` for automatic detection. The server identifies XLSX
or PDF from the bytes, not the filename, extension or browser-supplied MIME type.
The route retains the existing XLSX/PDF MIME labels as accepted transports.
Automatic detection is available only when reading a document. Check and Save
require a concrete registered supplier ID. Explicit supplier reads remain
supported by the API for existing clients. Missing supplier headers default to
The Fuel Store for existing clients;
explicit unknown or empty IDs fail before parsing, querying or saving.

Automatic detection runs the matching supported isolated reader and requires
its complete validation before returning any rows. A validated Silvey PDF supplies
document identity; the recognised Fuel Store spreadsheet supplies only a layout
suggestion. The read response distinguishes these cases with
`detection.method` (`document_identity`, `layout_only` or `manual`) and
`detection.requires_confirmation`. The browser keeps an unconfirmed layout out
of financial checks and saving until the user selects its supplier. The review
dropdown offers only profiles compatible with the validated source format;
selecting another provider cannot relabel an already parsed document. Filenames,
extensions and card-network names never establish supplier identity.

Unrecognised documents return a clear error without saving anything. The user
can try a supported original document or enter the purchases manually.
An API client's explicit supplier choice still runs that supplier's strict reader;
it does not bypass layout validation or make an unknown supplier supported. New invoice layouts
need a separately tested reader before they can be imported.

XLSX and PDF go through their selected supplier's isolated reader. Unsupported
supplier/format combinations receive a fixed message. Read results identify the
supplier, and the page validates that identity, label and source format before
showing rows. Check and Save also send and validate the supplier ID. Financial
services use the selected profile's supplier label and diesel-product list for
duplicate matching, confirmations and inserts; one supplier's rows cannot be
silently relabelled as another supplier through a hardcoded default.

New files, Clear and a fresh read reset supplier selection and confirmations.
Supplier selection preserves the spreadsheet review and edits while invalidating
pending checks. Late replies cannot restore an old selection or document.
The review supplier selector locks during Save. File chooser cancellation still
preserves the current draft; no document or supplier draft is persisted in
browser storage or session cookies.

`POST /fuel/import/read` accepts a raw document body with a CSRF header, with
a 10 MiB request cap before processing. It avoids multipart temporary-file
spooling. Responses use `no-store` and `nosniff`, and errors contain fixed safe
messages rather than parser exceptions or cell contents.

`xlsx_processing.read_fuel_store_xlsx_isolated` runs the standalone
`xlsx_worker.py`, which imports no Flask/database package and receives no parent
credentials. The worker applies Linux limits before importing the reader:
256 MiB address space, eight seconds CPU, no file output/core dumps and 64 file
descriptors. The parent enforces a ten-second wall timeout and an 8 MiB pipe
output cap while reading; failed/timed-out children are killed and reaped. The
parent validates the complete bounded result before exposing rows. Unsupported
resource controls fail closed. This follows the supported Linux preview and
Heroku runtime rather than providing an unbounded fallback on other platforms.

`silvey_processing.read_silvey_pdf_isolated` uses the same limits in a separate
standalone worker. Both PDF text extraction and semantic invoice parsing happen
inside that child. The parent validates the returned complete report, PDF page
references, exact amounts, supplier identity and reconciled totals.

All document readers use `document_processing.worker_environment()` for the
child's minimal environment. It preserves nonempty `PYTHONHOME` and
`LD_LIBRARY_PATH` so Heroku's relocated shared Python runtime can start, while
excluding `PYTHONPATH`, database URLs and other app configuration or credentials.
Runtime paths are never logged.

For Silvey, original transaction details include the actual PDF page. The local
**Original invoice** viewer opens a PDF-typed Blob made from the chosen file;
page links select the matching source page. Nothing is fetched from an external
viewer or stored on the server. Clear, choosing another file, a fresh read and leaving the
page revoke the object URL. Source invoice totals include all products before
VAT, while selected totals include only rows selected for diesel saving.

## Checks on the current selection

The preview checks selected, valid entries after reading the file and after an
edit to a purchase date, truck, litres, cost or inclusion. Excluded entries are
not part of these checks. Original source issues remain visible independently.

The checks identify:

- Possible duplicates within the selected rows, and against stored fuel entries,
  using exact truck, purchase date, normalized supplier, litres and cost.
- Unusual cost per litre, using the shared owner-review policy's inclusive
  £0.50–£3.00/litre range. Integer products determine the threshold without
  rounding a displayed unit price.
- Unavailable trucks and amounts outside the existing entry form's limits.

Matching purchase details are a **possible** duplicate. Fuel records have no
invoice transaction ID or purchase time, and genuine fills may share those
details. Warnings do not automatically remove or change rows. Different amounts
on the same truck/day and receipts from other suppliers are comparison context,
not duplicate warnings. Network labels are not supplier aliases. A missing Day
does not prevent recording a fuel purchase and does not produce a warning here.
No consumption, fuel economy or VAT calculation is introduced.

Stored receipt details and local links let users compare the recorded values.
Source unit-price disagreement remains a source warning; edits do not rewrite
the source evidence or compare a corrected cost with an outdated source price.
Users can recheck after reviewing recorded entries in another tab.

Changes immediately invalidate old results, then debounce a new request.
Aborted or late responses cannot restore results for an older selection.
Pending, invalid and failed checks are distinct from a completed check with no
duplicate or amount warnings. Failed checks provide a retry action. Every page
of the browser's selection is checked, including rows outside the visible page.

`POST /fuel/import/check` accepts bounded raw JSON and the CSRF header. It accepts
at most 10,000 rows in a 2 MiB body, validates canonical dates and exact decimal
strings, and returns a complete echoed selection with row issues. Queries use
only the selected truck/date pairs in chunks of 250, inside `no_autoflush` with
stored column values. A global 20,000-record lookup cap fails explicitly rather
than silently returning a partial result. Duplicate-group membership and stored
pair context are returned once per group, avoiding quadratic response sizes.
Server-computed supplier comparisons use the same normalization as owner checks.
Checks do not persist edited entries, results, dismissals or verifications.

## Saving a reviewed batch

**Save fuel entries** saves the selected rows across all pages, up to 500 entries
per batch. It stays unavailable while a suggested supplier is unconfirmed,
checks are pending/failed, fields are
invalid, a selected product is unsupported, or duplicate candidates remain.
Correct or exclude those rows. An identical genuine purchase can be entered
through the manual fuel form after review; confirmation cannot bypass the
importer's duplicate protection.

Original source warnings and unusual prices require a per-row confirmation.
Changing that row's truck, date, litres, cost or inclusion clears its
confirmation. This acknowledgement does not override amount limits or permit
unsupported products such as AdBlue to be imported as diesel. A confirmation is
an instruction for the current save, not a separate persisted audit record.

`POST /fuel/import/save` accepts only bounded JSON with the CSRF header, up to
512 KiB and 500 rows. It validates every row again, uses the confirmed registered
supplier's canonical label, and converts decimal strings directly to integer hundredths. The
model's float-based entry validators are not reapplied to those integers.
It does not accept or store a source document, filename, card number or driver.

Before writing, the saver locks selected truck rows in a consistent order and
rechecks current duplicates and unusual prices. Matching candidates in the
selection or database block the entire batch, including a repeated Save request.
These locks serialize importer requests on PostgreSQL. Legacy manual entry
paths do not share this locking protocol, so this is not a global uniqueness
constraint or a permanent transaction-ID/idempotency system.

Fuel can save without a Day. Matching Day rows are locked; the saver links a day
only if exactly one record matches the selected truck and purchase date.
Missing or multiple matches leave `day_id` empty rather than guessing a driver.
Fuel inserts and removal of all matching legacy missing-fuel anomalies (with
their joined base rows and feedback) share one commit. Existing fuel records
and unrelated anomalies are not changed. Any pre-commit failure rolls back the
whole batch. Unrelated pending ORM changes cause a refusal before the save
transaction instead of being committed or discarded.

Controls lock during Save. A confirmed success displays the count and a fuel
history link, and locks that batch against another submission. Clear or choosing
a new file starts a new draft. Validation/conflict failures retain the edits.
Network failure, an unexpected response or a lost COMMIT acknowledgement can
leave the outcome unconfirmed; the page preserves that warning, never retries
Save automatically, and requires a manual recheck with fuel-history review
before another attempt. Exact duplicate guards still run on every Save.

No schema migration is required. This adds a new save endpoint; the existing
manual fuel form and owner-analysis calculations retain their current behavior.

## Validation

Tests create fictional `.xlsx` and PDF files in memory. Run them from the repository
root:

```bash
python3 -m unittest discover -s tests -p 'test_fuel_*.py' -v
python3 -m unittest discover -s tests -p 'test_silvey_*.py' -v
```

The supplied sample is checked privately against the original workbook data;
its registrations, card numbers and financial records are excluded from Git.

The opt-in `test_fuel_import_save_postgres.py` starts its own disposable cluster
on a private Unix socket. Set `FUEL_TEST_POSTGRES_BIN` to the PostgreSQL binary
directory to test real locking, exact inserts and full transaction rollback.
It refuses configured application database targets and never contacts Heroku.

## Silvey reader and reconciliation

The supplied Silvey sample is a digital PDF with transaction-level DATE, REG.,
LITRES and PRICE fields. The user confirmed PRICE directly as fuel cost before
the separately listed VAT, with AdBlue excluded from diesel saving. PRICE is an
extended transaction cost, not a unit price. Diesel purchase amounts and litres
reconcile to the invoice/card/product summaries in the private sample review.

The parser recognises the supplied digital layout, retains transactions across
page/card continuations, and checks every card total, transaction Grand Total
and product/unit-price summary. Litres and PRICE use the printed decimal tokens
directly; the summary rate is additional comparison evidence, never a substitute
for PRICE. Incomplete, ambiguous or mismatching tables fail without returning a
partial batch. Two-digit purchase years are anchored to the printed invoice
date, including a previous-year purchase on a January invoice.

DERV/DIESEL are eligible under the Silvey profile. AdBlue remains visible and
excluded by default, and cannot be saved as diesel even after confirmation.
Scans/photos, password protection and unrecognised invoice layouts are not
supported by this deterministic reader. PDF limits are 10 MiB, 20 pages and
250,000 extracted characters.

The source PDF, extracted text, registrations, card numbers and invoice/customer
details remain outside the repository. An independent private extraction is
compared with the reader and worker without putting actual source values in
tests or Git.
