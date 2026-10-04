"""Login, logout, and role checks.

Protect any route with:

    @bp.get("/something")
    @require_role("sponsor")          # or "driver", "admin", or several: require_role("sponsor", "admin")
    def something():
        g.user["user_id"], g.user["role"], g.user["sponsor_id"]   # who is calling

View as: an admin can view the site as a driver or sponsor user (POST /api/view-as, /api/view-as/stop).
While viewing, g.user is that driver or sponsor, g.viewed_by is the real admin, and require_role
blocks anything but GET, so viewing is read-only.
"""
from functools import wraps

from flask import Blueprint, g, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from accounts import AccountError, create_user
from audit import log_audit
from db import query, transaction

bp = Blueprint("auth", __name__, url_prefix="/api")

MAX_FAILED_LOGINS = 5
VIEW_AS_ROLES = ("driver", "sponsor")
READ_ONLY_METHODS = ("GET", "HEAD", "OPTIONS")
# Compared against when the username doesn't exist, so a wrong username takes as long as a wrong password.
_DUMMY_HASH = generate_password_hash("not-a-real-password")


def load_user(user_id):
    """User plus role and organization. Role comes from which table the user_id appears in."""
    u = query(
        """SELECT u.user_id, u.username, u.first_name, u.last_name, u.email, u.account_status,
                  CASE WHEN a.admin_id IS NOT NULL THEN 'admin'
                       WHEN su.sponsor_user_id IS NOT NULL THEN 'sponsor'
                       WHEN d.driver_id IS NOT NULL THEN 'driver' END AS role,
                  COALESCE(su.sponsor_id, d.sponsor_id) AS sponsor_id,
                  s.sponsor_name
             FROM USER_ACCOUNT u
             LEFT JOIN ADMIN a ON a.admin_id = u.user_id
             LEFT JOIN SPONSOR_USER su ON su.sponsor_user_id = u.user_id
             LEFT JOIN DRIVER d ON d.driver_id = u.user_id
             LEFT JOIN SPONSOR_ORGANIZATION s ON s.sponsor_id = COALESCE(su.sponsor_id, d.sponsor_id)
            WHERE u.user_id = %s""",
        (user_id,), one=True)
    return u


def public_user(u, viewed_by=None):
    out = {k: u[k] for k in ("user_id", "username", "first_name", "last_name", "email",
                             "role", "sponsor_id", "sponsor_name")}
    if viewed_by:
        out["viewed_by"] = {k: viewed_by[k] for k in ("user_id", "first_name", "last_name")}
    return out


def current_user():
    """The signed-in user, re-checked against the DB so locked accounts lose access right away.
    While an admin is viewing as someone, this returns that someone and sets g.viewed_by to the admin."""
    if "user" in g:
        return g.user
    uid = session.get("user_id")
    if uid is None:
        return None
    u = load_user(uid)
    if u is None or u["account_status"] != "ACTIVE" or u["role"] is None:
        session.clear()
        return None
    g.viewed_by = None
    target_id = session.get("view_as")
    if target_id is not None:
        target = load_user(target_id) if u["role"] == "admin" else None
        if target is None or target["role"] not in VIEW_AS_ROLES:
            session.pop("view_as", None)
        else:
            g.viewed_by, u = u, target
    g.user = u
    return u


def require_role(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            u = current_user()
            if u is None:
                return jsonify(error="Please sign in."), 401
            if g.viewed_by and request.method not in READ_ONLY_METHODS:
                return jsonify(error=f"You're viewing as {u['first_name']} {u['last_name']}, "
                                     "so changes are turned off."), 403
            if roles and u["role"] not in roles:
                return jsonify(error="You don't have access to that."), 403
            return view(*args, **kwargs)
        return wrapped
    return decorator


def _failed_since_last_success(cur, username):
    cur.execute(
        """SELECT COALESCE(MAX(audit_event_id), 0) AS last_ok FROM AUDIT_EVENT
            WHERE category = 'LOGIN' AND success = TRUE AND subject_username = %s""", (username,))
    last_ok = cur.fetchone()["last_ok"]
    cur.execute(
        """SELECT COUNT(*) AS fails FROM AUDIT_EVENT
            WHERE category = 'LOGIN' AND success = FALSE AND subject_username = %s
              AND audit_event_id > %s""", (username, last_ok))
    return cur.fetchone()["fails"]

@bp.post("/register/driver")
def register_driver():
    data = request.get_json(silent=True) or {}

    password = str(data.get("password") or "")
    confirm_password = str(data.get("confirm_password") or "")

    if password != confirm_password:
        return jsonify(error="Passwords do not match."), 400

    try:
        with transaction() as cur:
            user_id = create_user(
                cur,
                "driver",
                username=data.get("username"),
                password=password,
                first_name=data.get("first_name"),
                last_name=data.get("last_name"),
                email=data.get("email"),
                phone=data.get("phone"),
                sponsor_id=None,
                created_by=None,
            )
    except AccountError as e:
        return jsonify(error=str(e)), 400

    return jsonify(
        ok=True,
        user_id=user_id,
        message="Driver account created. You can now sign in.",
    ), 201

@bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    identifier = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    if not identifier or not password:
        return jsonify(error="Enter your username and password."), 400

    with transaction() as cur:
        cur.execute(
            """SELECT user_id, username, password_hash, account_status FROM USER_ACCOUNT
                WHERE LOWER(username) = LOWER(%s) OR LOWER(email) = LOWER(%s)""",
            (identifier, identifier))
        row = cur.fetchone()

        if row is None:
            check_password_hash(_DUMMY_HASH, password)
            log_audit(cur, "LOGIN", False, subject_username=identifier[:100], details="Failed login: unknown user")
            return jsonify(error="Incorrect username or password."), 401

        if row["account_status"] == "LOCKED":
            log_audit(cur, "LOGIN", False, actor_user_id=row["user_id"], subject_username=row["username"],
                      details="Failed login: account locked")
            return jsonify(error="This account is locked. Contact your sponsor or an admin to unlock it."), 403
        if row["account_status"] != "ACTIVE":
            log_audit(cur, "LOGIN", False, actor_user_id=row["user_id"], subject_username=row["username"],
                      details="Failed login: account inactive")
            return jsonify(error="This account is inactive."), 403

        if not check_password_hash(row["password_hash"], password):
            log_audit(cur, "LOGIN", False, actor_user_id=row["user_id"], subject_username=row["username"],
                      details="Failed login: wrong password")
            if _failed_since_last_success(cur, row["username"]) >= MAX_FAILED_LOGINS:
                cur.execute("UPDATE USER_ACCOUNT SET account_status = 'LOCKED' WHERE user_id = %s", (row["user_id"],))
                log_audit(cur, "ACCOUNT", True, subject_username=row["username"], entity_type="USER_ACCOUNT",
                          entity_id=row["user_id"], details=f"Locked after {MAX_FAILED_LOGINS} failed logins")
                return jsonify(error="Too many failed attempts. This account is now locked."), 403
            return jsonify(error="Incorrect username or password."), 401

    u = load_user(row["user_id"])
    if u["role"] is None:
        return jsonify(error="This account has no role assigned yet."), 403

    with transaction() as cur:
        log_audit(cur, "LOGIN", True, actor_user_id=u["user_id"], subject_username=u["username"],
                  sponsor_id=u["sponsor_id"], driver_id=u["user_id"] if u["role"] == "driver" else None,
                  details="Successful login")

    session.clear()
    session["user_id"] = u["user_id"]
    session.permanent = True
    return jsonify(ok=True, user=public_user(u))


@bp.post("/logout")
def logout():
    u = current_user()
    if u:
        u = g.viewed_by or u  # signing out while viewing as someone signs out the admin
        with transaction() as cur:
            log_audit(cur, "LOGOUT", True, actor_user_id=u["user_id"], subject_username=u["username"],
                      details="Signed out")
    session.clear()
    return jsonify(ok=True)


@bp.get("/me")
def me():
    u = current_user()
    if u is None:
        return jsonify(error="Please sign in."), 401
    return jsonify(user=public_user(u, g.viewed_by))


@bp.post("/view-as")
def start_view_as():
    """Admin only: see the site as a driver or sponsor user. Body: {"user_id": ...}."""
    u = current_user()
    if u is None:
        return jsonify(error="Please sign in."), 401
    admin = g.viewed_by or u
    if admin["role"] != "admin":
        return jsonify(error="You don't have access to that."), 403
    try:
        target_id = int((request.get_json(silent=True) or {}).get("user_id"))
    except (TypeError, ValueError):
        return jsonify(error="Pick a user to view as."), 400
    target = load_user(target_id)
    if target is None:
        return jsonify(error="User not found."), 404
    if target["role"] not in VIEW_AS_ROLES:
        return jsonify(error="You can only view as a driver or sponsor user."), 400

    with transaction() as cur:
        log_audit(cur, "VIEW_AS", True, actor_user_id=admin["user_id"], sponsor_id=target["sponsor_id"],
                  driver_id=target["user_id"] if target["role"] == "driver" else None,
                  subject_username=target["username"], entity_type="USER_ACCOUNT", entity_id=target["user_id"],
                  details=f"Started viewing as {target['role']} {target['username']}")
    session["view_as"] = target["user_id"]
    return jsonify(ok=True, user=public_user(target, admin))


@bp.post("/view-as/stop")
def stop_view_as():
    u = current_user()
    if u is None:
        return jsonify(error="Please sign in."), 401
    admin = g.viewed_by
    if admin:
        with transaction() as cur:
            log_audit(cur, "VIEW_AS", True, actor_user_id=admin["user_id"], subject_username=u["username"],
                      entity_type="USER_ACCOUNT", entity_id=u["user_id"],
                      details=f"Stopped viewing as {u['role']} {u['username']}")
        session.pop("view_as", None)
    return jsonify(ok=True, user=public_user(admin or u))
