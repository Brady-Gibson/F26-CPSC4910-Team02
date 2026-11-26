"""Shared report helpers: date-range filters from the query string and CSV downloads.

    where, params = date_range("o.placed_at")          # reads ?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD
    return csv_response("sales-by-sponsor", columns, rows)

A report is a list of (key, label) columns plus a list of row dicts, so the same data feeds the page's table
and the CSV download.
"""
import csv
import io
from datetime import date, datetime, timezone
from decimal import Decimal

from flask import Response, request


def date_range(column):
    """SQL condition (with %s placeholders) for ?start_date / ?end_date on `column`. Raises ValueError on bad input.
    `column` is always a fixed string from our code, never user input."""
    dates = {}
    for field in ("start_date", "end_date"):
        raw = request.args.get(field, "").strip()
        if raw:
            try:
                if date.fromisoformat(raw).isoformat() != raw:
                    raise ValueError()
            except ValueError:
                raise ValueError("Dates must be valid dates in YYYY-MM-DD format.") from None
            dates[field] = raw
    if dates.get("start_date", "") > dates.get("end_date", "9999-12-31"):
        raise ValueError("Start date must be on or before end date.")
    clauses, params = [], []
    if "start_date" in dates:
        clauses.append(f"{column} >= %s")
        params.append(dates["start_date"] + " 00:00:00")
    if "end_date" in dates:
        clauses.append(f"{column} <= %s")
        params.append(dates["end_date"] + " 23:59:59.999999")
    return " AND ".join(clauses) or "1 = 1", params


def optional_id(name):
    """Positive integer from the query string, or None when missing. Raises ValueError when malformed."""
    raw = request.args.get(name, "").strip()
    if not raw:
        return None
    if not raw.isascii() or not raw.isdigit() or not 1 <= int(raw) <= 2147483647:
        raise ValueError("Choose a valid option.")
    return int(raw)


def csv_cell(value):
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        return str(value)   # numbers can't be formulas; keep -500 as a number, not '-500
    text = "" if value is None else str(value)
    # Spreadsheet applications can run formulas even in quoted CSV cells.
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        return "'" + text
    return text


def csv_response(name, columns, rows):
    """Download `rows` as name-YYYYMMDD-HHMMSS.csv with a header row of column labels."""
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow([label for _, label in columns])
    for row in rows:
        writer.writerow([csv_cell(row.get(key)) for key, _ in columns])
    filename = f"{name}-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.csv"
    return Response("﻿" + out.getvalue(), content_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
