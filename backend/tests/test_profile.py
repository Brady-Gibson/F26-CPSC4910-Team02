"""Profile page endpoints for a signed-in user: change password (POST /api/me/password) and edit profile.

Seed users from conftest.py all have password Password123!.
"""
PASSWORD = "Password123!"
NEW_PASSWORD = "Fresh-Pass9"


def login(client, username="testdriver", password=PASSWORD):
    return client.post("/api/login", json={"username": username, "password": password})


def change(client, current=PASSWORD, new=NEW_PASSWORD, confirm=None):
    return client.post("/api/me/password", json={"current_password": current, "new_password": new,
                                                 "confirm_password": new if confirm is None else confirm})


def test_driver_changes_password(client):
    assert login(client).status_code == 200
    assert change(client).status_code == 200
    client.post("/api/logout")
    assert login(client).status_code == 401
    assert login(client, password=NEW_PASSWORD).status_code == 200


def test_sponsor_and_admin_can_change_password_too(app):
    for username in ("testsponsor", "testadmin"):
        c = app.test_client()
        assert login(c, username).status_code == 200
        assert change(c).status_code == 200


def test_change_password_rejects_bad_input(client):
    assert login(client).status_code == 200
    assert change(client, current="Wrong-pass1").status_code == 400
    assert change(client, confirm="Different-1").status_code == 400
    assert change(client, new="weak").status_code == 400
    assert change(client, new=PASSWORD).status_code == 400          # same as current
    client.post("/api/logout")
    assert login(client).status_code == 200                          # nothing changed


def test_change_password_requires_sign_in(client):
    assert change(client).status_code == 401


def test_admin_viewing_as_driver_cannot_change_their_password(client):
    assert login(client, "testadmin").status_code == 200
    assert client.post("/api/view-as", json={"user_id": 900003}).status_code == 200
    assert change(client).status_code == 403


# ---- Edit profile (GET/POST /api/me/profile)

PROFILE = {"first_name": "Tess", "last_name": "Driver", "email": "Tess.Driver@Example.com", "phone": "864-555-0100"}


def test_driver_reads_and_updates_profile(client, db):
    assert login(client).status_code == 200
    assert client.get("/api/me/profile").get_json()["profile"]["username"] == "testdriver"
    r = client.post("/api/me/profile", json=PROFILE)
    assert r.status_code == 200 and "email" in r.get_json()["changed"]
    with db.cursor(dictionary=True) as cur:
        cur.execute("SELECT first_name, email, phone FROM USER_ACCOUNT WHERE user_id = 900003")
        assert cur.fetchone() == {"first_name": "Tess", "email": "tess.driver@example.com", "phone": "864-555-0100"}
    assert client.get("/api/me").get_json()["user"]["first_name"] == "Tess"
    assert client.post("/api/me/profile", json=PROFILE).get_json()["changed"] == []   # no-op save


def test_profile_rejects_bad_input(client):
    assert login(client).status_code == 200
    assert client.post("/api/me/profile", json={**PROFILE, "first_name": " "}).status_code == 400
    assert client.post("/api/me/profile", json={**PROFILE, "email": "not-an-email"}).status_code == 400
    r = client.post("/api/me/profile", json={**PROFILE, "email": "newdriver@example.com"})   # another user's email
    assert r.status_code == 400 and "already exists" in r.get_json()["error"]
