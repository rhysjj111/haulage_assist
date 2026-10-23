# Payslip PDF upload and review prototype

Upload a digital weekly management report from **Add Payslip → Import payroll
PDF**. The prototype reads section 4, suggests existing active drivers and
shows an editable table beside the original PDF. It does not create, update or
delete payslips. There is no Save action, document archive or database migration.

## Reviewing the prototype

1. Choose the original digital PDF and click **Read PDF**.
2. Check the proposed working week, driver selections, Total wage and Employer
   cost. Each employee's **Page** link selects the source page in the viewer.
3. Exact name matches ignore case and repeated spaces. Ambiguous matches require
   a choice. Other employees remain under a collapsed section, excluded unless
   an existing driver is selected. The choices use the same active-driver list
   as manual Add Payslip; unknown names never create drivers automatically.
4. Edit the week, driver and amounts locally. These changes are a preview only.
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

These checks help review the proposed entries; they do not confirm that payroll
is correct or that the entries can be saved. Choosing **Exclude** explicitly
removes an ambiguous employee from the selected entries. Changing an amount
updates local checks without uploading the PDF or amounts again.

The original viewer uses the browser's selected File through a local object
URL. A raw copy is sent to the app for short-lived extraction. No PDF or review
draft is stored in cookies, local storage, a database or a server file archive.
Neither a document URL nor an uploaded filename is sent in the request path.
The app makes no AI-service calls and does not send the PDF to another service.
Existing-record checks send only the selected driver IDs and week to the app;
they do not store a review draft. Their responses use `Cache-Control: no-store`.

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

The next prototype stage adds actual saving and must
revalidate the chosen week, driver, source amounts, duplicate protection and
the app's existing day-entry requirements before any database mutation. It must
also repeat database checks at save time: a successful preview check is only a
snapshot, and another employee may enter or change a payslip afterwards.
