# Owner Analysis

Owner Analysis is separate from the existing wage calculator and old analysis
pages. Open `/owner-analysis` for a Saturday–Friday payroll week, or
`/owner-analysis/monthly?month=YYYY-MM` for a payroll month. Overview, Drivers
and Trucks are available for both periods. Corrections and review actions are
performed on the weekly Overview.

## Figures and periods

- Recorded earnings are Job amounts plus Day additional earnings, each counted
  once. Split Job rows already contain their allocation. Truck assignments do
  not allocate driver earnings to trucks.
- Fuel spending and litres are purchases dated in the period, including receipts
  without a linked Day. The receipt's truck is authoritative. These figures are
  not fuel consumption or economy. No VAT conversion is performed.
- Employer wage cost comes from actual Payslip employer-cost entries, including
  paid absences. Missing costs remain pending until entered or explicitly
  confirmed as genuinely zero with an explanation. Duplicate and questionable
  entries require checking.
- Driver rows include recorded working, holiday and absent days. A blank date
  remains unknown. Period employment or recorded Day/Payslip entries determine
  membership, preserving drivers who have since left. Daily averages divide
  recorded earnings by recorded Working days; zero Working days means no average.
- Truck rows show recorded fuel spending, purchased litres and receipt counts.
  A referenced truck with no receipts has zero recorded purchases; this does not
  establish downtime. The standard per-truck weekly allowance is displayed
  separately. Historical settings identify a truck count, not registrations, so
  no historical overhead total or profit is assigned to a named truck.
- Each whole payroll week belongs to the month containing its Tuesday. Monthly
  totals include every expected finished week, even an empty one. A Friday week
  remains in progress until Saturday. Current and future weeks are listed
  separately. Monthly averages use total earnings divided by total Working days.
- Weekly records are cut off at today's date in Europe/London. This is a
  transaction-date cutoff, not a snapshot of past database contents. Later
  corrections to those records are visible and may reopen checks/reviews.

Money is stored/calculated in integer pence; fuel volume is integer hundredths
of a litre. Missing financial information withholds the estimated operating
result. Valid zero and negative amounts are not treated as unknown.

## Overhead setup

Use **Weekly overhead settings** once to enter the allowance per truck, the
truck count (including unused trucks), and the first Saturday they apply to.
Settings carry forward automatically. A later change applies from its selected
week up to the next scheduled change. Earlier weeks retain their prior values.
An intentionally historical effective date is an explicit correction.

No initial allowance, effective date or historical fleet count is guessed or
seeded. Four is only an unsaved form suggestion. A global settings-history
fingerprint rejects stale forms, including changes outside the currently viewed
week. Reads do not create weekly snapshots; snapshots are saved only by explicit
settings actions.

## Checks and notes

Checks cover missing expected days, working days without earnings, fuel flags
without receipts, missing or multiple payslips, numeric ranges, missing overhead
settings, and informational mileage issues. Plausible incorrect data and
unflagged missing purchases still need human review.

Legitimate exceptions require an explanation. Missing days require an actual Day
record (Working, Holiday or Absent). Unknown fuel and overhead costs cannot be
dismissed by a note. A mistaken fuel flag can be corrected without inventing a
purchase. Existing forms are reused through signed, record-specific correction
links. Historical inactive drivers remain eligible only for the exact correction.
Split-job allocation edits remain read-only to avoid breaking both allocations.

Verification and review history is append-only and independent of legacy alert
dismissals. Actual source-value fingerprints reopen a check or week when relevant
records change. Missing/added/moved records and same-ID edits are included. A
finished week requires explicit earnings, fuel and payroll confirmations before
signoff. No driver, truck or month has a separate signoff. The badge always
describes the whole period; a partly completed month can be reviewed only through
its last included Friday.

## Database changes and release

Two additive migrations follow the previous head:

1. `859d6ebe2110` → `7e9c2a41b6d8`: owner overhead settings/snapshots.
2. `7e9c2a41b6d8` → `b2e7a9c4106f`: issue explanations and weekly signoffs.

They do not seed configuration or change existing entry/payroll records. The
current Procfile does not automatically run migrations. Before a live release,
check the live revision/schema, obtain a fresh backup, rehearse on a separate
restored copy and agree the migration/deployment sequence. Do not stamp a database
or replay legacy migrations without checking its actual state. Rolling code back
can retain these additive tables; downgrading removes the new owner records.

## Verification and independent reconciliation

Run the isolated in-memory regression suite:

```sh
python -m unittest discover -s tests -v
```

Tests override developer database defaults and refuse non-isolated SQLite
databases. The PostgreSQL test is opt-in and creates/removes its own temporary
socket-only cluster:

```sh
OWNER_TEST_POSTGRES_BIN=/path/to/postgresql/bin python -m unittest discover -s tests -p test_owner_migration_postgres.py -v
```

`tools/reconcile_owner_analysis.py` independently sums dated records using SQL,
then compares the application reports. It requires explicit local test-copy
URLs, enforces read-only transactions and ignores optional developer env files.
It never downloads backups, applies migrations, invents employment history or
configures overheads. Financial JSON output belongs outside the repository.

The recovery verification on 17 October 2026 used the repository's historical
archive created **22 December 2024**, not a fresh live backup. The original
archive was restored unchanged. A separate clone successfully followed the
actual `615139181c4d` → `859d6ebe2110` legacy migration path and then both new
owner migrations. Original source columns/records were preserved. The two new
migrations were also checked separately on a synthetic previous-head database.

All **123 independent comparisons matched** across normal week 2–8 November
2024, holiday week 28 September–4 October 2024, absence week 30 November–6 December
2024, and October/November 2024 payroll months. October has five whole weeks;
November has four. Comparisons cover recorded earnings, employer costs, fuel
spending/litres, per-driver figures/status counts and per-truck fuel totals.

These checks establish arithmetic and migration behaviour for this historical
archive. They do not establish current live schema/data completeness or the
accuracy of the original receipts/payroll entries. Historical overhead settings
were left unknown, so no estimated result or final review was invented. A fresh
backup and confirmed effective overhead history are still required for current
real-data verification before deployment.
