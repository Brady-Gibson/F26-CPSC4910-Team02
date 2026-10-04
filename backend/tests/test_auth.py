"""Automated tests for login, logout, session handling, and account lockout."""

PASSWORD = "Password123!"


def login(client, username="testdriver", password=PASSWORD):
    return client.post(
        "/api/login",
        json={"username": username, "password": password},
    )


def test_login_success(client):
    response = login(client)

    assert response.status_code == 200

    data = response.get_json()
    assert data["ok"] is True
    assert data["user"]["username"] == "testdriver"
    assert data["user"]["role"] == "driver"


def test_login_wrong_password(client):
    response = login(client, password="WrongPassword123!")

    assert response.status_code == 401
    assert response.get_json()["error"] == "Incorrect username or password."


def test_login_unknown_user(client):
    response = login(client, username="doesnotexist")

    assert response.status_code == 401
    assert response.get_json()["error"] == "Incorrect username or password."


def test_login_requires_username_and_password(client):
    response = client.post("/api/login", json={})

    assert response.status_code == 400
    assert response.get_json()["error"] == "Enter your username and password."


def test_me_requires_login(client):
    response = client.get("/api/me")

    assert response.status_code == 401


def test_me_after_login(client):
    assert login(client).status_code == 200

    response = client.get("/api/me")

    assert response.status_code == 200
    assert response.get_json()["user"]["username"] == "testdriver"


def test_logout_ends_session(client):
    assert login(client).status_code == 200

    response = client.post("/api/logout")
    assert response.status_code == 200

    response = client.get("/api/me")
    assert response.status_code == 401


def test_account_locks_after_five_failed_logins(client, db):
    for attempt in range(4):
        response = login(client, password="WrongPassword123!")
        assert response.status_code == 401

    response = login(client, password="WrongPassword123!")
    assert response.status_code == 403
    assert "locked" in response.get_json()["error"].lower()

    with db.cursor(dictionary=True) as cursor:
        cursor.execute(
            "SELECT account_status FROM USER_ACCOUNT WHERE username = %s",
            ("testdriver",),
        )
        row = cursor.fetchone()

    assert row["account_status"] == "LOCKED"