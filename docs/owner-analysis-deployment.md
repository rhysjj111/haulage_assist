# Owner Analysis: deployment and rollback

This is a proposed release procedure for `jjcalc`. Opening this draft PR or
updating its recovery branch does not approve a production merge or deployment.
No commands in this document have been run against the live application.

## Release approach

The Procfile adds Heroku's native release phase:

```procfile
release: flask --app run:app db upgrade
web: gunicorn run:app
```

Heroku runs the migration command from the newly built code before promoting
that version's web process. The existing web version continues serving while
the release phase runs. A failed release phase does not promote the new web
version. This avoids exposing the new analysis routes before their tables exist.

This is a permanent deployment change: future pending, committed migrations will
also run during release. Review migration files before future releases, and do
not run a second manual migration command concurrently. An existing migration
head produces a no-op. The command explicitly selects `run:app`, without relying
on a separately configured `FLASK_APP` variable.

App configuration uses `HEROKU_POSTGRESQL_CHARCOAL_URL` in production. Preserve
that attachment/configuration and the current stack for this release. A separate
Heroku stack upgrade should remain a separate change. Do not copy live database
credentials into commands, PR comments or repository files.

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
```

Confirm all of the following before merging:

- The existing wages calculator and entry forms work, and the web process is up.
- The attachment is the application's existing production database. The app's
  `DEVELOPMENT` override is not enabled in production.
- Exactly one migration revision is reported: `859d6ebe2110`.
- None of the four new owner tables exists yet.
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

The two canonical migrations were rehearsed on isolated restored copies, with
the original tables, rows, schema objects and sequences preserved. The exact
release CLI command is also rehearsed against a disposable restored database.
Backups and detailed financial comparison results remain outside this public PR.

## 2. Approved merge and automatic deployment

Only after the owner approves this release:

1. Mark the PR ready and merge it into `main`. The existing GitHub integration
   can start an automatic Heroku build. Do not separately trigger another build
   or a manual database upgrade at the same time.
2. Watch Heroku's build/release logs. The release command should apply only:
   `859d6ebe2110` → `7e9c2a41b6d8` → `b2e7a9c4106f`.
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
```

Expect revision `b2e7a9c4106f` and all four owner tables. No initial overhead
settings or historical signoffs should have been seeded by the migration.

Check these screens using existing saved records, without creating fake live
entries or changing actual payroll values:

1. Home, existing wages calculator, and Add Job/Day/Fuel/Payslip forms and history.
2. Owner Analysis weekly Overview and monthly Overview, including date navigation.
3. Drivers and Trucks views, their filters, and switches between week/month.
4. Missing entries stay visible; incomplete/unknown results are not presented as
   reviewed or as a final profit estimate. An unflagged missing receipt still
   needs a human fuel-record check.

After those checks, use **Weekly overhead settings** on the new page to enter
the confirmed allowance, four-truck count and first applicable Saturday. These
carry forward automatically; do not infer historical values. Review/correct
recent underlying entries before sending final figures to the owner. Do not mark
a week reviewed merely to remove warnings.

## 4. If something fails

### Build or release phase fails

Do not promote the new version manually. Confirm the previous web process is
still serving and inspect the failed build/release logs. On PostgreSQL, the two
migrations run with transactional DDL. A separate deliberate-conflict rehearsal
checks that an error leaves the original revision and tables intact.

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

Confirm the old wages calculator/forms are working again. Keep the four additive
owner tables and the migration revision in place. They do not remove or alter
the legacy tables, and retaining them preserves any new overhead settings or
review notes. Do not roll back again to the failed new slug.

Heroku rollback restores a previous release's code/configuration, not its
database contents, and it does not run the previous release's release phase.
Check the attachment and relevant configuration after rollback. The old source
may not know the new migration revision; do not run old-code migration commands.
Any fix/redeployment should start from code containing both additive migrations.

Database restore is a separate disaster-recovery action, not the normal code
rollback. Restoring the backup would discard entries written after that backup
and needs a specific recovery decision. No database downgrade or restore is part
of this proposed release plan.

## References

- [Heroku release phase](https://devcenter.heroku.com/articles/release-phase)
- [Heroku release rollback](https://devcenter.heroku.com/articles/releases#rollback)
- [Heroku Postgres backups](https://devcenter.heroku.com/articles/heroku-postgres-backups)
