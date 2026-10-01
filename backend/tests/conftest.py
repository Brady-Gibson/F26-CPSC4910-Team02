"""Test setup. Needs a MySQL/MariaDB server you can create databases on.

Set these before running pytest (never point them at the shared RDS database,
the tests drop and recreate TEST_DB_NAME):
    TEST_DB_HOST, TEST_DB_USER, TEST_DB_PASSWORD, TEST_DB_NAME (default Team02_TEST)

Run from the backend folder:  python -m pytest tests -v
"""
import os
import re
import sys
from pathlib import Path

import pymysql
import pytest
from flask import Flask, session

BACKEND = Path(__file__).resolve().parents[1]
DATABASE = BACKEND.parent / "database"
sys.path.insert(0, str(BACKEND))

if "TEST_DB_HOST" not in os.environ:
    pytest.skip("TEST_DB_HOST not set, skipping database tests", allow_module_level=True)

DB_NAME = os.environ.get("TEST_DB_NAME", "Team02_TEST")


def run_sql_file(cur, path):
    sql = Path(path).read_text()
    sql = re.sub(r"(?im)^\s*USE\s+\w+\s*;", "", sql)          # always use the test database
    sql = re.sub(r"(?m)--.*$", "", sql)
    for stmt in sql.split(";"):
        if stmt.strip():
            cur.execute(stmt)


@pytest.fixture()
def app():
    conn = pymysql.connect(host=os.environ["TEST_DB_HOST"], user=os.environ["TEST_DB_USER"],
                           password=os.environ["TEST_DB_PASSWORD"], autocommit=True)
    with conn.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS {DB_NAME}")
        cur.execute(f"CREATE DATABASE {DB_NAME}")
        cur.execute(f"USE {DB_NAME}")
        run_sql_file(cur, DATABASE / "schema.sql")
        run_sql_file(cur, DATABASE / "seed_test_data.sql")
        for migration in sorted((DATABASE / "migrations").glob("*.sql")):
            run_sql_file(cur, migration)
        # Extra test rows: a second sponsor, its sponsor user, and a driver with no sponsor.
        cur.execute("""INSERT INTO SPONSOR_ORGANIZATION (sponsor_id, sponsor_name, status, point_dollar_rate)
                       VALUES (900002, 'Second Test Freight', 'ACTIVE', 0.01)""")
        cur.execute("""INSERT INTO USER_ACCOUNT (user_id, username, password_hash, first_name, last_name, email, account_status)
                       VALUES (900004, 'newdriver', 'x', 'New', 'Driver', 'newdriver@example.com', 'ACTIVE'),
                              (900005, 'secondsponsor', 'x', 'Second', 'Sponsor', 'second@example.com', 'ACTIVE')""")
        cur.execute("INSERT INTO DRIVER (driver_id, sponsor_id, participation_status) VALUES (900004, NULL, 'APPLICANT')")
        cur.execute("INSERT INTO SPONSOR_USER (sponsor_user_id, sponsor_id) VALUES (900005, 900002)")
    conn.close()

    os.environ.update(DB_HOST=os.environ["TEST_DB_HOST"], DB_USER=os.environ["TEST_DB_USER"],
                      DB_PASSWORD=os.environ["TEST_DB_PASSWORD"], DB_NAME=DB_NAME)
    from db import close_db
    from routes.driver_applications import bp

    flask_app = Flask(__name__)
    flask_app.secret_key = "test-only"
    flask_app.register_blueprint(bp)
    flask_app.teardown_appcontext(close_db)

    @flask_app.post("/test-login/<int:user_id>")      # stand-in for the real login route
    def test_login(user_id):
        session["user_id"] = user_id
        return "", 204

    yield flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def db():
    conn = pymysql.connect(host=os.environ["TEST_DB_HOST"], user=os.environ["TEST_DB_USER"],
                           password=os.environ["TEST_DB_PASSWORD"], database=DB_NAME,
                           cursorclass=pymysql.cursors.DictCursor, autocommit=True)
    yield conn
    conn.close()
