# RC#1: Bulk loading

Sponsor and admin navigation now includes **Bulk import**. Select a UTF-8 pipe-delimited text file with no header. Every physical line is one record. Empty interior lines are errors; a final newline is not an extra record. Quotes are ordinary characters, not quoting syntax. Pipes cannot appear inside values.

```
O|New Organization
D|New Organization|Joe|Driver|joe@example.com|100|Welcome bonus
S|New Organization|Jill|Sponsor|jill@example.com
```

Sponsors leave the organization field empty (`D||Joe|Driver|joe@example.com`). Their organization comes from the authenticated session. Supplying an organization reports a warning and ignores that field. Sponsor users cannot create organizations. Administrator organizations must already exist or precede their users in the file. New organizations use the application's default $0.01 per point.

Each valid line commits independently. A rejected line rolls back account, membership, point, notification, and audit writes together; subsequent lines continue. Results identify original line numbers. Sponsor-user points/reasons generate a warning and are ignored while the account is processed. This follows the PDF's written rule despite the contradictory “no errors” sample.

Email matches existing users case-insensitively using the database collation. Existing driver imports activate only the specified membership, approve pending applications for that membership, and add/subtract points without resetting its balance. Other sponsor balances remain unchanged. Existing passwords and profiles remain unchanged. Existing sponsor users must already belong to the target organization. Role conflicts and locked/inactive accounts are rejected. Admin accounts cannot be imported.

Points are signed integers within the database's BIGINT range. Reasons are required when points are supplied, including zero. Zero does not create a point transaction. Deductions cannot make a balance negative.

## Confirmed decisions

- Generate usernames and strong initial passwords for new users. Only password hashes are stored in the database. The uploader receives a separate credentials CSV, available in the current page session, and shares it privately. Users should change these initial passwords; a forced first-login password-change workflow is not part of this change.
- Preserve existing account validation, as requested: valid email addresses, 50-character first/last names, 100-character emails/organization names, and 500-character point reasons. These limits are an explicit exception to the PDF's unrestricted-fields statement.
- No database migration is required; the existing RC#2 schema supports these imports.

## Large files and interruptions

The browser incrementally decodes the file and sends numbered records to `POST /api/bulk-import`. There is no total file-size/count limit; the API accepts up to 20 lines per request and the page submits one line per request to avoid long-running upload requests and isolate uncertain outcomes. The UI keeps only the most recent 100 result rows in the DOM. Downloadable report/credential contents remain in browser memory until navigation; extremely large reports are subject to available browser memory.

Do not refresh or leave during an import. Download results and credentials before leaving. There are no automatic retries: importing a points record again deliberately adds its amount again. If a connection fails after a commit but before its response arrives, the current line may have succeeded. Check that line's account/audit/point history before resuming from the remaining lines. An administrator can reset a newly created password if the credentials response was lost. Previously confirmed lines remain saved. Use UTF-8 files; malformed UTF-8 stops processing rather than changing identity text silently.

## Verification

Use a non-production database. Never run the pytest database fixtures against the shared database: they recreate their named test database.

Backend coverage: ordered organization creation, line errors/rollback, organization isolation, role conflicts, generated-password hashes, existing-driver balance additions, multiple memberships, automatic pending-application approval, optional fields, Unicode/BOM/CRLF, inactive organizations, unauthorized users and view-as restrictions.

Frontend coverage: streaming chunk boundaries, empty lines, terminal newlines, invalid UTF-8, large inputs, and CSV escaping/formula protection.

## Backlog story drafts

These are drafts for Azure DevOps, not items created there. Keep the `RC#1:` prefix for traceability.

1. **RC#1: Upload Pipe-Delimited User Files** — As an admin or sponsor user, I can select a UTF-8 pipe-delimited file and process it in order without a total file-size limit.
2. **RC#1: Report Errors and Continue Importing** — Each invalid line is reported with its line number and rolled back; later valid lines are still processed. Download a complete result report.
3. **RC#1: Restrict Sponsor Imports to Their Organization** — Sponsors cannot import O records; nonempty organization fields are flagged and ignored; all accepted D/S records use the authenticated sponsor's organization.
4. **RC#1: Bulk Create Organizations as Admin** — Admins create active organizations with O records. User records referencing missing/ambiguous organizations fail until a preceding O record creates one.
5. **RC#1: Bulk Create Driver and Sponsor Accounts** — Create new users with generated login credentials and reject existing-account role conflicts. Admin records are unsupported.
6. **RC#1: Bulk Update Driver Points** — Match drivers by email, add signed point changes to the target membership, require a reason, preserve other balances, and reject negative resulting balances.
7. **RC#1: Automatically Accept Imported Drivers** — Activate the imported membership and approve its pending application without manual application review.
8. **RC#1: Ignore Points on Sponsor Records** — Report ignored point/reason fields while still creating or processing an otherwise valid sponsor account.
9. **RC#1: Download New-User Credentials** — Provide a separate credentials CSV to the authorized uploader; store only password hashes and preserve existing passwords.

## Manual acceptance checklist

- Admin: import the admin example; confirm the organization appears and new users can sign in using downloaded credentials.
- Sponsor: import the sponsor example; confirm both users belong only to that sponsor, then repeat a driver record with points and check the increment.
- Mix unknown record types, missing reasons, and an overspending deduction among valid lines; confirm exact line errors, no partial writes, and continued processing.
- Switch among a driver's sponsors and confirm unrelated balances remain unchanged.
- Import an S record with points and a sponsor D record with a foreign organization name; verify explicit warnings and correct scope.
- Download both reports and verify row numbers, credential accuracy, and error details.
