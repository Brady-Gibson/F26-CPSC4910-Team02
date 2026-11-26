"""Runs RECURRING_POINT_SCHEDULE: awards points when a schedule is due and moves next_run_at forward.

    run_due_schedules()     award every schedule whose next_run_at has passed (called by the background loop)
    run_schedule(cur, id)   award one schedule now, inside the caller's transaction ("Award now" button)
    start_background()      start the loop thread (application.py, unless RUN_SCHEDULER=0)

Each award goes through change_points(), so it updates the balance, writes POINT_TRANSACTION and AUDIT_EVENT, and
notifies the driver like any other point change. Rows are claimed with FOR UPDATE SKIP LOCKED, so the two gunicorn
workers never award the same schedule twice. A missed run (server was down) awards once and then schedules the next
run from now, rather than paying out every missed period at once.
"""
import logging
import os
import threading
import time

from audit import log_audit
from db import transaction
from points import PointsError, change_points

log = logging.getLogger(__name__)
INTERVALS = {"DAILY": "INTERVAL 1 DAY", "WEEKLY": "INTERVAL 1 WEEK", "MONTHLY": "INTERVAL 1 MONTH"}
POLL_SECONDS = int(os.getenv("SCHEDULER_POLL_SECONDS", 60))


def _pause(cur, s, why):
    cur.execute("UPDATE RECURRING_POINT_SCHEDULE SET is_active = FALSE WHERE schedule_id = %s", (s["schedule_id"],))
    log_audit(cur, "SCHEDULE", False, sponsor_id=s["sponsor_id"], driver_id=s["driver_id"],
              entity_type="RECURRING_POINT_SCHEDULE", entity_id=s["schedule_id"], details=f"Paused automatically: {why}")


def run_schedule(cur, s):
    """Award schedule row `s` (already locked by the caller) and advance it. Returns True if points were awarded."""
    interval = INTERVALS.get(s["frequency"])
    if interval is None:
        _pause(cur, s, f"unknown frequency {s['frequency']}")
        return False
    cur.execute("""SELECT m.participation_status, o.status AS sponsor_status
                     FROM DRIVER_SPONSOR m JOIN SPONSOR_ORGANIZATION o ON o.sponsor_id = m.sponsor_id
                    WHERE m.driver_id = %s AND m.sponsor_id = %s""", (s["driver_id"], s["sponsor_id"]))
    m = cur.fetchone()
    if m is None or m["participation_status"] != "ACTIVE" or m["sponsor_status"] != "ACTIVE":
        _pause(cur, s, "the driver or sponsor is no longer active")
        return False
    try:
        change_points(cur, s["driver_id"], s["sponsor_id"], int(s["points_amount"]),
                      f"{s['reason'] or 'Recurring award'} (recurring {s['frequency'].lower()} award)"[:500],
                      s["created_by_user_id"])
    except PointsError as e:
        _pause(cur, s, str(e))
        return False
    # Interval strings come from INTERVALS (fixed), never from user input.
    cur.execute(f"""UPDATE RECURRING_POINT_SCHEDULE
                       SET next_run_at = IF(DATE_ADD(COALESCE(next_run_at, CURRENT_TIMESTAMP), {interval}) > CURRENT_TIMESTAMP,
                                            DATE_ADD(COALESCE(next_run_at, CURRENT_TIMESTAMP), {interval}),
                                            DATE_ADD(CURRENT_TIMESTAMP, {interval}))
                     WHERE schedule_id = %s""", (s["schedule_id"],))
    return True


def run_due_schedules(limit=500):
    """Award every due schedule, one transaction each. Returns how many awards were made."""
    awarded = 0
    for _ in range(limit):
        with transaction() as cur:
            cur.execute("""SELECT * FROM RECURRING_POINT_SCHEDULE
                            WHERE is_active = TRUE AND next_run_at IS NOT NULL AND next_run_at <= CURRENT_TIMESTAMP
                            ORDER BY next_run_at LIMIT 1 FOR UPDATE SKIP LOCKED""")
            s = cur.fetchone()
            if s is None:
                break
            awarded += run_schedule(cur, s)
    return awarded


def _loop():
    while True:
        try:
            n = run_due_schedules()
            if n:
                log.info("Recurring points: made %s award(s)", n)
        except Exception:   # keep the loop alive through a DB hiccup; try again next poll
            log.exception("Recurring points run failed")
        time.sleep(POLL_SECONDS)


_started = False


def start_background():
    global _started
    if _started or os.getenv("RUN_SCHEDULER", "1") == "0":
        return
    _started = True
    threading.Thread(target=_loop, name="recurring-points", daemon=True).start()
