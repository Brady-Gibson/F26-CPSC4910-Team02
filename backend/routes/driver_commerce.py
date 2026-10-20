"""Driver commerce: every read and write is scoped to the selected membership.

Checkout identifies a cart explicitly, so retrying a completed request cannot
charge twice. Prices and membership status are rechecked inside the transaction.
"""
from decimal import Decimal

from flask import g, jsonify, request

from audit import log_audit, notify
from auth import require_role
from db import query, transaction
from points import PointsError, change_points
from routes.driver import bp


def _membership(cur):
    cur.execute('''SELECT m.current_points FROM DRIVER_SPONSOR m
        JOIN SPONSOR_ORGANIZATION s USING (sponsor_id)
        WHERE m.driver_id = %s AND m.sponsor_id = %s AND m.participation_status = 'ACTIVE'
          AND s.status = 'ACTIVE' FOR UPDATE''', (g.user['user_id'], g.user['sponsor_id']))
    if cur.fetchone() is None:
        raise PointsError('Select an active sponsor membership first.')


@bp.get('/catalog')
@require_role('driver')
def driver_catalog():
    rows = query('''SELECT p.*, c.point_price FROM CATALOG_ITEM c
        JOIN PRODUCT p USING (product_id) WHERE c.sponsor_id = %s AND c.is_active = TRUE
        ORDER BY p.product_name''', (g.user['sponsor_id'],))
    return jsonify(products=rows, sponsor_id=g.user['sponsor_id'])


@bp.get('/points')
@require_role('driver')
def driver_points():
    rows = query('''SELECT point_transaction_id, points_delta, balance_after, reason, created_at
        FROM POINT_TRANSACTION WHERE driver_id = %s AND sponsor_id = %s
        ORDER BY created_at DESC, point_transaction_id DESC''', (g.user['user_id'], g.user['sponsor_id']))
    return jsonify(transactions=rows, sponsor_id=g.user['sponsor_id'])


@bp.get('/orders')
@require_role('driver')
def driver_orders():
    rows = query('''SELECT * FROM CUSTOMER_ORDER WHERE driver_id = %s AND sponsor_id = %s
        ORDER BY order_id DESC''', (g.user['user_id'], g.user['sponsor_id']))
    for order in rows:
        order['items'] = query('''SELECT i.*, p.product_name FROM ORDER_ITEM i JOIN PRODUCT p USING (product_id)
            WHERE i.order_id = %s AND i.sponsor_id = %s''', (order['order_id'], g.user['sponsor_id']))
    return jsonify(orders=rows)


@bp.get('/cart')
@require_role('driver')
def driver_cart():
    cart = query('''SELECT cart_id FROM SHOPPING_CART WHERE driver_id = %s AND sponsor_id = %s
        AND status = 'ACTIVE' ''', (g.user['user_id'], g.user['sponsor_id']), one=True)
    items = query('''SELECT i.*, p.product_name FROM CART_ITEM i JOIN PRODUCT p USING (product_id)
        WHERE i.cart_id = %s AND i.sponsor_id = %s''', (cart['cart_id'], g.user['sponsor_id'])) if cart else []
    return jsonify(cart_id=cart['cart_id'] if cart else None, sponsor_id=g.user['sponsor_id'], items=items)


@bp.put('/cart/items/<int:product_id>')
@require_role('driver')
def set_cart_item(product_id):
    quantity = (request.get_json(silent=True) or {}).get('quantity')
    if type(quantity) is not int or not 0 <= quantity <= 100:
        return jsonify(error='Quantity must be a whole number from 0 to 100.'), 400
    uid, sid = g.user['user_id'], g.user['sponsor_id']
    try:
        with transaction() as cur:
            _membership(cur)
            cur.execute('''SELECT c.point_price FROM CATALOG_ITEM c JOIN PRODUCT p USING (product_id)
                WHERE c.sponsor_id = %s AND c.product_id = %s
                AND c.is_active = TRUE AND p.availability = 'AVAILABLE' FOR UPDATE''', (sid, product_id))
            item = cur.fetchone()
            if quantity and (item is None or item['point_price'] <= 0):
                raise PointsError('Product is not available in this sponsor catalog.')
            cur.execute("SELECT cart_id FROM SHOPPING_CART WHERE driver_id = %s AND sponsor_id = %s AND status = 'ACTIVE' FOR UPDATE", (uid, sid))
            cart = cur.fetchone()
            if not cart:
                cur.execute("INSERT INTO SHOPPING_CART (driver_id, sponsor_id, status) VALUES (%s, %s, 'ACTIVE')", (uid, sid))
            cart_id = cart['cart_id'] if cart else cur.lastrowid
            if quantity:
                cur.execute('''INSERT INTO CART_ITEM (cart_id, sponsor_id, product_id, quantity, point_price_snapshot)
                    VALUES (%s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE quantity = VALUES(quantity),
                    point_price_snapshot = VALUES(point_price_snapshot)''', (cart_id, sid, product_id, quantity, item['point_price']))
            else:
                cur.execute('DELETE FROM CART_ITEM WHERE cart_id = %s AND sponsor_id = %s AND product_id = %s', (cart_id, sid, product_id))
    except PointsError as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True, cart_id=cart_id)


@bp.post('/checkout')
@require_role('driver')
def checkout():
    cart_id = (request.get_json(silent=True) or {}).get('cart_id')
    if type(cart_id) is not int:
        return jsonify(error='Provide an integer cart_id.'), 400
    uid, sid = g.user['user_id'], g.user['sponsor_id']
    try:
        with transaction() as cur:
            _membership(cur)
            cur.execute('''SELECT status FROM SHOPPING_CART WHERE cart_id = %s AND driver_id = %s
                AND sponsor_id = %s FOR UPDATE''', (cart_id, uid, sid))
            cart = cur.fetchone()
            if cart is None or cart['status'] != 'ACTIVE':
                return jsonify(error='Active cart not found.'), 409
            cur.execute('''SELECT i.*, c.is_active, c.point_price, p.availability, p.dollar_price FROM CART_ITEM i
                JOIN CATALOG_ITEM c ON c.sponsor_id = i.sponsor_id AND c.product_id = i.product_id
                JOIN PRODUCT p ON p.product_id = i.product_id
                WHERE i.cart_id = %s AND i.sponsor_id = %s ORDER BY i.product_id FOR UPDATE''', (cart_id, sid))
            items = cur.fetchall()
            if not items:
                raise PointsError('Your cart is empty.')
            if any(not i['is_active'] or i['availability'] != 'AVAILABLE' or i['quantity'] <= 0 or i['point_price'] <= 0
                   or i['point_price'] != i['point_price_snapshot'] for i in items):
                raise PointsError('A catalog item changed. Update your cart before checkout.')
            total = sum(i['quantity'] * i['point_price'] for i in items)
            dollar_total = (sum((i['quantity'] * i['dollar_price'] for i in items), Decimal('0'))
                            if all(i['dollar_price'] is not None for i in items) else None)
            if dollar_total is not None and not Decimal('0') <= dollar_total <= Decimal('9999999999.99'):
                raise PointsError('Order dollar amount is outside the supported range.')
            # Debit before order creation: both writes roll back together on any failure.
            result = change_points(cur, uid, sid, -total, f'Redeemed: cart #{cart_id}', performed_by=uid)
            cur.execute('''INSERT INTO CUSTOMER_ORDER (driver_id, sponsor_id, placed_by_user_id, status, total_points, total_dollar_amount)
                VALUES (%s, %s, %s, 'PLACED', %s, %s)''', (uid, sid, uid, total, dollar_total))
            order_id = cur.lastrowid
            for line, item in enumerate(items, 1):
                cur.execute('''INSERT INTO ORDER_ITEM (order_id, line_number, sponsor_id, product_id, quantity, unit_point_price, unit_dollar_price)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)''', (order_id, line, sid, item['product_id'], item['quantity'], item['point_price'], item['dollar_price']))
            cur.execute("UPDATE SHOPPING_CART SET status = 'CHECKED_OUT' WHERE cart_id = %s", (cart_id,))
            log_audit(cur, 'ORDER', True, actor_user_id=uid, sponsor_id=sid, driver_id=uid,
                      entity_type='CUSTOMER_ORDER', entity_id=order_id, details=f'Redeemed {total} points')
            cur.execute('SELECT order_summary_enabled FROM ALERT_PREFERENCE WHERE user_id = %s', (uid,))
            pref = cur.fetchone()
            if pref is None or pref['order_summary_enabled']:
                notify(cur, uid, 'ORDER_SUMMARY', f'Order #{order_id} placed with {g.user["sponsor_name"]}: {total} points.')
    except PointsError as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True, order_id=order_id, **result), 201


@bp.post('/orders/<int:order_id>/cancel')
@require_role('driver')
def cancel_driver_order(order_id):
    uid = g.user['user_id']
    try:
        with transaction() as cur:
            cur.execute("SELECT sponsor_id, status, total_points FROM CUSTOMER_ORDER WHERE order_id = %s AND driver_id = %s FOR UPDATE", (order_id, uid))
            order = cur.fetchone()
            if order is None:
                return jsonify(error='Order not found.'), 404
            if order['status'] != 'PLACED':
                return jsonify(error='Only placed orders can be cancelled.'), 409
            sid = order['sponsor_id']
            if order['total_points']:
                change_points(cur, uid, sid, int(order['total_points']),
                              f'Refund: order #{order_id} cancelled', performed_by=uid, allow_inactive=True)
            cur.execute("UPDATE CUSTOMER_ORDER SET status = 'CANCELLED', cancelled_at = CURRENT_TIMESTAMP WHERE order_id = %s", (order_id,))
            log_audit(cur, 'ORDER', True, actor_user_id=uid, driver_id=uid, sponsor_id=sid,
                      entity_type='CUSTOMER_ORDER', entity_id=order_id, details='Order cancelled by driver')
    except PointsError as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True, order_id=order_id, status='CANCELLED')
