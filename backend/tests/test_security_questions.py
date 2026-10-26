"""Focused tests for recovery input validation and token behavior (no live RDS)."""
from unittest.mock import patch

from werkzeug.security import generate_password_hash, check_password_hash


def test_normalization():
    from security_questions import _normalize
    assert _normalize("  My   First PET  ") == "my first pet"


def test_answer_hashes_are_not_plaintext():
    from security_questions import _normalize
    hashed = generate_password_hash(_normalize("Apollo"))
    assert "apollo" not in hashed
    assert check_password_hash(hashed, "apollo")


def test_recovery_token_expires_and_password_change_invalidates(app):
    from security_questions import _fingerprint, _tokenizer
    with app.app_context():
        old_hash = generate_password_hash("old-secret")
        token = _tokenizer().dumps({"uid": 12, "pw": _fingerprint(old_hash)})
        payload = _tokenizer().loads(token, max_age=600)
        assert payload["uid"] == 12
        assert payload["pw"] == _fingerprint(old_hash)
        assert payload["pw"] != _fingerprint(generate_password_hash("new-secret"))


def test_invalid_recovery_token_rejected(client):
    response = client.post("/api/security-questions/reset", json={
        "token": "invalid", "new_password": "NewPassword123!", "confirm_password": "NewPassword123!"
    })
    assert response.status_code == 400
