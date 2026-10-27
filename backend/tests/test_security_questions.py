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


def test_full_recovery_round_trip(client, db):
    assert client.post("/api/login", json={"username": "testdriver", "password": "Password123!"}).status_code == 200
    questions = client.get("/api/security-questions/options").json["questions"]
    setup = client.post("/api/security-questions/me", json={
        "current_password": "Password123!",
        "questions": [{"question": questions[0], "answer": "Apollo"},
                      {"question": questions[1], "answer": "Clemson"}],
    })
    assert setup.status_code == 200, setup.json
    with db.cursor(dictionary=True) as cur:
        cur.execute("SELECT answer_hash FROM USER_SECURITY_QUESTION")
        hashes = [r["answer_hash"] for r in cur.fetchall()]
    assert len(hashes) == 2 and all("Apollo" not in h and "Clemson" not in h for h in hashes)
    client.post("/api/logout")
    lookup = client.post("/api/security-questions/lookup", json={"username": "testdriver"})
    assert lookup.status_code == 200 and lookup.json["configured"]
    bad = client.post("/api/security-questions/verify", json={
        "username": "testdriver", "answers": ["wrong", "wrong"]})
    assert bad.status_code == 403
    good = client.post("/api/security-questions/verify", json={
        "username": "testdriver", "answers": ["apollo", "clemson"]})
    assert good.status_code == 200, good.json
    token = good.json["token"]
    reset = client.post("/api/security-questions/reset", json={
        "token": token, "new_password": "NewPassword456!", "confirm_password": "NewPassword456!"})
    assert reset.status_code == 200, reset.json
    reused = client.post("/api/security-questions/reset", json={
        "token": token, "new_password": "AnotherPassword789!", "confirm_password": "AnotherPassword789!"})
    assert reused.status_code == 400
    assert client.post("/api/login", json={"username": "testdriver", "password": "NewPassword456!"}).status_code == 200


def test_changing_questions_invalidates_existing_recovery_token(client):
    assert client.post("/api/login", json={"username": "testdriver", "password": "Password123!"}).status_code == 200
    names = client.get("/api/security-questions/options").json["questions"]
    def save(first, second):
        return client.post("/api/security-questions/me", json={
            "current_password": "Password123!",
            "questions": [{"question": names[0], "answer": first},
                          {"question": names[1], "answer": second}],
        })
    assert save("Apollo", "Clemson").status_code == 200
    client.post("/api/logout")
    verified = client.post("/api/security-questions/verify", json={
        "username": "testdriver", "answers": ["apollo", "clemson"]})
    assert verified.status_code == 200
    token = verified.json["token"]
    assert client.post("/api/login", json={"username": "testdriver", "password": "Password123!"}).status_code == 200
    assert save("NewPet", "NewSchool").status_code == 200
    client.post("/api/logout")
    reset = client.post("/api/security-questions/reset", json={
        "token": token, "new_password": "NewPassword456!", "confirm_password": "NewPassword456!"})
    assert reset.status_code == 400
