"""Self-service password recovery using AWS SES. No schema migration required."""
import os
import hmac
import hashlib
from urllib.parse import quote
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from flask import Blueprint, jsonify, request, current_app
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from werkzeug.security import generate_password_hash
from accounts import AccountError, check_password
from audit import log_audit
from db import query, transaction

bp = Blueprint("password_recovery", __name__, url_prefix="/api/password-reset")
GENERIC = "If an active account uses that email, a reset link will be sent."
EXPIRY_SECONDS = 1800

def fingerprint(password_hash):
    return hmac.new(current_app.config['SECRET_KEY'].encode(), password_hash.encode(), hashlib.sha256).hexdigest()

def serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="tigertruck-password-reset-v1")

@bp.post("/request")
def request_reset():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email") or "").strip().lower()
    if not email or len(email) > 100 or "@" not in email:
        return jsonify(error="Enter a valid email address."), 400
    # Database-backed throttling works across Beanstalk instances without extra services.
    # Hash the email and remote address so raw recovery identifiers are not logged.
    ip = request.remote_addr or "unknown"
    key = hmac.new(current_app.config["SECRET_KEY"].encode(), email.encode(), hashlib.sha256).hexdigest()
    ip_key = hmac.new(current_app.config["SECRET_KEY"].encode(), ip.encode(), hashlib.sha256).hexdigest()
    with transaction() as cur:
        cur.execute("""SELECT COUNT(*) AS n FROM AUDIT_EVENT
            WHERE category = 'PASSWORD_RECOVERY' AND subject_username = %s
              AND created_at > UTC_TIMESTAMP() - INTERVAL 1 HOUR""", (key,))
        email_count = cur.fetchone()["n"]
        cur.execute("""SELECT COUNT(*) AS n FROM AUDIT_EVENT
            WHERE category = 'PASSWORD_RECOVERY' AND reason_or_details = %s
              AND created_at > UTC_TIMESTAMP() - INTERVAL 1 HOUR""", (ip_key,))
        ip_count = cur.fetchone()["n"]
        if email_count >= 3 or ip_count >= 10:
            return jsonify(ok=True, message=GENERIC)
        cur.execute("""INSERT INTO AUDIT_EVENT (category, subject_username, success, reason_or_details)
            VALUES ('PASSWORD_RECOVERY', %s, TRUE, %s)""", (key, ip_key))
    row = query("SELECT user_id, email, password_hash FROM USER_ACCOUNT WHERE LOWER(email) = %s AND account_status = 'ACTIVE'", (email,), one=True)
    if row:
        sender = os.getenv("SES_FROM_EMAIL")
        base = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
        if not sender or not base or not base.startswith("https://"):
            current_app.logger.error("Password reset SES_FROM_EMAIL or HTTPS PUBLIC_BASE_URL not configured")
            return jsonify(error="Password recovery is temporarily unavailable."), 503
        token = serializer().dumps([row["user_id"], fingerprint(row["password_hash"])])
        link = base + "/reset-password.html?token=" + quote(token, safe="")
        try:
            boto3.client("ses", region_name=os.getenv("AWS_REGION", "us-east-1")).send_email(
                Source=sender,
                Destination={"ToAddresses": [row["email"]]},
                Message={"Subject": {"Data": "Reset your TigerTruck password"},
                         "Body": {"Text": {"Data": "Use this link to reset your password (valid for 30 minutes):\n" + link + "\n\nIf you didn't request this, ignore this email."}}})
        except (BotoCoreError, ClientError):
            current_app.logger.exception("SES password recovery email failed")
            return jsonify(error="Password recovery is temporarily unavailable."), 503
    return jsonify(ok=True, message=GENERIC)

@bp.post("/confirm")
def confirm_reset():
    data = request.get_json(silent=True) or {}
    token = str(data.get("token") or "")
    password = str(data.get("new_password") or "")
    if not token or len(token) > 2048:
        return jsonify(error="Invalid or expired reset link. Request a new one."), 400
    if password != str(data.get("confirm_password") or ""):
        return jsonify(error="Passwords do not match."), 400
    try:
        check_password(password)
    except AccountError as exc:
        return jsonify(error=str(exc)), 400
    try:
        user_id, old_hash = serializer().loads(token, max_age=EXPIRY_SECONDS)
    except (BadSignature, SignatureExpired, ValueError, TypeError):
        return jsonify(error="Invalid or expired reset link. Request a new one."), 400
    with transaction() as cur:
        cur.execute("SELECT username, password_hash, account_status FROM USER_ACCOUNT WHERE user_id = %s FOR UPDATE", (user_id,))
        row = cur.fetchone()
        if not row or row["account_status"] != "ACTIVE" or not hmac.compare_digest(fingerprint(row["password_hash"]), old_hash):
            return jsonify(error="This reset link has already been used or is no longer valid."), 400
        cur.execute("UPDATE USER_ACCOUNT SET password_hash = %s WHERE user_id = %s", (generate_password_hash(password), user_id))
        log_audit(cur, "ACCOUNT", True, subject_username=row["username"], entity_type="USER_ACCOUNT",
                  entity_id=user_id, details="Self-service password reset")
    return jsonify(ok=True, message="Password updated. You can now sign in.")
