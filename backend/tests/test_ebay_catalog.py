"""Tests for adding eBay listings to a sponsor catalog. eBay itself is faked; nothing here calls the network.

Seed: sponsor 900001 (testsponsor) point_dollar_rate 0.01, sponsor 900002 (secondsponsor).
"""
from decimal import Decimal

import pytest

import ebay

ITEM = "v1|1234567890|0"


def listing(item_id=ITEM, price="12.34", availability="AVAILABLE"):
    return {"external_product_id": item_id, "product_name": "Trucker Dash Cam", "description": "New",
            "dollar_price": Decimal(price), "availability": availability,
            "image_url": "https://i.ebayimg.com/images/g/x/s-l500.jpg", "category": "Dash Cams",
            "item_web_url": "https://www.ebay.com/itm/1234567890"}


@pytest.fixture()
def fake_ebay(monkeypatch):
    store = {ITEM: listing()}

    def get_item(item_id):
        if item_id not in store:
            raise ebay.EbayError("That eBay listing no longer exists.", 404)
        return dict(store[item_id])

    monkeypatch.setattr(ebay, "configured", lambda: True)
    monkeypatch.setattr(ebay, "search", lambda q, limit=20, offset=0: ([dict(v) for v in store.values()], len(store)))
    monkeypatch.setattr(ebay, "get_item", get_item)
    return store


def login(client, username="testsponsor"):
    r = client.post("/api/login", json={"username": username, "password": "Password123!"})
    assert r.status_code == 200, r.get_json()


def one(db, sql, *args):
    with db.cursor(dictionary=True) as cur:
        cur.execute(sql, args)
        return cur.fetchone()


def test_search_suggests_points_and_flags_my_items(client, fake_ebay):
    login(client)
    r = client.get("/api/sponsor/catalog/ebay/search?q=dash cam")
    assert r.status_code == 200
    result = r.get_json()["results"][0]
    assert result["suggested_points"] == 1234 and result["in_catalog"] is False   # $12.34 / $0.01
    client.post("/api/sponsor/catalog/ebay", json={"item_id": ITEM})
    assert client.get("/api/sponsor/catalog/ebay/search?q=dash cam").get_json()["results"][0]["in_catalog"] is True


def test_search_validation(client, fake_ebay):
    login(client)
    assert client.get("/api/sponsor/catalog/ebay/search?q=a").status_code == 400


def test_add_uses_ebay_price_not_the_browser(client, db, fake_ebay):
    login(client)
    r = client.post("/api/sponsor/catalog/ebay", json={"item_id": ITEM, "dollar_price": 0.01})
    assert r.status_code == 201
    pid = r.get_json()["product_id"]
    assert r.get_json()["point_price"] == 1234
    p = one(db, "SELECT * FROM PRODUCT WHERE product_id = %s", pid)
    assert p["api_source"] == "EBAY" and p["dollar_price"] == Decimal("12.34") and p["availability"] == "AVAILABLE"
    assert one(db, "SELECT is_active FROM CATALOG_ITEM WHERE sponsor_id = 900001 AND product_id = %s", pid)["is_active"]
    # The driver of that sponsor now sees it.
    client.post("/api/logout")
    login(client, "testdriver")
    assert pid in [p["product_id"] for p in client.get("/api/driver/catalog").get_json()["products"]]


def test_readding_keeps_my_price_unless_given(client, db, fake_ebay):
    login(client)
    pid = client.post("/api/sponsor/catalog/ebay", json={"item_id": ITEM, "point_price": 999}).get_json()["product_id"]
    client.put(f"/api/sponsor/catalog/{pid}", json={"point_price": 999, "is_active": False})
    assert client.post("/api/sponsor/catalog/ebay", json={"item_id": ITEM}).get_json()["point_price"] == 999
    assert client.post("/api/sponsor/catalog/ebay", json={"item_id": ITEM, "point_price": 50}).get_json()["point_price"] == 50
    assert one(db, "SELECT COUNT(*) AS n FROM PRODUCT WHERE external_product_id = %s", ITEM)["n"] == 1


def test_add_rejects_missing_or_unavailable(client, fake_ebay):
    login(client)
    assert client.post("/api/sponsor/catalog/ebay", json={}).status_code == 400
    assert client.post("/api/sponsor/catalog/ebay", json={"item_id": "v1|gone|0"}).status_code == 404
    fake_ebay["v1|out|0"] = listing("v1|out|0", availability="UNAVAILABLE")
    assert client.post("/api/sponsor/catalog/ebay", json={"item_id": "v1|out|0"}).status_code == 400
    assert client.post("/api/sponsor/catalog/ebay", json={"item_id": ITEM, "point_price": -5}).status_code == 400


def test_other_sponsors_ebay_items_stay_out_of_my_list(client, fake_ebay):
    login(client)
    pid = client.post("/api/sponsor/catalog/ebay", json={"item_id": ITEM}).get_json()["product_id"]
    client.post("/api/logout")
    login(client, "secondsponsor")
    ids = [p["product_id"] for p in client.get("/api/sponsor/catalog").get_json()["products"]]
    assert pid not in ids and 900001 in ids       # the seeded non-eBay product still shows


def test_refresh_updates_price_and_marks_ended_listings(client, db, fake_ebay):
    login(client)
    pid = client.post("/api/sponsor/catalog/ebay", json={"item_id": ITEM}).get_json()["product_id"]
    fake_ebay[ITEM] = listing(price="20.00")
    r = client.post("/api/sponsor/catalog/ebay/refresh").get_json()
    assert r["refreshed"] == 1 and r["unavailable"] == 0
    assert one(db, "SELECT dollar_price FROM PRODUCT WHERE product_id = %s", pid)["dollar_price"] == Decimal("20.00")
    del fake_ebay[ITEM]
    assert client.post("/api/sponsor/catalog/ebay/refresh").get_json()["unavailable"] == 1
    assert one(db, "SELECT availability FROM PRODUCT WHERE product_id = %s", pid)["availability"] == "UNAVAILABLE"


def test_not_configured_returns_503(client, monkeypatch):
    monkeypatch.delenv("EBAY_CLIENT_ID", raising=False)
    login(client)
    assert client.get("/api/sponsor/catalog").get_json()["ebay_enabled"] is False
    assert client.get("/api/sponsor/catalog/ebay/search?q=dash cam").status_code == 503


def test_driver_cannot_use_ebay_routes(client, fake_ebay):
    login(client, "testdriver")
    assert client.get("/api/sponsor/catalog/ebay/search?q=dash cam").status_code == 403


def test_parses_ebay_item():
    p = ebay._product({"itemId": ITEM, "title": "Cam", "price": {"value": "9.99", "currency": "USD"},
                       "categoryPath": "Electronics|Dash Cams", "image": {"imageUrl": "https://i.ebayimg.com/a.jpg"},
                       "estimatedAvailabilities": [{"estimatedAvailabilityStatus": "IN_STOCK"}]})
    assert p["dollar_price"] == Decimal("9.99") and p["category"] == "Dash Cams" and p["availability"] == "AVAILABLE"
    assert ebay._product({"itemId": ITEM, "price": {"value": "5", "currency": "GBP"}})["availability"] == "UNAVAILABLE"
    assert ebay._product({"itemId": ITEM, "price": {"value": "5", "currency": "USD"},
                          "estimatedAvailabilities": [{"estimatedAvailabilityStatus": "OUT_OF_STOCK"}]})["availability"] == "UNAVAILABLE"
