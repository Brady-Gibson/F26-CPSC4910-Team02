"""Sponsor Driver Management: driver detail, point + purchase history, editing contact info, adding a driver.

Test users (seed data + conftest.py), password Password123!:
    testdriver (900003)    ACTIVE with sponsor 900001, has a 1000-point award and a 500-point order
    newdriver (900004)     no sponsor
    testsponsor            sponsor user for 900001 (Tiger Test Trucking)
    secondsponsor          sponsor user for 900002 (Second Test Freight)
"""
SEED_DRIVER_ID, NEW_DRIVER_ID = 900003, 900004
PASSWORD = "Password123!"


def login(client, username):
    r = client.post("/api/login", json={"username": username, "password": PASSWORD})
    assert r.status_code == 200, r.get_json()


def one(db, sql, *args):
    with db.cursor(dictionary=True) as cur:
        cur.execute(sql, args)
        return cur.fetchone()


CONTACT = {"first_name": "Test", "last_name": "Driver", "email": "testdriver@example.com", "phone": "555-0003"}


# ---- Driver details / point balance / point history / purchase history

def test_driver_detail_shows_profile_history_and_orders(client):
    login(client, "testsponsor")
    r = client.get(f"/api/sponsor/drivers/{SEED_DRIVER_ID}")
    assert r.status_code == 200
    data = r.get_json()
    d = data["driver"]
    assert d["username"] == "testdriver" and d["participation_status"] == "ACTIVE"
    assert d["email"] == "testdriver@example.com" and d["current_points"] == 500
    assert [t["points_delta"] for t in data["transactions"]] == [-500, 1000]   # newest first
    assert data["transactions"][1]["performed_by"] == "Test Sponsor"
    assert len(data["orders"]) == 1 and data["orders"][0]["items"][0]["product_name"] == "Test Gift Card"
    assert "password_hash" not in d


def test_other_sponsor_cannot_see_driver(client):
    login(client, "secondsponsor")
    assert client.get(f"/api/sponsor/drivers/{SEED_DRIVER_ID}").status_code == 404


def test_detail_hides_other_sponsors_history(client, db):
    # Give testdriver a second membership with points from sponsor 2, then check sponsor 1 can't see it.
    with db.cursor() as cur:
        cur.execute("INSERT INTO DRIVER_SPONSOR (driver_id, sponsor_id, current_points, participation_status) "
                    "VALUES (900003, 900002, 250, 'ACTIVE')")
        cur.execute("INSERT INTO POINT_TRANSACTION (driver_id, sponsor_id, performed_by_user_id, points_delta, "
                    "balance_after, reason) VALUES (900003, 900002, 900005, 250, 250, 'Other sponsor award')")
    login(client, "testsponsor")
    data = client.get(f"/api/sponsor/drivers/{SEED_DRIVER_ID}").get_json()
    assert data["driver"]["current_points"] == 500
    assert all(t["reason"] != "Other sponsor award" for t in data["transactions"])


def test_drivers_cannot_use_detail(client):
    login(client, "testdriver")
    assert client.get(f"/api/sponsor/drivers/{SEED_DRIVER_ID}").status_code == 403


# ---- Update Driver's Information + Recording Driving

def test_update_driver_contact_info_logs_and_notifies(client, db):
    login(client, "testsponsor")
    r = client.patch(f"/api/sponsor/drivers/{SEED_DRIVER_ID}",
                     json={**CONTACT, "phone": "864-555-1212", "email": "New.Email@Example.com"})
    assert r.status_code == 200 and r.get_json()["changed"] == ["email", "phone"]
    u = one(db, "SELECT email, phone FROM USER_ACCOUNT WHERE user_id = 900003")
    assert u == {"email": "new.email@example.com", "phone": "864-555-1212"}
    audit = one(db, "SELECT * FROM AUDIT_EVENT WHERE category = 'DRIVER_UPDATE' ORDER BY audit_event_id DESC LIMIT 1")
    assert audit["actor_user_id"] == 900002 and audit["driver_id"] == 900003 and "email, phone" in audit["reason_or_details"]
    note = one(db, "SELECT * FROM NOTIFICATION WHERE user_id = 900003 ORDER BY notification_id DESC LIMIT 1")
    assert note["notification_type"] == "PROFILE_UPDATED"


def test_update_with_no_changes_does_not_log(client, db):
    login(client, "testsponsor")
    r = client.patch(f"/api/sponsor/drivers/{SEED_DRIVER_ID}", json=CONTACT)
    assert r.status_code == 200 and r.get_json()["changed"] == []
    assert one(db, "SELECT COUNT(*) AS n FROM AUDIT_EVENT WHERE category = 'DRIVER_UPDATE'")["n"] == 0


def test_update_validation(client):
    login(client, "testsponsor")
    url = f"/api/sponsor/drivers/{SEED_DRIVER_ID}"
    assert client.patch(url, json={**CONTACT, "email": "not-an-email"}).status_code == 400
    assert client.patch(url, json={**CONTACT, "first_name": ""}).status_code == 400
    # Email already used by another account.
    assert client.patch(url, json={**CONTACT, "email": "newdriver@example.com"}).status_code == 400


def test_cannot_update_driver_outside_my_org(client):
    login(client, "testsponsor")
    assert client.patch(f"/api/sponsor/drivers/{NEW_DRIVER_ID}", json=CONTACT).status_code == 404
    login(client, "secondsponsor")
    assert client.patch(f"/api/sponsor/drivers/{SEED_DRIVER_ID}", json=CONTACT).status_code == 404


# ---- New Driver User

NEW = {"username": "jlee", "password": "Truck!ng2026", "first_name": "Jordan", "last_name": "Lee",
       "email": "jlee@example.com", "phone": "555-0100"}


def test_sponsor_creates_driver_in_their_program(client, db):
    login(client, "testsponsor")
    r = client.post("/api/sponsor/drivers", json=NEW)
    assert r.status_code == 201
    new_id = r.get_json()["driver_id"]
    m = one(db, "SELECT * FROM DRIVER_SPONSOR WHERE driver_id = %s", new_id)
    assert m["sponsor_id"] == 900001 and m["participation_status"] == "ACTIVE"
    assert any(d["driver_id"] == new_id for d in client.get("/api/sponsor/drivers").get_json()["drivers"])
    # The new driver can sign in with the temporary password.
    assert client.post("/api/login", json={"username": "jlee", "password": NEW["password"]}).status_code == 200


def test_create_driver_validation(client):
    login(client, "testsponsor")
    assert client.post("/api/sponsor/drivers", json={**NEW, "password": "weak"}).status_code == 400
    assert client.post("/api/sponsor/drivers", json={**NEW, "username": "testdriver"}).status_code == 400
    assert client.post("/api/sponsor/drivers", json={**NEW, "email": "bad"}).status_code == 400
