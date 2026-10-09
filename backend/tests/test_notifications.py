"""Driver notifications and alert settings, plus the password-change security notice.

Seed users from conftest.py all have password Password123!.
"""
PASSWORD = "Password123!"


def login(client, username="testdriver", password=PASSWORD):
    assert client.post("/api/login", json={"username": username, "password": password}).status_code == 200


def notes(client):
    return client.get("/api/driver/notifications").get_json()


def test_password_change_sends_a_notice(client):
    login(client)
    before = notes(client)["unread"]
    r = client.post("/api/me/password", json={"current_password": PASSWORD, "new_password": "Fresh-Pass9",
                                              "confirm_password": "Fresh-Pass9"})
    assert r.status_code == 200
    data = notes(client)
    assert data["unread"] == before + 1
    assert data["notifications"][0]["notification_type"] == "PASSWORD_CHANGED"
    assert data["notifications"][0]["is_read"] is False


def test_failed_password_change_sends_no_notice(client):
    login(client)
    before = len(notes(client)["notifications"])
    client.post("/api/me/password", json={"current_password": "Wrong-pass1", "new_password": "Fresh-Pass9",
                                          "confirm_password": "Fresh-Pass9"})
    assert len(notes(client)["notifications"]) == before


def test_admin_reset_notifies_the_driver(app):
    admin, driver = app.test_client(), app.test_client()
    login(admin, "testadmin")
    assert admin.post("/api/admin/users/900003/reset-password", json={"password": "Fresh-Pass9"}).status_code == 200
    login(driver, password="Fresh-Pass9")
    assert notes(driver)["notifications"][0]["notification_type"] == "PASSWORD_RESET"


def test_mark_all_read(client):
    login(client)
    client.post("/api/me/password", json={"current_password": PASSWORD, "new_password": "Fresh-Pass9",
                                          "confirm_password": "Fresh-Pass9"})
    assert notes(client)["unread"] > 0
    assert client.post("/api/driver/notifications/read-all").status_code == 200
    data = notes(client)
    assert data["unread"] == 0 and all(n["is_read"] for n in data["notifications"])


def test_only_your_own_notifications(app):
    one, two = app.test_client(), app.test_client()
    login(one)
    one.post("/api/me/password", json={"current_password": PASSWORD, "new_password": "Fresh-Pass9",
                                       "confirm_password": "Fresh-Pass9"})
    login(two, "newdriver")
    assert all(n["notification_type"] != "PASSWORD_CHANGED" for n in notes(two)["notifications"])


def test_alert_preferences_save_and_drop_alerts_stay_on(client, db):
    login(client)
    r = client.post("/api/driver/alert-preferences",
                    json={"point_change_enabled": False, "drop_alert_enabled": False})
    assert r.status_code == 200
    prefs = notes(client)["preferences"]
    assert prefs == {"point_change_enabled": False, "order_summary_enabled": True, "drop_alert_enabled": True}
    assert client.post("/api/driver/alert-preferences", json={"point_change_enabled": "no"}).status_code == 400


def test_preferences_work_without_an_existing_row(client, db):
    with db.cursor() as cur:
        cur.execute("DELETE FROM ALERT_PREFERENCE WHERE user_id = 900004")
    login(client, "newdriver")
    assert notes(client)["preferences"]["point_change_enabled"] is True
    assert client.post("/api/driver/alert-preferences", json={"order_summary_enabled": False}).status_code == 200
    assert notes(client)["preferences"]["order_summary_enabled"] is False


def test_sponsor_cannot_use_driver_notifications(client):
    login(client, "testsponsor")
    assert client.get("/api/driver/notifications").status_code == 403
