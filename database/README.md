# RC#2 database changes

## What is implemented

- `DRIVER_SPONSOR` identifies each membership by `(driver_id, sponsor_id)` and
  stores its own nonnegative balance, participation status, and join date.
- Foreign keys tie point transactions, recurring schedules, carts, and orders
  to a specific membership. Keep ended memberships for history and refunds.
- Applications permit different sponsors concurrently. A generated nullable key
  permits only one PENDING application for each driver/sponsor pair; rejected
  and approved history is retained, and reapplication after rejection is allowed.
- Each driver can have one ACTIVE cart per sponsor. Composite foreign keys
  require cart/order items to use their parent cart/order's sponsor and a valid
  product from that sponsor's catalog.
- New seed data demonstrates one driver with 500 points at one sponsor and
  200 at a second. It includes separate catalogs and carts.

## Important application boundary

The local backend now uses DRIVER_SPONSOR for account assignment, approvals,
drops, point changes, refunds, schedules, and driver commerce. Driver pages use
scoped APIs and a sponsor selector; administrators can view and add memberships.
**Neither the migration nor this application version has been deployed to RDS.**

The old DRIVER sponsor/balance/status/date fields remain temporarily and are not
synchronized. They are no longer authoritative. Keep them until every external
consumer has been checked; remove them in a separate cleanup migration.

Sponsor-scoped APIs derive the sponsor from the signed-in sponsor user. Only
administrators and the driver can list that driver's other memberships. The
all-table development bootstrap now requires an administrator and remains
disabled in production.

Selected sponsor is a session preference, not another membership column. Check
that it still refers to an active membership on every relevant request. Do not
infer membership from an old APPROVED application.

For redemption, within the same transaction as the order and ledger writes:

```sql
UPDATE DRIVER_SPONSOR
SET current_points = current_points - :cost
WHERE driver_id = :driver_id AND sponsor_id = :sponsor_id
  AND participation_status = 'ACTIVE' AND current_points >= :cost;
```

The backend must validate a strictly positive cost derived from the sponsor's
catalog, require exactly one affected row, and roll back the whole transaction
on failure. Never sum balances across sponsors. The placeholders above are
illustrative; use the connector's parameter syntax. Refund against the original
order's pair, even after membership ends. Membership balance and ledger writes
must be atomic; the schema does not automatically charge an inserted order.

## Fresh local database

1. Create/select a disposable schema.
2. Run `schema.sql` (change its USE statement if needed).
3. Optionally run `seed_test_data.sql` in that same schema.
4. Run `test_queries.sql` for example reads.

The fresh schema already includes migrations 001 and 002. **Do not run the
numbered migrations again on a fresh schema.** Seed files are test data only,
not production migration scripts.

## Existing database upgrade

1. Verify the coordinated RC#2 backend/frontend build on MySQL 8.4 and staging.
2. Back up the existing database and rehearse restoration and migration on a
   staging copy using the same MySQL version as RDS.
3. Pause all writers, including background schedules. Confirm migration 001
   was already applied (CDL/application detail fields exist).
4. Run `migrations/002_multiple_sponsors.sql`. Use a SQL client that supports
   DELIMITER and stored routines. It requires CREATE/ALTER/REFERENCES and
   CREATE ROUTINE/ALTER ROUTINE/EXECUTE privileges.
5. Its procedure checks conflicts before changing tables: duplicate pending
   applications or active carts for the same pair, cross-sponsor items,
   negative/unassigned balances, and historical records for sponsors that
   differ from the driver's legacy sponsor.
6. If a check fails, stop and reconcile the reported records on staging first.
   Historical balances and ended memberships cannot safely be inferred from
   the single legacy balance. Do not delete history or relabel it to bypass a
   check. Such databases require an explicitly reconciled membership mapping
   and a tailored backfill before applying membership foreign keys.
7. Run `verify_multiple_sponsors.sql`. Confirm every legacy membership was copied with the same balance, status,
   and join date. Existing ledger, order, and application rows are not rewritten.
   Confirm total counts and per-sponsor balances against the backup.
8. Deploy the RC#2 backend before resuming writes. After all consumers stop
   reading legacy DRIVER columns, remove those columns and fk_driver_sponsor
   in a separate reviewed cleanup migration.

The migration is intentionally one-time and refuses to overwrite an existing
membership table. MySQL DDL auto-commits: a failure after preflight may leave
partial schema changes. Keep writers paused, inspect the failure, and restore
the backup rather than blindly rerunning. Preflight failures do not change
business tables, though the temporary migration procedure may remain.

## Verification and CI

`database/tests/test_rc2_database.py` tests fresh schema, independent balances,
application/cart uniqueness, sponsor isolation, membership foreign keys,
history preservation, upgrade equivalence, unsafe-data preflight, and replay
rejection. It creates randomly named disposable databases on a local test server.
It never reads backend/.env and refuses non-local RC2_TEST_HOST values.

```sh
RC2_TEST_HOST=127.0.0.1 RC2_TEST_USER=root RC2_TEST_PASSWORD=your-test-password \
  backend/venv/bin/python -m pytest database/tests -v
```

Alternatively set RC2_TEST_SOCKET to a local isolated server's Unix socket.
CI runs this suite on its MySQL 8.4 service before deployment.

`backend/tests/conftest.py` now builds the current consolidated schema and seed.
Backend integration tests cover independent applications, approvals, balances,
drops, refunds, session selection, admin assignments, checkout isolation,
rollback, and replay protection. The legacy fixtures remain only for testing
the upgrade migration.

Local verification uses MySQL 9.5. CI is configured for MySQL 8.4; the remote CI
run and migration rehearsal on the RDS version still need to pass before rollout.
