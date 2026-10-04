"""Tests for the sponsor page endpoints: drivers, points, drop, schedules, catalog, orders, reports, organization.

Seed state (see seed_test_data.sql + conftest.py), password Password123!:
    900003 testdriver     ACTIVE with sponsor 900001, 500 points, order 900001 PLACED for 500 points
    900002 testsponsor    sponsor user for 900001 (Tiger Test Trucking)
    900005 secondsponsor  sponsor user for 900002 (Second Test Freight), has no drivers
"""
DRIVER = 900003


def login(client, username="testsponsor"):
    r = client.post("/api/login", json={"username": username, "password": "Password123!"})
    assert r.status_code == 200, r.get_json()


def one(db, sql, *args):
    with db.cursor(dictionary=True) as cur:
        cur.execute(sql, args)
        return cur.fetchone()


# ---- Drivers + points

def test_drivers_list_is_scoped_to_my_sponsor(client):
    login(client)
    data = client.get("/api/sponsor/drivers").get_json()
    assert data["sponsor"]["sponsor_name"] == "Tiger Test Trucking"
    assert [d["driver_id"] for d in data["drivers"]] == [DRIVER]
    assert "password_hash" not in data["drivers"][0]

    login(client, "secondsponsor")
    assert client.get("/api/sponsor/drivers").get_json()["drivers"] == []


def test_adjust_points(client, db):
    login(client)
    r = client.post(f"/api/sponsor/drivers/{DRIVER}/points", json={"delta": 250, "reason": "Clean inspection"})
    assert r.status_code == 200 and r.get_json()["balance_after"] == 750
    assert one(db, "SELECT current_points FROM DRIVER WHERE driver_id=%s", DRIVER)["current_points"] == 750


def test_adjust_points_rejects_bad_input(client):
    login(client)
    assert client.post(f"/api/sponsor/drivers/{DRIVER}/points", json={"delta": 0, "reason": "x"}).status_code == 400
    assert client.post(f"/api/sponsor/drivers/{DRIVER}/points", json={"delta": 5, "reason": ""}).status_code == 400
    assert client.post(f"/api/sponsor/drivers/{DRIVER}/points", json={"delta": -9999, "reason": "x"}).status_code == 400


def test_other_sponsor_cannot_touch_my_driver(client, db):
    login(client, "secondsponsor")
    assert client.post(f"/api/sponsor/drivers/{DRIVER}/points", json={"delta": 5, "reason": "x"}).status_code == 404
    assert client.post(f"/api/sponsor/drivers/{DRIVER}/drop").status_code == 404
    assert one(db, "SELECT current_points FROM DRIVER WHERE driver_id=%s", DRIVER)["current_points"] == 500


def test_drop_forfeits_points_and_pauses_schedules(client, db):
    login(client)
    r = client.post(f"/api/sponsor/drivers/{DRIVER}/drop")
    assert r.status_code == 200 and r.get_json()["forfeited"] == 500
    d = one(db, "SELECT current_points, participation_status FROM DRIVER WHERE driver_id=%s", DRIVER)
    assert d == {"current_points": 0, "participation_status": "DROPPED"}
    assert one(db, "SELECT COUNT(*) AS n FROM RECURRING_POINT_SCHEDULE WHERE driver_id=%s AND is_active", DRIVER)["n"] == 0
    assert one(db, "SELECT 1 AS ok FROM NOTIFICATION WHERE user_id=%s AND notification_type='DROPPED'", DRIVER)
    assert client.post(f"/api/sponsor/drivers/{DRIVER}/drop").status_code == 409


def test_driver_cannot_use_sponsor_routes(client):
    login(client, "testdriver")
    assert client.get("/api/sponsor/drivers").status_code == 403


# ---- Recurring points

def test_create_and_pause_schedule(client, db):
    login(client)
    r = client.post("/api/sponsor/schedules", json={"driver_id": DRIVER, "points_amount": 300,
                                                    "frequency": "weekly", "reason": "Weekly bonus"})
    assert r.status_code == 201
    sid = r.get_json()["schedule_id"]
    row = one(db, "SELECT frequency, is_active, next_run_at > NOW() AS future FROM RECURRING_POINT_SCHEDULE WHERE schedule_id=%s", sid)
    assert row == {"frequency": "WEEKLY", "is_active": 1, "future": 1}

    assert client.post(f"/api/sponsor/schedules/{sid}/active", json={"is_active": False}).status_code == 200
    assert one(db, "SELECT is_active FROM RECURRING_POINT_SCHEDULE WHERE schedule_id=%s", sid)["is_active"] == 0
    assert len(client.get("/api/sponsor/schedules").get_json()["schedules"]) == 2


def test_schedule_validation(client):
    login(client)
    good = {"driver_id": DRIVER, "points_amount": 300, "frequency": "MONTHLY", "reason": "Bonus"}
    assert client.post("/api/sponsor/schedules", json={**good, "frequency": "HOURLY"}).status_code == 400
    assert client.post("/api/sponsor/schedules", json={**good, "points_amount": 0}).status_code == 400
    assert client.post("/api/sponsor/schedules", json={**good, "reason": " "}).status_code == 400
    login(client, "secondsponsor")
    assert client.post("/api/sponsor/schedules", json=good).status_code == 400
    assert client.post("/api/sponsor/schedules/900001/active", json={"is_active": False}).status_code == 404


# ---- Catalog

def test_catalog_put_creates_and_updates(client, db):
    login(client, "secondsponsor")
    products = client.get("/api/sponsor/catalog").get_json()["products"]
    assert products[0]["in_catalog"] == 0 and products[0]["point_price"] is None

    assert client.put("/api/sponsor/catalog/900001", json={"point_price": 700, "is_active": True}).status_code == 200
    assert client.put("/api/sponsor/catalog/900001", json={"point_price": 650, "is_active": False}).status_code == 200
    row = one(db, "SELECT point_price, is_active FROM CATALOG_ITEM WHERE sponsor_id=900002 AND product_id=900001")
    assert row == {"point_price": 650, "is_active": 0}
    # Sponsor 900001's own price is untouched.
    assert one(db, "SELECT point_price FROM CATALOG_ITEM WHERE sponsor_id=900001 AND product_id=900001")["point_price"] == 500

    assert client.put("/api/sponsor/catalog/900001", json={"point_price": -1, "is_active": True}).status_code == 400
    assert client.put("/api/sponsor/catalog/424242", json={"point_price": 5, "is_active": True}).status_code == 404


# ---- Orders

def test_cancel_order_refunds(client, db):
    login(client)
    orders = client.get("/api/sponsor/orders").get_json()["orders"]
    assert orders[0]["order_id"] == 900001 and orders[0]["items"][0]["product_name"] == "Test Gift Card"

    assert client.post("/api/sponsor/orders/900001/cancel").status_code == 200
    assert one(db, "SELECT status FROM CUSTOMER_ORDER WHERE order_id=900001")["status"] == "CANCELLED"
    assert one(db, "SELECT current_points FROM DRIVER WHERE driver_id=%s", DRIVER)["current_points"] == 1000
    assert client.post("/api/sponsor/orders/900001/cancel").status_code == 409


def test_other_sponsor_cannot_cancel_order(client):
    login(client, "secondsponsor")
    assert client.get("/api/sponsor/orders").get_json()["orders"] == []
    assert client.post("/api/sponsor/orders/900001/cancel").status_code == 404


# ---- Reports

def test_reports_leave_out_purchases(client):
    login(client)
    r = client.get("/api/sponsor/reports").get_json()
    # Seed: +1000 award, -500 "Test catalog purchase" (a purchase, so not counted), order for 500.
    assert (r["awarded"], r["deducted"], r["redeemed"]) == (1000, 0, 500)
    assert [t["reason"] for t in r["recent"]] == ["Test safe-driving award"]
    assert r["per_driver"][0]["driver_name"] == "Test Driver"


# ---- Organization

def test_update_organization(client, db):
    login(client)
    org = client.get("/api/sponsor/organization").get_json()
    assert org["organization"]["sponsor_name"] == "Tiger Test Trucking" and len(org["team"]) == 1

    r = client.patch("/api/sponsor/organization", json={"point_dollar_rate": "0.05", "contact_email": "Ops@Tiger.com",
                                                        "phone": "555-2222"})
    assert r.status_code == 200
    row = one(db, "SELECT point_dollar_rate, contact_email FROM SPONSOR_ORGANIZATION WHERE sponsor_id=900001")
    assert float(row["point_dollar_rate"]) == 0.05 and row["contact_email"] == "ops@tiger.com"


def test_update_organization_validation(client):
    login(client)
    assert client.patch("/api/sponsor/organization", json={"point_dollar_rate": "0.005"}).status_code == 400
    assert client.patch("/api/sponsor/organization", json={"point_dollar_rate": "abc"}).status_code == 400
    assert client.patch("/api/sponsor/organization", json={"point_dollar_rate": "0.01", "contact_email": "nope"}).status_code == 400
