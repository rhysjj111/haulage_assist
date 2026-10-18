# Owner Analysis: deployment and rollback

This is the proposed release procedure for the owner-reporting redesign and
stage 3 data checks on `jjcalc`. The recorded working production baseline is
commit `c67e8a22803356ab6d804c9ceb68674734266d33`, with database revision
`b2e7a9c4106f` and all four owner tables already present. Verify the actual live
state again immediately before release; these recorded facts are not a current
live preflight. Opening or updating the draft PR does not approve a production
merge or deployment. The preflight, backup and release commands below have not
been run against production for this proposed release.

## Release approach

The Procfile already uses Heroku's native release phase:

```procfile
release: flask --app run:app db upgrade
web: gunicorn run:app
```

Heroku runs the migration command from the newly built code before promoting
that version's web process. The existing web version continues serving while
the release phase runs. A failed release phase does not promote the new web
version. This release requires one new migration before the new decision options
can be saved.

Future pending, committed migrations also run during release. Review migration
files before releases, and do
not run a second manual migration command concurrently. An existing migration
head produces a no-op. The command explicitly selects `run:app`, without relying
on a separately configured `FLASK_APP` variable.

App configuration uses `HEROKU_POSTGRESQL_CHARCOAL_URL` in production. Preserve
that attachment/configuration and the current stack for this release. A separate
Heroku stack upgrade should remain a separate change. Do not copy live database
credentials into commands, PR comments or repository files.

The only pending schema change is `b2e7a9c4106f` → `d4a8f6c239b1`. It widens
`ck_owner_issue_decision` on `owner_issue_verification` to accept `dismissed` and
`awaiting_invoice`, alongside the existing decisions. It creates no tables or
columns, inserts no records and changes no financial values. The existing
overhead settings, weekly snapshots, review notes and sign-offs are retained.

## 1. Before an approved merge

Use an authenticated Heroku CLI session with access to `jjcalc`. Record the
results privately. This procedure still requires a live preflight; a restored
backup cannot establish the application's current state at release time.

```sh
heroku releases --app jjcalc
heroku ps --app jjcalc
heroku pg:info HEROKU_POSTGRESQL_CHARCOAL --app jjcalc
heroku pg:psql HEROKU_POSTGRESQL_CHARCOAL --app jjcalc --command "SELECT version_num FROM alembic_version;"
heroku pg:psql HEROKU_POSTGRESQL_CHARCOAL --app jjcalc --command "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_name IN ('owner_overhead_setting', 'owner_weekly_overhead', 'owner_issue_verification', 'owner_week_review') ORDER BY table_name;"
heroku pg:psql HEROKU_POSTGRESQL_CHARCOAL --app jjcalc --command "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'public.owner_issue_verification'::regclass AND conname = 'ck_owner_issue_decision';"
```

Confirm all of the following before merging:

- The existing wages calculator and entry forms work, and the web process is up.
- The attachment is the application's existing production database. The app's
  `DEVELOPMENT` override is not enabled in production.
- Exactly one migration revision is reported: `b2e7a9c4106f`.
- All four owner tables exist: `owner_overhead_setting`,
  `owner_weekly_overhead`, `owner_issue_verification` and `owner_week_review`.
- The decision constraint allows `verified`, `confirmed_zero` and `note`.
- Record the current overhead configuration and representative financial totals
  privately for comparison after release. Preserve existing configuration; this
  is not an initial owner-table installation.
- Record the currently working release number, such as `v123`, with its source
  commit. The example is not the actual live release number.
- Check the latest `main` and recovery-branch heads. Review/retest any intervening
  changes before merging; do not overwrite another person's work.

If the database, revision, existing tables or application state differs, stop and
investigate the actual state. Do not use `db stamp`, `db.create_all()`, a migration
downgrade, or a blind retry to force a match.

Capture a backup of that exact attachment immediately before the approved release:

```sh
heroku pg:backups:capture HEROKU_POSTGRESQL_CHARCOAL --app jjcalc
heroku pg:backups --app jjcalc
```

Confirm capture completed successfully and record its backup ID and creation
time. Retain a downloaded copy privately. Confirm that this is a **backup of the
production database**, not a test database or a previous backup mistaken for the
new capture. Keep the prior working release available for code rollback.

The new migration has passed an isolated PostgreSQL rehearsal of upgrade,
downgrade, re-upgrade and constraint rejection, with source records, overhead
settings and review history preserved. Updating an existing metadata-created
Codespace schema has also been rehearsed without reseeding or stamping. These
synthetic tests do not replace a rehearsal of the exact proposed release against
an isolated restored copy of the fresh production backup. Run that rehearsal
before merging and compare financial records, settings and review history before
and after. Backups and detailed comparison results must stay outside the public
repository. Never run `tools/setup_review.py` against production; it is restricted
to the dedicated synthetic review database.

## 2. Approved merge and automatic deployment

Only after the owner approves this release:

1. Mark the PR ready and merge it into `main`. The existing GitHub integration
   can start an automatic Heroku build. Do not separately trigger another build
   or a manual database upgrade at the same time.
2. Watch Heroku's build/release logs. The release command should apply only:
   `b2e7a9c4106f` → `d4a8f6c239b1`.
3. Confirm the release phase succeeded, then confirm the new web release is up.
   A successful build alone does not establish that the release succeeded.

Read-only status checks:

```sh
heroku releases --app jjcalc
heroku ps --app jjcalc
heroku logs --tail --app jjcalc
```

Use the activity/release details to inspect the migration command's logs. Stop
log tailing with Ctrl-C after verification. Do not paste private log contents
into a public PR.

## 3. Verify the release

Check the database without changing any records:

```sh
heroku pg:psql HEROKU_POSTGRESQL_CHARCOAL --app jjcalc --command "SELECT version_num FROM alembic_version;"
heroku pg:psql HEROKU_POSTGRESQL_CHARCOAL --app jjcalc --command "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_name IN ('owner_overhead_setting', 'owner_weekly_overhead', 'owner_issue_verification', 'owner_week_review') ORDER BY table_name;"
heroku pg:psql HEROKU_POSTGRESQL_CHARCOAL --app jjcalc --command "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'public.owner_issue_verification'::regclass AND conname = 'ck_owner_issue_decision';"
```

Expect revision `d4a8f6c239b1`, the same four owner tables and the decision
constraint allowing all five values. No records should have been seeded or
rewritten. Compare the recorded financial totals, overhead settings and review
history with the preflight; investigate differences before sending figures.

Check these screens using existing saved records, without creating fake live
entries or changing actual payroll values:

1. Home, existing wages calculator, and Add Job/Day/Fuel/Payslip forms and history.
2. Owner Analysis weekly Overview and monthly Overview, including date navigation.
3. Drivers and Trucks views, their detail popups, and switches between week/month.
   Blank weekends are not absences; actual recorded weekend work remains visible.
4. Data Checks has one Review action for a check, with the relevant evidence and
   form together. Grouped missing weekdays retain their individual dates.
5. Fuel price-per-litre/possible-duplicate and payroll warnings show the source
   figures. Essential and optional checks are clearly distinguished, with
   optional information not blocking sign-off.
6. Missing costs and entries remain visible. An awaiting-invoice note retains
   the outstanding fuel cost; a dismissal never supplies a missing cost or
   deletes a receipt. Incomplete figures are not presented as final profit.
7. The grouped menu reaches the existing entry forms, wages calculator, new
   reporting and settings. Old weekly/monthly analysis links are removed from
   the menu; new report date switches and contextual back links still work.

Keep the existing **Truck & overhead settings**. They already carry forward;
neither this release nor a new week requires re-entering them. Record a dated
change only when the fleet count or agreed allowance actually changes. Review
recent underlying entries and outstanding invoices before sending final figures
to the owner. Do not mark a week reviewed merely to remove warnings.

## 4. If something fails

### Build or release phase fails

Do not promote the new version manually. Confirm the previous web process is
still serving and inspect the failed build/release logs. PostgreSQL applies this
constraint change with transactional DDL. The isolated compatibility rehearsal
also verifies that a surrounding failure rolls back the constraint update.

Even so, inspect the **actual** revision/schema after a failure before retrying:
config changes, a manually applied migration or concurrent work can change the
situation. Repair the concrete cause, then retry the intended release. Do not
stamp a revision or delete tables to bypass an error.

### Migration succeeds but the new app misbehaves

Roll code back to the working release recorded before deployment. For example,
**replace `v123` with the actual recorded release number**:

```sh
heroku rollback v123 --app jjcalc
heroku ps --app jjcalc
```

Confirm the old wages calculator/forms are working again. Keep all four owner
tables, the expanded decision constraint and revision `d4a8f6c239b1` in place.
The original three decisions remain valid, and no legacy financial schema was
changed. Existing dismissals and awaiting-invoice notes remain stored, although
an older app may not understand those new decision types. Do not roll back again
to the failed new slug.

Heroku rollback restores a previous release's code/configuration, not its
database contents, and it does not run the previous release's release phase.
Check the attachment and relevant configuration after rollback. The old source
may not know the new migration revision; do not run old-code migration commands.
Any fix/redeployment should start from code containing the complete committed
migration chain, including `d4a8f6c239b1`.

A deliberate downgrade of `d4a8f6c239b1` is available if separately required and
rehearsed: it maps `dismissed` to `verified` and `awaiting_invoice` to `note`
before restoring the original CHECK. It preserves every row's ID, explanation,
timestamp and source fingerprint, but changes those decision labels. This is
not part of a normal Heroku code rollback. Do not downgrade the earlier owner
migrations, which would remove their tables and stored history.

Database restore is a separate disaster-recovery action, not the normal code
rollback. Restoring the backup would discard entries written after that backup
and needs a specific recovery decision. No database downgrade or restore is part
of this proposed release plan.

## References

- [Heroku release phase](https://devcenter.heroku.com/articles/release-phase)
- [Heroku release rollback](https://devcenter.heroku.com/articles/releases#rollback)
- [Heroku Postgres backups](https://devcenter.heroku.com/articles/heroku-postgres-backups)
