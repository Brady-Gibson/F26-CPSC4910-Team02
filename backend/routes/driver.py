"""Driver endpoints: /api/driver/...   Every route here uses @require_role("driver").

Dashboard
    GET  /api/driver/dashboard       feeds frontend/driver/dashboard.html

Driver Sponsor Application (Sprint 3)
    GET  /api/driver/sponsors        sponsors this driver can apply to
    GET  /api/driver/applications    this driver's applications: status, dates, rejection reason
    POST /api/driver/applications    apply to a sponsor

Stories covered here: Sponsor Incentive Program, Driver Application Status, Rejection Reason
Statement, Required Information, One Sponsor, Recorded Application. The two alert stories
(Application Alert / Application Rejection Alert) happen when the sponsor decides, in routes/sponsor.py.
"""
from flask import Blueprint, g, jsonify, request

from audit import log_audit
from auth import require_role
from db import query, transaction

bp = Blueprint("driver", __name__, url_prefix="/api/driver")


@bp.get("/dashboard")
@require_role("driver")
def dashboard():
    """Example read endpoint. Feeds frontend/driver/dashboard.html."""
    uid = g.user["user_id"]
    driver = query(
        """SELECT d.driver_id, u.first_name, u.last_name, d.current_points, d.participation_status,
                  d.sponsor_id, s.sponsor_name, s.point_dollar_rate
             FROM DRIVER d
             JOIN USER_ACCOUNT u ON u.user_id = d.driver_id
             LEFT JOIN SPONSOR_ORGANIZATION s ON s.sponsor_id = d.sponsor_id
            WHERE d.driver_id = %s""", (uid,), one=True)
    transactions = query(
        """SELECT pt.point_transaction_id, pt.points_delta, pt.balance_after, pt.reason, pt.created_at,
                  p.first_name AS by_first_name, p.last_name AS by_last_name
             FROM POINT_TRANSACTION pt
             LEFT JOIN USER_ACCOUNT p ON p.user_id = pt.performed_by_user_id
            WHERE pt.driver_id = %s
            ORDER BY pt.created_at DESC, pt.point_transaction_id DESC
            LIMIT 5""", (uid,))
    open_orders = query(
        """SELECT order_id, status, total_points, placed_at FROM CUSTOMER_ORDER
            WHERE driver_id = %s AND status IN ('PLACED', 'SHIPPED')
            ORDER BY placed_at DESC""", (uid,))
    next_award = query(
        """SELECT points_amount, next_run_at FROM RECURRING_POINT_SCHEDULE
            WHERE driver_id = %s AND is_active = TRUE AND next_run_at IS NOT NULL
            ORDER BY next_run_at LIMIT 1""", (uid,), one=True)
    return jsonify(driver=driver, transactions=transactions, open_orders=open_orders, next_award=next_award)


# ---------------------------------------------------------------- Driver Sponsor Application

US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN",
    "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH",
    "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT",
    "VT", "VA", "WA", "WV", "WI", "WY",
}


def _clean_application(data):
    """Check the application form. Returns (values, None) or (None, error message)."""
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

    return {"sponsor_id": sponsor_id, "cdl_number": cdl_number, "cdl_state": cdl_state,
            "years_experience": years, "notes": notes or None}, None


@bp.get("/sponsors")
@require_role("driver")
def sponsors():
    """Active sponsor organizations, minus the one the driver is already with."""
    rows = query(
        """SELECT sponsor_id, sponsor_name FROM SPONSOR_ORGANIZATION
            WHERE status = 'ACTIVE' AND sponsor_id <> COALESCE(%s, 0)
            ORDER BY sponsor_name""",
        (g.user["sponsor_id"],))
    return jsonify(sponsors=rows)


@bp.get("/applications")
@require_role("driver")
def applications():
    """Driver Application Status + Rejection Reason Statement."""
    rows = query(
        """SELECT a.application_id, a.sponsor_id, s.sponsor_name, a.status,
                  a.submitted_at, a.decision_at,
                  CASE WHEN a.status = 'REJECTED' THEN a.reason END AS rejection_reason,
                  a.cdl_number, a.cdl_state, a.years_experience, a.applicant_notes
             FROM DRIVER_APPLICATION a
             JOIN SPONSOR_ORGANIZATION s ON s.sponsor_id = a.sponsor_id
            WHERE a.driver_id = %s
            ORDER BY a.submitted_at DESC, a.application_id DESC""",
        (g.user["user_id"],))
    return jsonify(applications=rows)


@bp.post("/applications")
@require_role("driver")
def apply():
    """Sponsor Incentive Program + Required Information + One Sponsor + Recorded Application."""
    values, problem = _clean_application(request.get_json(silent=True) or {})
    if problem:
        return jsonify(error=problem), 400

    driver_id, username = g.user["user_id"], g.user["username"]
    with transaction() as cur:
        # Lock the driver row so a double-click can't create two applications.
        cur.execute("SELECT sponsor_id, participation_status FROM DRIVER WHERE driver_id = %s FOR UPDATE",
                    (driver_id,))
        driver = cur.fetchone()

        cur.execute("SELECT sponsor_name FROM SPONSOR_ORGANIZATION WHERE sponsor_id = %s AND status = 'ACTIVE'",
                    (values["sponsor_id"],))
        sponsor = cur.fetchone()
        if sponsor is None:
            return jsonify(error="That sponsor isn't accepting applications."), 404

        # One Sponsor rule
        blocked = None
        if driver["sponsor_id"] is not None and driver["participation_status"] == "ACTIVE":
            blocked = "You already have a sponsor. Drivers can only be with one sponsor at a time."
        else:
            cur.execute("SELECT 1 FROM DRIVER_APPLICATION WHERE driver_id = %s AND status = 'PENDING' LIMIT 1",
                        (driver_id,))
            if cur.fetchone():
                blocked = "You already have an application waiting for review."
        if blocked:
            log_audit(cur, "APPLICATION", False, actor_user_id=driver_id, sponsor_id=values["sponsor_id"],
                      driver_id=driver_id, subject_username=username, entity_type="DRIVER_APPLICATION",
                      details=f"Application blocked: {blocked}")
            return jsonify(error=blocked), 409

        cur.execute(
            """INSERT INTO DRIVER_APPLICATION
                 (driver_id, sponsor_id, status, cdl_number, cdl_state, years_experience, applicant_notes)
               VALUES (%s, %s, 'PENDING', %s, %s, %s, %s)""",
            (driver_id, values["sponsor_id"], values["cdl_number"], values["cdl_state"],
             values["years_experience"], values["notes"]))
        application_id = cur.lastrowid
        log_audit(cur, "APPLICATION", True, actor_user_id=driver_id, sponsor_id=values["sponsor_id"],
                  driver_id=driver_id, subject_username=username, entity_type="DRIVER_APPLICATION",
                  entity_id=application_id, details=f"Applied to {sponsor['sponsor_name']}")

    return jsonify(ok=True, application_id=application_id, status="PENDING"), 201
