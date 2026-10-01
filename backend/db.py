"""Database connection helper.

Reads the RDS connection info from environment variables so no credentials
live in the repo. If the team's Flask setup already has its own connection
helper, swap get_db() in routes/driver_applications.py for that one.

Environment variables:
    DB_HOST, DB_PORT (default 3306), DB_USER, DB_PASSWORD, DB_NAME (default Team02_DB)
"""
import os

import pymysql
import pymysql.cursors
from flask import g


def get_db():
    """Return one connection per request (stored on flask.g)."""
    if "db" not in g:
        g.db = pymysql.connect(
            host=os.environ["DB_HOST"],
            port=int(os.environ.get("DB_PORT", 3306)),
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
            database=os.environ.get("DB_NAME", "Team02_DB"),
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=False,
        )
    return g.db


def close_db(_exc=None):
    """Close the request's connection. Register with app.teardown_appcontext(close_db)."""
    db = g.pop("db", None)
    if db is not None:
        db.close()
