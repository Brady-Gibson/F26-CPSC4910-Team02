"""Write AUDIT_EVENT and NOTIFICATION rows. Pass the cursor from transaction() so they commit with the change."""


def log_audit(cur, category, success, *, actor_user_id=None, sponsor_id=None, driver_id=None,
              subject_username=None, entity_type=None, entity_id=None, details=None):
    cur.execute(
        """INSERT INTO AUDIT_EVENT
             (actor_user_id, sponsor_id, driver_id, category, subject_username,
              entity_type, entity_id, success, reason_or_details)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (actor_user_id, sponsor_id, driver_id, category, subject_username,
         entity_type, entity_id, bool(success), details),
    )


def notify(cur, user_id, notification_type, message):
    cur.execute(
        "INSERT INTO NOTIFICATION (user_id, notification_type, message) VALUES (%s, %s, %s)",
        (user_id, notification_type, message),
    )
