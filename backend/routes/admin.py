"""Admin endpoints: /api/admin/...   Every route here uses @require_role("admin").

    GET  /api/admin/users        every account with its role
    POST /api/admin/sponsors     create a sponsor company (Add sponsor on admin/sponsors.html)
"""
from decimal import Decimal, InvalidOperation

from flask import Blueprint, g, jsonify, request

from accounts import EMAIL_RE
from audit import log_audit
from auth import require_role
from db import query, transaction

bp = Blueprint("admin", __name__, url_prefix="/api/admin")


@bp.get("/users")
@require_role("admin")
def users():
    """Read endpoint for frontend/admin/users.html (page not converted yet). Never select password_hash."""
    rows = query(
        """SELECT u.user_id, u.username, u.first_name, u.last_name, u.email, u.account_status, u.created_at,
                  CASE WHEN a.admin_id IS NOT NULL THEN 'admin'
                       WHEN su.sponsor_user_id IS NOT NULL THEN 'sponsor'
                       WHEN d.driver_id IS NOT NULL THEN 'driver' END AS role
             FROM USER_ACCOUNT u
             LEFT JOIN ADMIN a ON a.admin_id = u.user_id
             LEFT JOIN SPONSOR_USER su ON su.sponsor_user_id = u.user_id
             LEFT JOIN DRIVER d ON d.driver_id = u.user_id
            ORDER BY u.user_id""")
    return jsonify(users=rows)


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
