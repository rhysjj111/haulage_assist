# Owner Analysis

Owner Analysis is separate from the existing wage calculator and old analysis
pages. Open `/owner-analysis` for a Saturday–Friday payroll week, or
`/owner-analysis/monthly?month=YYYY-MM` for a payroll month. Overview, Drivers
and Trucks are available for both periods. The Overview puts estimated profit
first, followed by recorded earnings, wages (employer cost), fuel and overheads.
Missing financial information is shown beside the pending result.

Open **Data Checks** from the menu (`/owner-analysis/checks`) to correct or verify
entries, add weekly notes and complete weekly reviews. Its default is the latest
finished payroll week. `/owner-analysis/checks/monthly?month=YYYY-MM` groups the
included completed weeks. Owner Analysis keeps a compact whole-period check
count and link on every view. Driver and truck views show all cards; the review
status covers the whole period. Zero outstanding checks still requires an explicit review.

Open **View week** on a driver or truck card for a read-only popup. Driver
details show dated jobs, collections/deliveries, notes, truck assignments,
earnings and recorded payslips. Truck details show each day's driver and mileage
readings, valid recorded mileage differences, and actual dated fuel receipts.
Monthly popups group the same completed payroll weeks used by the report.
Unfinished weeks and future-dated entries stay outside those figures.

Details load only when a card is opened. Closing or changing a request cancels
the previous load; errors offer a normal details-page link. Without JavaScript,
the same link opens the read-only page and returns to the selected period/view.
Individual dropdown filters have been removed. Old selection URLs still
validate and preserve existing signed correction links, but do not hide cards.

## Navigation

The same burger menu is available on Home, existing entry/history pages, the
wages calculator and the owner reporting/review pages. Home stays at the top;
visible headings group **Enter data** (Job, Day, Fuel, Payslip and Expense),
**Wages & reporting** (Wages Calculator, Owner Analysis and Data Checks) and
**Settings** (Drivers, Trucks and Truck & overhead settings). No dropdowns are
needed. The menu scrolls when the screen is shorter than its contents.

The old Weekly Analysis and Monthly Analysis menu links are removed; their
existing routes remain available. The weekly/monthly switch within Owner
Analysis and contextual back links retain their selected report/check period.

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
- Driver rows include recorded working, holiday and absent days. Blank weekdays
  remain unknown; blank Saturday/Sunday dates are not scheduled and do not count
  as missing or absent. Actual recorded weekend work still counts. Period employment or recorded Day/Payslip entries determine
  membership, preserving drivers who have since left. Daily averages divide
  recorded earnings by recorded Working days; zero Working days means no average.
- Truck rows show recorded fuel spending, purchased litres and receipt counts.
  A referenced truck with no receipts has zero recorded purchases; this does not
  establish downtime. The standard per-truck weekly allowance is displayed
  separately. Historical settings identify a truck count, not registrations, so
  no historical overhead total or profit is assigned to a named truck.
  Detail popups retain separate readings where several drivers used a truck;
  overlapping or invalid readings do not establish an aggregate distance, and
  a blank truck day does not establish downtime.
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

Open **Truck & overhead settings** from the menu or the small link below the
Overview figures (`/owner-analysis/overheads`). Enter the allowance per truck,
the truck count (including unused trucks), and the first Saturday they apply to.
The page shows current settings and dated previous/scheduled changes. Expand
**Add a change** when the fleet count or allowance changes; it is not a weekly
entry task. The change form initially proposes the current payroll week, even
when opened from an older report. Choose an earlier Saturday deliberately if
setting up historical reports or correcting an earlier setting.
Settings carry forward automatically. A later change applies from its selected
week up to the next scheduled change. Earlier weeks retain their prior values.
An intentionally historical effective date is an explicit correction.

No initial allowance, effective date or historical fleet count is guessed or
seeded. Four is only an unsaved form suggestion. A global settings-history
fingerprint rejects stale forms, including changes outside the currently viewed
week. Reads do not create weekly snapshots; snapshots are saved only by explicit
settings actions.

Weekly Overview shows the truck count and per-truck allowance applicable to that
week. Monthly Overview describes only its included completed weeks; if their
settings differ, expand **Settings varied during this period** for the dated
breakdown. Current/future settings are not substituted for historical values,
and missing settings remain unknown rather than zero.

Successful saves return to settings with the report week/month preserved for
the back link. Invalid entries remain on the form with a 400 response; stale or
conflicting saves return 409 with a refresh link and do not write changes.
The existing carry-forward calculation and database schema are unchanged.

## Checks and notes

Checks cover missing expected days, working days without earnings, fuel flags
without receipts, missing or multiple payslips, numeric ranges, missing overhead
settings, and informational mileage issues. Plausible incorrect data and
unflagged missing purchases still need human review.

Detailed checks, explanations, verification history and final-review forms live
on Data Checks. Weekly/monthly links retain the originating driver/truck view;
signed, validated report context returns corrections and settings to the same
checks period. Only known local reporting routes are valid return destinations.
Monthly checks and their counts include completed weeks only, matching the
monthly financial totals. Each included finished week has its own review; there
is no month-wide signoff. Informational checks remain in the outstanding count.

Explicit business notes for a week remain visible read-only on Owner Analysis.
Adding another note preserves earlier notes; lengthy notes have a short preview
and an expandable full version. Per-issue explanations and verification history
stay on Data Checks.

Each check has a **Review check** link with the available correction and review
actions beside the weekly evidence. The same read-only investigation panel
appears beside the correction forms on desktop. It shows all
seven dates, actual Working/Holiday/Absent entries and explicit unknown gaps,
recorded trucks, jobs/additional earnings, and the selected week's payslips for
all drivers. The selected date, driver and record are highlighted. Dates after
today are not yet due and are excluded from the week-so-far context and totals.
Truck context shows recorded day assignments and fuel receipts without
attributing driver earnings to trucks or inferring downtime from blank days.

**Show this driver's nearby payslips** is an explicit, bounded read-only request
for the preceding and following payroll weeks, capped at 50 records. Nearby
records stay separate from the selected week's figures. Already-recorded
future-dated nearby slips are visible and labelled, to help identify a mistaken
pay date. No nearby history query is run on initial page loading. The subject
comes from the actual check or signed correction, not independent driver/truck
query overrides.

The selected check can be explained/verified or have a confirmed Holiday/Absent
day recorded without leaving the weekly evidence. These use the same guarded
actions as Data Checks, including required explanations, CSRF, source-value
fingerprints and signed return navigation. Verification is offered only where
the rule permits it. A confirmed-zero payroll decision is explicitly labelled;
already verified checks show the saved explanation without another action form.
Final weekly signoff remains on Data Checks.

Legitimate exceptions require an explanation. Missing days require an actual Day
record (Working, Holiday or Absent). Unknown fuel and overhead costs cannot be
dismissed by a note. A mistaken fuel flag can be corrected without inventing a
purchase. Dedicated correction forms use signed, record-specific links with clear
units, save/cancel actions and a fixed driver identity. Missing-entry dates and
the truck on a missing-fuel check are fixed; existing-entry dates can only move within
the same payroll week. Money, mileage and litres are displayed in human units
once, and rejected submissions retain the entered text. Working-day controls are
shown only for Working status; changing to Holiday/Absent explains that day
details and additional amounts are cleared while existing jobs are retained.
Duplicate payslips can be compared, with an explicit duplicate confirmation
required before deletion. Historical inactive drivers remain eligible only for the exact correction.
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

They do not seed configuration or change existing entry/payroll records. This
branch adds a Heroku release phase to apply pending migrations before a new web
release starts. Future pending migrations will also run during release. Follow
the [deployment and rollback procedure](owner-analysis-deployment.md). Before a live release,
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
were left unknown, so no estimated result or final review was invented. Those
historical checks do not replace the live preflight, fresh pre-release backup
and confirmed effective overhead history described in the deployment procedure.
Uploaded backups and private financial comparison results are not committed.
