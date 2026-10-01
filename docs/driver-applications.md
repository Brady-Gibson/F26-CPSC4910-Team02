# Driver Sponsor Application (Sprint 3)

Backend for drivers applying to a sponsor, plus the sponsor approve/reject step it depends on.

## Files

| File | What it is |
|---|---|
| `database/migrations/001_driver_application_details.sql` | Adds CDL number, CDL state, years of experience, and notes to `DRIVER_APPLICATION` |
| `backend/db.py` | Connection helper (mysql-connector, same `.env` variables as `application.py`) |
| `backend/routes/driver_applications.py` | The routes (a Flask blueprint) |
| `backend/tests/` | 14 pytest tests, success and failure cases |

## Plugging it into the main Flask app

Already done in `backend/application.py`:

```python
from db import close_db
from routes.driver_applications import bp as driver_applications_bp

application.secret_key = os.getenv("SECRET_KEY")
application.register_blueprint(driver_applications_bp)
application.teardown_appcontext(close_db)
```

Add `SECRET_KEY=` (any long random string) to your `.env`. Flask needs it to keep users logged in.

The routes read the logged-in user from `session["user_id"]`, so the login route needs to set that.
If the team already has its own DB helper, change the `from db import get_db` line to use it.

## Routes

| Method | URL | Who | Body | Returns |
|---|---|---|---|---|
| GET | `/api/driver/sponsors` | driver | | `[{sponsor_id, sponsor_name}]` |
| GET | `/api/driver/applications` | driver | | list with `status`, `submitted_at`, `decision_at`, `rejection_reason`, applicant fields |
| POST | `/api/driver/applications` | driver | `{sponsor_id, cdl_number, cdl_state, years_experience, notes?}` | `201 {application_id, status}` |
| POST | `/api/sponsor/applications/<id>/decision` | sponsor user | `{decision: "APPROVE"/"REJECT", reason}` | `{application_id, status}` |

Errors come back as `{"error": "message to show the user"}` with 400 (bad input), 401 (not logged in),
403 (wrong role), 404 (not found / not your org), or 409 (blocked by a rule).

## Rules enforced

- CDL number, two-letter state, and years of experience (0 to 70) are required.
- A driver who is ACTIVE with a sponsor can't apply to another one.
- Only one PENDING application at a time. After a rejection the driver can apply again.
- Rejecting requires a reason, and the driver sees it.
- Sponsors can only decide applications sent to their own organization.
- Every submission, blocked attempt, and decision writes an `AUDIT_EVENT` row.
- Every decision writes a `NOTIFICATION` row for the driver.

## Running the tests

Needs a local MySQL/MariaDB (never the shared RDS database, the tests drop and recreate their database).

```powershell
cd backend
pip install -r requirements.txt pytest
$env:TEST_DB_HOST="localhost"; $env:TEST_DB_USER="root"; $env:TEST_DB_PASSWORD="yourpassword"
python -m pytest tests -v
```
