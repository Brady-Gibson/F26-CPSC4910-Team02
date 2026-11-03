"""Invite sponsor user: a sponsor adds another sponsor user to their own organization.

Test users (seed data + conftest.py), password Password123!:
    testsponsor     sponsor user for 900001 (Tiger Test Trucking)
    secondsponsor   sponsor user for 900002 (Second Test Freight)
    testdriver      driver
"""
PASSWORD = "Password123!"
NEW = {"username": "mgarcia", "password": "Sp0nsor!2026", "first_name": "Maria", "last_name": "Garcia",
       "email": "mgarcia@example.com", "phone": "555-0200", "job_title": "Fleet Manager"}


def login(client, username, password=PASSWORD):
    r = client.post("/api/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.get_json()


def one(db, sql, *args):
    with db.cursor(dictionary=True) as cur:
        cur.execute(sql, args)
        return cur.fetchone()


def test_sponsor_adds_user_to_their_org(client, db):
    login(client, "testsponsor")
    r = client.post("/api/sponsor/organization/users", json=NEW)
    assert r.status_code == 201
    new_id = r.get_json()["sponsor_user_id"]
    su = one(db, "SELECT sponsor_id, job_title FROM SPONSOR_USER WHERE sponsor_user_id = %s", new_id)
    assert su == {"sponsor_id": 900001, "job_title": "Fleet Manager"}
    team = client.get("/api/sponsor/organization").get_json()["team"]
    assert any(t["sponsor_user_id"] == new_id for t in team)
    audit = one(db, "SELECT * FROM AUDIT_EVENT WHERE entity_type = 'USER_ACCOUNT' AND entity_id = %s", new_id)
    assert audit["actor_user_id"] == 900002 and audit["sponsor_id"] == 900001


def test_new_sponsor_user_can_sign_in_as_sponsor(client):
    login(client, "testsponsor")
    assert client.post("/api/sponsor/organization/users", json=NEW).status_code == 201
    client.post("/api/logout")
    login(client, "mgarcia", NEW["password"])
    assert client.get("/api/sponsor/organization").get_json()["organization"]["sponsor_id"] == 900001


def test_body_sponsor_id_is_ignored(client, db):
    # A sponsor can't sneak a user into another company by sending sponsor_id.
    login(client, "testsponsor")
    r = client.post("/api/sponsor/organization/users", json={**NEW, "sponsor_id": 900002})
    new_id = r.get_json()["sponsor_user_id"]
    assert one(db, "SELECT sponsor_id FROM SPONSOR_USER WHERE sponsor_user_id = %s", new_id)["sponsor_id"] == 900001


def test_invite_validation(client):
    login(client, "testsponsor")
    url = "/api/sponsor/organization/users"
    assert client.post(url, json={**NEW, "password": "weak"}).status_code == 400
    assert client.post(url, json={**NEW, "username": "testdriver"}).status_code == 400
    assert client.post(url, json={**NEW, "email": "testdriver@example.com"}).status_code == 400
    assert client.post(url, json={**NEW, "email": "bad"}).status_code == 400
    assert client.post(url, json={**NEW, "first_name": ""}).status_code == 400


def test_drivers_cannot_invite(client):
    login(client, "testdriver")
    assert client.post("/api/sponsor/organization/users", json=NEW).status_code == 403
