"""Change password (POST /api/me/password) for a signed-in user.

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
