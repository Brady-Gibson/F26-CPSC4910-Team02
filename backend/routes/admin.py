"""Admin endpoints: /api/admin/...   Every route here uses @require_role("admin").

    GET  /api/admin/users                        every account with its role, plus sponsor companies for forms
    POST /api/admin/users                        create a driver, sponsor user, or admin account
    POST /api/admin/users/<id>/status            lock, unlock, deactivate, or reactivate an account
    POST /api/admin/users/<id>/reset-password    set a new password (also unlocks a locked account)
    POST /api/admin/sponsors                     create a sponsor company (Add sponsor on admin/sponsors.html)
"""
from decimal import Decimal, InvalidOperation

from flask import Blueprint, g, jsonify, request
from werkzeug.security import generate_password_hash

from accounts import EMAIL_RE, ROLES, AccountError, check_password, create_user
from audit import log_audit, notify
from auth import PASSWORD_RESET, REACTIVATED, UNLOCKED, require_role
from db import query, transaction

bp = Blueprint("admin", __name__, url_prefix="/api/admin")


@bp.get("/users")
@require_role("admin")
def users():
    """Read endpoint for frontend/admin/users.html (and the View as dialog). Never select password_hash."""
    rows = query(
        """SELECT u.user_id, u.username, u.first_name, u.last_name, u.email, u.phone, u.account_status, u.created_at,
                  CASE WHEN a.admin_id IS NOT NULL THEN 'admin'
                       WHEN su.sponsor_user_id IS NOT NULL THEN 'sponsor'
                       WHEN d.driver_id IS NOT NULL THEN 'driver' END AS role,
                  COALESCE(su.sponsor_id, d.sponsor_id) AS sponsor_id, s.sponsor_name
             FROM USER_ACCOUNT u
             LEFT JOIN ADMIN a ON a.admin_id = u.user_id
             LEFT JOIN SPONSOR_USER su ON su.sponsor_user_id = u.user_id
             LEFT JOIN DRIVER d ON d.driver_id = u.user_id
             LEFT JOIN SPONSOR_ORGANIZATION s ON s.sponsor_id = COALESCE(su.sponsor_id, d.sponsor_id)
            ORDER BY u.user_id""")
    sponsors = query("SELECT sponsor_id, sponsor_name, status FROM SPONSOR_ORGANIZATION ORDER BY sponsor_name")
    return jsonify(users=rows, sponsors=sponsors)


@bp.post("/users")
@require_role("admin")
def create_account():
    """Create a driver, sponsor user, or admin. Drivers given a sponsor start ACTIVE with that sponsor."""
    data = request.get_json(silent=True) or {}
    role = str(data.get("role") or "").strip().lower()
    if role not in ROLES:
        return jsonify(error="Pick a role: driver, sponsor user, or admin."), 400
    sponsor_id = None
    if role != "admin" and data.get("sponsor_id") not in (None, ""):
        try:
            sponsor_id = int(data["sponsor_id"])
        except (TypeError, ValueError):
            return jsonify(error="Pick a sponsor company."), 400
    try:
        with transaction() as cur:
            user_id = create_user(cur, role, username=data.get("username"), password=str(data.get("password") or ""),
                                  first_name=data.get("first_name"), last_name=data.get("last_name"),
                                  email=data.get("email"), phone=data.get("phone"), sponsor_id=sponsor_id,
                                  job_title=data.get("job_title") if role == "sponsor" else None,
                                  created_by=g.user["user_id"])
    except AccountError as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True, user_id=user_id), 201


def _target(cur, user_id):
    cur.execute("SELECT user_id, username, account_status FROM USER_ACCOUNT WHERE user_id = %s FOR UPDATE", (user_id,))
    return cur.fetchone()


# (current status, new status) -> audit details. UNLOCKED and REACTIVATED also restart the failed-login count.
STATUS_CHANGES = {
    ("ACTIVE", "LOCKED"): "Locked by admin",
    ("ACTIVE", "INACTIVE"): "Deactivated by admin",
    ("LOCKED", "INACTIVE"): "Deactivated by admin",
    ("LOCKED", "ACTIVE"): UNLOCKED,
    ("INACTIVE", "ACTIVE"): REACTIVATED,
}


@bp.post("/users/<int:user_id>/status")
@require_role("admin")
def set_status(user_id):
    """Body: {"status": "ACTIVE" | "LOCKED" | "INACTIVE"}. Takes effect on the user's next request."""
    status = str((request.get_json(silent=True) or {}).get("status") or "").strip().upper()
    if status not in ("ACTIVE", "LOCKED", "INACTIVE"):
        return jsonify(error="Status must be ACTIVE, LOCKED, or INACTIVE."), 400
    if user_id == g.user["user_id"]:
        return jsonify(error="You can't change the status of your own account."), 400
    with transaction() as cur:
        u = _target(cur, user_id)
        if u is None:
            return jsonify(error="User not found."), 404
        details = STATUS_CHANGES.get((u["account_status"], status))
        if details is None:
            return jsonify(error=f"That account is already {u['account_status'].lower()}."), 400
        cur.execute("UPDATE USER_ACCOUNT SET account_status = %s WHERE user_id = %s",
                    (status, user_id))
        log_audit(cur, "ACCOUNT", True, actor_user_id=g.user["user_id"], subject_username=u["username"],
                  entity_type="USER_ACCOUNT", entity_id=user_id, details=details)
    return jsonify(ok=True, account_status=status)


@bp.post("/users/<int:user_id>/reset-password")
@require_role("admin")
def reset_password(user_id):
    """Body: {"password": "..."}. The admin passes the new password to the user. A LOCKED account is unlocked;
    an INACTIVE one stays inactive."""
    password = str((request.get_json(silent=True) or {}).get("password") or "")
    try:
        check_password(password)
    except AccountError as e:
        return jsonify(error=str(e)), 400
    with transaction() as cur:
        u = _target(cur, user_id)
        if u is None:
            return jsonify(error="User not found."), 404
        status = "ACTIVE" if u["account_status"] == "LOCKED" else u["account_status"]
        cur.execute("UPDATE USER_ACCOUNT SET password_hash = %s, account_status = %s "
                    "WHERE user_id = %s", (generate_password_hash(password), status, user_id))
        log_audit(cur, "ACCOUNT", True, actor_user_id=g.user["user_id"], subject_username=u["username"],
                  entity_type="USER_ACCOUNT", entity_id=user_id, details=PASSWORD_RESET)
        notify(cur, user_id, "ACCOUNT", "An admin reset your password.")
    return jsonify(ok=True, account_status=status)


@bp.post("/sponsors")
@require_role("admin")
def create_sponsor():
    """Create a sponsor company. Its sponsor users are added separately."""
    data = request.get_json(silent=True) or {}
    name = str(data.get("sponsor_name") or "").strip()
    email = str(data.get("contact_email") or "").strip().lower()
    phone = str(data.get("phone") or "").strip()

    if not name:
        return jsonify(error="Sponsor name is required."), 400
    if len(name) > 100:
        return jsonify(error="Sponsor name must be 100 characters or fewer."), 400
    if email and (len(email) > 100 or not EMAIL_RE.match(email)):
        return jsonify(error="Enter a valid contact email."), 400
    if len(phone) > 20:
        return jsonify(error="Phone must be 20 characters or fewer."), 400
    try:
        rate = Decimal(str(data.get("point_dollar_rate") or "0.01").strip())
    except InvalidOperation:
        return jsonify(error="Point value must be a dollar amount, like 0.01."), 400
    # The column is DECIMAL(10,2), so anything finer than a cent would be silently rounded.
    if not rate.is_finite() or not Decimal("0.01") <= rate <= Decimal("1000") or rate != rate.quantize(Decimal("0.01")):
        return jsonify(error="Point value must be between $0.01 and $1,000.00, in whole cents."), 400

    with transaction() as cur:
        cur.execute("SELECT 1 FROM SPONSOR_ORGANIZATION WHERE LOWER(sponsor_name) = LOWER(%s) LIMIT 1", (name,))
        if cur.fetchone():
            return jsonify(error="A sponsor with that name already exists."), 400
        cur.execute(
            """INSERT INTO SPONSOR_ORGANIZATION (sponsor_name, status, point_dollar_rate, contact_email, phone)
               VALUES (%s, 'ACTIVE', %s, %s, %s)""",
            (name, rate, email or None, phone or None))
        sponsor_id = cur.lastrowid
        log_audit(cur, "ACCOUNT", True, actor_user_id=g.user["user_id"], sponsor_id=sponsor_id,
                  subject_username=name[:100], entity_type="SPONSOR_ORGANIZATION", entity_id=sponsor_id,
                  details=f"Created sponsor {name} (1 point = ${rate})")

    return jsonify(ok=True, sponsor_id=sponsor_id), 201
