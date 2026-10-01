"""Success and failure tests for the Driver Sponsor Application stories.

Test users (from seed data + conftest.py):
    900003 testdriver     already ACTIVE with sponsor 900001
    900004 newdriver      no sponsor yet
    900002 testsponsor    sponsor user for 900001 (Tiger Test Trucking)
    900005 secondsponsor  sponsor user for 900002 (Second Test Freight)
"""
NEW_DRIVER, SEED_DRIVER = 900004, 900003
SPONSOR_1_USER, SPONSOR_2_USER = 900002, 900005
GOOD = {"sponsor_id": 900001, "cdl_number": "SC1234567", "cdl_state": "sc",
        "years_experience": 4, "notes": "Regional routes"}


def login(client, user_id):
    client.post(f"/test-login/{user_id}")


def apply(client, **overrides):
    return client.post("/api/driver/applications", json={**GOOD, **overrides})


def one(db, sql, *args):
    with db.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchone()


# ---- Sponsor Incentive Program / Required Information / Recorded Application

def test_driver_can_apply(client, db):
    login(client, NEW_DRIVER)
    r = apply(client)
    assert r.status_code == 201
    app_id = r.get_json()["application_id"]
    row = one(db, "SELECT * FROM DRIVER_APPLICATION WHERE application_id=%s", app_id)
    assert row["status"] == "PENDING" and row["cdl_state"] == "SC" and row["years_experience"] == 4
    audit = one(db, "SELECT * FROM AUDIT_EVENT WHERE entity_id=%s AND category='APPLICATION'", app_id)
    assert audit["success"] == 1 and audit["subject_username"] == "newdriver"


def test_required_fields_enforced(client):
    login(client, NEW_DRIVER)
    assert apply(client, cdl_number="").status_code == 400
    assert apply(client, cdl_state="ZZ").status_code == 400
    assert apply(client, years_experience="lots").status_code == 400
    assert apply(client, years_experience=-1).status_code == 400
    assert apply(client, sponsor_id=None).status_code == 400


def test_unknown_sponsor(client):
    login(client, NEW_DRIVER)
    assert apply(client, sponsor_id=123).status_code == 404


# ---- One Sponsor

def test_driver_with_sponsor_cannot_apply_elsewhere(client, db):
    login(client, SEED_DRIVER)
    r = apply(client, sponsor_id=900002)
    assert r.status_code == 409
    audit = one(db, "SELECT * FROM AUDIT_EVENT WHERE driver_id=%s AND success=0", SEED_DRIVER)
    assert "already have a sponsor" in audit["reason_or_details"]


def test_only_one_pending_application(client):
    login(client, NEW_DRIVER)
    assert apply(client).status_code == 201
    assert apply(client, sponsor_id=900002).status_code == 409


# ---- Driver Application Status / Rejection Reason Statement / alerts

def test_status_and_rejection_reason(client, db):
    login(client, NEW_DRIVER)
    app_id = apply(client).get_json()["application_id"]

    login(client, SPONSOR_1_USER)
    r = client.post(f"/api/sponsor/applications/{app_id}/decision",
                    json={"decision": "REJECT", "reason": "Need 5+ years experience"})
    assert r.status_code == 200

    login(client, NEW_DRIVER)
    apps = client.get("/api/driver/applications").get_json()
    assert apps[0]["status"] == "REJECTED"
    assert apps[0]["rejection_reason"] == "Need 5+ years experience"
    note = one(db, "SELECT * FROM NOTIFICATION WHERE user_id=%s ORDER BY notification_id DESC", NEW_DRIVER)
    assert note["notification_type"] == "APPLICATION_REJECTED" and "5+ years" in note["message"]

    # After a rejection the driver may apply again.
    assert apply(client, sponsor_id=900002).status_code == 201


def test_approval_sets_sponsor_and_notifies(client, db):
    login(client, NEW_DRIVER)
    app_id = apply(client).get_json()["application_id"]
    login(client, SPONSOR_1_USER)
    assert client.post(f"/api/sponsor/applications/{app_id}/decision",
                       json={"decision": "APPROVE"}).status_code == 200

    d = one(db, "SELECT * FROM DRIVER WHERE driver_id=%s", NEW_DRIVER)
    assert d["sponsor_id"] == 900001 and d["participation_status"] == "ACTIVE"
    note = one(db, "SELECT * FROM NOTIFICATION WHERE user_id=%s ORDER BY notification_id DESC", NEW_DRIVER)
    assert note["notification_type"] == "APPLICATION_APPROVED"

    login(client, NEW_DRIVER)
    assert apply(client, sponsor_id=900002).status_code == 409   # now has a sponsor


def test_reject_requires_reason(client):
    login(client, NEW_DRIVER)
    app_id = apply(client).get_json()["application_id"]
    login(client, SPONSOR_1_USER)
    r = client.post(f"/api/sponsor/applications/{app_id}/decision", json={"decision": "REJECT"})
    assert r.status_code == 400


def test_sponsor_cannot_decide_other_orgs_application(client):
    login(client, NEW_DRIVER)
    app_id = apply(client).get_json()["application_id"]
    login(client, SPONSOR_2_USER)
    r = client.post(f"/api/sponsor/applications/{app_id}/decision", json={"decision": "APPROVE"})
    assert r.status_code == 404


def test_cannot_decide_twice(client):
    login(client, NEW_DRIVER)
    app_id = apply(client).get_json()["application_id"]
    login(client, SPONSOR_1_USER)
    url = f"/api/sponsor/applications/{app_id}/decision"
    assert client.post(url, json={"decision": "APPROVE"}).status_code == 200
    assert client.post(url, json={"decision": "REJECT", "reason": "oops"}).status_code == 409


# ---- Access control

def test_must_be_logged_in(client):
    assert client.get("/api/driver/applications").status_code == 401


def test_sponsor_cannot_use_driver_routes(client):
    login(client, SPONSOR_1_USER)
    assert apply(client).status_code == 403


def test_driver_cannot_decide(client):
    login(client, NEW_DRIVER)
    app_id = apply(client).get_json()["application_id"]
    r = client.post(f"/api/sponsor/applications/{app_id}/decision", json={"decision": "APPROVE"})
    assert r.status_code == 403


def test_sponsor_list_excludes_current_sponsor(client):
    login(client, SEED_DRIVER)
    ids = [s["sponsor_id"] for s in client.get("/api/driver/sponsors").get_json()]
    assert 900001 not in ids and 900002 in ids
