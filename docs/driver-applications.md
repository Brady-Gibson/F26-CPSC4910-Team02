# Driver pages + Driver Sponsor Application (Sprint 3)

Built on the backend foundation (`db.py`, `auth.py`, `audit.py`). Uses `query()` / `transaction()`,
`@require_role(...)`, and `log_audit()` / `notify()`.

## Files

| File | What it is |
|---|---|
| `frontend/driver/*.html` | The 8 driver pages from the driver bundle. `sponsor.html` is converted to the live API. |
| `frontend/sponsor/applications.html` | Sponsor approve/reject page, converted to the live API |
| `backend/routes/driver.py` | `/api/driver/dashboard` (from the bundle) + the application endpoints |
| `backend/routes/sponsor.py` | `/api/sponsor/applications` + the approve/reject endpoint |
| `database/migrations/001_driver_application_details.sql` | Adds CDL number, CDL state, years of experience, and notes to `DRIVER_APPLICATION` |
| `backend/tests/` | 15 pytest tests against the real app and real `/api/login` |

**Run the migration on RDS before using the apply form**, or the insert fails (the columns won't exist).

## Endpoints

| Method | URL | Role | Body | Returns |
|---|---|---|---|---|
| GET | `/api/driver/sponsors` | driver | | `{sponsors: [{sponsor_id, sponsor_name}]}` |
| GET | `/api/driver/applications` | driver | | `{applications: [...]}` with `status`, `submitted_at`, `decision_at`, `rejection_reason`, CDL fields |
| POST | `/api/driver/applications` | driver | `{sponsor_id, cdl_number, cdl_state, years_experience, notes?}` | `201 {ok, application_id, status}` |
| GET | `/api/sponsor/applications` | sponsor | | `{applications: [...]}` for my organization only |
| POST | `/api/sponsor/applications/<id>/decision` | sponsor | `{decision: "APPROVE"/"REJECT", reason}` | `{ok, application_id, status}` |

Errors come back as `{"error": "message to show the user"}`: 400 bad input, 401 not signed in,
403 wrong role, 404 not found / not your org, 409 blocked by a rule.

## Rules enforced

- CDL number, two-letter state, and years of experience (0 to 70) are required.
- A driver who is ACTIVE with a sponsor can't apply to another one.
- Only one PENDING application at a time. After a rejection the driver can apply again.
- Rejecting requires a reason, and the driver sees it.
- Sponsors only see and decide applications sent to their own organization.
- Every submission, blocked attempt, and decision writes an `AUDIT_EVENT` row (category `APPLICATION`).
- Every decision writes a `NOTIFICATION` for the driver (`APPLICATION_APPROVED` / `APPLICATION_REJECTED`).

## Running the tests

Needs a local MySQL/MariaDB. **Never** point these at RDS: they drop and recreate their own database.

```powershell
cd backend
pip install pytest
$env:TEST_DB_HOST="localhost"; $env:TEST_DB_USER="root"; $env:TEST_DB_PASSWORD="yourpassword"
python -m pytest tests -v
```
