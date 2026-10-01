"""Test setup: builds a fresh test database and runs the real Flask app (application.py) against it.

Needs a MySQL/MariaDB server you can create databases on. NEVER point this at the shared RDS
database: it drops and recreates TEST_DB_NAME before every test.

    $env:TEST_DB_HOST="localhost"; $env:TEST_DB_USER="root"; $env:TEST_DB_PASSWORD="yourpassword"
    python -m pytest tests -v          (run from the backend folder)
"""
import os
import re
import sys
from pathlib import Path

import mysql.connector
import pytest

BACKEND = Path(__file__).resolve().parents[1]
DATABASE = BACKEND.parent / "database"
sys.path.insert(0, str(BACKEND))

if "TEST_DB_HOST" not in os.environ:
    pytest.skip("TEST_DB_HOST not set, skipping database tests", allow_module_level=True)

DB_NAME = os.environ.get("TEST_DB_NAME", "Team02_TEST")
PASSWORD = "Password123!"

# Point the app at the test database before application.py (and its .env) loads.
os.environ.update(DB_HOST=os.environ["TEST_DB_HOST"], DB_USER=os.environ["TEST_DB_USER"],
                  DB_PASSWORD=os.environ["TEST_DB_PASSWORD"], DB_NAME=DB_NAME,
                  DB_PORT=os.environ.get("TEST_DB_PORT", "3306"), SECRET_KEY="test-only",
                  APP_ENV="development")


def _run_sql_file(cur, path):
    sql = Path(path).read_text()
    sql = re.sub(r"(?im)^\s*USE\s+\w+\s*;", "", sql)      # always stay in the test database
    sql = re.sub(r"(?m)--.*$", "", sql)
    for stmt in sql.split(";"):
        if stmt.strip():
            cur.execute(stmt)


def _connect(**kw):
    return mysql.connector.connect(host=os.environ["TEST_DB_HOST"], user=os.environ["TEST_DB_USER"],
                                   password=os.environ["TEST_DB_PASSWORD"],
                                   port=int(os.environ.get("TEST_DB_PORT", 3306)), autocommit=True, **kw)


@pytest.fixture()
def app():
    from werkzeug.security import generate_password_hash

    conn = _connect()
    cur = conn.cursor()
    cur.execute(f"DROP DATABASE IF EXISTS {DB_NAME}")
    cur.execute(f"CREATE DATABASE {DB_NAME}")
    cur.execute(f"USE {DB_NAME}")
    _run_sql_file(cur, DATABASE / "schema.sql")
    _run_sql_file(cur, DATABASE / "seed_test_data.sql")
    for migration in sorted((DATABASE / "migrations").glob("*.sql")):
        _run_sql_file(cur, migration)
    # Extra rows: a second sponsor org + its sponsor user, and a driver with no sponsor yet.
    cur.execute("""INSERT INTO SPONSOR_ORGANIZATION (sponsor_id, sponsor_name, status, point_dollar_rate)
                   VALUES (900002, 'Second Test Freight', 'ACTIVE', 0.01)""")
    cur.execute("""INSERT INTO USER_ACCOUNT (user_id, username, password_hash, first_name, last_name, email, account_status)
                   VALUES (900004, 'newdriver', 'TEST_HASH_ONLY', 'New', 'Driver', 'newdriver@example.com', 'ACTIVE'),
                          (900005, 'secondsponsor', 'TEST_HASH_ONLY', 'Second', 'Sponsor', 'second@example.com', 'ACTIVE')""")
    cur.execute("INSERT INTO DRIVER (driver_id, sponsor_id, participation_status) VALUES (900004, NULL, 'APPLICANT')")
    cur.execute("INSERT INTO SPONSOR_USER (sponsor_user_id, sponsor_id) VALUES (900005, 900002)")
    cur.execute("UPDATE USER_ACCOUNT SET password_hash = %s", (generate_password_hash(PASSWORD),))
    conn.close()

    import db
    db._pool = None            # fresh connection pool for the fresh database
    from application import application
    application.config["TESTING"] = True
    yield application


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def db():
    conn = _connect(database=DB_NAME)
    yield conn
    conn.close()
