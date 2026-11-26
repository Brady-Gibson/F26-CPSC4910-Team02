"""Admin reports (frontend/admin/reports.html). Every route is admin-only.

    GET /api/admin/reports?report=...&sponsor_id=&driver_id=&start_date=&end_date=&view=summary|detail
    GET /api/admin/reports/export.csv   same parameters, downloads the report as CSV

Reports (cancelled orders never count as sales):
    sponsor_sales   Sales by sponsor: per sponsor (summary) or every order (detail)
    driver_sales    Sales by driver: per driver and sponsor (summary) or every item bought (detail)
    invoice         Invoice / fee tracking: what each sponsor owes the program, FEE_RATE of its sales
The audit log report lives in routes/admin_audit.py (it has its own page and CSV export).
"""
from decimal import ROUND_HALF_UP, Decimal

from flask import Blueprint, jsonify, request

from auth import require_role
from db import query
from reports import csv_response, date_range, optional_id

bp = Blueprint("admin_reports", __name__, url_prefix="/api/admin/reports")

# The program's fee: 1% of each sponsor's redemption sales (dollar value of points spent on catalog orders).
FEE_RATE = Decimal("0.01")
CENTS = Decimal("0.01")


def _filters():
    """WHERE clause + params shared by every report: date range on order time, optional sponsor and driver."""
    where, params = date_range("o.placed_at")
    clauses = ["o.status <> 'CANCELLED'", where]
    sponsor_id, driver_id = optional_id("sponsor_id"), optional_id("driver_id")
    if sponsor_id:
        clauses.append("o.sponsor_id = %s")
        params.append(sponsor_id)
    if driver_id:
        clauses.append("o.driver_id = %s")
        params.append(driver_id)
    return " AND ".join(clauses), params


def _fee(amount):
    return (Decimal(str(amount or 0)) * FEE_RATE).quantize(CENTS, rounding=ROUND_HALF_UP)


def sponsor_sales(where, params, detail):
    if detail:
        cols = [("placed_at", "Date"), ("order_id", "Order #"), ("sponsor_name", "Sponsor"),
                ("driver_name", "Driver"), ("status", "Status"), ("items", "Items"),
                ("total_points", "Points"), ("total_dollar_amount", "Sales ($)")]
        rows = query(f"""SELECT o.order_id, o.placed_at, o.status, o.total_points, o.total_dollar_amount,
                                s.sponsor_name, CONCAT(u.first_name, ' ', u.last_name) AS driver_name,
                                (SELECT COALESCE(SUM(i.quantity), 0) FROM ORDER_ITEM i WHERE i.order_id = o.order_id) AS items
                           FROM CUSTOMER_ORDER o
                           JOIN SPONSOR_ORGANIZATION s ON s.sponsor_id = o.sponsor_id
                           JOIN USER_ACCOUNT u ON u.user_id = o.driver_id
                          WHERE {where} ORDER BY o.placed_at DESC, o.order_id DESC""", params)
    else:
        cols = [("sponsor_name", "Sponsor"), ("orders", "Orders"), ("drivers", "Drivers buying"),
                ("total_points", "Points redeemed"), ("total_dollar_amount", "Sales ($)")]
        rows = query(f"""SELECT s.sponsor_id, s.sponsor_name, COUNT(o.order_id) AS orders,
                                COUNT(DISTINCT o.driver_id) AS drivers,
                                COALESCE(SUM(o.total_points), 0) AS total_points,
                                COALESCE(SUM(o.total_dollar_amount), 0) AS total_dollar_amount
                           FROM CUSTOMER_ORDER o JOIN SPONSOR_ORGANIZATION s ON s.sponsor_id = o.sponsor_id
                          WHERE {where}
                          GROUP BY s.sponsor_id, s.sponsor_name ORDER BY total_dollar_amount DESC, s.sponsor_name""",
                     params)
    return cols, rows


def driver_sales(where, params, detail):
    if detail:
        cols = [("placed_at", "Date"), ("order_id", "Order #"), ("driver_name", "Driver"),
                ("sponsor_name", "Sponsor"), ("product_name", "Item"), ("quantity", "Qty"),
                ("points", "Points"), ("dollars", "Sales ($)")]
        rows = query(f"""SELECT o.order_id, o.placed_at, CONCAT(u.first_name, ' ', u.last_name) AS driver_name,
                                s.sponsor_name, p.product_name, i.quantity,
                                i.quantity * i.unit_point_price AS points,
                                i.quantity * COALESCE(i.unit_dollar_price, 0) AS dollars
                           FROM CUSTOMER_ORDER o
                           JOIN ORDER_ITEM i ON i.order_id = o.order_id
                           JOIN PRODUCT p ON p.product_id = i.product_id
                           JOIN SPONSOR_ORGANIZATION s ON s.sponsor_id = o.sponsor_id
                           JOIN USER_ACCOUNT u ON u.user_id = o.driver_id
                          WHERE {where} ORDER BY o.placed_at DESC, o.order_id DESC, i.line_number""", params)
    else:
        cols = [("driver_name", "Driver"), ("username", "Username"), ("sponsor_name", "Sponsor"),
                ("orders", "Orders"), ("total_points", "Points redeemed"), ("total_dollar_amount", "Sales ($)")]
        rows = query(f"""SELECT o.driver_id, CONCAT(u.first_name, ' ', u.last_name) AS driver_name, u.username,
                                s.sponsor_name, COUNT(o.order_id) AS orders,
                                COALESCE(SUM(o.total_points), 0) AS total_points,
                                COALESCE(SUM(o.total_dollar_amount), 0) AS total_dollar_amount
                           FROM CUSTOMER_ORDER o
                           JOIN USER_ACCOUNT u ON u.user_id = o.driver_id
                           JOIN SPONSOR_ORGANIZATION s ON s.sponsor_id = o.sponsor_id
                          WHERE {where}
                          GROUP BY o.driver_id, u.first_name, u.last_name, u.username, s.sponsor_id, s.sponsor_name
                          ORDER BY total_dollar_amount DESC, driver_name""", params)
    return cols, rows


def invoice(where, params, detail):
    """One invoice line per sponsor (or per sponsor + driver in detail view). Fee = FEE_RATE x sales, rounded to cents."""
    if detail:
        cols = [("sponsor_name", "Sponsor"), ("driver_name", "Driver"), ("orders", "Orders"),
                ("total_dollar_amount", "Sales ($)"), ("fee", "Fee due ($)")]
        rows = query(f"""SELECT s.sponsor_name, CONCAT(u.first_name, ' ', u.last_name) AS driver_name,
                                COUNT(o.order_id) AS orders, COALESCE(SUM(o.total_dollar_amount), 0) AS total_dollar_amount
                           FROM CUSTOMER_ORDER o
                           JOIN SPONSOR_ORGANIZATION s ON s.sponsor_id = o.sponsor_id
                           JOIN USER_ACCOUNT u ON u.user_id = o.driver_id
                          WHERE {where}
                          GROUP BY s.sponsor_id, s.sponsor_name, o.driver_id, u.first_name, u.last_name
                          ORDER BY s.sponsor_name, driver_name""", params)
    else:
        cols = [("sponsor_name", "Sponsor"), ("contact_email", "Billing contact"), ("orders", "Orders"),
                ("total_dollar_amount", "Sales ($)"), ("fee_rate", "Fee rate"), ("fee", "Fee due ($)")]
        rows = query(f"""SELECT s.sponsor_id, s.sponsor_name, s.contact_email, COUNT(o.order_id) AS orders,
                                COALESCE(SUM(o.total_dollar_amount), 0) AS total_dollar_amount
                           FROM CUSTOMER_ORDER o JOIN SPONSOR_ORGANIZATION s ON s.sponsor_id = o.sponsor_id
                          WHERE {where}
                          GROUP BY s.sponsor_id, s.sponsor_name, s.contact_email ORDER BY s.sponsor_name""", params)
    for r in rows:
        r["fee"] = _fee(r["total_dollar_amount"])
        if not detail:
            r["fee_rate"] = f"{(FEE_RATE * 100).normalize():f}%"
    return cols, rows


REPORTS = {
    "sponsor_sales": ("Sales by sponsor", sponsor_sales),
    "driver_sales": ("Sales by driver", driver_sales),
    "invoice": ("Invoice", invoice),
}
# Columns added up for the totals row.
SUMMED = ("orders", "items", "quantity", "total_points", "points", "total_dollar_amount", "dollars", "fee")


def _build():
    name = request.args.get("report", "sponsor_sales")
    if name not in REPORTS:
        raise ValueError("Pick a report.")
    view = request.args.get("view", "summary")
    if view not in ("summary", "detail"):
        raise ValueError("View must be summary or detail.")
    where, params = _filters()
    title, fn = REPORTS[name]
    cols, rows = fn(where, params, view == "detail")
    totals = {k: sum((Decimal(str(r[k] or 0)) for r in rows), Decimal(0)) for k, _ in cols if k in SUMMED}
    return name, title, view, cols, rows, totals


@bp.get("")
@require_role("admin")
def report():
    try:
        name, title, view, cols, rows, totals = _build()
    except ValueError as e:
        return jsonify(error=str(e)), 400
    return jsonify(report=name, title=title, view=view, fee_rate=FEE_RATE,
                   columns=[{"key": k, "label": label} for k, label in cols], rows=rows, totals=totals,
                   sponsors=query("SELECT sponsor_id, sponsor_name FROM SPONSOR_ORGANIZATION ORDER BY sponsor_name"),
                   drivers=query("""SELECT d.driver_id, CONCAT(u.first_name, ' ', u.last_name) AS name, u.username
                                      FROM DRIVER d JOIN USER_ACCOUNT u ON u.user_id = d.driver_id
                                     ORDER BY u.first_name, u.last_name"""))


@bp.get("/export.csv")
@require_role("admin")
def export():
    try:
        name, title, view, cols, rows, totals = _build()
    except ValueError as e:
        return jsonify(error=str(e)), 400
    if rows and totals:
        rows = rows + [{**{k: "" for k, _ in cols}, cols[0][0]: "TOTAL", **totals}]
    return csv_response(f"{name.replace('_', '-')}-{view}", cols, rows)
