"""Admin endpoints: /api/admin/...   Every route here uses @require_role("admin").

    GET  /api/admin/users                        every account with its role, plus sponsor companies for forms
    POST /api/admin/users                        create a driver, sponsor user, or admin account
    POST /api/admin/users/<id>/status            lock, unlock, deactivate, or reactivate an account
    POST /api/admin/users/<id>/reset-password    set a new password (also unlocks a locked account)
    PATCH /api/admin/users/<id>                  edit name, email, phone (and job title for sponsor users)
    GET  /api/admin/sponsors                     every sponsor company with driver / user / points counts
    POST /api/admin/sponsors                     create a sponsor company (Add sponsor on admin/sponsors.html)
    PATCH /api/admin/sponsors/<id>               edit name, contact, point value, or status (ACTIVE / INACTIVE)
"""
from decimal import Decimal, InvalidOperation

from flask import Blueprint, g, jsonify, request
from werkzeug.security import generate_password_hash

import mysql.connector

from accounts import EMAIL_RE, ROLES, AccountError, check_password, clean_profile, create_user
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
                  su.sponsor_id AS sponsor_id, s.sponsor_name, su.job_title
             FROM USER_ACCOUNT u
             LEFT JOIN ADMIN a ON a.admin_id = u.user_id
             LEFT JOIN SPONSOR_USER su ON su.sponsor_user_id = u.user_id
             LEFT JOIN DRIVER d ON d.driver_id = u.user_id
             LEFT JOIN SPONSOR_ORGANIZATION s ON s.sponsor_id = su.sponsor_id
            ORDER BY u.user_id""")
    memberships = query("""SELECT m.*, s.sponsor_name FROM DRIVER_SPONSOR m
        JOIN SPONSOR_ORGANIZATION s USING (sponsor_id) ORDER BY m.sponsor_id""")
    for row in rows:
        if row["role"] == "driver":
            row["memberships"] = [m for m in memberships if m["driver_id"] == row["user_id"]]
            row["sponsor_name"] = ", ".join(m["sponsor_name"] for m in row["memberships"]
                                           if m["participation_status"] == "ACTIVE") or None
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
        notify(cur, user_id, "PASSWORD_RESET", "An admin reset your password. Sign in with the new password they gave you.")
    return jsonify(ok=True, account_status=status)


PROFILE_KEYS = ("first_name", "last_name", "email", "phone")


@bp.patch("/users/<int:user_id>")
@require_role("admin")
def edit_user(user_id):
    """Body: {"first_name", "last_name", "email", "phone", "job_title" (sponsor users only)}. Username can't change."""
    data = request.get_json(silent=True) or {}
    try:
        first_name, last_name, email, phone = clean_profile(*(data.get(k) for k in PROFILE_KEYS))
    except AccountError as e:
        return jsonify(error=str(e)), 400
    job_title = str(data.get("job_title") or "").strip()
    if len(job_title) > 100:
        return jsonify(error="Job title must be 100 characters or fewer."), 400
    with transaction() as cur:
        cur.execute("SELECT user_id, username, first_name, last_name, email, phone FROM USER_ACCOUNT "
                    "WHERE user_id = %s FOR UPDATE", (user_id,))
        before = cur.fetchone()
        if before is None:
            return jsonify(error="User not found."), 404
        cur.execute("SELECT 1 FROM USER_ACCOUNT WHERE LOWER(email) = %s AND user_id <> %s LIMIT 1", (email, user_id))
        if cur.fetchone():
            return jsonify(error="An account with that email already exists."), 400
        after = dict(zip(PROFILE_KEYS, (first_name, last_name, email, phone)))
        changed = [k for k in PROFILE_KEYS if before[k] != after[k]]
        try:
            cur.execute("UPDATE USER_ACCOUNT SET first_name = %s, last_name = %s, email = %s, phone = %s, "
                        "updated_at = CURRENT_TIMESTAMP WHERE user_id = %s",
                        (first_name, last_name, email, phone, user_id))
        except mysql.connector.IntegrityError:
            return jsonify(error="An account with that email already exists."), 400
        cur.execute("SELECT job_title, sponsor_id FROM SPONSOR_USER WHERE sponsor_user_id = %s", (user_id,))
        su = cur.fetchone()
        if su and (su["job_title"] or "") != job_title:
            cur.execute("UPDATE SPONSOR_USER SET job_title = %s WHERE sponsor_user_id = %s", (job_title or None, user_id))
            changed.append("job_title")
        if changed:
            log_audit(cur, "ACCOUNT", True, actor_user_id=g.user["user_id"], subject_username=before["username"],
                      sponsor_id=su["sponsor_id"] if su else None, entity_type="USER_ACCOUNT", entity_id=user_id,
                      details="Edited by admin: " + ", ".join(k.replace("_", " ") for k in changed))
    return jsonify(ok=True, changed=changed)


def _sponsor_fields(data, partial=False):
    """Validate sponsor company fields. Returns a dict of the fields present (all of them unless partial)."""
    out = {}
    if not partial or "sponsor_name" in data:
        name = str(data.get("sponsor_name") or "").strip()
        if not name:
            raise AccountError("Sponsor name is required.")
        if len(name) > 100:
            raise AccountError("Sponsor name must be 100 characters or fewer.")
        out["sponsor_name"] = name
    if not partial or "contact_email" in data:
        email = str(data.get("contact_email") or "").strip().lower()
        if email and (len(email) > 100 or not EMAIL_RE.match(email)):
            raise AccountError("Enter a valid contact email.")
        out["contact_email"] = email or None
    if not partial or "phone" in data:
        phone = str(data.get("phone") or "").strip()
        if len(phone) > 20:
            raise AccountError("Phone must be 20 characters or fewer.")
        out["phone"] = phone or None
    if not partial or "point_dollar_rate" in data:
        try:
            rate = Decimal(str(data.get("point_dollar_rate") or "0.01").strip())
        except InvalidOperation:
            raise AccountError("Point value must be a dollar amount, like 0.01.") from None
        # The column is DECIMAL(10,2), so anything finer than a cent would be silently rounded.
        if not rate.is_finite() or not Decimal("0.01") <= rate <= Decimal("1000") or rate != rate.quantize(Decimal("0.01")):
            raise AccountError("Point value must be between $0.01 and $1,000.00, in whole cents.")
        out["point_dollar_rate"] = rate
    if partial and "status" in data:
        status = str(data.get("status") or "").strip().upper()
        if status not in ("ACTIVE", "INACTIVE"):
            raise AccountError("Status must be ACTIVE or INACTIVE.")
        out["status"] = status
    return out


@bp.get("/sponsors")
@require_role("admin")
def sponsors():
    """Read endpoint for admin/sponsors.html."""
    rows = query("""SELECT s.sponsor_id, s.sponsor_name, s.status, s.point_dollar_rate, s.contact_email, s.phone,
                           s.created_at,
                           (SELECT COUNT(*) FROM DRIVER_SPONSOR m WHERE m.sponsor_id = s.sponsor_id
                               AND m.participation_status = 'ACTIVE') AS drivers,
                           (SELECT COUNT(*) FROM SPONSOR_USER su WHERE su.sponsor_id = s.sponsor_id) AS sponsor_users,
                           (SELECT COALESCE(SUM(m.current_points), 0) FROM DRIVER_SPONSOR m
                             WHERE m.sponsor_id = s.sponsor_id AND m.participation_status = 'ACTIVE') AS points_outstanding,
                           (SELECT COUNT(*) FROM DRIVER_APPLICATION a WHERE a.sponsor_id = s.sponsor_id
                               AND a.status = 'PENDING') AS pending_applications
                      FROM SPONSOR_ORGANIZATION s ORDER BY s.sponsor_name""")
    return jsonify(sponsors=rows)


@bp.patch("/sponsors/<int:sponsor_id>")
@require_role("admin")
def edit_sponsor(sponsor_id):
    """Body: any of sponsor_name, contact_email, phone, point_dollar_rate, status. Deactivating a sponsor hides it
    from drivers (catalog, applications, sponsor switcher) without deleting any history."""
    data = request.get_json(silent=True) or {}
    try:
        fields = _sponsor_fields(data, partial=True)
    except AccountError as e:
        return jsonify(error=str(e)), 400
    if not fields:
        return jsonify(error="Nothing to change."), 400
    with transaction() as cur:
        cur.execute("SELECT * FROM SPONSOR_ORGANIZATION WHERE sponsor_id = %s FOR UPDATE", (sponsor_id,))
        before = cur.fetchone()
        if before is None:
            return jsonify(error="Sponsor not found."), 404
        if "sponsor_name" in fields:
            cur.execute("SELECT 1 FROM SPONSOR_ORGANIZATION WHERE LOWER(sponsor_name) = LOWER(%s) AND sponsor_id <> %s "
                        "LIMIT 1", (fields["sponsor_name"], sponsor_id))
            if cur.fetchone():
                return jsonify(error="A sponsor with that name already exists."), 400
        changed = {k: v for k, v in fields.items() if before[k] != v}
        if changed:
            # Column names come from _sponsor_fields (fixed strings), never from the request.
            cur.execute("UPDATE SPONSOR_ORGANIZATION SET " + ", ".join(f"{k} = %s" for k in changed) +
                        " WHERE sponsor_id = %s", (*changed.values(), sponsor_id))
            log_audit(cur, "ORGANIZATION", True, actor_user_id=g.user["user_id"], sponsor_id=sponsor_id,
                      subject_username=before["sponsor_name"][:100], entity_type="SPONSOR_ORGANIZATION",
                      entity_id=sponsor_id,
                      details="Edited by admin: " + ", ".join(f"{k.replace('_', ' ')} = {v}" for k, v in changed.items()))
    return jsonify(ok=True, changed=list(changed))


@bp.post("/sponsors")
@require_role("admin")
def create_sponsor():
    """Create a sponsor company. Its sponsor users are added separately."""
    try:
        f = _sponsor_fields(request.get_json(silent=True) or {})
    except AccountError as e:
        return jsonify(error=str(e)), 400
    name, rate, email, phone = f["sponsor_name"], f["point_dollar_rate"], f["contact_email"], f["phone"]

    with transaction() as cur:
        cur.execute("SELECT 1 FROM SPONSOR_ORGANIZATION WHERE LOWER(sponsor_name) = LOWER(%s) LIMIT 1", (name,))
        if cur.fetchone():
            return jsonify(error="A sponsor with that name already exists."), 400
        cur.execute(
            """INSERT INTO SPONSOR_ORGANIZATION (sponsor_name, status, point_dollar_rate, contact_email, phone)
               VALUES (%s, 'ACTIVE', %s, %s, %s)""",
            (name, rate, email, phone))
        sponsor_id = cur.lastrowid
        log_audit(cur, "ACCOUNT", True, actor_user_id=g.user["user_id"], sponsor_id=sponsor_id,
                  subject_username=name[:100], entity_type="SPONSOR_ORGANIZATION", entity_id=sponsor_id,
                  details=f"Created sponsor {name} (1 point = ${rate})")

    return jsonify(ok=True, sponsor_id=sponsor_id), 201


@bp.get('/drivers/<int:driver_id>/sponsors')
@require_role('admin')
def driver_sponsors(driver_id):
    rows = query('''SELECT m.*, s.sponsor_name FROM DRIVER_SPONSOR m
        JOIN SPONSOR_ORGANIZATION s USING (sponsor_id) WHERE m.driver_id = %s
        ORDER BY m.sponsor_id''', (driver_id,))
    return jsonify(memberships=rows)


@bp.post('/drivers/<int:driver_id>/sponsors')
@require_role('admin')
def assign_sponsors(driver_id):
    """Add memberships without replacing any existing sponsor or its balance."""
    data = request.get_json(silent=True) or {}
    ids = data.get('sponsor_ids', [data.get('sponsor_id')])
    if not isinstance(ids, list) or not ids or any(type(s) is not int or s <= 0 for s in ids):
        return jsonify(error='Provide a nonempty list of integer sponsor_ids.'), 400
    try:
        with transaction() as cur:
            cur.execute('SELECT driver_id FROM DRIVER WHERE driver_id = %s FOR UPDATE', (driver_id,))
            if cur.fetchone() is None:
                return jsonify(error='Driver not found.'), 404
            for sid in sorted(set(ids)):
                cur.execute("SELECT sponsor_name FROM SPONSOR_ORGANIZATION WHERE sponsor_id = %s AND status = 'ACTIVE'", (sid,))
                org = cur.fetchone()
                if org is None:
                    raise AccountError('Every sponsor must exist and be active.')
                cur.execute('''INSERT INTO DRIVER_SPONSOR (driver_id, sponsor_id, participation_status)
                    VALUES (%s, %s, 'ACTIVE') ON DUPLICATE KEY UPDATE participation_status = 'ACTIVE' ''', (driver_id, sid))
                cur.execute('''UPDATE DRIVER_APPLICATION SET status = 'APPROVED', decision_at = CURRENT_TIMESTAMP,
                    decided_by_user_id = %s, reason = 'Assigned by admin'
                    WHERE driver_id = %s AND sponsor_id = %s AND status = 'PENDING' ''',
                    (g.user['user_id'], driver_id, sid))
                log_audit(cur, 'APPLICATION', True, actor_user_id=g.user['user_id'], driver_id=driver_id,
                          sponsor_id=sid, entity_type='DRIVER_SPONSOR', entity_id=driver_id,
                          details='Membership assigned by admin')
                notify(cur, driver_id, 'APPLICATION_APPROVED', f"An administrator assigned you to {org['sponsor_name']}.")
    except AccountError as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True)
