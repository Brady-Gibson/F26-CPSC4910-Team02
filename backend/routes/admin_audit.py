"""Admin-only audit log reads and CSV export. Both use the same validated filters."""
import csv
import io
from datetime import date, datetime, timezone

from flask import Blueprint, Response, jsonify, request

from auth import require_role
from db import query

bp = Blueprint("admin_audit", __name__, url_prefix="/api/admin/audit")


def _filters():
    clauses, values = [], []
    category = request.args.get("category", "").strip()
    if len(category) > 50:
        raise ValueError("Category is too long.")
    if category:
        clauses.append("a.category = %s")
        values.append(category)
    success = request.args.get("success", "")
    if success:
        if success not in ("0", "1"):
            raise ValueError("Result must be succeeded or failed.")
        clauses.append("a.success = %s")
        values.append(int(success))
    sponsor = request.args.get("sponsor_id", "")
    if sponsor:
        if not sponsor.isascii() or not sponsor.isdigit() or not 1 <= int(sponsor) <= 2147483647:
            raise ValueError("Choose a valid sponsor.")
        clauses.append("a.sponsor_id = %s")
        values.append(int(sponsor))
    dates = {}
    for field in ("start_date", "end_date"):
        raw = request.args.get(field, "")
        if raw:
            try:
                parsed = date.fromisoformat(raw)
                if parsed.isoformat() != raw:
                    raise ValueError()
            except ValueError:
                raise ValueError("Dates must be valid dates in YYYY-MM-DD format.") from None
            dates[field] = raw
    if dates.get("start_date", "") > dates.get("end_date", "9999-12-31"):
        raise ValueError("Start date must be on or before end date.")
    if "start_date" in dates:
        clauses.append("a.created_at >= %s")
        values.append(dates["start_date"] + " 00:00:00")
    if "end_date" in dates:
        clauses.append("a.created_at <= %s")
        values.append(dates["end_date"] + " 23:59:59.999999")
    return " AND ".join(clauses) or "1 = 1", tuple(values)


def _entries():
    where, params = _filters()
    return query(f"""SELECT a.audit_event_id, a.created_at, a.category, a.subject_username,
                           a.actor_user_id, CONCAT(u.first_name, ' ', u.last_name) AS actor_name,
                           a.sponsor_id, s.sponsor_name, a.reason_or_details, a.success
                      FROM AUDIT_EVENT a
                      LEFT JOIN USER_ACCOUNT u ON u.user_id = a.actor_user_id
                      LEFT JOIN SPONSOR_ORGANIZATION s ON s.sponsor_id = a.sponsor_id
                     WHERE {where}
                     ORDER BY a.created_at DESC, a.audit_event_id DESC""", params)


def _csv_cell(value):
    text = "" if value is None else str(value)
    # Spreadsheet applications can execute formulas even in quoted CSV cells.
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        return "'" + text
    return text


@bp.get("")
@require_role("admin")
def audit_entries():
    try:
        entries = _entries()
    except ValueError as error:
        return jsonify(error=str(error)), 400
    response = jsonify(entries=entries,
        categories=[r["category"] for r in query("SELECT DISTINCT category FROM AUDIT_EVENT ORDER BY category")],
        sponsors=query("SELECT sponsor_id, sponsor_name FROM SPONSOR_ORGANIZATION ORDER BY sponsor_name"))
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.get("/export.csv")
@require_role("admin")
def export_audit():
    try:
        entries = _entries()
    except ValueError as error:
        return jsonify(error=str(error)), 400
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["Event ID", "Timestamp (database time)", "Category", "Subject username",
                     "Actor ID", "Actor name", "Sponsor ID", "Sponsor", "Details", "Result"])
    for entry in entries:
        writer.writerow([_csv_cell(value) for value in (
            entry["audit_event_id"], entry["created_at"], entry["category"], entry["subject_username"],
            entry["actor_user_id"], entry["actor_name"], entry["sponsor_id"], entry["sponsor_name"],
            entry["reason_or_details"], "Succeeded" if entry["success"] else "Failed")])
    filename = f"audit-log-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.csv"
    return Response("\ufeff" + output.getvalue(), content_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
