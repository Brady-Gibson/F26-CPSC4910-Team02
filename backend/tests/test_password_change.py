"""Tests for changing a password while signed in."""

from werkzeug.security import check_password_hash

OLD_PASSWORD = "Password123!"
NEW_PASSWORD = "NewPassword456!"


def login(client, password=OLD_PASSWORD):
    return client.post("/api/login", json={
        "username": "testdriver",
        "password": password,
    })


def change_password(client, current=OLD_PASSWORD,
                    new=NEW_PASSWORD, confirm=NEW_PASSWORD):
    return client.post("/api/me/password", json={
        "current_password": current,
        "new_password": new,
        "confirm_password": confirm,
    })


def test_password_change_requires_login(client):
    response = change_password(client)
    assert response.status_code == 401


def test_wrong_current_password(client):
    assert login(client).status_code == 200

    response = change_password(client, current="WrongPassword123!")
    assert response.status_code == 400


def test_password_confirmation_must_match(client):
    assert login(client).status_code == 200

    response = change_password(client, confirm="DifferentPassword123!")
    assert response.status_code == 400


def test_weak_password_rejected(client):
    assert login(client).status_code == 200

    response = change_password(client, new="abc", confirm="abc")
    assert response.status_code == 400


def test_successful_password_change(client, db):
    assert login(client).status_code == 200

    response = change_password(client)
    assert response.status_code == 200

    with db.cursor(dictionary=True) as cursor:
        cursor.execute(
            "SELECT password_hash FROM USER_ACCOUNT WHERE username = %s",
            ("testdriver",),
        )
        password_hash = cursor.fetchone()["password_hash"]

    assert check_password_hash(password_hash, NEW_PASSWORD)

    client.post("/api/logout")

    assert login(client, OLD_PASSWORD).status_code == 401
    assert login(client, NEW_PASSWORD).status_code == 200
