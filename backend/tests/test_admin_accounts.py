"""Admin account management: create accounts, lock/unlock/deactivate, reset passwords.

Test users (from seed data + conftest.py), all with password Password123!:
    900001 testadmin      admin
    900003 testdriver     driver with sponsor 900001
    900004 newdriver      driver with no sponsor yet
    900002 testsponsor    sponsor user for 900001
"""
PASSWORD = "Password123!"
NEW_PASSWORD = "Fresh-Pass9"


def login(client, username, password=PASSWORD):
    return client.post("/api/login", json={"username": username, "password": password})


def as_admin(client):
    assert login(client, "testadmin").status_code == 200


def new_account(**overrides):
    return {"role": "sponsor", "sponsor_id": 900001, "username": "newsponsor", "first_name": "New",
            "last_name": "Sponsor", "email": "newsponsor@example.com", "password": PASSWORD, **overrides}


def one(db, sql, *args):
    with db.cursor(dictionary=True) as cur:
        cur.execute(sql, args)
        return cur.fetchone()


def test_users_list_includes_sponsors_and_no_password(client):
    as_admin(client)
    data = client.get("/api/admin/users").get_json()
    assert any(s["sponsor_id"] == 900001 for s in data["sponsors"])
    driver = next(u for u in data["users"] if u["username"] == "testdriver")
    assert driver["role"] == "driver" and driver["sponsor_name"] == "Tiger Test Trucking"
    assert all("password_hash" not in u for u in data["users"])


def test_admin_creates_sponsor_user_who_can_sign_in(client, db):
    as_admin(client)
    r = client.post("/api/admin/users", json=new_account(job_title="Dispatcher"))
    assert r.status_code == 201
    row = one(db, "SELECT * FROM SPONSOR_USER WHERE sponsor_user_id=%s", r.get_json()["user_id"])
    assert row["sponsor_id"] == 900001 and row["job_title"] == "Dispatcher"
    client.post("/api/logout")
    me = login(client, "newsponsor").get_json()["user"]
    assert me["role"] == "sponsor" and me["sponsor_id"] == 900001


def test_admin_creates_driver_with_and_without_sponsor(client, db):
    as_admin(client)
    r = client.post("/api/admin/users", json=new_account(role="driver", username="d1", email="d1@example.com"))
    assert one(db, "SELECT * FROM DRIVER WHERE driver_id=%s", r.get_json()["user_id"])["participation_status"] == "ACTIVE"
    r = client.post("/api/admin/users", json=new_account(role="driver", sponsor_id=None, username="d2", email="d2@example.com"))
    row = one(db, "SELECT * FROM DRIVER WHERE driver_id=%s", r.get_json()["user_id"])
    assert row["participation_status"] == "APPLICANT" and row["sponsor_id"] is None


def test_admin_creates_admin(client, db):
    as_admin(client)
    r = client.post("/api/admin/users", json=new_account(role="admin", username="admin2", email="a2@example.com"))
    assert one(db, "SELECT * FROM ADMIN WHERE admin_id=%s", r.get_json()["user_id"])


def test_create_rejects_bad_input(client):
    as_admin(client)
    assert client.post("/api/admin/users", json=new_account(role="boss")).status_code == 400
    assert client.post("/api/admin/users", json=new_account(sponsor_id=None)).status_code == 400
    assert client.post("/api/admin/users", json=new_account(password="weak")).status_code == 400
    r = client.post("/api/admin/users", json=new_account(username="testdriver"))
    assert r.status_code == 400 and "taken" in r.get_json()["error"]


def test_non_admin_cannot_manage_accounts(client):
    assert login(client, "testsponsor").status_code == 200
    assert client.post("/api/admin/users", json=new_account()).status_code == 403
    assert client.post("/api/admin/users/900003/status", json={"status": "LOCKED"}).status_code == 403
    assert client.post("/api/admin/users/900003/reset-password", json={"password": NEW_PASSWORD}).status_code == 403


def test_lock_unlock_deactivate_reactivate(client, db):
    as_admin(client)
    status = lambda: one(db, "SELECT account_status FROM USER_ACCOUNT WHERE user_id=900003")["account_status"]
    for to in ("LOCKED", "ACTIVE", "INACTIVE", "ACTIVE"):
        r = client.post("/api/admin/users/900003/status", json={"status": to})
        assert r.status_code == 200, r.get_json()
        assert status() == to
    assert client.post("/api/admin/users/900003/status", json={"status": "ACTIVE"}).status_code == 400
    assert client.post("/api/admin/users/900001/status", json={"status": "LOCKED"}).status_code == 400  # self


def test_locked_user_is_signed_out_right_away(app, db):
    admin, driver = app.test_client(), app.test_client()
    as_admin(admin)
    assert login(driver, "testdriver").status_code == 200
    admin.post("/api/admin/users/900003/status", json={"status": "LOCKED"})
    assert driver.get("/api/me").status_code == 401
    assert login(driver, "testdriver").status_code == 403


def test_reset_password_unlocks_and_restarts_failed_login_count(client):
    for _ in range(5):
        login(client, "testdriver", "Wrong-pass1")
    assert login(client, "testdriver").status_code == 403  # locked

    as_admin(client)
    r = client.post("/api/admin/users/900003/reset-password", json={"password": NEW_PASSWORD})
    assert r.status_code == 200 and r.get_json()["account_status"] == "ACTIVE"
    client.post("/api/logout")

    assert login(client, "testdriver").status_code == 401             # old password no longer works
    assert login(client, "testdriver", NEW_PASSWORD).status_code == 200


def test_unlock_restarts_failed_login_count(client):
    for _ in range(5):
        login(client, "testdriver", "Wrong-pass1")
    as_admin(client)
    client.post("/api/admin/users/900003/status", json={"status": "ACTIVE"})
    client.post("/api/logout")
    assert login(client, "testdriver", "Wrong-pass1").status_code == 401  # one miss doesn't relock
    assert login(client, "testdriver").status_code == 200


def test_reset_password_rejects_weak_password(client):
    as_admin(client)
    assert client.post("/api/admin/users/900003/reset-password", json={"password": "short"}).status_code == 400
    assert client.post("/api/admin/users/123/reset-password", json={"password": NEW_PASSWORD}).status_code == 404
