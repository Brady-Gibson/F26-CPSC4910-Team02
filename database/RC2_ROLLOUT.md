# RC#2 live rollout — October 20, 2026

Migration `002_multiple_sponsors.sql` was applied to shared `Team02_DB`
on RDS MySQL 8.4.9 after the user confirmed no other writers and the
Beanstalk application was placed in maintenance mode.

## Data verification

- Rehearsed restoration and migration of the real backup on an isolated
  MySQL 8.4.9 instance.
- All 91 backend/database tests passed on MySQL 8.4.9.
- Took a fresh backup after maintenance started.
- Row counts and content hashes matched for all 18 original tables after
  migration.
- Created two existing sponsor memberships; balance, participation status,
  and join date matched the legacy records with zero mismatches.
- Verified 36 foreign keys in the migrated schema.
- No test seed data was loaded into the shared database.

The private cutover backup and detailed verification report are stored locally:

```
database/backups/Team02_DB_cutover_20261020T155138Z.sql
database/backups/Team02_DB_cutover_20261020T155138Z.verification.json
```

This directory is excluded from Git and deployment bundles. Preserve these
files securely; they contain database data. Backup SHA-256:
`76384e416299a7f21a131ff856780052957b381789e6a59ad64a698d3ccf1b3e`.

## Application compatibility

The matching application bundle is based on commit
`de5708bf131caa76a0fe5ed01037cf5cecac8c25` from
`codex/rc2-multiple-sponsors`, deployed as `de5708b-rc2-20261020` to
`Team02-gdip-env`.

Post-deployment HTTP checks confirmed `/api/health` returns 200 with a successful
connection to `Team02_DB`, `/login.html` and `/assets/js/driver-live.js` return
200, and the new memberships API returns 401 for an unauthenticated request.
These are availability checks; authenticated workflows were covered by the
isolated integration tests, not by creating test transactions in production.

Do not rerun migration 002, the consolidated schema, or test seeds in Workbench
against this shared database. Refresh the schema browser to see DRIVER_SPONSOR.
Legacy DRIVER columns remain intentionally for a later reviewed cleanup;
DRIVER_SPONSOR is now authoritative.

The old main-branch application is incompatible with this migrated database.
Merge the RC#2 branch before future deployments from main. Do not redeploy an
older application version as a standalone rollback: restoring the old schema
requires a coordinated backup restore and reconciliation of any newer writes.
