"""Admin reports + invoice, admin sponsor/user editing, sponsor team management, sponsor report downloads,
sponsor View as driver, and the recurring-points job.

Test users (seed data + conftest.py), password Password123!:
    testadmin       admin
    testsponsor     sponsor user 900002 for 900001 (Tiger Test Trucking)
    secondsponsor   sponsor user 900005 for 900002 (Second Test Freight)
    testdriver      driver 900003, active with 900001 (500 points) and 900010
    newdriver       driver 900004, applicant (no sponsor)
Seed order 900001: testdriver, Tiger Test Trucking, PLACED, 500 points, $5.00.
"""
PASSWORD = "Password123!"


def login(client, username):
    r = client.post("/api/login", json={"username": username, "password": PASSWORD})
    assert r.status_code == 200, r.get_json()


def one(db, sql, *args):
    with db.cursor(dictionary=True) as cur:
        cur.execute(sql, args)
        return cur.fetchone()


def run(db, sql, *args):
    with db.cursor() as cur:
        cur.execute(sql, args)
    db.commit()


# ---------------------------------------------------------------- admin reports

def test_admin_sales_by_sponsor_and_invoice(client):
    login(client, "testadmin")
    r = client.get("/api/admin/reports?report=sponsor_sales").get_json()
    row = next(x for x in r["rows"] if x["sponsor_name"] == "Tiger Test Trucking")
    assert row["orders"] == 1 and row["total_dollar_amount"] == 5 and row["total_points"] == 500
    inv = client.get("/api/admin/reports?report=invoice").get_json()
    line = next(x for x in inv["rows"] if x["sponsor_name"] == "Tiger Test Trucking")
    assert line["fee"] == 0.05 and line["fee_rate"] == "1%"
    assert inv["totals"]["fee"] == sum(x["fee"] for x in inv["rows"])


def test_cancelled_orders_are_not_sales(client, db):
    run(db, "UPDATE CUSTOMER_ORDER SET status = 'CANCELLED' WHERE order_id = 900001")
    login(client, "testadmin")
    assert client.get("/api/admin/reports?report=sponsor_sales").get_json()["rows"] == []


def test_driver_sales_detail_and_filters(client):
    login(client, "testadmin")
    r = client.get("/api/admin/reports?report=driver_sales&view=detail&driver_id=900003").get_json()
    assert [x["product_name"] for x in r["rows"]] == ["Test Gift Card"]
    assert client.get("/api/admin/reports?report=driver_sales&sponsor_id=900002").get_json()["rows"] == []
    assert client.get("/api/admin/reports?report=driver_sales&start_date=2099-01-01").get_json()["rows"] == []


def test_admin_report_csv_has_totals(client):
    login(client, "testadmin")
    r = client.get("/api/admin/reports/export.csv?report=invoice")
    assert r.status_code == 200 and r.headers["Content-Type"].startswith("text/csv")
    assert "attachment" in r.headers["Content-Disposition"]
    lines = r.get_data(as_text=True).lstrip("﻿").splitlines()
    assert lines[0].startswith("Sponsor,") and lines[-1].startswith("TOTAL")


def test_admin_reports_validate_and_require_admin(client):
    login(client, "testadmin")
    assert client.get("/api/admin/reports?report=nope").status_code == 400
    assert client.get("/api/admin/reports?start_date=2026-13-01").status_code == 400
    assert client.get("/api/admin/reports?sponsor_id=abc").status_code == 400
    client.post("/api/logout")
    login(client, "testsponsor")
    assert client.get("/api/admin/reports").status_code == 403
    assert client.get("/api/admin/reports/export.csv").status_code == 403


# ---------------------------------------------------------------- admin sponsors + users

def test_admin_lists_edits_and_deactivates_sponsor(client, db):
    login(client, "testadmin")
    rows = client.get("/api/admin/sponsors").get_json()["sponsors"]
    tiger = next(s for s in rows if s["sponsor_id"] == 900001)
    assert tiger["sponsor_users"] == 1 and tiger["drivers"] >= 1
    r = client.patch("/api/admin/sponsors/900001", json={"phone": "555-9999", "point_dollar_rate": "0.05"})
    assert r.status_code == 200 and set(r.get_json()["changed"]) == {"phone", "point_dollar_rate"}
    assert client.patch("/api/admin/sponsors/900001", json={"status": "INACTIVE"}).status_code == 200
    assert one(db, "SELECT status, phone FROM SPONSOR_ORGANIZATION WHERE sponsor_id = 900001") == \
        {"status": "INACTIVE", "phone": "555-9999"}
    assert one(db, "SELECT 1 AS x FROM AUDIT_EVENT WHERE category = 'ORGANIZATION' AND sponsor_id = 900001 LIMIT 1")


def test_admin_sponsor_edit_validation(client):
    login(client, "testadmin")
    assert client.patch("/api/admin/sponsors/900001", json={"status": "GONE"}).status_code == 400
    assert client.patch("/api/admin/sponsors/900001", json={"point_dollar_rate": "0.001"}).status_code == 400
    assert client.patch("/api/admin/sponsors/900001", json={"sponsor_name": "second test freight"}).status_code == 400
    assert client.patch("/api/admin/sponsors/900001", json={}).status_code == 400
    assert client.patch("/api/admin/sponsors/1", json={"phone": "1"}).status_code == 404


def test_admin_edits_user_profile(client, db):
    login(client, "testadmin")
    r = client.patch("/api/admin/users/900002", json={"first_name": "Tess", "last_name": "Sponsor",
                                                      "email": "TESS@example.com", "job_title": "Director"})
    assert r.status_code == 200
    u = one(db, "SELECT first_name, email FROM USER_ACCOUNT WHERE user_id = 900002")
    assert u == {"first_name": "Tess", "email": "tess@example.com"}
    assert one(db, "SELECT job_title FROM SPONSOR_USER WHERE sponsor_user_id = 900002")["job_title"] == "Director"
    dup = client.patch("/api/admin/users/900002", json={"first_name": "T", "last_name": "S",
                                                        "email": "testdriver@example.com"})
    assert dup.status_code == 400


# ---------------------------------------------------------------- sponsor team

NEW = {"username": "teammate", "password": "Sp0nsor!2026", "first_name": "Team", "last_name": "Mate",
       "email": "teammate@example.com"}


def test_sponsor_edits_removes_and_restores_teammate(client, db):
    login(client, "testsponsor")
    uid = client.post("/api/sponsor/organization/users", json=NEW).get_json()["sponsor_user_id"]
    r = client.patch(f"/api/sponsor/organization/users/{uid}",
                     json={**NEW, "first_name": "Renamed", "job_title": "Dispatcher"})
    assert r.status_code == 200
    assert one(db, "SELECT first_name FROM USER_ACCOUNT WHERE user_id = %s", uid)["first_name"] == "Renamed"
    assert client.post(f"/api/sponsor/organization/users/{uid}/status", json={"status": "INACTIVE"}).status_code == 200
    client.post("/api/logout")
    assert client.post("/api/login", json={"username": "teammate", "password": NEW["password"]}).status_code != 200
    login(client, "testsponsor")
    assert client.post(f"/api/sponsor/organization/users/{uid}/status", json={"status": "ACTIVE"}).status_code == 200


def test_sponsor_cannot_touch_other_orgs_or_self(client):
    login(client, "testsponsor")
    assert client.patch("/api/sponsor/organization/users/900005", json=NEW).status_code == 404
    assert client.post("/api/sponsor/organization/users/900005/status", json={"status": "INACTIVE"}).status_code == 404
    assert client.post("/api/sponsor/organization/users/900002/status", json={"status": "INACTIVE"}).status_code == 400


# ---------------------------------------------------------------- sponsor report downloads

def test_sponsor_csv_reports_are_scoped(client):
    login(client, "secondsponsor")
    points = client.get("/api/sponsor/reports/export.csv?report=points").get_data(as_text=True)
    assert "testdriver" not in points
    client.post("/api/logout")
    login(client, "testsponsor")
    r = client.get("/api/sponsor/reports/export.csv?report=points")
    assert r.status_code == 200 and "Test safe-driving award" in r.get_data(as_text=True)
    assert "Test catalog purchase" not in r.get_data(as_text=True)   # purchases aren't awards/deductions
    sales = client.get("/api/sponsor/reports/export.csv?report=sales").get_data(as_text=True)
    assert "900001" in sales
    assert client.get("/api/sponsor/reports/export.csv?report=bogus").status_code == 400


# ---------------------------------------------------------------- sponsor View as driver

def test_sponsor_views_as_own_driver_read_only(client):
    login(client, "testsponsor")
    r = client.post("/api/view-as", json={"user_id": 900003})
    assert r.status_code == 200
    user = r.get_json()["user"]
    assert user["role"] == "driver" and user["sponsor_id"] == 900001 and user["viewed_by"]["role"] == "sponsor"
    assert client.get("/api/driver/dashboard").status_code == 200
    assert client.post("/api/driver/notifications/read-all").status_code == 403
    assert client.post("/api/view-as/stop").get_json()["user"]["role"] == "sponsor"


def test_sponsor_cannot_view_as_outsiders(client):
    login(client, "secondsponsor")
    assert client.post("/api/view-as", json={"user_id": 900003}).status_code == 400   # not their driver
    assert client.post("/api/view-as", json={"user_id": 900002}).status_code == 400   # sponsor user
    client.post("/api/logout")
    login(client, "testdriver")
    assert client.post("/api/view-as", json={"user_id": 900003}).status_code == 403


def test_sponsor_view_as_ends_when_driver_dropped(client, db):
    login(client, "testsponsor")
    assert client.post("/api/view-as", json={"user_id": 900003}).status_code == 200
    run(db, "UPDATE DRIVER_SPONSOR SET participation_status = 'DROPPED' WHERE driver_id = 900003 AND sponsor_id = 900001")
    assert client.get("/api/me").get_json()["user"]["role"] == "sponsor"


# ---------------------------------------------------------------- recurring points job

def test_due_schedule_awards_points_once(client, db):
    import scheduler
    run(db, "UPDATE RECURRING_POINT_SCHEDULE SET next_run_at = DATE_SUB(NOW(), INTERVAL 1 HOUR) WHERE schedule_id = 900001")
    assert scheduler.run_due_schedules() == 1
    assert scheduler.run_due_schedules() == 0
    bal = one(db, "SELECT current_points FROM DRIVER_SPONSOR WHERE driver_id = 900003 AND sponsor_id = 900001")
    assert bal["current_points"] == 600
    s = one(db, "SELECT next_run_at > NOW() AS future FROM RECURRING_POINT_SCHEDULE WHERE schedule_id = 900001")
    assert s["future"] == 1
    assert one(db, "SELECT 1 AS x FROM NOTIFICATION WHERE user_id = 900003 AND notification_type = 'POINT_CHANGE' LIMIT 1")


def test_schedule_for_dropped_driver_is_paused_not_awarded(client, db):
    import scheduler
    run(db, "UPDATE DRIVER_SPONSOR SET participation_status = 'DROPPED' WHERE driver_id = 900003 AND sponsor_id = 900001")
    run(db, "UPDATE RECURRING_POINT_SCHEDULE SET next_run_at = DATE_SUB(NOW(), INTERVAL 1 HOUR) WHERE schedule_id = 900001")
    assert scheduler.run_due_schedules() == 0
    assert one(db, "SELECT is_active FROM RECURRING_POINT_SCHEDULE WHERE schedule_id = 900001")["is_active"] == 0


def test_sponsor_award_now(client, db):
    login(client, "testsponsor")
    assert client.post("/api/sponsor/schedules/900001/run").status_code == 200
    bal = one(db, "SELECT current_points FROM DRIVER_SPONSOR WHERE driver_id = 900003 AND sponsor_id = 900001")
    assert bal["current_points"] == 600
    client.post("/api/logout")
    login(client, "secondsponsor")
    assert client.post("/api/sponsor/schedules/900001/run").status_code == 404
