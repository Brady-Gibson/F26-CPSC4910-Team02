"""The ONE place driver points change. Awards, deductions, orders, refunds, and recurring schedules all call this.

    with transaction() as cur:
        change_points(cur, driver_id, sponsor_id, -500, "Redeemed: order #42", performed_by=user_id)

It locks the driver row, updates DRIVER.current_points, inserts POINT_TRANSACTION, logs AUDIT_EVENT,
and notifies the driver if their alert preference allows. Raises PointsError on bad input, which the
caller turns into a 400. Because it runs on the caller's cursor, everything rolls back together.
"""
from audit import log_audit, notify


class PointsError(ValueError):
    pass


def change_points(cur, driver_id, sponsor_id, delta, reason, performed_by):
    if not isinstance(delta, int) or isinstance(delta, bool) or delta == 0:
        raise PointsError("Points must be a whole number other than zero.")
    reason = (reason or "").strip()
    if not reason:
        raise PointsError("A reason is required.")
    if len(reason) > 500:
        raise PointsError("Reason must be 500 characters or fewer.")

    cur.execute(
        """SELECT d.current_points, d.sponsor_id, u.username
             FROM DRIVER d JOIN USER_ACCOUNT u ON u.user_id = d.driver_id
            WHERE d.driver_id = %s
              FOR UPDATE""",
        (driver_id,),
    )
    row = cur.fetchone()
    if row is None:
        raise PointsError("Driver not found.")
    if row["sponsor_id"] != sponsor_id:
        raise PointsError("This driver isn't with your sponsor.")

    balance = int(row["current_points"]) + delta
    if balance < 0:
        raise PointsError(f"That would leave the driver at {balance:,} points. Balances can't go below zero.")

    cur.execute("UPDATE DRIVER SET current_points = %s WHERE driver_id = %s", (balance, driver_id))
    cur.execute(
        """INSERT INTO POINT_TRANSACTION
             (driver_id, sponsor_id, performed_by_user_id, points_delta, balance_after, reason)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (driver_id, sponsor_id, performed_by, delta, balance, reason),
    )
    transaction_id = cur.lastrowid

    log_audit(cur, "POINT_CHANGE", True, actor_user_id=performed_by, sponsor_id=sponsor_id,
              driver_id=driver_id, subject_username=row["username"], entity_type="POINT_TRANSACTION",
              entity_id=transaction_id, details=reason)

    cur.execute("SELECT point_change_enabled FROM ALERT_PREFERENCE WHERE user_id = %s", (driver_id,))
    pref = cur.fetchone()
    if pref is None or pref["point_change_enabled"]:
        verb = "added" if delta > 0 else "deducted"
        notify(cur, driver_id, "POINT_CHANGE",
               f"{abs(delta):,} points were {verb}: {reason}. New balance: {balance:,}.")

    return {"point_transaction_id": transaction_id, "balance_after": balance}
