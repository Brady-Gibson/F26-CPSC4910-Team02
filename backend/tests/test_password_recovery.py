"""Regression tests for password recovery; run with the disposable MySQL test DB."""
import re
from unittest.mock import patch
from werkzeug.security import check_password_hash

def test_unknown_email_does_not_reveal_account(client):
    with patch("password_recovery.boto3.client") as ses:
        response = client.post("/api/password-reset/request", json={"email": "missing@example.com"})
    assert response.status_code == 200
    assert "If an active account" in response.json["message"]
    ses.assert_not_called()

def test_invalid_reset_token(client):
    response = client.post("/api/password-reset/confirm", json={
        "token": "invalid", "new_password": "NewPassword456!", "confirm_password": "NewPassword456!"})
    assert response.status_code == 400

def test_password_recovery_round_trip(client, db, monkeypatch):
    monkeypatch.setenv("SES_FROM_EMAIL", "verified@example.com")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://example.com")
    with patch("password_recovery.boto3.client") as ses:
        response = client.post("/api/password-reset/request", json={"email": "testdriver@example.com"})
    assert response.status_code == 200
    assert ses.return_value.send_email.called
    email = ses.return_value.send_email.call_args.kwargs["Message"]["Body"]["Text"]["Data"]
    token = email.split("token=", 1)[1].splitlines()[0].strip()
    payload = {"token": token, "new_password": "NewPassword456!", "confirm_password": "NewPassword456!"}
    assert client.post("/api/password-reset/confirm", json=payload).status_code == 200
    assert client.post("/api/password-reset/confirm", json=payload).status_code == 400
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT password_hash FROM USER_ACCOUNT WHERE username = 'testdriver'")
    assert check_password_hash(cur.fetchone()["password_hash"], "NewPassword456!")
    cur.close()

def test_request_rate_limit(client, monkeypatch):
    monkeypatch.setenv("SES_FROM_EMAIL", "verified@example.com")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://example.com")
    with patch("password_recovery.boto3.client") as ses:
        for _ in range(5):
            response = client.post("/api/password-reset/request", json={"email": "testdriver@example.com"})
    assert response.status_code == 200
    assert ses.return_value.send_email.call_count == 3
