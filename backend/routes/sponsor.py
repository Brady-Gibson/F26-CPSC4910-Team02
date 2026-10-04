"""Sponsor routes (/api/sponsor/...). Every route here is sponsor-only and scoped to g.user["sponsor_id"].

Driver Application Review (Sprint 4 feature, needed now so Sprint 3's alerts can happen)
    GET  /api/sponsor/applications                    applications sent to my organization
    POST /api/sponsor/applications/<id>/decision      {"decision": "APPROVE"|"REJECT", "reason": "..."}

The decision sends the driver a NOTIFICATION (Application Alert / Application Rejection Alert)
and writes AUDIT_EVENT.

Drivers (sponsor/drivers.html)
    GET  /api/sponsor/drivers                         my drivers + my point value
    POST /api/sponsor/drivers/<id>/points             {"delta": 500, "reason": "..."}
    POST /api/sponsor/drivers/<id>/drop               forfeits their points, pauses their schedules

Recurring points (sponsor/schedules.html)
    GET  /api/sponsor/schedules                       schedules + active drivers for the form
    POST /api/sponsor/schedules                       {"driver_id", "points_amount", "frequency", "reason"}
    POST /api/sponsor/schedules/<id>/active           {"is_active": true|false}

Catalog (sponsor/catalog.html)
    GET  /api/sponsor/catalog                         every product + my point price / in-catalog flag
    PUT  /api/sponsor/catalog/<product_id>            {"point_price": 500, "is_active": true}

Orders (sponsor/orders.html)
    GET  /api/sponsor/orders                          my drivers' orders with their items
    POST /api/sponsor/orders/<id>/cancel              PLACED orders only; refunds the points

Reports (sponsor/reports.html)
    GET  /api/sponsor/reports                         awarded / deducted / redeemed totals, per driver, recent

Organization (sponsor/organization.html)
    GET   /api/sponsor/organization                   my company + my sponsor team
    PATCH /api/sponsor/organization                   {"point_dollar_rate", "contact_email", "phone"}
"""
from decimal import Decimal, InvalidOperation

from flask import Blueprint, g, jsonify, request

from accounts import EMAIL_RE
from audit import log_audit, notify
from auth import require_role
from db import query, transaction
from points import PointsError, change_points

bp = Blueprint("sponsor", __name__, url_prefix="/api/sponsor")

# Purchases and refunds aren't sponsor awards/deductions. POINT_TRANSACTION has no order_id, so tell them apart by reason.
PURCHASE_REASON = "(redeemed|refund|purchase)"
# Fixed SQL snippets (never user input) for how far ahead the next scheduled award is.
FREQUENCIES = {"DAILY": "INTERVAL 1 DAY", "WEEKLY": "INTERVAL 1 WEEK", "MONTHLY": "INTERVAL 1 MONTH"}
MAX_POINTS = 1_000_000_000


def _whole_number(value, field, low=1, high=MAX_POINTS):
    """Parse a positive whole number from JSON. Returns (number, error)."""
    if isinstance(value, bool):
        return None, f"{field} must be a whole number."
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None, f"{field} must be a whole number."
    if not low <= number <= high:
        return None, f"{field} must be between {low:,} and {high:,}."
    return number, None


def _my_driver(cur, driver_id, lock=False):
    """The driver row if they belong to my sponsor, else None (same answer for 'missing' and 'not yours')."""
    cur.execute(
        """SELECT d.driver_id, d.sponsor_id, d.participation_status, d.current_points, u.username,
                  u.first_name, u.last_name
             FROM DRIVER d JOIN USER_ACCOUNT u ON u.user_id = d.driver_id
            WHERE d.driver_id = %s""" + (" FOR UPDATE" if lock else ""),
        (driver_id,))
    row = cur.fetchone()
    return row if row and row["sponsor_id"] == g.user["sponsor_id"] else None


@bp.get("/applications")
@require_role("sponsor")
def applications():
    rows = query(
        """SELECT a.application_id, a.driver_id, u.first_name, u.last_name, u.email,
                  a.status, a.submitted_at, a.decision_at, a.reason,
                  a.cdl_number, a.cdl_state, a.years_experience, a.applicant_notes,
                  CONCAT(du.first_name, ' ', du.last_name) AS decided_by
             FROM DRIVER_APPLICATION a
             JOIN USER_ACCOUNT u ON u.user_id = a.driver_id
             LEFT JOIN USER_ACCOUNT du ON du.user_id = a.decided_by_user_id
            WHERE a.sponsor_id = %s
            ORDER BY (a.status = 'PENDING') DESC, a.submitted_at DESC""",
        (g.user["sponsor_id"],))
    return jsonify(applications=rows)


@bp.post("/applications/<int:application_id>/decision")
@require_role("sponsor")
def decide(application_id):
    data = request.get_json(silent=True) or {}
    decision = str(data.get("decision") or "").upper()
    reason = str(data.get("reason") or "").strip()
    if decision not in ("APPROVE", "REJECT"):
        return jsonify(error="Decision must be APPROVE or REJECT."), 400
    if decision == "REJECT" and not reason:
        return jsonify(error="Give a reason when rejecting. The driver will see it."), 400
    if len(reason) > 500:
        return jsonify(error="Reason can be at most 500 characters."), 400

    my_sponsor_id, me = g.user["sponsor_id"], g.user["user_id"]
    with transaction() as cur:
        cur.execute(
            """SELECT a.driver_id, a.sponsor_id, a.status, s.sponsor_name, u.username
                 FROM DRIVER_APPLICATION a
                 JOIN SPONSOR_ORGANIZATION s ON s.sponsor_id = a.sponsor_id
                 JOIN USER_ACCOUNT u ON u.user_id = a.driver_id
                WHERE a.application_id = %s FOR UPDATE""",
            (application_id,))
        app = cur.fetchone()
        # Same answer for "doesn't exist" and "not yours" so sponsors can't probe other orgs.
        if app is None or app["sponsor_id"] != my_sponsor_id:
            return jsonify(error="Application not found."), 404
        if app["status"] != "PENDING":
            return jsonify(error=f"This application was already {app['status'].lower()}."), 409

        driver_id = app["driver_id"]
        if decision == "APPROVE":
            cur.execute("SELECT sponsor_id, participation_status FROM DRIVER WHERE driver_id = %s FOR UPDATE",
                        (driver_id,))
            d = cur.fetchone()
            if d["sponsor_id"] not in (None, my_sponsor_id) and d["participation_status"] == "ACTIVE":
                return jsonify(error="This driver already joined another sponsor."), 409
            cur.execute("""UPDATE DRIVER SET sponsor_id = %s, participation_status = 'ACTIVE',
                                  joined_at = CURRENT_TIMESTAMP WHERE driver_id = %s""",
                        (my_sponsor_id, driver_id))
            new_status = "APPROVED"
            message = f"Your application to {app['sponsor_name']} was approved. You can start earning points now."
        else:
            new_status = "REJECTED"
            message = f"Your application to {app['sponsor_name']} was not approved. Reason: {reason}"

        cur.execute(
            """UPDATE DRIVER_APPLICATION
                  SET status = %s, decided_by_user_id = %s, decision_at = CURRENT_TIMESTAMP, reason = %s
                WHERE application_id = %s""",
            (new_status, me, reason or "Application approved", application_id))
        notify(cur, driver_id, f"APPLICATION_{new_status}", message)
        log_audit(cur, "APPLICATION", True, actor_user_id=me, sponsor_id=my_sponsor_id, driver_id=driver_id,
                  subject_username=app["username"], entity_type="DRIVER_APPLICATION",
                  entity_id=application_id,
                  details=f"Application {new_status.lower()}" + (f": {reason}" if reason else ""))

    return jsonify(ok=True, application_id=application_id, status=new_status)


# ---------------------------------------------------------------- Drivers

@bp.get("/drivers")
@require_role("sponsor")
def drivers():
    sid = g.user["sponsor_id"]
    sponsor = query("SELECT sponsor_id, sponsor_name, point_dollar_rate FROM SPONSOR_ORGANIZATION WHERE sponsor_id = %s",
                    (sid,), one=True)
    rows = query(
        """SELECT d.driver_id, u.first_name, u.last_name, u.username, u.account_status,
                  d.participation_status, d.joined_at, d.current_points
             FROM DRIVER d JOIN USER_ACCOUNT u ON u.user_id = d.driver_id
            WHERE d.sponsor_id = %s
            ORDER BY (d.participation_status = 'ACTIVE') DESC, u.last_name, u.first_name""",
        (sid,))
    return jsonify(sponsor=sponsor, drivers=rows)


@bp.post("/drivers/<int:driver_id>/points")
@require_role("sponsor")
def adjust_points(driver_id):
    data = request.get_json(silent=True) or {}
    me, sid = g.user["user_id"], g.user["sponsor_id"]
    try:
        with transaction() as cur:
            d = _my_driver(cur, driver_id)
            if d is None:
                return jsonify(error="Driver not found."), 404
            if d["participation_status"] != "ACTIVE":
                return jsonify(error="This driver isn't active in your program."), 400
            result = change_points(cur, driver_id, sid, data.get("delta"), data.get("reason"), performed_by=me)
    except PointsError as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True, **result)


@bp.post("/drivers/<int:driver_id>/drop")
@require_role("sponsor")
def drop_driver(driver_id):
    me, sid = g.user["user_id"], g.user["sponsor_id"]
    try:
        with transaction() as cur:
            d = _my_driver(cur, driver_id, lock=True)
            if d is None:
                return jsonify(error="Driver not found."), 404
            if d["participation_status"] != "ACTIVE":
                return jsonify(error="This driver isn't active in your program."), 409
            forfeited = int(d["current_points"])
            if forfeited:
                change_points(cur, driver_id, sid, -forfeited, "Points forfeited on program drop", performed_by=me)
            cur.execute("UPDATE DRIVER SET participation_status = 'DROPPED' WHERE driver_id = %s", (driver_id,))
            cur.execute("UPDATE RECURRING_POINT_SCHEDULE SET is_active = FALSE WHERE driver_id = %s AND sponsor_id = %s",
                        (driver_id, sid))
            cur.execute("SELECT drop_alert_enabled FROM ALERT_PREFERENCE WHERE user_id = %s", (driver_id,))
            pref = cur.fetchone()
            if pref is None or pref["drop_alert_enabled"]:
                notify(cur, driver_id, "DROPPED", f"You were dropped from {g.user['sponsor_name']}.")
            log_audit(cur, "DRIVER_DROP", True, actor_user_id=me, sponsor_id=sid, driver_id=driver_id,
                      subject_username=d["username"], entity_type="DRIVER", entity_id=driver_id,
                      details=f"Dropped from program; {forfeited:,} points forfeited")
    except PointsError as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True, forfeited=forfeited)


# ---------------------------------------------------------------- Recurring points

@bp.get("/schedules")
@require_role("sponsor")
def schedules():
    sid = g.user["sponsor_id"]
    rows = query(
        """SELECT r.schedule_id, r.driver_id, u.first_name, u.last_name, r.points_amount, r.reason,
                  r.frequency, r.next_run_at, r.is_active
             FROM RECURRING_POINT_SCHEDULE r JOIN USER_ACCOUNT u ON u.user_id = r.driver_id
            WHERE r.sponsor_id = %s
            ORDER BY r.is_active DESC, r.next_run_at""",
        (sid,))
    active = query(
        """SELECT d.driver_id, u.first_name, u.last_name
             FROM DRIVER d JOIN USER_ACCOUNT u ON u.user_id = d.driver_id
            WHERE d.sponsor_id = %s AND d.participation_status = 'ACTIVE'
            ORDER BY u.last_name, u.first_name""",
        (sid,))
    return jsonify(schedules=rows, drivers=active)


@bp.post("/schedules")
@require_role("sponsor")
def create_schedule():
    data = request.get_json(silent=True) or {}
    me, sid = g.user["user_id"], g.user["sponsor_id"]
    points, problem = _whole_number(data.get("points_amount"), "Points")
    frequency = str(data.get("frequency") or "").upper()
    reason = str(data.get("reason") or "").strip()
    if not problem and frequency not in FREQUENCIES:
        problem = "Frequency must be DAILY, WEEKLY, or MONTHLY."
    if not problem and not reason:
        problem = "A reason is required. The driver sees it with each award."
    if not problem and len(reason) > 500:
        problem = "Reason must be 500 characters or fewer."
    if problem:
        return jsonify(error=problem), 400
    try:
        driver_id = int(data.get("driver_id"))
    except (TypeError, ValueError):
        return jsonify(error="Pick a driver."), 400

    with transaction() as cur:
        d = _my_driver(cur, driver_id)
        if d is None or d["participation_status"] != "ACTIVE":
            return jsonify(error="Pick one of your active drivers."), 400
        cur.execute(
            f"""INSERT INTO RECURRING_POINT_SCHEDULE
                  (driver_id, sponsor_id, created_by_user_id, points_amount, reason, frequency, next_run_at, is_active)
                VALUES (%s, %s, %s, %s, %s, %s, DATE_ADD(CURRENT_TIMESTAMP, {FREQUENCIES[frequency]}), TRUE)""",
            (driver_id, sid, me, points, reason, frequency))
        schedule_id = cur.lastrowid
        log_audit(cur, "SCHEDULE", True, actor_user_id=me, sponsor_id=sid, driver_id=driver_id,
                  subject_username=d["username"], entity_type="RECURRING_POINT_SCHEDULE", entity_id=schedule_id,
                  details=f"Created {frequency.lower()} schedule: +{points:,} ({reason})"[:500])
    return jsonify(ok=True, schedule_id=schedule_id), 201


@bp.post("/schedules/<int:schedule_id>/active")
@require_role("sponsor")
def set_schedule_active(schedule_id):
    is_active = (request.get_json(silent=True) or {}).get("is_active")
    if not isinstance(is_active, bool):
        return jsonify(error="is_active must be true or false."), 400
    me, sid = g.user["user_id"], g.user["sponsor_id"]
    with transaction() as cur:
        cur.execute(
            """SELECT r.driver_id, r.frequency, d.participation_status, u.username
                 FROM RECURRING_POINT_SCHEDULE r
                 JOIN DRIVER d ON d.driver_id = r.driver_id
                 JOIN USER_ACCOUNT u ON u.user_id = r.driver_id
                WHERE r.schedule_id = %s AND r.sponsor_id = %s FOR UPDATE""",
            (schedule_id, sid))
        r = cur.fetchone()
        if r is None:
            return jsonify(error="Schedule not found."), 404
        if is_active and (r["participation_status"] != "ACTIVE" or r["frequency"] not in FREQUENCIES):
            return jsonify(error="This schedule can't be resumed. The driver isn't active in your program."), 409
        if is_active:
            # Resuming: never leave the next award at a date that already passed.
            cur.execute(
                f"""UPDATE RECURRING_POINT_SCHEDULE SET is_active = TRUE,
                           next_run_at = GREATEST(COALESCE(next_run_at, CURRENT_TIMESTAMP),
                                                  DATE_ADD(CURRENT_TIMESTAMP, {FREQUENCIES[r['frequency']]}))
                     WHERE schedule_id = %s""",
                (schedule_id,))
        else:
            cur.execute("UPDATE RECURRING_POINT_SCHEDULE SET is_active = FALSE WHERE schedule_id = %s", (schedule_id,))
        log_audit(cur, "SCHEDULE", True, actor_user_id=me, sponsor_id=sid, driver_id=r["driver_id"],
                  subject_username=r["username"], entity_type="RECURRING_POINT_SCHEDULE", entity_id=schedule_id,
                  details="Resumed schedule" if is_active else "Paused schedule")
    return jsonify(ok=True, is_active=is_active)


# ---------------------------------------------------------------- Catalog

@bp.get("/catalog")
@require_role("sponsor")
def catalog():
    sid = g.user["sponsor_id"]
    sponsor = query("SELECT sponsor_id, sponsor_name, point_dollar_rate FROM SPONSOR_ORGANIZATION WHERE sponsor_id = %s",
                    (sid,), one=True)
    products = query(
        """SELECT p.product_id, p.product_name, p.category, p.external_product_id, p.availability, p.dollar_price,
                  c.point_price, COALESCE(c.is_active, FALSE) AS in_catalog
             FROM PRODUCT p
             LEFT JOIN CATALOG_ITEM c ON c.product_id = p.product_id AND c.sponsor_id = %s
            ORDER BY p.category, p.product_name""",
        (sid,))
    return jsonify(sponsor=sponsor, products=products)


@bp.put("/catalog/<int:product_id>")
@require_role("sponsor")
def set_catalog_item(product_id):
    data = request.get_json(silent=True) or {}
    me, sid = g.user["user_id"], g.user["sponsor_id"]
    price, problem = _whole_number(data.get("point_price"), "Point price")
    is_active = data.get("is_active")
    if problem:
        return jsonify(error=problem), 400
    if not isinstance(is_active, bool):
        return jsonify(error="is_active must be true or false."), 400
    with transaction() as cur:
        cur.execute("SELECT product_name FROM PRODUCT WHERE product_id = %s", (product_id,))
        product = cur.fetchone()
        if product is None:
            return jsonify(error="Product not found."), 404
        cur.execute(
            """INSERT INTO CATALOG_ITEM (sponsor_id, product_id, point_price, is_active) VALUES (%s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE point_price = VALUES(point_price), is_active = VALUES(is_active)""",
            (sid, product_id, price, is_active))
        log_audit(cur, "CATALOG", True, actor_user_id=me, sponsor_id=sid, entity_type="PRODUCT", entity_id=product_id,
                  details=f"{product['product_name'][:200]}: {price:,} pts, {'in catalog' if is_active else 'hidden'}")
    return jsonify(ok=True, product_id=product_id, point_price=price, is_active=is_active)


# ---------------------------------------------------------------- Orders

@bp.get("/orders")
@require_role("sponsor")
def orders():
    sid = g.user["sponsor_id"]
    rows = query(
        """SELECT o.order_id, o.driver_id, o.placed_by_user_id, o.status, o.total_points, o.total_dollar_amount,
                  o.placed_at, o.cancelled_at,
                  CONCAT(du.first_name, ' ', du.last_name) AS driver_name,
                  CONCAT(pu.first_name, ' ', pu.last_name) AS placed_by_name
             FROM CUSTOMER_ORDER o
             JOIN USER_ACCOUNT du ON du.user_id = o.driver_id
             JOIN USER_ACCOUNT pu ON pu.user_id = o.placed_by_user_id
            WHERE o.sponsor_id = %s
            ORDER BY o.placed_at DESC, o.order_id DESC""",
        (sid,))
    items = query(
        """SELECT i.order_id, i.line_number, i.quantity, i.unit_point_price, p.product_name
             FROM ORDER_ITEM i
             JOIN CUSTOMER_ORDER o ON o.order_id = i.order_id
             JOIN PRODUCT p ON p.product_id = i.product_id
            WHERE o.sponsor_id = %s
            ORDER BY i.order_id, i.line_number""",
        (sid,))
    by_order = {}
    for item in items:
        by_order.setdefault(item["order_id"], []).append(item)
    for o in rows:
        o["items"] = by_order.get(o["order_id"], [])
    return jsonify(orders=rows)


@bp.post("/orders/<int:order_id>/cancel")
@require_role("sponsor")
def cancel_order(order_id):
    me, sid = g.user["user_id"], g.user["sponsor_id"]
    try:
        with transaction() as cur:
            cur.execute(
                """SELECT o.driver_id, o.status, o.total_points, u.username
                     FROM CUSTOMER_ORDER o JOIN USER_ACCOUNT u ON u.user_id = o.driver_id
                    WHERE o.order_id = %s AND o.sponsor_id = %s FOR UPDATE""",
                (order_id, sid))
            o = cur.fetchone()
            if o is None:
                return jsonify(error="Order not found."), 404
            if o["status"] != "PLACED":
                return jsonify(error=f"Only placed orders can be cancelled. This one is {o['status'].lower()}."), 409
            cur.execute("UPDATE CUSTOMER_ORDER SET status = 'CANCELLED', cancelled_at = CURRENT_TIMESTAMP WHERE order_id = %s",
                        (order_id,))
            if o["total_points"]:
                change_points(cur, o["driver_id"], sid, int(o["total_points"]),
                              f"Refund: order #{order_id} cancelled", performed_by=me)
            log_audit(cur, "ORDER", True, actor_user_id=me, sponsor_id=sid, driver_id=o["driver_id"],
                      subject_username=o["username"], entity_type="CUSTOMER_ORDER", entity_id=order_id,
                      details=f"Order cancelled by sponsor; {int(o['total_points']):,} points refunded")
    except PointsError as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True, order_id=order_id, status="CANCELLED")


# ---------------------------------------------------------------- Reports

@bp.get("/reports")
@require_role("sponsor")
def reports():
    sid = g.user["sponsor_id"]
    totals = query(
        """SELECT COALESCE(SUM(CASE WHEN points_delta > 0 THEN points_delta END), 0) AS awarded,
                  COALESCE(SUM(CASE WHEN points_delta < 0 THEN -points_delta END), 0) AS deducted
             FROM POINT_TRANSACTION
            WHERE sponsor_id = %s AND LOWER(reason) NOT REGEXP %s""",
        (sid, PURCHASE_REASON), one=True)
    redeemed = query(
        """SELECT COALESCE(SUM(total_points), 0) AS redeemed FROM CUSTOMER_ORDER
            WHERE sponsor_id = %s AND status <> 'CANCELLED'""",
        (sid,), one=True)
    per_driver = query(
        """SELECT pt.driver_id, CONCAT(u.first_name, ' ', u.last_name) AS driver_name,
                  COALESCE(SUM(CASE WHEN pt.points_delta > 0 THEN pt.points_delta END), 0) AS awarded,
                  COALESCE(SUM(CASE WHEN pt.points_delta < 0 THEN -pt.points_delta END), 0) AS deducted
             FROM POINT_TRANSACTION pt JOIN USER_ACCOUNT u ON u.user_id = pt.driver_id
            WHERE pt.sponsor_id = %s AND LOWER(pt.reason) NOT REGEXP %s
            GROUP BY pt.driver_id, u.first_name, u.last_name
            ORDER BY awarded DESC""",
        (sid, PURCHASE_REASON))
    recent = query(
        """SELECT pt.point_transaction_id, pt.driver_id, pt.points_delta, pt.balance_after, pt.reason, pt.created_at,
                  CONCAT(du.first_name, ' ', du.last_name) AS driver_name,
                  CONCAT(bu.first_name, ' ', bu.last_name) AS by_name
             FROM POINT_TRANSACTION pt
             JOIN USER_ACCOUNT du ON du.user_id = pt.driver_id
             LEFT JOIN USER_ACCOUNT bu ON bu.user_id = pt.performed_by_user_id
            WHERE pt.sponsor_id = %s AND LOWER(pt.reason) NOT REGEXP %s
            ORDER BY pt.created_at DESC, pt.point_transaction_id DESC
            LIMIT 8""",
        (sid, PURCHASE_REASON))
    return jsonify(awarded=totals["awarded"], deducted=totals["deducted"], redeemed=redeemed["redeemed"],
                   per_driver=per_driver, recent=recent)


# ---------------------------------------------------------------- Organization

@bp.get("/organization")
@require_role("sponsor")
def organization():
    sid = g.user["sponsor_id"]
    org = query(
        """SELECT sponsor_id, sponsor_name, status, point_dollar_rate, contact_email, phone
             FROM SPONSOR_ORGANIZATION WHERE sponsor_id = %s""",
        (sid,), one=True)
    team = query(
        """SELECT su.sponsor_user_id, su.job_title, u.first_name, u.last_name, u.email, u.account_status
             FROM SPONSOR_USER su JOIN USER_ACCOUNT u ON u.user_id = su.sponsor_user_id
            WHERE su.sponsor_id = %s
            ORDER BY u.last_name, u.first_name""",
        (sid,))
    return jsonify(organization=org, team=team)


@bp.patch("/organization")
@require_role("sponsor")
def update_organization():
    data = request.get_json(silent=True) or {}
    email = str(data.get("contact_email") or "").strip().lower()
    phone = str(data.get("phone") or "").strip()
    if email and (len(email) > 100 or not EMAIL_RE.match(email)):
        return jsonify(error="Enter a valid contact email."), 400
    if len(phone) > 20:
        return jsonify(error="Phone must be 20 characters or fewer."), 400
    try:
        rate = Decimal(str(data.get("point_dollar_rate") or "").strip())
    except InvalidOperation:
        return jsonify(error="Point value must be a dollar amount, like 0.01."), 400
    # Same rule as Add sponsor: the column is DECIMAL(10,2), so anything finer than a cent would silently round.
    if not rate.is_finite() or not Decimal("0.01") <= rate <= Decimal("1000") or rate != rate.quantize(Decimal("0.01")):
        return jsonify(error="Point value must be between $0.01 and $1,000.00, in whole cents."), 400

    me, sid = g.user["user_id"], g.user["sponsor_id"]
    with transaction() as cur:
        cur.execute(
            "UPDATE SPONSOR_ORGANIZATION SET point_dollar_rate = %s, contact_email = %s, phone = %s WHERE sponsor_id = %s",
            (rate, email or None, phone or None, sid))
        log_audit(cur, "ORGANIZATION", True, actor_user_id=me, sponsor_id=sid, entity_type="SPONSOR_ORGANIZATION",
                  entity_id=sid, details=f"Updated settings (1 point = ${rate})")
    return jsonify(ok=True)
