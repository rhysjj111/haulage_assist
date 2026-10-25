# Import and review payroll PDFs

Upload a digital weekly management report from **Add Payslip → Import
payslips**. The prototype reads section 4, suggests existing active drivers and
shows an editable table beside the original PDF. **Save payslips** creates the
selected entries together after repeating the checks. Uploading and editing
alone do not change records. There is no document archive or database migration.

## Reviewing the prototype

1. Choose the original digital PDF and click **Read document**.
2. Check the proposed working week, driver selections, Total wage and Employer
   cost. Each employee's **Page** link selects the source page in the viewer.
3. Exact name matches ignore case and repeated spaces. Ambiguous matches require
   a choice. Other employees remain under a collapsed section, excluded unless
   an existing driver is selected. The choices use the same active-driver list
   as manual Add Payslip; unknown names never create drivers automatically.
4. Edit the week, driver and amounts locally. These remain a draft until saved.
   Refreshing, clearing or replacing the document clears the draft; cancelling
   a file chooser preserves the existing preview.
5. Review the inline checks. Selecting a driver twice flags both rows. Selected
   amounts must contain at most two decimal places, be greater than £1 and less
   than £3,000, and have employer cost at least equal to Total wage. Excluded
   employees do not affect these checks.
6. Existing payslips are checked again when the selected week or drivers change.
   A recorded payslip shows its amounts and a **View payslip** link; nothing is
   overwritten or excluded automatically. If more than one historical payslip
   exists, all are shown. An unsuccessful check remains visibly unavailable
   until retried, while your edits stay on the page.
7. Each selected driver needs an existing day entry for the **Friday ending the
   selected week**, matching ordinary Add Payslip's same-date requirement. The
   row shows the exact missing date and an **Add day entry** link to the ordinary
   form in a new tab. Select that driver/date there, then return and click
   **Recheck entries**. Working, Holiday and Absent day records are all accepted;
   the importer never creates attendance records automatically.
8. Click **Save N payslips** once the selected rows are ready. The server repeats
   the validations against current records and saves the entire batch in one
   transaction. An invalid row stops the batch; existing payslips are never
   overwritten or silently skipped. A confirmed result shows the saved count
   and a **View payslip history** link, and locks that batch against resubmission.

These checks help review the proposed entries; they do not confirm that payroll
is correct. Both import pages use the assignment dropdown to include or exclude
rows: select a driver here, or a truck in fuel. Choosing **Exclude** explicitly
removes an employee from the selected entries. Changing an amount
updates local checks without uploading the PDF or amounts again.

While saving, editable controls are locked to prevent double submissions. A
validation failure keeps your mappings, amounts and original PDF available.
If a response is interrupted or cannot confirm the result, the page retains an
unconfirmed-save message and a history link. Save stays unavailable until the
user manually selects **Recheck entries** and current checks finish successfully,
matching fuel's recovery flow. Editing or returning to the tab does not clear
this gate or warning. Check the recorded payslips before trying again: a lost
response can follow a successful commit. The page never retries Save automatically.
Use **Clear** or choose another PDF to start a new batch after success.

Both pages use **Read document**, **Clear**, **Retry checks**, saved counts and
history links. Payroll retains its week selection and blocking driver/day
checks; fuel retains individual purchase dates and its optional warning
confirmations. Supported formats and financial rules are unchanged.

The original viewer uses the browser's selected File through a local object
URL. A raw copy is sent to the app for short-lived extraction. No PDF or review
draft is stored in cookies, local storage, a database or a server file archive.
Neither a document URL nor an uploaded filename is sent in the request path.
The app makes no AI-service calls and does not send the PDF to another service.
Existing-record checks send only the selected driver IDs and week to the app;
they do not store a review draft. Their responses use `Cache-Control: no-store`.
The explicit save request sends the selected row numbers, driver IDs, edited
amounts and week. It stores normal payslip records, without the PDF, filename,
excluded employees or a persistent import draft. Draft edits are still lost on
refresh; previously saved payslips remain recorded.

## Agreed mapping

| Management report | Payslip entry |
| --- | --- |
| Employee | Match to an existing driver during review |
| Total Payments | Total wage, before employee deductions |
| Total Cost Per Employee | Total cost to employer |
| Pay Date | The Saturday-Friday working week containing that date |

The report's payroll-run number is not an app/ISO week number. For example, a
Pay Date of Friday 25 September 2026 selects 19-25 September 2026. No net-pay
column, company-wide total or year-to-date value supplies a payslip amount.
Manual-entry labels and owner-review help now use this confirmed pre-deduction
mapping. Existing historical amounts are not converted or recalculated. The
saved payslip date is the Friday of the selected week; changing the week changes
that date, while the report's original Pay Date remains visible for comparison.

## Calling the reader

After installing `requirements.txt`, internal application code can call the
reader directly for trusted local inputs:

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
or the database's integer pence. The save service validates decimal strings and
converts them to integer pence exactly once, without the legacy model's float
conversion. Date, driver, amount bounds and same-date day requirements are
validated explicitly before the narrowly scoped insert.

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

For HTTP uploads, use
`haulage_app.payslip.pdf_processing.read_payroll_pdf_isolated(pdf_bytes)`.
The upload endpoint requires a CSRF token, validates the PDF content type and
reads at most 10 MiB plus one byte before rejecting an oversized request. A raw
PDF body avoids multipart upload spooling. Responses, including errors, use
`Cache-Control: no-store`.

Text extraction runs in a standalone child process with a 256 MiB address-space
limit, an eight-second CPU limit and a ten-second parent wall-clock timeout.
The child imports no Flask/database code, inherits no app credentials and has
file output/core dumps disabled. Extracted output is bounded and validated
before semantic parsing in the parent. Table lines and monetary token lengths
are also bounded. Resource failures return a generic error without partial
entries. This bounded worker requires Linux/Unix resource controls and fails
closed if they are unavailable; Heroku and the supplied Codespaces setup use
Linux.

Worker launches share `document_processing.worker_environment()`. Alongside the
minimal interpreter settings, it retains nonempty `PYTHONHOME` and
`LD_LIBRARY_PATH`, which Heroku's relocated shared Python runtime needs to start.
It still excludes `PYTHONPATH`, database URLs and other app configuration or
credentials. Runtime paths are never logged.

The reader and worker make no network calls and write no document files or
business records. Callers must not log private report data or commit it as a
test fixture. The original direct-reader function is not a resource sandbox for
untrusted uploads; use the isolated wrapper for the web endpoint.

## Validation

Run the focused tests from the repository root:

```bash
python3 -m unittest discover -s tests -p 'test_payslip_pdf*.py' -v
```

The tests generate fictional PDFs in memory using the same pinned PDF library;
they need no real payroll reports, extra PDF-generation package, AI credentials
or configured database. Existing test setup selects isolated in-memory SQLite.
The supplied report was also checked privately; it is excluded from the Git
changes and from the synthetic fixtures.

## Save behavior and database compatibility

The server accepts at most 500 selected rows in a bounded JSON request and
requires CSRF protection. It rechecks currently active drivers, actual
Saturday-Friday payslip dates and the exact Friday day records. Driver rows are
locked in a consistent order so simultaneous importer requests and retries
cannot both add the same batch. The batch and exact-date legacy missing-payslip
anomaly cleanup commit together; failures roll back the transaction. Owner
reports detect the changed source records through their existing fingerprints.

The repository's existing payslip uniqueness constraint uses a generated week
number without a year and does not always agree with Saturday-Friday date
ranges. This addition does not change that schema or historical data. The new
importer checks actual dates, but a retained legacy constraint can still reject
an otherwise valid batch (for example a clash with another year's week). That
failure rolls back the whole batch and asks for a history review. Existing
manual entry paths keep their existing constraints; importer locking is not a
new universal uniqueness rule for those separate paths.

Optional PostgreSQL tests start their own disposable cluster on a private Unix
socket, exercise the real generated column/constraint and check concurrent
requests and transaction rollback. They never use a configured app database:

```bash
PAYSLIP_TEST_POSTGRES_BIN=/path/to/postgresql/bin python3 -m unittest discover \
  -s tests -p 'test_payslip_pdf_save_postgres.py' -v
```
