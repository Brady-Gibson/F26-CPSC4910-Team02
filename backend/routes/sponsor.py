"""Sponsor routes (/api/sponsor/...). Every route here is sponsor-only and scoped to g.user["sponsor_id"].

Driver Application Review (Sprint 4 feature, needed now so Sprint 3's alerts can happen)
    GET  /api/sponsor/applications                    applications sent to my organization
    POST /api/sponsor/applications/<id>/decision      {"decision": "APPROVE"|"REJECT", "reason": "..."}

The decision sends the driver a NOTIFICATION (Application Alert / Application Rejection Alert)
and writes AUDIT_EVENT.
"""
from flask import Blueprint, g, jsonify, request

from audit import log_audit, notify
from auth import require_role
from db import query, transaction

bp = Blueprint("sponsor", __name__, url_prefix="/api/sponsor")


@bp.get("/applications")
@require_role("sponsor")
def applications():
    rows = query(
        """SELECT a.application_id, a.driver_id, u.first_name, u.last_name, u.email,
                  a.status, a.submitted_at, a.decision_at, a.reason,
                  a.cdl_number, a.cdl_state, a.years_experience, a.applicant_notes,
                  CONCAT(du.first_name, ' ', du.last_name) AS decided_by
             FROM DRIVER_APPLICATION a
             JOIN USER_ACCOUNT u ON u.user_id = a.driver_id
             LEFT JOIN USER_ACCOUNT du ON du.user_id = a.decided_by_user_id
            WHERE a.sponsor_id = %s
            ORDER BY (a.status = 'PENDING') DESC, a.submitted_at DESC""",
        (g.user["sponsor_id"],))
    return jsonify(applications=rows)


@bp.post("/applications/<int:application_id>/decision")
@require_role("sponsor")
def decide(application_id):
    data = request.get_json(silent=True) or {}
    decision = str(data.get("decision") or "").upper()
    reason = str(data.get("reason") or "").strip()
    if decision not in ("APPROVE", "REJECT"):
        return jsonify(error="Decision must be APPROVE or REJECT."), 400
    if decision == "REJECT" and not reason:
        return jsonify(error="Give a reason when rejecting. The driver will see it."), 400
    if len(reason) > 500:
        return jsonify(error="Reason can be at most 500 characters."), 400

    my_sponsor_id, me = g.user["sponsor_id"], g.user["user_id"]
    with transaction() as cur:
        cur.execute(
            """SELECT a.driver_id, a.sponsor_id, a.status, s.sponsor_name, u.username
                 FROM DRIVER_APPLICATION a
                 JOIN SPONSOR_ORGANIZATION s ON s.sponsor_id = a.sponsor_id
                 JOIN USER_ACCOUNT u ON u.user_id = a.driver_id
                WHERE a.application_id = %s FOR UPDATE""",
            (application_id,))
        app = cur.fetchone()
        # Same answer for "doesn't exist" and "not yours" so sponsors can't probe other orgs.
        if app is None or app["sponsor_id"] != my_sponsor_id:
            return jsonify(error="Application not found."), 404
        if app["status"] != "PENDING":
            return jsonify(error=f"This application was already {app['status'].lower()}."), 409

        driver_id = app["driver_id"]
        if decision == "APPROVE":
            cur.execute("SELECT sponsor_id, participation_status FROM DRIVER WHERE driver_id = %s FOR UPDATE",
                        (driver_id,))
            d = cur.fetchone()
            if d["sponsor_id"] not in (None, my_sponsor_id) and d["participation_status"] == "ACTIVE":
                return jsonify(error="This driver already joined another sponsor."), 409
            cur.execute("""UPDATE DRIVER SET sponsor_id = %s, participation_status = 'ACTIVE',
                                  joined_at = CURRENT_TIMESTAMP WHERE driver_id = %s""",
                        (my_sponsor_id, driver_id))
            new_status = "APPROVED"
            message = f"Your application to {app['sponsor_name']} was approved. You can start earning points now."
        else:
            new_status = "REJECTED"
            message = f"Your application to {app['sponsor_name']} was not approved. Reason: {reason}"

        cur.execute(
            """UPDATE DRIVER_APPLICATION
                  SET status = %s, decided_by_user_id = %s, decision_at = CURRENT_TIMESTAMP, reason = %s
                WHERE application_id = %s""",
            (new_status, me, reason or "Application approved", application_id))
        notify(cur, driver_id, f"APPLICATION_{new_status}", message)
        log_audit(cur, "APPLICATION", True, actor_user_id=me, sponsor_id=my_sponsor_id, driver_id=driver_id,
                  subject_username=app["username"], entity_type="DRIVER_APPLICATION",
                  entity_id=application_id,
                  details=f"Application {new_status.lower()}" + (f": {reason}" if reason else ""))

    return jsonify(ok=True, application_id=application_id, status=new_status)
