"""DEV ONLY. /api/bootstrap dumps every table so pages that aren't converted yet can show real data.
Returns 404 when APP_ENV=production. Delete this file once every page uses its own endpoint."""
import os

from flask import Blueprint, abort, jsonify

from db import get_db_connection

bp = Blueprint("dev", __name__, url_prefix="/api")

TABLES = ["USER_ACCOUNT", "ADMIN", "SPONSOR_ORGANIZATION", "SPONSOR_USER", "DRIVER", "DRIVER_APPLICATION",
          "POINT_TRANSACTION", "RECURRING_POINT_SCHEDULE", "PRODUCT", "CATALOG_ITEM", "SHOPPING_CART",
          "CART_ITEM", "CUSTOMER_ORDER", "ORDER_ITEM", "NOTIFICATION", "ALERT_PREFERENCE", "AUDIT_EVENT",
          "ABOUT_RELEASE"]


@bp.get("/bootstrap")
def bootstrap():
    if os.getenv("APP_ENV", "development") == "production":
        abort(404)
    out = {}
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        for t in TABLES:
            if t == "USER_ACCOUNT":  # never send password hashes
                cur.execute("SELECT user_id, username, first_name, last_name, email, phone, account_status, "
                            "created_at FROM USER_ACCOUNT")
            else:
                cur.execute(f"SELECT * FROM {t}")
            out[t.lower()] = {"cols": list(cur.column_names), "rows": [list(r) for r in cur.fetchall()]}
    finally:
        cur.close()
        conn.close()
    return jsonify(out)
