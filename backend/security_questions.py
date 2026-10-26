"""Optional security-question recovery. Answers are never stored in plaintext."""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from flask import Blueprint, current_app, g, jsonify, request
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from werkzeug.security import check_password_hash, generate_password_hash

from accounts import AccountError, check_password
from audit import log_audit, notify
from auth import require_role
from db import query, transaction

bp = Blueprint("security_questions", __name__, url_prefix="/api/security-questions")
QUESTIONS = (
    "What was the name of your first pet?",
    "What was the name of your first school?",
    "What was the name of the street you grew up on?",
    "What was your childhood nickname?",
    "What was the name of your favorite childhood teacher?",
    "What was the name of your first stuffed animal?",
)
GENERIC = "If this account has recovery questions configured, you can continue."
DUMMY = generate_password_hash("dummy-answer-" + secrets.token_hex(8))


def _tokenizer():
    return URLSafeTimedSerializer(current_app.secret_key, salt="security-question-recovery-v1")


def _normalize(value):
    return " ".join(str(value or "").strip().casefold().split())


def _identity(identifier):
    return query("""SELECT user_id, username, password_hash FROM USER_ACCOUNT
                    WHERE (LOWER(username)=LOWER(%s) OR LOWER(email)=LOWER(%s))
                      AND account_status='ACTIVE'""", (identifier, identifier), one=True)


def _questions(user_id):
    return query("""SELECT question_number, question_text, answer_hash
                    FROM USER_SECURITY_QUESTION WHERE user_id=%s ORDER BY question_number""", (user_id,))


def _fingerprint(password_hash):
    return hmac.new(current_app.secret_key.encode(), password_hash.encode(), hashlib.sha256).hexdigest()


def _attempts(identifier):
    # Account-based throttling across processes, recorded in existing audit log.
    row = query("""SELECT COUNT(*) AS attempts FROM AUDIT_EVENT
                   WHERE category='ACCOUNT' AND success=FALSE AND subject_username=%s
                     AND reason_or_details='Security question verification failed'
                     AND created_at > DATE_SUB(NOW(), INTERVAL 1 HOUR)""",
                (identifier[:100],), one=True)
    return int(row["attempts"]) if row else 0


@bp.get("/options")
def options():
    return jsonify(questions=list(QUESTIONS))


@bp.get("/me")
@require_role()
def my_questions():
    rows = _questions(g.user["user_id"])
    return jsonify(configured=len(rows) == 2,
                   questions=[{"number": r["question_number"], "question": r["question_text"]} for r in rows])


@bp.post("/me")
@require_role()
def save_questions():
    data = request.get_json(silent=True) or {}
    entries = data.get("questions")
    password = str(data.get("current_password") or "")
    if not isinstance(entries, list) or len(entries) != 2:
        return jsonify(error="Choose two security questions."), 400
    names = [e.get("question") if isinstance(e, dict) else None for e in entries]
    answers = [_normalize(e.get("answer")) if isinstance(e, dict) else "" for e in entries]
    if len(set(names)) != 2 or any(name not in QUESTIONS for name in names):
        return jsonify(error="Choose two different questions from the list."), 400
    if any(len(a) < 3 or len(a) > 150 for a in answers):
        return jsonify(error="Each answer must be between 3 and 150 characters."), 400
    with transaction() as cur:
        cur.execute("SELECT password_hash FROM USER_ACCOUNT WHERE user_id=%s FOR UPDATE", (g.user["user_id"],))
        row = cur.fetchone()
        if not password or not check_password_hash(row["password_hash"], password):
            return jsonify(error="Current password is incorrect."), 403
        cur.execute("DELETE FROM USER_SECURITY_QUESTION WHERE user_id=%s", (g.user["user_id"],))
        for i, (name, answer) in enumerate(zip(names, answers), 1):
            cur.execute("""INSERT INTO USER_SECURITY_QUESTION
                           (user_id, question_number, question_text, answer_hash)
                           VALUES (%s,%s,%s,%s)""",
                        (g.user["user_id"], i, name, generate_password_hash(answer)))
        log_audit(cur, "ACCOUNT", True, actor_user_id=g.user["user_id"],
                  subject_username=g.user["username"], entity_type="USER_ACCOUNT",
                  entity_id=g.user["user_id"], details="Security questions configured")
    return jsonify(ok=True)


@bp.post("/lookup")
def lookup():
    identifier = str((request.get_json(silent=True) or {}).get("username") or "").strip()
    if not identifier or len(identifier) > 100:
        return jsonify(error="Enter your username or email."), 400
    user = _identity(identifier)
    rows = _questions(user["user_id"]) if user else []
    if len(rows) != 2:
        return jsonify(message="Recovery questions are not available for this account. Contact an administrator.",
                       configured=False)
    return jsonify(configured=True, questions=[r["question_text"] for r in rows])


@bp.post("/verify")
def verify():
    data = request.get_json(silent=True) or {}
    identifier = str(data.get("username") or "").strip()
    answers = data.get("answers")
    if not identifier or len(identifier) > 100 or not isinstance(answers, list) or len(answers) != 2:
        return jsonify(error="Enter your username and both answers."), 400
    user = _identity(identifier)
    audit_name = (user["username"] if user else identifier)[:100]
    if _attempts(audit_name) >= 5:
        return jsonify(error="Too many attempts. Try again in one hour or contact an administrator."), 429
    rows = _questions(user["user_id"]) if user else []
    valid = len(rows) == 2
    for index in range(2):
        hashed = rows[index]["answer_hash"] if valid else DUMMY
        answer = _normalize(answers[index])
        matched = check_password_hash(hashed, answer)
        valid = valid and matched and bool(answer)
    if not valid:
        with transaction() as cur:
            log_audit(cur, "ACCOUNT", False, subject_username=audit_name,
                      details="Security question verification failed")
        return jsonify(error="Unable to verify these answers."), 403
    token = _tokenizer().dumps({"uid": user["user_id"], "pw": _fingerprint(user["password_hash"])})
    return jsonify(ok=True, token=token, expires_in=600)


@bp.post("/reset")
def reset():
    data = request.get_json(silent=True) or {}
    token = str(data.get("token") or "")
    new = str(data.get("new_password") or "")
    if not token or len(token) > 2000:
        return jsonify(error="Recovery session is missing or invalid."), 400
    if new != str(data.get("confirm_password") or ""):
        return jsonify(error="Passwords do not match."), 400
    try:
        payload = _tokenizer().loads(token, max_age=600)
        uid = int(payload["uid"])
        fingerprint = payload["pw"]
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError):
        return jsonify(error="Recovery session expired or invalid. Start again."), 400
    try:
        check_password(new)
    except AccountError as e:
        return jsonify(error=str(e)), 400
    with transaction() as cur:
        cur.execute("""SELECT username, password_hash FROM USER_ACCOUNT
                       WHERE user_id=%s AND account_status='ACTIVE' FOR UPDATE""", (uid,))
        user = cur.fetchone()
        if not user or not hmac.compare_digest(_fingerprint(user["password_hash"]), fingerprint):
            return jsonify(error="Recovery session expired or already used."), 400
        if check_password_hash(user["password_hash"], new):
            return jsonify(error="Choose a password different from your current one."), 400
        cur.execute("UPDATE USER_ACCOUNT SET password_hash=%s WHERE user_id=%s",
                    (generate_password_hash(new), uid))
        log_audit(cur, "ACCOUNT", True, actor_user_id=uid, subject_username=user["username"],
                  entity_type="USER_ACCOUNT", entity_id=uid, details="Password reset via security questions")
        notify(cur, uid, "PASSWORD_CHANGED",
               "Your password was reset using security questions. If this wasn't you, contact an administrator.")
    return jsonify(ok=True, message="Password reset. You can sign in now.")
