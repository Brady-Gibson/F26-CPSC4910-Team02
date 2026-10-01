"""Database connection helper for the blueprints in routes/.

Uses mysql-connector-python and the same .env variables as application.py:
    DB_HOST, DB_PORT (default 3306), DB_USER, DB_PASSWORD, DB_NAME

One connection per request, stored on flask.g. Register close_db with
application.teardown_appcontext(close_db) so it gets closed after each request.
"""
import os

import mysql.connector
from flask import g


def get_db():
    if "db" not in g:
        g.db = mysql.connector.connect(
            host=os.getenv("DB_HOST"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            database=os.getenv("DB_NAME"),
            port=int(os.getenv("DB_PORT", 3306)),
            autocommit=False,
        )
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None and db.is_connected():
        db.close()
