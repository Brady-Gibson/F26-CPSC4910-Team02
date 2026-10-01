"""Database helpers. Every route uses these instead of opening its own connection.

    rows = query("SELECT ... WHERE driver_id = %s", (driver_id,))
    row  = query("SELECT ... WHERE user_id = %s", (user_id,), one=True)

    with transaction() as cur:       # all-or-nothing: commits at the end, rolls back on any error
        cur.execute("UPDATE ...", (...))
        cur.execute("INSERT ...", (...))
"""
import os
from contextlib import contextmanager

import mysql.connector
from mysql.connector import pooling

_pool = None


def _get_pool():
    global _pool
    if _pool is None:
        _pool = pooling.MySQLConnectionPool(
            pool_name="team02",
            pool_size=int(os.getenv("DB_POOL_SIZE", 5)),
            pool_reset_session=True,
            host=os.getenv("DB_HOST"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            database=os.getenv("DB_NAME"),
            port=int(os.getenv("DB_PORT", 3306)),
            autocommit=True,  # plain reads don't hold transactions open; transaction() starts one explicitly
        )
    return _pool


def get_db_connection():
    conn = _get_pool().get_connection()
    conn.ping(reconnect=True, attempts=2, delay=0)  # RDS drops idle connections
    return conn


def query(sql, params=(), one=False):
    """Run a SELECT and return a list of dicts (or a single dict / None with one=True)."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        rows = cur.fetchall()
        return (rows[0] if rows else None) if one else rows
    finally:
        cur.close()
        conn.close()  # returns it to the pool


@contextmanager
def transaction():
    """Yield a dict cursor inside a transaction. Commits if the block finishes, rolls back if it raises."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        conn.start_transaction()
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()
