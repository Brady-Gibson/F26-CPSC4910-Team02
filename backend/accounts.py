"""Creating accounts. Every sign-up / create-user endpoint calls create_user(), so the rules live in one place.

    from accounts import AccountError, create_user

    try:
        with transaction() as cur:
            user_id = create_user(cur, "driver", username=..., password=..., first_name=..., last_name=...,
                                  email=..., created_by=None)
    except AccountError as e:
        return jsonify(error=str(e)), 400

Roles:
  "admin"   -> USER_ACCOUNT + ADMIN
  "sponsor" -> USER_ACCOUNT + SPONSOR_USER   (sponsor_id required)
  "driver"  -> USER_ACCOUNT + DRIVER         (no sponsor_id = APPLICANT until a sponsor approves them)
Every account also gets default ALERT_PREFERENCE settings and an ACCOUNT audit event.
"""
import re

import mysql.connector
from werkzeug.security import generate_password_hash

from audit import log_audit

ROLES = ("admin", "sponsor", "driver")

# Password rules. Change these to match the requirements doc; everything else picks them up.
PASSWORD_MIN_LENGTH = 8
PASSWORD_RULES = [
    (r"[A-Z]", "an uppercase letter"),
    (r"[a-z]", "a lowercase letter"),
    (r"[0-9]", "a number"),
    (r"[^A-Za-z0-9]", "a symbol"),
]

USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,50}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AccountError(ValueError):
    pass


def check_password(password):
    """Raise AccountError describing what's missing. Also use this for change-password."""
    missing = [label for pattern, label in PASSWORD_RULES if not re.search(pattern, password or "")]
    if len(password or "") < PASSWORD_MIN_LENGTH or missing:
        need = ([f"at least {PASSWORD_MIN_LENGTH} characters"] if len(password or "") < PASSWORD_MIN_LENGTH else []) + missing
        text = need[0] if len(need) == 1 else ", ".join(need[:-1]) + (", and " if len(need) > 2 else " and ") + need[-1]
        raise AccountError(f"Password needs {text}.")


def _clean(value, field, max_len, required=True):
    value = (value or "").strip()
    if required and not value:
        raise AccountError(f"{field} is required.")
    if len(value) > max_len:
        raise AccountError(f"{field} must be {max_len} characters or fewer.")
    return value or None


def clean_profile(first_name, last_name, email, phone):
    """Validate the editable profile fields. Returns (first_name, last_name, email, phone); raises AccountError."""
    email = _clean(email, "Email", 100).lower()
    if not EMAIL_RE.match(email):
        raise AccountError("Enter a valid email address.")
    return (_clean(first_name, "First name", 50), _clean(last_name, "Last name", 50), email,
            _clean(phone, "Phone", 20, required=False))


def create_user(cur, role, *, username, password, first_name, last_name, email,
                phone=None, sponsor_id=None, job_title=None, created_by=None):
    """Create a user and their role row inside the caller's transaction. Returns the new user_id."""
    if role not in ROLES:
        raise AccountError(f"Unknown role: {role}")

    username = _clean(username, "Username", 50)
    if not USERNAME_RE.match(username):
        raise AccountError("Username must be 3-50 characters: letters, numbers, dots, dashes, or underscores.")
    first_name, last_name, email, phone = clean_profile(first_name, last_name, email, phone)
    job_title = _clean(job_title, "Job title", 100, required=False)
    check_password(password)

    cur.execute(
        """SELECT LOWER(username) = LOWER(%s) AS same_username, LOWER(email) = LOWER(%s) AS same_email
             FROM USER_ACCOUNT WHERE LOWER(username) = LOWER(%s) OR LOWER(email) = LOWER(%s) LIMIT 1""",
        (username, email, username, email))
    clash = cur.fetchone()
    if clash:
        raise AccountError("That username is taken." if clash["same_username"] else "An account with that email already exists.")

    if role == "sponsor" and sponsor_id is None:
        raise AccountError("Sponsor users must belong to a sponsor company.")
    if sponsor_id is not None:
        cur.execute("SELECT status FROM SPONSOR_ORGANIZATION WHERE sponsor_id = %s", (sponsor_id,))
        org = cur.fetchone()
        if org is None:
            raise AccountError("That sponsor company doesn't exist.")
        if role == "driver" and org["status"] != "ACTIVE":
            raise AccountError("That sponsor isn't accepting drivers right now.")

    try:
        cur.execute(
            """INSERT INTO USER_ACCOUNT
                 (username, password_hash, first_name, last_name, email, phone, account_status)
               VALUES (%s, %s, %s, %s, %s, %s, 'ACTIVE')""",
            (username, generate_password_hash(password), first_name, last_name, email, phone))
    except mysql.connector.IntegrityError:  # someone grabbed the name a moment ago
        raise AccountError("That username or email is already in use.")
    user_id = cur.lastrowid

    if role == "admin":
        cur.execute("INSERT INTO ADMIN (admin_id) VALUES (%s)", (user_id,))
    elif role == "sponsor":
        cur.execute("INSERT INTO SPONSOR_USER (sponsor_user_id, sponsor_id, job_title) VALUES (%s, %s, %s)",
                    (user_id, sponsor_id, job_title))
    else:
        cur.execute("INSERT INTO DRIVER (driver_id, sponsor_id, current_points, participation_status) "
                    "VALUES (%s, %s, 0, %s)", (user_id, sponsor_id, "ACTIVE" if sponsor_id else "APPLICANT"))

    cur.execute("INSERT INTO ALERT_PREFERENCE (user_id) VALUES (%s)", (user_id,))

    log_audit(cur, "ACCOUNT", True, actor_user_id=created_by, sponsor_id=sponsor_id,
              driver_id=user_id if role == "driver" else None, subject_username=username,
              entity_type="USER_ACCOUNT", entity_id=user_id, details=f"Created {role} account")
    return user_id
