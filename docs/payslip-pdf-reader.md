# Payslip PDF reader: stage 1

The reader accepts the digital weekly management-report format reviewed for
this project. It returns section 4's employee rows and amounts for a later
upload-and-review page. Stage 1 adds no route, form, driver matching, document
archive, migration or payslip-saving action.

## Agreed mapping

| Management report | Future payslip entry |
| --- | --- |
| Employee | Match to an existing driver during review |
| Total Payments | Total wage, before employee deductions |
| Total Cost Per Employee | Total cost to employer |
| Pay Date | The Saturday-Friday working week containing that date |

The report's payroll-run number is not an app/ISO week number. For example, a
Pay Date of Friday 25 September 2026 selects 19-25 September 2026. No net-pay
column, company-wide total or year-to-date value supplies a payslip amount.
The existing app's older take-home-pay help text needs aligning with this
confirmed mapping before a future Save stage; this reader does not alter it.

## Calling the reader

After installing `requirements.txt`, application code can call:

```python
from haulage_app.payslip.pdf_reader import PayrollPDFError, read_payroll_pdf

try:
    report = read_payroll_pdf(pdf_bytes)
except PayrollPDFError as error:
    # error.code is suitable for choosing a UI state. The message contains no
    # extracted employee names, amounts, file contents or parser traceback.
    message = str(error)
```

`report` has `pay_date`, `week_start`, `week_end`, immutable `rows` and printed
`totals`. Each employee row has `employee_name`, its one-based `page_number`,
`total_payments`, `employer_pension`, `employer_ni`, `employer_ni_class_1a` and
`total_cost_to_employer`. Amounts are exact `Decimal` pounds, not float values
or the database's integer pence. The later entry stage must use the normal
validated save path and must not multiply values twice.

Every employee row is returned, including non-drivers. Matching and exclusions
belong to the review page; the reader never creates drivers. Zero and negative
source amounts are retained for explicit review, rather than being discarded,
changed to positive amounts or automatically accepted by entry validation.

## Checks and limits

- Require the section 4 Employer Costs heading and the expected column order.
- Read a table continued onto the next page, including repeated table headings.
- Require one consistent, valid Pay Date across the report.
- Check each employee cost against payments plus employer contributions.
- Reconcile all five columns against the printed Totals row.
- Reject incomplete rows, missing totals and repeated employee names, rather
  than return a partial set for saving.
- Accept PDF bytes up to 10 MiB, 20 pages and 250,000 extracted characters.
- Reject encrypted, broken, image-only and unsupported-layout PDFs with a
  clear error. Scans, photographs and other suppliers' layouts are later work.

These limits bound normal report input; they are not a complete resource sandbox
for arbitrary hostile PDFs. A future upload route must bound the request before
reading it, protect processing time/resources and avoid relying on Heroku disk
or Flask session cookies to hold document/review state between requests.

The reader makes no network calls and writes no files or business records.
Callers must not log private report data or commit it as a test fixture.

## Validation

Run the focused tests from the repository root:

```bash
python3 -m unittest discover -s tests -p test_payslip_pdf_reader.py -v
```

The tests generate fictional PDFs in memory using the same pinned PDF library;
they need no real payroll reports, extra PDF-generation package, AI credentials
or configured database. Existing test setup selects isolated in-memory SQLite.
The supplied report was also checked privately; it is excluded from the Git
changes and from the synthetic fixtures.

The next stage is a temporary PDF upload and editable review page. Actual
payslip saving remains a separate stage after reviewing the prototype.
