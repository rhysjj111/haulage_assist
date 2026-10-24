# The Fuel Store Excel reader

This first stage reads **The Fuel Store's Transactions `.xlsx` export** into
proposed fuel transactions. It adds no upload page, database writes, truck
creation, document archive or AI service. The supplied workbook is private and
is not a repository fixture.

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
Card Type says Esso, Shell or UK Fuels. The reader does not match registrations
to database trucks. It returns both registration columns and flags a missing
transaction registration or a disagreement, without silently substituting the
card registration. Registration comparisons ignore case and spaces.

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
arbitrary uploads. Before adding a public upload endpoint, run spreadsheet
processing in a bounded worker, enforce request limits before reading, protect
requests with CSRF, and keep documents and review drafts out of cookies and a
server archive, following the payslip import's approach.

## Validation and next stage

Tests create fictional `.xlsx` files in memory. Run them from the repository
root:

```bash
python3 -m unittest discover -s tests -p 'test_fuel_xlsx*.py' -v
```

The supplied sample is checked privately against the original workbook data;
its registrations, card numbers and financial records are excluded from Git.

The next stage adds upload and editable review, with registration matching and
source-row references. Later stages add existing-record/amount checks and
explicit batch saving. Fuel may be recorded without a day entry under the
existing manual workflow; an importer must preserve that rule and avoid guessing
a linked day when several drivers used a truck on the same date.
