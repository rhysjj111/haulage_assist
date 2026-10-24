# The Fuel Store spreadsheet import

The reader, editable preview and review checks read **The Fuel Store's
Transactions `.xlsx` export** into proposed fuel transactions. They add no
database writes, truck creation, document archive or AI service. The supplied workbook is private and
is not a repository fixture. Explicit batch saving is a later stage.

The user confirmed **The Fuel Store** as the supplier and **Cost** as the amount
normally entered in the app. Card Type contains different networks, so it does
not determine the app's fuel-card supplier.

## Confirmed field mapping

| Spreadsheet column | Meaning for the app |
| --- | --- |
| Date | The individual purchase date; retain the source time for review |
| Tran VRN | Proposed truck registration |
| Quantity | Litres, using the source's two-decimal display |
| Cost | Fuel cost, copied directly without a VAT adjustment |
| Card Type | Source network/card-type information for review |
| Card VRN | Additional registration evidence; flag disagreements |

All rows use the supplier label **The Fuel Store**, including transactions whose
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

Open **Add Fuel → Import fuel spreadsheet**, or `/fuel/import`. Select the
Transactions export and click **Read spreadsheet**. The preview contains every
source row, its purchase date, proposed truck, litres and cost. Each row has an
original-row expansion with the extracted values, both registrations, source
time, network, product and unit price. This is an extracted comparison, not an
embedded Excel viewer; the workbook is not sent to an external document service.

Truck suggestions use exact registration matches after ignoring whitespace and
case. Unknown or ambiguous registrations, a missing Tran VRN, or disagreement
between Tran VRN and Card VRN require an explicit truck choice. There is no fuzzy
matching, truck creation, driver inference or day linking. All existing trucks
are available, as on the manual fuel form.

Users can edit the purchase date, truck, litres and cost, or exclude a row.
Unmatched/conflicting rows, unsupported products and nonpositive amounts start
excluded but remain visible with their source issues. Source details and flags
remain unchanged when review fields are edited. The supplier stays **The Fuel
Store**; network values do not change it. Dates may span several payroll weeks.

Displayed source totals are calculated sums of the extracted rows. Selected
totals use edited values and exact integer hundredths. Local field feedback
follows the existing fuel form's volume/cost limits. The read-only checks below
compare selected entries with recorded receipts without claiming they are ready
to save. Larger exports are paged in the browser, retaining edits and totals
across pages.

There is no save action in this stage. Drafts live only in the current page's
memory and are discarded by Clear, choosing another file or leaving/reloading
the page. Neither source documents nor edits are stored in browser storage,
session cookies, database rows or an upload archive.

`POST /fuel/import/read` accepts only the raw XLSX body with a CSRF header, with
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
No edited entries, check result, dismissal or verification is persisted.

## Validation and next stage

Tests create fictional `.xlsx` files in memory. Run them from the repository
root:

```bash
python3 -m unittest discover -s tests -p 'test_fuel_*.py' -v
```

The supplied sample is checked privately against the original workbook data;
its registrations, card numbers and financial records are excluded from Git.

The next stage adds explicit batch saving with server-side rechecks.
Fuel may be recorded without a day entry under the existing manual workflow;
an importer must preserve that rule and avoid guessing
a linked day when several drivers used a truck on the same date.
