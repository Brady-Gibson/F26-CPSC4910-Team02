"""Driver Sponsor Application (Sprint 3) + the decision step it depends on.

Driver routes
    GET  /api/driver/sponsors          sponsors the driver can apply to
    GET  /api/driver/applications      the driver's applications, status, and rejection reasons
    POST /api/driver/applications      submit a new application

Sponsor route (shared with Sprint 4, Driver Application Review)
    POST /api/sponsor/applications/<id>/decision   approve or reject

User stories covered
    Sponsor Incentive Program     submit an application
    Driver Application Status     GET /api/driver/applications
    Application Alert             NOTIFICATION row on approval
    Application Rejection Alert   NOTIFICATION row on rejection
    Rejection Reason Statement    reason is returned with each application
    Required Information          cdl_number, cdl_state, years_experience are required
    One Sponsor                   blocked if the driver already has a sponsor or a pending application
    Recorded Application          AUDIT_EVENT row for every submission and decision

Who is logged in: this file reads session["user_id"]. The login route (Driver Login
feature) needs to set that after checking the password.

Register in application.py:
    from db import close_db
    from routes.driver_applications import bp as driver_applications_bp
    application.secret_key = os.getenv("SECRET_KEY")
    application.register_blueprint(driver_applications_bp)
    application.teardown_appcontext(close_db)
"""
from functools import wraps

from flask import Blueprint, jsonify, request, session

from db import get_db

bp = Blueprint("driver_applications", __name__)

US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN",
    "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH",
    "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT",
    "VT", "VA", "WA", "WV", "WI", "WY",
}


# ---------------------------------------------------------------- helpers

def error(message, status):
    return jsonify({"error": message}), status


def require_role(table, id_column):
    """Only let the request through if the logged-in user has a row in `table`."""
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user_id = session.get("user_id")
            if user_id is None:
                return error("Please log in.", 401)
            with get_db().cursor(dictionary=True) as cur:
                cur.execute(f"SELECT 1 FROM {table} WHERE {id_column} = %s", (user_id,))
                if cur.fetchone() is None:
                    return error("You don't have access to this page.", 403)
            return view(user_id, *args, **kwargs)
        return wrapped
    return decorator


driver_only = require_role("DRIVER", "driver_id")
sponsor_only = require_role("SPONSOR_USER", "sponsor_user_id")


def log_audit(cur, *, actor_user_id, sponsor_id, driver_id, success, details, entity_id=None):
    """Write one APPLICATION row to AUDIT_EVENT (same transaction as the change)."""
    cur.execute(
        """INSERT INTO AUDIT_EVENT
               (actor_user_id, sponsor_id, driver_id, category, subject_username,
                entity_type, entity_id, success, reason_or_details)
           VALUES (%s, %s, %s, 'APPLICATION',
                   (SELECT username FROM USER_ACCOUNT WHERE user_id = %s),
                   'DRIVER_APPLICATION', %s, %s, %s)""",
        (actor_user_id, sponsor_id, driver_id, driver_id, entity_id, success, details[:500]),
    )


def validate_application(data):
    """Return (clean_values, None) or (None, error message)."""
    try:
        sponsor_id = int(data.get("sponsor_id"))
    except (TypeError, ValueError):
        return None, "Pick a sponsor to apply to."

    cdl_number = str(data.get("cdl_number") or "").strip().upper()
    if not cdl_number or len(cdl_number) > 30 or not cdl_number.replace("-", "").isalnum():
        return None, "Enter a valid CDL number (letters and numbers, up to 30 characters)."

    cdl_state = str(data.get("cdl_state") or "").strip().upper()
    if cdl_state not in US_STATES:
        return None, "Enter the two-letter state that issued your CDL."

    try:
        years = int(data.get("years_experience"))
    except (TypeError, ValueError):
        return None, "Enter your years of driving experience as a whole number."
    if not 0 <= years <= 70:
        return None, "Years of experience must be between 0 and 70."

    notes = str(data.get("notes") or "").strip()
    if len(notes) > 500:
        return None, "Notes can be at most 500 characters."

    return {
        "sponsor_id": sponsor_id,
        "cdl_number": cdl_number,
        "cdl_state": cdl_state,
        "years_experience": years,
        "notes": notes or None,
    }, None


# ---------------------------------------------------------------- driver routes

@bp.get("/api/driver/sponsors")
@driver_only
def list_sponsors(driver_id):
    """Active sponsor organizations, minus the driver's current sponsor."""
    with get_db().cursor(dictionary=True) as cur:
        cur.execute(
            """SELECT s.sponsor_id, s.sponsor_name
                 FROM SPONSOR_ORGANIZATION s
                WHERE s.status = 'ACTIVE'
                  AND s.sponsor_id <> COALESCE(
                        (SELECT sponsor_id FROM DRIVER WHERE driver_id = %s), 0)
                ORDER BY s.sponsor_name""",
            (driver_id,),
        )
        return jsonify(cur.fetchall())


@bp.get("/api/driver/applications")
@driver_only
def my_applications(driver_id):
    """Every application this driver has sent, newest first, with status and reason."""
    with get_db().cursor(dictionary=True) as cur:
        cur.execute(
            """SELECT a.application_id, a.sponsor_id, s.sponsor_name, a.status,
                      a.submitted_at, a.decision_at,
                      CASE WHEN a.status = 'REJECTED' THEN a.reason END AS rejection_reason,
                      a.cdl_number, a.cdl_state, a.years_experience, a.applicant_notes
                 FROM DRIVER_APPLICATION a
                 JOIN SPONSOR_ORGANIZATION s ON s.sponsor_id = a.sponsor_id
                WHERE a.driver_id = %s
                ORDER BY a.submitted_at DESC, a.application_id DESC""",
            (driver_id,),
        )
        rows = cur.fetchall()
    for r in rows:
        for k in ("submitted_at", "decision_at"):
            r[k] = r[k].isoformat(sep=" ") if r[k] else None
    return jsonify(rows)


@bp.post("/api/driver/applications")
@driver_only
def submit_application(driver_id):
    values, problem = validate_application(request.get_json(silent=True) or {})
    if problem:
        return error(problem, 400)

    db = get_db()
    try:
        with db.cursor(dictionary=True) as cur:
            # Lock the driver row so two quick clicks can't create two applications.
            cur.execute(
                "SELECT sponsor_id, participation_status FROM DRIVER WHERE driver_id = %s FOR UPDATE",
                (driver_id,),
            )
            driver = cur.fetchone()

            cur.execute(
                "SELECT sponsor_name FROM SPONSOR_ORGANIZATION WHERE sponsor_id = %s AND status = 'ACTIVE'",
                (values["sponsor_id"],),
            )
            sponsor = cur.fetchone()
            if sponsor is None:
                db.rollback()
                return error("That sponsor isn't accepting applications.", 404)

            # One Sponsor rule
            blocked = None
            if driver["sponsor_id"] is not None and driver["participation_status"] == "ACTIVE":
                blocked = "You already have a sponsor. Drivers can only be with one sponsor at a time."
            else:
                cur.execute(
                    "SELECT 1 FROM DRIVER_APPLICATION WHERE driver_id = %s AND status = 'PENDING' LIMIT 1",
                    (driver_id,),
                )
                if cur.fetchone():
                    blocked = "You already have an application waiting for review."
            if blocked:
                log_audit(cur, actor_user_id=driver_id, sponsor_id=values["sponsor_id"],
                          driver_id=driver_id, success=False,
                          details=f"Application blocked: {blocked}")
                db.commit()
                return error(blocked, 409)

            cur.execute(
                """INSERT INTO DRIVER_APPLICATION
                       (driver_id, sponsor_id, status, cdl_number, cdl_state,
                        years_experience, applicant_notes)
                   VALUES (%s, %s, 'PENDING', %s, %s, %s, %s)""",
                (driver_id, values["sponsor_id"], values["cdl_number"], values["cdl_state"],
                 values["years_experience"], values["notes"]),
            )
            application_id = cur.lastrowid
            log_audit(cur, actor_user_id=driver_id, sponsor_id=values["sponsor_id"],
                      driver_id=driver_id, success=True, entity_id=application_id,
                      details=f"Driver applied to {sponsor['sponsor_name']}")
        db.commit()
    except Exception:
        db.rollback()
        raise

    return jsonify({"application_id": application_id, "status": "PENDING"}), 201


# ---------------------------------------------------------------- sponsor decision

@bp.post("/api/sponsor/applications/<int:application_id>/decision")
@sponsor_only
def decide_application(sponsor_user_id, application_id):
    """Body: {"decision": "APPROVE" | "REJECT", "reason": "..."}  (reason required to reject)."""
    data = request.get_json(silent=True) or {}
    decision = str(data.get("decision") or "").upper()
    reason = str(data.get("reason") or "").strip()
    if decision not in ("APPROVE", "REJECT"):
        return error("Decision must be APPROVE or REJECT.", 400)
    if decision == "REJECT" and not reason:
        return error("Give a reason when rejecting. The driver will see it.", 400)
    if len(reason) > 500:
        return error("Reason can be at most 500 characters.", 400)

    db = get_db()
    try:
        with db.cursor(dictionary=True) as cur:
            cur.execute("SELECT sponsor_id FROM SPONSOR_USER WHERE sponsor_user_id = %s",
                        (sponsor_user_id,))
            my_sponsor_id = cur.fetchone()["sponsor_id"]

            cur.execute(
                """SELECT a.application_id, a.driver_id, a.sponsor_id, a.status, s.sponsor_name
                     FROM DRIVER_APPLICATION a
                     JOIN SPONSOR_ORGANIZATION s ON s.sponsor_id = a.sponsor_id
                    WHERE a.application_id = %s FOR UPDATE""",
                (application_id,),
            )
            app = cur.fetchone()
            # Same message for "doesn't exist" and "not yours" so sponsors can't probe other orgs.
            if app is None or app["sponsor_id"] != my_sponsor_id:
                db.rollback()
                return error("Application not found.", 404)
            if app["status"] != "PENDING":
                db.rollback()
                return error(f"This application was already {app['status'].lower()}.", 409)

            driver_id = app["driver_id"]
            if decision == "APPROVE":
                cur.execute("SELECT sponsor_id, participation_status FROM DRIVER "
                            "WHERE driver_id = %s FOR UPDATE", (driver_id,))
                d = cur.fetchone()
                if d["sponsor_id"] is not None and d["participation_status"] == "ACTIVE" \
                        and d["sponsor_id"] != my_sponsor_id:
                    db.rollback()
                    return error("This driver already joined another sponsor.", 409)
                cur.execute(
                    """UPDATE DRIVER SET sponsor_id = %s, participation_status = 'ACTIVE',
                              joined_at = CURRENT_TIMESTAMP WHERE driver_id = %s""",
                    (my_sponsor_id, driver_id),
                )
                new_status, message = "APPROVED", (
                    f"Your application to {app['sponsor_name']} was approved. "
                    "You can start earning points now.")
                reason = reason or "Application approved"
            else:
                new_status, message = "REJECTED", (
                    f"Your application to {app['sponsor_name']} was not approved. Reason: {reason}")

            cur.execute(
                """UPDATE DRIVER_APPLICATION
                      SET status = %s, decided_by_user_id = %s,
                          decision_at = CURRENT_TIMESTAMP, reason = %s
                    WHERE application_id = %s""",
                (new_status, sponsor_user_id, reason, application_id),
            )
            # Application Alert / Application Rejection Alert
            cur.execute(
                """INSERT INTO NOTIFICATION (user_id, notification_type, message)
                   VALUES (%s, %s, %s)""",
                (driver_id, f"APPLICATION_{new_status}", message),
            )
            log_audit(cur, actor_user_id=sponsor_user_id, sponsor_id=my_sponsor_id,
                      driver_id=driver_id, success=True, entity_id=application_id,
                      details=f"Application {new_status.lower()}: {reason}")
        db.commit()
    except Exception:
        db.rollback()
        raise

    return jsonify({"application_id": application_id, "status": new_status})
