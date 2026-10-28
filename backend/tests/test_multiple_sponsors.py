"""Integration tests of RC2 isolation through real HTTP endpoints and MySQL."""
from test_driver_applications import login, one, apply


def balance(db, sid):
    return one(db, 'SELECT current_points FROM DRIVER_SPONSOR WHERE driver_id=900003 AND sponsor_id=%s', sid)['current_points']


def select(client, sid):
    return client.post('/api/driver/selected-sponsor', json={'sponsor_id': sid})


def test_switch_scopes_dashboard_and_history(client, db):
    login(client, 'testdriver')
    assert select(client, 900010).status_code == 200
    data = client.get('/api/driver/dashboard').get_json()
    assert data['driver']['current_points'] == 200
    assert len(data['transactions']) == 1
    assert data['open_orders'] == []
    assert client.get('/api/me').get_json()['user']['sponsor_id'] == 900010
    assert select(client, 900002).status_code == 404
    assert client.get('/api/driver/dashboard').get_json()['driver']['sponsor_id'] == 900010
    assert select(client, 900001).status_code == 200
    assert client.get('/api/driver/dashboard').get_json()['driver']['current_points'] == 500


def test_catalog_returns_selected_membership_points(client):
    login(client, 'testdriver')
    assert client.get('/api/driver/catalog').get_json()['current_points'] == 500
    select(client, 900010)
    assert client.get('/api/driver/catalog').get_json()['current_points'] == 200


def test_approve_second_membership_preserves_first(client, db):
    login(client, 'testdriver')
    app_id = apply(client, sponsor_id=900002).get_json()['application_id']
    login(client, 'secondsponsor')
    assert client.post(f'/api/sponsor/applications/{app_id}/decision', json={'decision': 'APPROVE'}).status_code == 200
    assert balance(db, 900001) == 500 and balance(db, 900010) == 200 and balance(db, 900002) == 0
    assert client.post('/api/sponsor/drivers/900003/points', json={'delta': 50, 'reason': 'Safe driving'}).status_code == 200
    assert balance(db, 900002) == 50 and balance(db, 900001) == 500


def test_rejection_and_drop_do_not_change_other_memberships(client, db):
    login(client, 'testdriver')
    aid = apply(client, sponsor_id=900002).get_json()['application_id']
    login(client, 'secondsponsor')
    assert client.post(f'/api/sponsor/applications/{aid}/decision', json={'decision':'REJECT','reason':'Not eligible'}).status_code == 200
    assert balance(db, 900001) == 500 and balance(db, 900010) == 200
    login(client, 'testsponsor')
    assert client.post('/api/sponsor/drivers/900003/drop').status_code == 200
    assert balance(db, 900001) == 0 and balance(db, 900010) == 200
    # Historical order refunds still go to the original sponsor, even after a drop.
    assert client.post('/api/sponsor/orders/900001/cancel').status_code == 200
    assert balance(db, 900001) == 500 and balance(db, 900010) == 200


def test_admin_assignments_are_additive_and_atomic(client, db):
    login(client, 'testadmin')
    url = '/api/admin/drivers/900003/sponsors'
    assert client.post(url, json={'sponsor_ids':[900002, 999999]}).status_code == 400
    assert one(db, 'SELECT 1 FROM DRIVER_SPONSOR WHERE driver_id=900003 AND sponsor_id=900002') is None
    assert client.post(url, json={'sponsor_ids':[900001,900002]}).status_code == 200
    assert balance(db, 900001) == 500
    assert len(client.get(url).get_json()['memberships']) == 3
    login(client, 'testsponsor')
    assert client.get(url).status_code == 403
    assert client.get('/api/bootstrap').status_code == 403
    assert client.get('/api/sponsor/drivers').get_json()['drivers'][0]['current_points'] == 500


def test_checkout_cannot_pool_points_and_retry_cannot_double_charge(client, db):
    login(client, 'testdriver')
    assert select(client, 900010).status_code == 200
    r = client.put('/api/driver/cart/items/900001', json={'quantity':1})
    assert r.status_code == 200
    cart = r.get_json()['cart_id']
    assert client.post('/api/driver/checkout', json={'cart_id':cart}).status_code == 400
    assert balance(db, 900010) == 200 and balance(db, 900001) == 500
    assert select(client, 900001).status_code == 200
    assert client.post('/api/driver/checkout', json={'cart_id':cart}).status_code == 409
    r = client.put('/api/driver/cart/items/900001', json={'quantity':1})
    cart = r.get_json()['cart_id']
    r = client.post('/api/driver/checkout', json={'cart_id':cart})
    assert r.status_code == 201, r.get_json()
    assert balance(db, 900001) == 0 and balance(db, 900010) == 200
    assert client.post('/api/driver/checkout', json={'cart_id':cart}).status_code == 409


def test_removed_selection_cannot_redirect_a_write(app, db):
    driver, sponsor = app.test_client(), app.test_client()
    login(driver, 'testdriver')
    select(driver, 900001)
    login(sponsor, 'testsponsor')
    sponsor.post('/api/sponsor/drivers/900003/drop')
    assert driver.put('/api/driver/cart/items/900001', json={'quantity':1}).status_code == 400
    assert balance(db, 900010) == 200


def test_no_memberships_dashboard_and_view_as_read_only(client):
    login(client, 'newdriver')
    assert client.get('/api/driver/dashboard').get_json()['driver']['sponsor_id'] is None
    login(client, 'testadmin')
    assert client.post('/api/view-as', json={'user_id':900003}).status_code == 200
    assert select(client, 900010).status_code == 403
    assert client.post('/api/driver/checkout', json={'cart_id':900001}).status_code == 403


def test_checkout_rejects_changed_catalog_and_rolls_back(client, db):
    login(client, 'testdriver')
    cart = client.put('/api/driver/cart/items/900001', json={'quantity':1}).get_json()['cart_id']
    with db.cursor() as cur:
        cur.execute('UPDATE CATALOG_ITEM SET point_price=100 WHERE sponsor_id=900001 AND product_id=900001')
    assert client.post('/api/driver/checkout', json={'cart_id':cart}).status_code == 400
    assert balance(db, 900001) == 500
    assert one(db, 'SELECT status FROM SHOPPING_CART WHERE cart_id=%s', cart)['status'] == 'ACTIVE'


def test_concurrent_checkout_charges_once(app, db):
    from concurrent.futures import ThreadPoolExecutor
    a, b = app.test_client(), app.test_client()
    login(a, 'testdriver')
    login(b, 'testdriver')
    cart = a.put('/api/driver/cart/items/900001', json={'quantity':1}).get_json()['cart_id']
    with ThreadPoolExecutor(max_workers=2) as executor:
        codes = list(executor.map(lambda c: c.post('/api/driver/checkout', json={'cart_id':cart}).status_code, [a,b]))
    assert sorted(codes) == [201,409]
    assert balance(db, 900001) == 0 and balance(db, 900010) == 200


def test_driver_refund_uses_original_sponsor_and_checks_ownership(client, db):
    login(client, 'newdriver')
    assert client.post('/api/driver/orders/900001/cancel').status_code == 404
    login(client, 'testdriver')
    select(client, 900010)
    assert client.post('/api/driver/orders/900001/cancel').status_code == 200
    assert balance(db, 900001) == 1000 and balance(db, 900010) == 200
    assert client.post('/api/driver/orders/900001/cancel').status_code == 409


def test_driver_can_only_cancel_within_the_window(client, db):
    login(client, 'testdriver')
    orders = client.get('/api/driver/orders').get_json()
    assert orders['cancel_window_days'] == 3 and orders['orders'][0]['can_cancel'] is True
    with db.cursor() as cur:
        cur.execute('UPDATE CUSTOMER_ORDER SET placed_at = NOW() - INTERVAL 4 DAY WHERE order_id = 900001')
    assert client.get('/api/driver/orders').get_json()['orders'][0]['can_cancel'] is False
    r = client.post('/api/driver/orders/900001/cancel')
    assert r.status_code == 409 and '3 days' in r.get_json()['error']
    assert balance(db, 900001) == 500
    assert one(db, 'SELECT status FROM CUSTOMER_ORDER WHERE order_id = 900001')['status'] == 'PLACED'
