"""Admin endpoints: /api/admin/...   Every route here uses @require_role("admin")."""
from flask import Blueprint, jsonify

from auth import require_role
from db import query

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
